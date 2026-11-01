#!/usr/bin/env python3
"""
File: tools/jev/headless.py
Description: The local loop runner's headless Claude Code layer — what a
             local loop attempt runs `claude -p` with, and how its outcome is
             read back (jev conflicts' tiers 1-2 still build their own argv
             until they are ported onto this). It holds:
               * the § 13.8 session isolation flags (`--restricted`,
                 `--safe-mode`, `--tools` from the spec's tool families,
                 dontAsk with no prompts, an empty strict MCP config, no slash
                 commands, no session persistence, a debug file);
               * the `--settings` document: a mandatory, fail-closed Seatbelt
                 sandbox for Bash with no network, home fenced, and the
                 credential variables and files denied;
               * the agent's environment, built from scratch (no GitHub token,
                 no SSH agent, at most ONE Claude credential);
               * the credential choice in CLAUDE_AUTH_ORDER (env, stored login,
                 .env — the first present wins, once, no in-run fallback);
               * redaction, the streaming runner with its SIGINT-first wall
                 clock, and the outcome classifier (claude-cost's order);
               * the $0 probes: the flag preflight and the self-calibrating
                 isolation probe.
             dash-gen's `ai-run` imports this module (lazily, the hub root
             appended to its import path); this module never imports dash-gen.
             Decision: docs/adr/0002 (P1 — the executor and its posture).
Author: bamr87
Created: 2026-10-31
Version: 0.1.0
Usage: imported by .github/scripts/dash-gen/ai_activity.py (`dash ai run`); P1's
       engine (tools/jev/loop.py, PR-B) will import it as well.
Dependencies: Python 3.12 stdlib, plus tools.jev.common (PyYAML). The claude
              CLI only when a function runs it.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import math
import os
import queue
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import IO, Literal

from .common import HUB, JevError, dotenv_values

#: --permission-prompts needs 2.1.259 (the headless docs: earlier versions reject
#: it as an unknown option); --restricted, --safe-mode, --tools,
#: --append-system-prompt and --debug-file all exist in 2.1.308.
MIN_CLI = (2, 1, 259)
CREDENTIAL_ENV = {"oauth": "CLAUDE_CODE_OAUTH_TOKEN", "api_key": "ANTHROPIC_API_KEY"}
#: The CLI's other auth inputs. Each can replace or redirect the credential a
#: run was given (ANTHROPIC_AUTH_TOKEN beats a stored login, CLAUDE_CONFIG_DIR
#: picks another keychain entry, the provider switches change the backend), so
#: wherever a credential is chosen, these go.
AUTH_OVERRIDE_ENV = ("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "CLAUDE_CONFIG_DIR", "CLAUDE_CODE_USE_BEDROCK",
                     "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY", "CLAUDE_CODE_USE_GATEWAY",
                     "ANTHROPIC_UNIX_SOCKET")
#: Never in an agent's environment; denied to sandboxed commands as well, and
#: redacted wherever their values appear.
SECRET_ENV = ("GH_TOKEN", "GITHUB_TOKEN", "FLEET_TOKEN", "FLEET_WRITE_TOKEN", "PROJECTS_TOKEN",
              "NPM_TOKEN", "RUBYGEMS_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY",
              "ANTHROPIC_AUTH_TOKEN")
#: Added to the spec's own allowlist as --disallowedTools. Deny rules win over
#: allow rules, so a broad grant such as Bash(python3:*) cannot reach these.
DENY_TOOLS = ("WebFetch", "WebSearch", "Bash(gh:*)", "Bash(git push:*)", "Bash(git remote:*)",
              "Bash(git config:*)", "Bash(curl:*)", "Bash(wget:*)", "Bash(ssh:*)", "Bash(scp:*)",
              "Bash(nc:*)", "Bash(open:*)", "Bash(osascript:*)", "Bash(security:*)")
#: Credential stores a sandboxed command may not read (the hub .env is added
#: with its absolute path by settings_doc).
CREDENTIAL_FILES = ("~/.ssh", "~/.aws", "~/.config/gh", "~/.netrc", "~/.git-credentials", "~/.npmrc",
                    "~/.docker", "~/.kube", "~/.gnupg", "~/.claude", "~/.claude.json")
#: Appended to the system prompt — a code constant, so the byte-pinned spec
#: prompt stays the CI prompt.
LOCAL_RUNNER_NOTE = (
    "This run is on a local runner whose shell is sandboxed: no network, no GitHub access, no home "
    "directory, and symbolic links in this checkout are plain files. A command that fails for one of "
    "those reasons says nothing about the repository: never propose work from such a failure.")
#: The same pattern as dash-gen repo_scout.SECRET_RE; tools/test_jev_headless.py
#: holds the two equal (this module cannot import dash-gen).
SECRET_RE = re.compile(
    r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|sk-ant-[A-Za-z0-9_-]{20,})"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----"
)
#: claude-cost's usage-limit message test, verbatim.
USAGE_LIMIT_RX = re.compile(r"session limit|usage limit|weekly limit|rate limit", re.I)
#: The debug-log line the CLI writes when it wraps a Bash command in Seatbelt
#: (or bubblewrap). Undocumented wording: the probe and the canary exist so a
#: change is detected rather than trusted.
SANDBOX_LINE_RX = re.compile(r"\[Sandbox (macOS|Linux)\] Applied restrictions")
#: What the CLI prints when it refuses its own argv before any request: the
#: option parser's wordings and the missing-prompt error. classify() reads it
#: against the FIRST stderr line only — json output cannot show whether a
#: session started, so a looser match (any `error: ` line, `is invalid`
#: anywhere in the tail) would book a run that spent as no-spend.
STARTUP_ERROR_RX = re.compile(r"^error: (?:unknown option|too many arguments|missing required argument|"
                              r"required option|option '[^']*' argument (?:missing|'[^']*' is invalid))"
                              r"|Input must be provided")
INPUT_REQUIRED = "Input must be provided"
OUTCOMES = ("ok", "budget_hit", "max_turns", "usage_limit", "credential_rejected", "agent_error",
            "unparseable", "timeout", "interrupted", "startup_failed", "cli_missing")
COST_SOURCES = ("reported", "estimated", "no-spend")
EMPTY_MCP = '{"mcpServers":{}}'
#: Tools the default `-p` toolset carries that no spec may grant a loop agent:
#: SendMessage and ListAgents reach the user's other local Claude sessions,
#: ScheduleWakeup keeps a `-p` run alive, the rest widen the grant or reach the
#: network. Named so a refusal can say why; GRANTABLE_TOOLS below is the rule.
#: Edit and NotebookEdit are grantable (doctor, evolve and the issue tiers edit
#: files), and the probe's exact-toolset check refuses them wherever the spec
#: does not grant them.
NEVER_GRANTABLE_TOOLS = frozenset({"Task", "Agent", "Skill", "SendMessage", "ListAgents", "CronCreate",
                                   "CronDelete", "CronList", "ScheduleWakeup", "Workflow", "EnterWorktree",
                                   "ExitWorktree", "ToolSearch", "WebFetch", "WebSearch"})
#: The ONLY tool families a spec may grant — an allowlist, because the CLI
#: keeps shipping tools that reach past the Bash sandbox (Artifact,
#: RemoteTrigger, PushNotification, SendUserFile, Monitor, MCP tools, …) and a
#: denylist would let each new one through. Widening it is a reviewed change
#: here, never a spec's choice.
GRANTABLE_TOOLS = frozenset({"Bash", "Read", "Write", "Edit", "NotebookEdit", "Glob", "Grep"})
#: The asynchronous signals whose default action would end ai-run: INT, TERM,
#: HUP and QUIT (Ctrl-C, a cancel or backstop, a closed terminal, Ctrl-\) and
#: the ones nothing here sends but a stray `kill` or a CPU limit can (USR1,
#: USR2, ALRM, VTALRM, PROF, XCPU). Each starts the SIGINT-first ladder, so
#: claude — which runs in its own session, out of the terminal's reach — is
#: still ended and the run still leaves a ledger row. Python already ignores
#: PIPE and XFSZ. What is left orphans claude, bounded by its own cap and turn
#: limit: SIGKILL, which nothing can catch, a fault (SEGV, BUS, …) and, on
#: Linux, a real-time or other platform signal.
FORWARDED_SIGNALS = tuple(getattr(signal, n) for n in ("SIGINT", "SIGTERM", "SIGHUP", "SIGQUIT", "SIGUSR1",
                                                       "SIGUSR2", "SIGALRM", "SIGVTALRM", "SIGPROF", "SIGXCPU")
                          if hasattr(signal, n))
TRACE_CAP_BYTES = 20 * 1024 * 1024
TOOL_RESULT_CAP = 4096
STDERR_RING = 64 * 1024
NOISE_CAP = 4096
ECHO_INPUT, ECHO_TEXT = 120, 160


class NoCredential(JevError):
    """No Claude credential in CLAUDE_AUTH_ORDER is present."""


# --------------------------------------------------------------------------- #
# posture and auth
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Posture:
    """How much the agent may do. `sandbox` keeps Bash inside Seatbelt; `reduced`
    removes Bash altogether (the explicit, never-scheduled fallback)."""

    name: Literal["sandbox", "reduced"] = "sandbox"
    network: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.name not in ("sandbox", "reduced"):
            raise JevError(f"posture {self.name!r} is not sandbox or reduced")
        if self.network:
            # § 13.8: any allowed domain is a per-domain, gated decision with its
            # exfiltration trade-off recorded; P1 has none.
            raise JevError("P1 allows no network for a local agent (allowedDomains [])")


@dataclass(frozen=True)
class AuthChoice:
    """Which credential a run uses and where it came from — never the value."""

    method: str  # oauth | api_key
    source: str  # env | login | dotenv

    def __post_init__(self) -> None:
        if self.method not in CREDENTIAL_ENV or self.source not in ("env", "login", "dotenv"):
            raise JevError(f"not a credential choice: {self.method}/{self.source}")

    def __repr__(self) -> str:
        return f"AuthChoice({self.method}/{self.source})"

    def __str__(self) -> str:
        return f"{self.method} ({self.source})"


def _parse_order(value: object) -> list[str]:
    items = value if isinstance(value, list) else str(value or "").split(",")
    out: list[str] = []
    for item in items:
        m = str(item).strip()
        if m and m not in out:
            out.append(m)
    return out


def auth_order(fleet: Mapping, environ: Mapping[str, str], *, repo: str | None = None) -> list[str]:
    """The order the credentials are tried in, as every CI call site reads it.

    `CLAUDE_AUTH_ORDER` in the environment, else the `ai_auth:` entry for the
    hub (`repos:` beats `groups:` beats `default:`), else oauth then api_key.
    Only the hub's own entry is resolved here: a group is matched by its
    `repos:` list, never by `categories:`, and a repo key only by its full or
    bare name — tools/fleet-config.py also matches registry categories and
    names, so a P3 caller passing another `repo=` must not rely on parity.
    """
    order = _parse_order(environ.get("CLAUDE_AUTH_ORDER"))
    if not order:
        ai = fleet.get("ai_auth") or {}
        nwo = repo or str((fleet.get("hub") or {}).get("repo") or "bamr87/bamr87")
        keys = {nwo, nwo.split("/")[-1]}
        for key, value in (ai.get("repos") or {}).items():
            if str(key) in keys:
                order = _parse_order(value)
                break
        if not order:
            for spec in (ai.get("groups") or {}).values():
                if any(str(k) in keys for k in ((spec or {}).get("repos") or [])):
                    order = _parse_order((spec or {}).get("order"))
                    break
        order = order or _parse_order(ai.get("default")) or ["oauth", "api_key"]
    unknown = [m for m in order if m not in CREDENTIAL_ENV]
    if unknown:
        raise JevError(f"auth order {','.join(order)}: unknown method(s) {unknown} "
                       f"(one of {', '.join(CREDENTIAL_ENV)})")
    return order


def _without_credentials(environ: Mapping[str, str]) -> dict[str, str]:
    drop = {*CREDENTIAL_ENV.values(), *AUTH_OVERRIDE_ENV}
    return {k: v for k, v in environ.items() if k not in drop}


def stored_login(claude_bin: str, environ: Mapping[str, str]) -> bool:
    """Is there a claude.ai login the agent's environment will find?

    Read with both credential variables and every AUTH_OVERRIDE_ENV name
    (CLAUDE_CONFIG_DIR among them) unset — the environment a run chosen this
    way gets — so the answer is about the default keychain login alone.
    `claude auth status` makes no model request.
    """
    try:
        proc = subprocess.run([claude_bin, "auth", "status", "--json"], env=_without_credentials(environ),
                              stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30, check=False)
        data = json.loads(proc.stdout or "{}")
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return False
    method = str(data.get("authMethod") or "").lower()
    return bool(data.get("loggedIn")) and "api" not in method


def choose_auth(order: Iterable[str], environ: Mapping[str, str], dotenv: Mapping[str, str],
                login: Callable[[], bool]) -> AuthChoice:
    """The FIRST PRESENT credential in `order` — chosen once, never retried.

    oauth: the env token, then a stored login, then the hub .env value.
    api_key: the env key, then the .env value. A refused credential or a spent
    window is not answered by trying the other method (#348 holds that
    decision open); `login` is only called when it is the next candidate.
    """
    for method in order:
        name = CREDENTIAL_ENV[method]
        if environ.get(name):
            return AuthChoice(method, "env")
        if method == "oauth" and login():
            return AuthChoice("oauth", "login")
        if dotenv.get(name):
            return AuthChoice(method, "dotenv")
    raise NoCredential(
        f"no Claude credential for auth order {','.join(order)}: set CLAUDE_CODE_OAUTH_TOKEN or "
        "ANTHROPIC_API_KEY, run `claude login`, or put one in the hub .env")


def credential_value(choice: AuthChoice, environ: Mapping[str, str], dotenv: Mapping[str, str]) -> str | None:
    """The chosen credential's value, or None for a stored login (the CLI reads it)."""
    if choice.source == "login":
        return None
    name = CREDENTIAL_ENV[choice.method]
    return (environ if choice.source == "env" else dotenv).get(name) or None


def hub_dotenv(path: Path | None = None) -> dict[str, str]:
    """The two Claude credential names from the hub .env (`JEV_DOTENV` overrides
    the path) — nothing else is read."""
    return dotenv_values(tuple(CREDENTIAL_ENV.values()),
                         path or Path(os.environ.get("JEV_DOTENV") or HUB / ".env"))


def with_one_credential(environ: Mapping[str, str], choice: AuthChoice, value: str | None) -> dict[str, str]:
    """`environ` with exactly the chosen credential: claude-run's `env -u`.

    Under `-p` an exported ANTHROPIC_API_KEY wins over OAuth, so the other
    variable is not merely deprioritised, it is removed — and so is every
    AUTH_OVERRIDE_ENV name, so the credential the run uses is the one
    `stored_login` checked (an ANTHROPIC_AUTH_TOKEN would beat it, and a
    CLAUDE_CONFIG_DIR would read another keychain entry). Everything else is
    inherited.
    """
    env = _without_credentials(environ)
    if value:
        env[CREDENTIAL_ENV[choice.method]] = value
    return env


# --------------------------------------------------------------------------- #
# the CLI
# --------------------------------------------------------------------------- #
def parse_version(text: str) -> tuple[int, int, int] | None:
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", text or "")
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def cli_version(claude_bin: str = "claude") -> tuple[int, int, int] | None:
    try:
        proc = subprocess.run([claude_bin, "--version"], capture_output=True, text=True,
                              timeout=30, check=False, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return parse_version(proc.stdout)


def version_str(v: tuple[int, int, int] | None) -> str | None:
    return ".".join(map(str, v)) if v else None


def run_prefix(cap_usd: float, *, stream: bool) -> list[str]:
    """What ai-run puts before every passthrough: print mode, the output format
    its parser reads, and the dollar cap. One source, so the preflight parses
    the argv the run will use. A cap that is not a finite number above 0 is
    refused here too, the last line before claude: `inf` or `nan` caps nothing."""
    if isinstance(cap_usd, bool) or not isinstance(cap_usd, (int, float)) or not (math.isfinite(cap_usd)
                                                                                 and cap_usd > 0):
        raise JevError(f"refusing: a dollar cap must be a finite number above 0, got {cap_usd!r}")
    fmt = ["--output-format", "stream-json", "--verbose"] if stream else ["--output-format", "json"]
    return ["-p", *fmt, "--max-budget-usd", f"{cap_usd:g}"]


# --------------------------------------------------------------------------- #
# argv, settings, environment
# --------------------------------------------------------------------------- #
def tool_families(allowed_tools: Iterable[str]) -> tuple[str, ...]:
    """`Bash(git status:*)` → `Bash`, in first-appearance order: the `--tools` set."""
    out: list[str] = []
    for t in allowed_tools:
        family = t.split("(", 1)[0]
        if family not in out:
            out.append(family)
    return tuple(out)


def posture_tools(allowed_tools: Iterable[str], posture: Posture) -> tuple[str, ...]:
    """The allowlist a posture grants: the spec's, verbatim (CI parity), or —
    reduced — the same list with every Bash entry removed."""
    tools = tuple(allowed_tools)
    if posture.name == "reduced":
        tools = tuple(t for t in tools if tool_families([t]) != ("Bash",))
    return tools


def claude_flags(spec, posture: Posture, *, settings_path: Path, session_id: str, debug_path: Path,
                 note: str = LOCAL_RUNNER_NOTE) -> list[str]:
    """The flags ai-run passes after `--` for one loop attempt.

    `spec` is a tools.jev.spec.StepSpec: model, turns and the allowlist come
    from it (resolved from _data/fleet.yml); `-p`, the output format and the
    dollar cap are ai-run's own prefix. Every variadic option gets ONE
    comma-joined value, and there is no positional prompt — it goes on stdin.
    A spec that grants a family outside GRANTABLE_TOOLS (a NEVER_GRANTABLE_TOOLS
    one included) is refused here, before any probe or run.
    """
    allowed = posture_tools(spec.allowed_tools, posture)
    families = set(tool_families(allowed))
    never = sorted(families & NEVER_GRANTABLE_TOOLS)
    if never:
        raise JevError(f"the spec grants {never}, which no loop agent may hold")
    unknown = sorted(families - GRANTABLE_TOOLS)
    if unknown:
        raise JevError(f"the spec grants {unknown}, outside the families a loop agent may hold "
                       f"({', '.join(sorted(GRANTABLE_TOOLS))})")
    return [
        "--model", spec.resolved.model,
        "--max-turns", str(spec.resolved.max_turns),
        "--tools", ",".join(tool_families(allowed)),
        "--allowedTools", ",".join(allowed),
        "--disallowedTools", ",".join(DENY_TOOLS),
        "--permission-mode", "dontAsk",
        "--permission-prompts", "none",
        "--restricted",
        "--safe-mode",
        "--settings", str(settings_path),
        "--strict-mcp-config",
        "--mcp-config", EMPTY_MCP,
        "--disable-slash-commands",
        "--no-session-persistence",
        "--session-id", session_id,
        "--append-system-prompt", note,
        "--debug-file", str(debug_path),
    ]


def settings_doc(posture: Posture, *, hub: Path = HUB) -> dict:
    """The `--settings` document. `--restricted` ignores every settings FILE, so
    this is the only settings a loop attempt reads besides managed policy."""
    doc: dict = {
        "disableAllHooks": True,
        "permissions": {"defaultMode": "dontAsk", "blockReadsOutsideWorkingDirectories": True},
    }
    if posture.name == "sandbox":
        doc["sandbox"] = {
            "enabled": True,
            # an unavailable sandbox is a startup error, never a silent
            # unsandboxed run
            "failIfUnavailable": True,
            # dangerouslyDisableSandbox is ignored outright
            "allowUnsandboxedCommands": False,
            # its default (true) would approve any sandboxed command outside
            # the allowlist
            "autoAllowBashIfSandboxed": False,
            "excludedCommands": [],
            "network": {"allowedDomains": list(posture.network), "strictAllowlist": True},
            "credentials": {
                "envVars": [{"name": n, "mode": "deny"} for n in SECRET_ENV],
                "files": [{"path": p, "mode": "deny"} for p in (*CREDENTIAL_FILES, str(Path(hub) / ".env"))],
            },
        }
    return doc


#: A fixed parent environment, so the posture template hashes the KEY SET
#: agent_env builds, never this machine's values.
_TEMPLATE_ENVIRON = {"PATH": "/usr/bin:/bin", "HOME": "/HOME", "USER": "u", "LOGNAME": "u", "SHELL": "/bin/sh",
                     "LANG": "C.UTF-8"}


def posture_template(spec, posture: Posture) -> dict:
    """Everything the probe and the canary prove, with every per-run value and
    every local path held fixed: the `--settings` document, the isolation
    flags (which carry the spec's toolset, allowlist and deny list), the agent
    environment's key set and the posture's name."""
    return {
        "posture": posture.name,
        "settings": settings_doc(posture, hub=Path("/HUB")),
        "flags": claude_flags(spec, posture, settings_path=Path("/SETTINGS"), session_id="SESSION",
                              debug_path=Path("/DEBUG")),
        "env_keys": sorted(agent_env(_TEMPLATE_ENVIRON, None, credential_value=None, tmp=Path("/TMP"),
                                     gh_config_dir=Path("/GH"), hub=Path("/HUB"), work=Path("/WORK"))),
    }


def posture_template_sha(spec, posture: Posture) -> str:
    """`posture_template`'s content hash. With the CLI version, the cache key a
    probe or canary result is stored under — so a change to any part of the
    template invalidates a cached pass instead of inheriting it."""
    body = json.dumps(posture_template(spec, posture), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def work_root(environ: Mapping[str, str] | None = None) -> Path:
    """Where loop workspaces live: outside the hub tree, inside the home fence."""
    env = os.environ if environ is None else environ
    return Path(env.get("JEV_WORK_ROOT") or "~/.cache/jev/work").expanduser()


def _under(path: Path, root: Path) -> bool:
    try:
        return path.resolve().is_relative_to(root.resolve())
    except OSError:
        return True


def agent_env(environ: Mapping[str, str], auth: AuthChoice | None, *, credential_value: str | None,
              tmp: Path, gh_config_dir: Path, hub: Path = HUB, work: Path | None = None) -> dict[str, str]:
    """The agent's environment, built from scratch — an allowlist, not a scrub.

    Kept from the parent: PATH (minus empty, relative, hub and work-root
    entries), HOME (the keychain login needs it), USER, LOGNAME, SHELL and the
    locale. Everything else is set here. Never passed, by construction: every
    GitHub token, SSH_AUTH_SOCK, ANTHROPIC_BASE_URL (it would carry the OAuth
    credential to another host), CLAUDE_CONFIG_DIR, PYTHONPATH, NODE_OPTIONS,
    OTEL_*, AWS_*, DYLD_*/LD_*. At most ONE Claude credential.

    Deliberately NOT set: CLAUDE_CODE_SUBPROCESS_ENV_SCRUB. On 2.1.308 it forces
    the permission mode to `default`, overriding `--permission-mode dontAsk`
    and the settings' `defaultMode`; the credential variables are kept from
    Bash by the sandbox's `credentials.envVars` deny list instead.
    """
    work = work_root(environ) if work is None else work
    path = []
    for entry in str(environ.get("PATH") or "").split(os.pathsep):
        p = Path(entry)
        if not entry or not p.is_absolute() or _under(p, hub) or _under(p, work):
            continue
        if entry not in path:
            path.append(entry)
    tmp, gh_config_dir = Path(tmp), Path(gh_config_dir)
    env: dict[str, str] = {"PATH": os.pathsep.join(path or ["/usr/bin", "/bin"])}
    for key in ("HOME", "USER", "LOGNAME", "SHELL"):
        if environ.get(key):
            env[key] = str(environ[key])
    env["LANG"] = str(environ.get("LANG") or "en_US.UTF-8")
    for key in ("LC_ALL", "LC_CTYPE"):
        if environ.get(key):
            env[key] = str(environ[key])
    env.update({
        "TERM": "dumb", "NO_COLOR": "1", "TZ": "UTC",
        "TMPDIR": str(tmp),
        "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0",
        "GIT_OPTIONAL_LOCKS": "0", "GIT_PAGER": "cat", "PAGER": "cat", "GIT_LFS_SKIP_SMUDGE": "1",
        "GH_CONFIG_DIR": str(gh_config_dir), "GH_PROMPT_DISABLED": "1",
        "npm_config_cache": str(tmp / "npm"), "npm_config_userconfig": "/dev/null",
        "npm_config_offline": "true", "npm_config_update_notifier": "false",
        "PIP_NO_INDEX": "1", "PIP_CONFIG_FILE": "/dev/null", "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1",
        "DISABLE_AUTOUPDATER": "1",
    })
    if auth is not None and credential_value:
        env[CREDENTIAL_ENV[auth.method]] = credential_value
    return env


# --------------------------------------------------------------------------- #
# redaction and the trace
# --------------------------------------------------------------------------- #
class Redactor:
    """Exact secret values, credential shapes and $HOME out of anything kept.

    Pattern- and value-based, not exhaustive: the trace stays local and
    gitignored whatever this catches.
    """

    def __init__(self, environ: Mapping[str, str], extra: Mapping[str, str] | None = None):
        pairs = {(n, str(environ[n])) for n in SECRET_ENV if len(str(environ.get(n) or "")) >= 8}
        pairs |= {(n, v) for n, v in (extra or {}).items() if v and len(v) >= 8}
        self._values = sorted(pairs, key=lambda p: -len(p[1]))
        home = str(environ.get("HOME") or "")
        self._home = home.rstrip("/") if len(home) > 1 else ""

    def text(self, s: str) -> str:
        for name, value in self._values:
            s = s.replace(value, f"[REDACTED:{name}]")
        s = SECRET_RE.sub("[REDACTED]", s)
        return s.replace(self._home, "~") if self._home else s

    def obj(self, o: object) -> object:
        if isinstance(o, str):
            return self.text(o)
        if isinstance(o, list):
            return [self.obj(x) for x in o]
        if isinstance(o, dict):
            return {(self.text(k) if isinstance(k, str) else k): self.obj(v) for k, v in o.items()}
        return o


def _clip_tool_results(event: dict) -> dict:
    """tool_result blocks over TOOL_RESULT_CAP keep their head and a sha256.

    Applied to an ALREADY-redacted event: clipping first could cut a secret in
    two and leave a prefix no pattern matches, and the digest would be of the
    unredacted text."""
    content = (event.get("message") or {}).get("content")
    if not isinstance(content, list):
        return event
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "tool_result":
            continue
        body = block.get("content")
        text = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
        if len(text) > TOOL_RESULT_CAP:
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
            block["content"] = text[:TOOL_RESULT_CAP]
            block["jev_truncated"] = {"chars": len(text), "sha256": digest}
    return event


class Trace:
    """A redacted, size-capped JSONL copy of the session (the cap is in UTF-8
    bytes, as written)."""

    def __init__(self, path: Path | None, redactor: Redactor, cap: int = TRACE_CAP_BYTES):
        self.path, self.redactor, self.cap = path, redactor, cap
        self.written = 0
        self.full = False
        self._fh: IO[str] | None = None
        if path is not None:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            self._fh = Path(path).open("w", encoding="utf-8")

    def write(self, event: object | None, raw: str) -> None:
        if self._fh is None or self.full:
            return
        if isinstance(event, dict):
            line = json.dumps(_clip_tool_results(self.redactor.obj(event)), ensure_ascii=False)
        else:
            line = json.dumps({"type": "jev_raw", "text": self.redactor.text(raw)[:TOOL_RESULT_CAP]})
        size = len(line.encode("utf-8")) + 1
        if self.written + size > self.cap:
            self._fh.write(json.dumps({"type": "jev_trace_truncated", "cap_bytes": self.cap}) + "\n")
            self.full = True
            return
        self._fh.write(line + "\n")
        self.written += size

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None


def _one_line(s: object, n: int) -> str:
    text = " ".join(str(s).split())
    return text if len(text) <= n else text[: n - 1] + "…"


def condensed(event: dict, cap_usd: float, redactor: Redactor) -> list[str]:
    """The tee: one short, redacted line per thing a watching human cares about."""
    kind = event.get("type")
    out: list[str] = []
    if kind == "system" and event.get("subtype") == "init":
        out.append(f"· init {event.get('model', '?')} · {len(event.get('tools') or [])} tools · "
                   f"{event.get('permissionMode', '?')}")
    elif kind == "assistant":
        for block in (event.get("message") or {}).get("content") or []:
            if not isinstance(block, dict):
                continue
            # redacted BEFORE the clip: a cut secret keeps a prefix no pattern
            # or value match recognises
            if block.get("type") == "tool_use":
                args = json.dumps(block.get("input") or {}, ensure_ascii=False)
                out.append(f"▸ {block.get('name')} {_one_line(redactor.text(args), ECHO_INPUT)}")
            elif block.get("type") == "text" and str(block.get("text") or "").strip():
                out.append(f"◂ {_one_line(redactor.text(str(block['text'])), ECHO_TEXT)}")
    elif kind == "user":
        for block in (event.get("message") or {}).get("content") or []:
            if isinstance(block, dict) and block.get("type") == "tool_result" and block.get("is_error"):
                body = block.get("content")
                text = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
                if re.search(r"permission|denied|not allowed", text, re.I):
                    out.append(f"✗ denied {_one_line(redactor.text(text), ECHO_INPUT)}")
    elif kind == "result":
        cost = float(event.get("total_cost_usd") or 0.0)
        out.append(f"■ {event.get('subtype')} turns={event.get('num_turns', 0)} ${cost:.4f} of "
                   f"${cap_usd:g} (API-equivalent estimate)")
    return [redactor.text(line) for line in out]


# --------------------------------------------------------------------------- #
# streaming
# --------------------------------------------------------------------------- #
@dataclass
class Invocation:
    """Everything one `claude -p` process left behind."""

    rc: int
    result: dict | None = None
    init: dict | None = None
    timed_out: bool = False
    interrupted: str = ""
    duration_s: float = 0.0
    stderr_tail: str = ""
    stdout_text: str = ""
    tool_uses: dict[str, int] = field(default_factory=dict)
    permission_denials: int = 0
    rate_limited: bool = False
    garbage_lines: int = 0
    #: a redacted tail of the non-JSON stdout lines a stream-json run printed
    stdout_noise: str = ""
    started: bool = True
    fmt: str = "stream-json"
    #: the tee could not be written (a hung-up terminal): it is dropped, and
    #: the run — and its ledger row — go on
    echo_lost: bool = False
    #: how many of the caller's `received` signals arrived while claude was
    #: still running (or before it was started); any later one did not stop
    #: the run, and is the caller's to act on
    signals_seen: int = 0


def last_result(text: str) -> dict | None:
    """The LAST `type: "result"` object in a JSON document, an array, or JSONL."""
    def found(value: object) -> list[dict]:
        if isinstance(value, dict):
            return [value] if value.get("type") == "result" else []
        if isinstance(value, list):
            return [r for item in value for r in found(item)]
        return []

    text = (text or "").strip()
    if not text:
        return None
    try:
        hits = found(json.loads(text))
    except json.JSONDecodeError:
        hits = []
        for line in text.splitlines():
            try:
                hits.extend(found(json.loads(line)))
            except json.JSONDecodeError:
                continue
    return hits[-1] if hits else None


@contextlib.contextmanager
def held_signals(into: list[str]) -> Iterator[list[str]]:
    """Hold FORWARDED_SIGNALS until the block ends: each one is appended to
    `into` by name instead of ending the process.

    ai-run wraps a run AND its bookkeeping in this, so a cancel that lands
    after claude has reported its cost (a second Ctrl-C, a backstop SIGTERM)
    cannot kill it before the ledger row and the outcome file are written.
    `stream` saves and restores whatever handler is installed — this one — and
    reads `into`: a signal already there cancels the run before claude starts,
    and one that lands after claude exited stays there for the caller.
    Outside the main thread nothing can be installed, and nothing is."""
    if threading.current_thread() is not threading.main_thread():
        yield into
        return

    def hold(signum: int, _frame: object) -> None:
        into.append(signal.Signals(signum).name)

    old = {sig: signal.signal(sig, hold) for sig in FORWARDED_SIGNALS}
    try:
        yield into
    finally:
        for sig, handler in old.items():
            signal.signal(sig, handler)


def _signal_group(pid: int, sig: int) -> None:
    try:
        os.killpg(pid, sig)
    except (ProcessLookupError, PermissionError):
        return


def stream(argv: list[str], *, prompt: str | None, cwd: Path | None, env: Mapping[str, str] | None,
           timeout_s: float | None, trace: Trace | None, redactor: Redactor, cap_usd: float,
           echo: IO[str] | None = None, fmt: str = "stream-json",
           int_grace: float = 15.0, term_grace: float = 10.0, received: list[str] | None = None) -> Invocation:
    """Run claude in its own process group, read it line by line, keep its end.

    The wall clock is SIGINT first: SIGINT ends the turn and the CLI still
    reports a result (cost included), while SIGTERM records none. After
    `int_grace` seconds SIGTERM, after `term_grace` more SIGKILL. Any of
    FORWARDED_SIGNALS sent to THIS process starts the same ladder, so an outer
    backstop or a closed terminal still gets a result. When the leader exits,
    whatever is left of its group is killed. A signal outside that set that
    ends this process (SIGKILL, which nothing can catch, or a fault) orphans
    claude.

    `received` is the caller's list of signal names, when it holds them
    (`held_signals`): one already there means the run was cancelled before it
    began, so claude is never started; one arriving before this installs its
    own handlers starts the ladder, and the names land in it. Only a signal
    that arrived while claude was still running is the run's `interrupted`
    (`signals_seen` counts them): one that lands after claude exited, as this
    tidies up, is left in `received` for the caller.
    """
    start = time.monotonic()
    received = [] if received is None else received
    if received:
        # cancelled while the caller was still setting up: nothing to stop,
        # and nothing spent
        if trace is not None:
            trace.close()
        return Invocation(rc=128 + signal.Signals[received[0]].value, started=False, fmt=fmt,
                          interrupted=",".join(received), signals_seen=len(received))
    # In its own session claude is not the terminal's foreground group, so an
    # inherited TTY stdin would stop it (SIGTTIN). With no prompt to send, a
    # pipe stays inherited and a terminal becomes /dev/null — `claude -p`
    # never reads a TTY for its prompt anyway.
    if prompt is not None:
        stdin = subprocess.PIPE
    else:
        try:
            stdin = subprocess.DEVNULL if os.isatty(0) else None
        except OSError:
            stdin = None
    try:
        proc = subprocess.Popen(  # noqa: S603 - argv is a list, never a shell string
            argv, cwd=str(cwd) if cwd else None, env=dict(env) if env is not None else None,
            stdin=stdin,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    except FileNotFoundError as exc:
        if trace is not None:
            trace.close()
        return Invocation(rc=127, started=False, stderr_tail=str(exc), fmt=fmt)

    lines: queue.Queue[bytes | None] = queue.Queue()
    ring: list[str] = []
    ring_len = [0]

    def feed() -> None:
        try:
            assert proc.stdin is not None
            proc.stdin.write((prompt or "").encode("utf-8"))
            proc.stdin.close()
        except (BrokenPipeError, OSError):
            return

    def read_out() -> None:
        assert proc.stdout is not None
        for raw in iter(proc.stdout.readline, b""):
            lines.put(raw)
        lines.put(None)

    def read_err() -> None:
        assert proc.stderr is not None
        for raw in iter(proc.stderr.readline, b""):
            text = raw.decode("utf-8", errors="replace")
            ring.append(text)
            ring_len[0] += len(text)
            while ring_len[0] > STDERR_RING and len(ring) > 1:
                ring_len[0] -= len(ring.pop(0))

    threads = [threading.Thread(target=read_out, daemon=True), threading.Thread(target=read_err, daemon=True)]
    if prompt is not None:
        threads.append(threading.Thread(target=feed, daemon=True))
    for t in threads:
        t.start()

    inv = Invocation(rc=0, fmt=fmt)
    ladder: list[tuple[float, int]] = []

    def begin_ladder(now: float) -> None:
        if not ladder:
            ladder.extend([(now, signal.SIGINT), (now + int_grace, signal.SIGTERM),
                           (now + int_grace + term_grace, signal.SIGKILL)])

    old_handlers: dict = {}
    if threading.current_thread() is threading.main_thread():
        def forward(signum: int, _frame: object) -> None:
            received.append(signal.Signals(signum).name)
            begin_ladder(time.monotonic())
        for sig in FORWARDED_SIGNALS:
            old_handlers[sig] = signal.signal(sig, forward)

    deadline = start + timeout_s if timeout_s else None
    out_buf: list[str] = []
    eof = False
    alive_seen = 0
    try:
        while True:
            now = time.monotonic()
            if proc.poll() is None:
                # every signal so far reached a claude that was still running
                alive_seen = len(received)
            if received and not ladder:
                # held by the caller before this process's handlers were in
                begin_ladder(now)
            if deadline is not None and now >= deadline and not ladder:
                inv.timed_out = True
                begin_ladder(now)
            while ladder and ladder[0][0] <= now:
                _, sig = ladder.pop(0)
                _signal_group(proc.pid, sig)
            if eof and proc.poll() is not None:
                break
            if not eof and proc.poll() is not None and lines.empty():
                # the leader is gone; a grandchild may still hold stdout open
                try:
                    raw = lines.get(timeout=0.5)
                except queue.Empty:
                    break
            else:
                try:
                    raw = lines.get(timeout=0.2)
                except queue.Empty:
                    continue
            if raw is None:
                eof = True
                continue
            text = raw.decode("utf-8", errors="replace")
            if fmt == "json":
                out_buf.append(text)
            _take(text, inv, trace, redactor, cap_usd, echo)
    finally:
        rc = proc.poll()
        if rc is None:
            _signal_group(proc.pid, signal.SIGKILL)
            rc = proc.wait()
        _signal_group(proc.pid, signal.SIGKILL)
        for sig, handler in old_handlers.items():
            signal.signal(sig, handler)
        for t in threads:
            t.join(timeout=1.0)
        while True:
            try:
                raw = lines.get_nowait()
            except queue.Empty:
                break
            if raw is not None:
                text = raw.decode("utf-8", errors="replace")
                if fmt == "json":
                    out_buf.append(text)
                _take(text, inv, trace, redactor, cap_usd, echo)
        if trace is not None:
            trace.close()
    inv.rc = rc
    inv.duration_s = round(time.monotonic() - start, 3)
    inv.stderr_tail = redactor.text("".join(ring))
    inv.signals_seen = alive_seen
    inv.interrupted = ",".join(received[:alive_seen])
    if fmt == "json":
        inv.stdout_text = redactor.text("".join(out_buf))
        inv.result = inv.result or last_result("".join(out_buf))
    return inv


def _take(text: str, inv: Invocation, trace: Trace | None, redactor: Redactor, cap_usd: float,
          echo: IO[str] | None) -> None:
    stripped = text.strip()
    if not stripped:
        return
    try:
        event = json.loads(stripped)
    except json.JSONDecodeError:
        if inv.fmt != "json":
            inv.garbage_lines += 1
            inv.stdout_noise = (inv.stdout_noise + redactor.text(stripped)[:ECHO_TEXT] + "\n")[-NOISE_CAP:]
        if trace is not None:
            trace.write(None, stripped)
        return
    if trace is not None:
        trace.write(event, stripped)
    if not isinstance(event, dict):
        return
    kind = event.get("type")
    if kind == "system" and event.get("subtype") == "init":
        inv.init = event
    elif kind == "system" and event.get("subtype") == "api_retry":
        if re.search(r"rate.?limit|429", json.dumps(event), re.I):
            inv.rate_limited = True
    elif kind == "result":
        inv.result = event
        inv.permission_denials = len(event.get("permission_denials") or [])
    elif kind == "assistant":
        for block in (event.get("message") or {}).get("content") or []:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                name = str(block.get("name") or "?")
                inv.tool_uses[name] = inv.tool_uses.get(name, 0) + 1
    if echo is not None and not inv.echo_lost:
        try:
            for line in condensed(event, cap_usd, redactor):
                echo.write(f"  {line}\n")
            echo.flush()
        except OSError:
            # EIO/EPIPE once the terminal is gone: losing the tee must not end
            # the read loop, whose finally would SIGKILL claude before its result
            inv.echo_lost = True


# --------------------------------------------------------------------------- #
# classifying
# --------------------------------------------------------------------------- #
@dataclass
class Outcome:
    """What one invocation came to, and what it is charged."""

    kind: str
    cost_usd: float
    cost_source: str
    session_id: str | None = None
    turns: int = 0
    models: list[str] = field(default_factory=list)
    detail: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


def classify(inv: Invocation, cap_usd: float, redactor: Redactor | None = None) -> Outcome:
    """The invocation's outcome, in claude-cost's order (budget, usage limit,
    credential, then agent failure), plus the cases only a local run has.

    Charge-at-cap: a run that may have spent but left no figure is charged the
    cap as `estimated` (HUB-032 — a run whose cost cannot be read is otherwise a
    run charged to nobody). `no-spend` only where the model was provably never
    reached: no process; under stream-json, no init event (the CLI prints it
    before any request); under json, no output and the CLI's own argv refusal
    as the first stderr line (STARTUP_ERROR_RX).

    With a `redactor`, the result message is redacted BEFORE it is clipped to
    the detail's 200 characters, so a cut secret cannot survive as a prefix.

    A forwarded signal (Ctrl-C, a console cancel, a hangup) is read like the
    wall clock, BEFORE the usage-limit and credential tests: a turn aborted before
    its first response reports $0 and an empty modelUsage — the
    credential-rejected signature — for a request that was in flight.
    """
    if not inv.started:
        if inv.interrupted:
            return Outcome("interrupted", 0.0, "no-spend",
                           detail=f"stopped by {inv.interrupted} before claude was started")
        return Outcome("cli_missing", 0.0, "no-spend", detail=_one_line(inv.stderr_tail, 200))
    r = inv.result
    stopped_by = f"stopped by {inv.interrupted}" if inv.interrupted else ""
    if r is None:
        sid = (inv.init or {}).get("session_id")
        if inv.timed_out:
            return Outcome("timeout", cap_usd, "estimated", sid, detail="the wall clock stopped it before a result")
        if inv.interrupted:
            return Outcome("interrupted", cap_usd, "estimated", sid,
                           detail=f"{stopped_by} before a result; charged at the cap")
        first = next((line.strip() for line in (inv.stderr_tail or "").splitlines() if line.strip()), "")
        startup = not inv.init and not inv.stdout_text.strip() and STARTUP_ERROR_RX.search(first)
        if inv.init or (inv.fmt == "json" and not startup):
            started = ("after the session started" if inv.init
                       else "and json output cannot show whether the session started")
            return Outcome("unparseable", cap_usd, "estimated", sid,
                           detail=f"no result record {started}; charged at the cap")
        return Outcome("startup_failed", 0.0, "no-spend",
                       detail=_one_line(inv.stderr_tail, 200) or f"exit {inv.rc} before init")
    cost = float(r.get("total_cost_usd") or 0.0)
    subtype = str(r.get("subtype") or "")
    is_error = bool(r.get("is_error"))
    usage = r.get("modelUsage")
    models = sorted(usage) if isinstance(usage, dict) else []
    base = dict(session_id=r.get("session_id"), turns=int(r.get("num_turns") or 0), models=models)
    text = str(r.get("result") or "")
    message = _one_line(redactor.text(text) if redactor is not None else text, 200)
    if "budget" in subtype.lower() or (is_error and cap_usd > 0 and cost >= cap_usd):
        return Outcome("budget_hit", cost, "reported", detail=f"stopped at ${cost:.4f} of ${cap_usd:g}", **base)
    if inv.timed_out:
        return Outcome("timeout", cost, "reported", detail="the wall clock stopped it; the turn ended", **base)
    if inv.interrupted:
        return Outcome("interrupted", cost, "reported", detail=f"{stopped_by}; the turn ended", **base)
    status = str(r.get("api_error_status") or "")
    if is_error and (status == "429" or USAGE_LIMIT_RX.search(message) or inv.rate_limited):
        return Outcome("usage_limit", cost, "reported", detail=message or "HTTP 429", **base)
    if is_error and cost == 0 and not models:
        return Outcome("credential_rejected", 0.0, "no-spend", detail=message or "the model was never reached",
                       **base)
    if subtype == "error_max_turns":
        return Outcome("max_turns", cost, "reported", detail=f"{base['turns']} turns", **base)
    if is_error or subtype.startswith("error"):
        return Outcome("agent_error", cost, "reported", detail=message or subtype, **base)
    return Outcome("ok", cost, "reported", **base)


# --------------------------------------------------------------------------- #
# the debug log
# --------------------------------------------------------------------------- #
#: The CLI skips a `--settings` document that fails validation (or is not JSON)
#: and, under json or stream-json output, says so ONLY in the debug log — the
#: run then goes ahead without its sandbox.
SETTINGS_SKIPPED_RX = re.compile(r"Invalid setting skipped|did not load|Invalid or malformed JSON")
#: cc-plugin-agents-md under --safe-mode: no CLAUDE.md / AGENTS.md is loaded.
MEMORY_OFF_RX = re.compile(r"project memory is off")
DEBUG_KEEP_RX = re.compile(r"\[Sandbox|settingsEnv keys|flagSettings|"
                           + SETTINGS_SKIPPED_RX.pattern + "|" + MEMORY_OFF_RX.pattern)


def reduce_debug_log(path: Path, *, delete: bool = True) -> list[str]:
    """The few debug lines worth keeping (sandbox, settings env, flag rules, a
    skipped settings document, memory off); the full log — which can hold
    paths and prompt fragments — is deleted."""
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    if delete:
        p.unlink(missing_ok=True)
    return [line for line in text.splitlines() if DEBUG_KEEP_RX.search(line)]


def sandbox_engaged(lines: Iterable[str]) -> bool:
    return any(SANDBOX_LINE_RX.search(line) for line in lines)


def init_problems(init: Mapping, expected_tools: Iterable[str]) -> list[str]:
    """Pure and fail-closed: what a session's own init record shows that the
    isolation posture forbids — exactly the spec's tool families, nothing
    never-grantable or outside GRANTABLE_TOOLS, `dontAsk`, no MCP server, no skill, the default output
    style. The probe's isolated run is held to it, and so (PR-C) is every
    attempt's init before its output is read."""
    problems: list[str] = []
    expected = set(expected_tools)
    tools = set(init.get("tools") or [])
    if tools != expected:
        problems.append(f"tools {sorted(tools)} != {sorted(expected)}")
    if tools & NEVER_GRANTABLE_TOOLS:
        problems.append(f"never-grantable tools {sorted(tools & NEVER_GRANTABLE_TOOLS)}")
    outside = tools - GRANTABLE_TOOLS - NEVER_GRANTABLE_TOOLS
    if outside:
        problems.append(f"tools outside the grantable families {sorted(outside)}")
    if init.get("permissionMode") != "dontAsk":
        problems.append(f"permissionMode {init.get('permissionMode')!r}, not dontAsk")
    if init.get("mcp_servers"):
        problems.append(f"MCP servers {init.get('mcp_servers')!r}")
    if init.get("skills"):
        problems.append(f"skills {init.get('skills')!r}")
    if init.get("output_style") != "default":
        problems.append(f"output_style {init.get('output_style')!r} — a settings file was read")
    return problems


# --------------------------------------------------------------------------- #
# the $0 probes
# --------------------------------------------------------------------------- #
def probe_env(scratch: Path, environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """The $0 probes' environment: what agent_env builds for a run — so the
    probes test the environment a run actually gets — with no credential and
    a scratch, logged-out CLAUDE_CONFIG_DIR. Whatever `environ` holds goes
    through agent_env's allowlist, so no credential or config dir survives."""
    scratch = Path(scratch)
    tmp, gh_none, cfg = scratch / "tmp", scratch / "gh-none", scratch / "config"
    for d in (tmp, gh_none, cfg):
        d.mkdir(parents=True, exist_ok=True)
    env = agent_env(os.environ if environ is None else environ, None, credential_value=None, tmp=tmp,
                    gh_config_dir=gh_none)
    env["CLAUDE_CONFIG_DIR"] = str(cfg)
    return env


def _logged_in(claude_bin: str, env: Mapping[str, str]) -> bool | None:
    """`claude auth status` under `env` (no model request); None if unreadable."""
    try:
        proc = subprocess.run([claude_bin, "auth", "status", "--json"], env=dict(env), stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=30, check=False)
        data = json.loads(proc.stdout or "{}")
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return None
    return bool(data.get("loggedIn")) if isinstance(data, dict) else None


def preflight_parse(claude_bin: str, flags: list[str], cwd: Path | None = None,
                    environ: Mapping[str, str] | None = None) -> str | None:
    """$0: the real argv with stdin /dev/null must answer "Input must be
    provided", and nothing it prints or logs may report its `--settings`
    document skipped.

    The CLI validates every option before it reads input, so this proves each
    flag parses — the hidden --max-turns included — on THIS CLI version. Under
    `-p` a settings document that fails validation is skipped with nothing but
    a debug-log line, so the debug log is read too. This is a NEGATIVE check:
    a debug log that was never written passes it. The positive proof that the
    rules loaded (a `flagSettings` line) is the isolation probe's, and only
    the canary proves which settings keys the CLI enforces (unknown keys are
    dropped silently).

    What keeps it at $0: stdin /dev/null and the probe environment (no
    credential, a scratch CLAUDE_CONFIG_DIR), refused outright when that
    environment is logged in. `flags` must carry print mode and the dollar cap
    (`run_prefix(...) + claude_flags(...)`), so not even a stray positional
    could run uncapped. None means the argv parses and no settings document
    was reported skipped; otherwise the problem, naming the flag or the
    settings line.
    """
    if not {"-p", "--print"} & set(flags) or "--max-budget-usd" not in flags:
        return "refusing to preflight: flags must carry -p and --max-budget-usd (run_prefix + claude_flags)"
    scratch = Path(tempfile.mkdtemp(prefix="jev-preflight-"))
    try:
        env = probe_env(scratch, environ)
        logged_in = _logged_in(claude_bin, env)
        if logged_in is None:
            return f"could not read the preflight environment's auth status with {claude_bin}"
        if logged_in:
            return "the preflight environment is logged in — refusing: the preflight must not be able to spend"
        argv = [claude_bin, *flags]
        if "--debug-file" in flags:
            debug = Path(flags[flags.index("--debug-file") + 1])
        else:
            debug = scratch / "preflight.debug.log"
            argv += ["--debug-file", str(debug)]
        debug.unlink(missing_ok=True)
        try:
            proc = subprocess.run(argv, cwd=str(cwd) if cwd else None, env=env, stdin=subprocess.DEVNULL,
                                  capture_output=True, text=True, timeout=60, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return f"could not run {claude_bin}: {exc}"
        finally:
            # the run starts with a clean log
            kept = reduce_debug_log(debug)
        said = f"{proc.stdout}\n{proc.stderr}"
        skipped = next((line.strip() for line in [*said.splitlines(), *kept] if SETTINGS_SKIPPED_RX.search(line)),
                       None)
        if skipped:
            return f"the --settings document did not load: {_one_line(skipped, 240)}"
        if INPUT_REQUIRED in said:
            return None
        first = next((line.strip() for line in said.splitlines() if line.strip()), f"exit {proc.returncode}")
        return f"the CLI refused the argv: {first}"
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


@dataclass
class ProbeResult:
    ok: bool
    problems: list[str]
    facts: dict


@dataclass
class ProbeRun:
    """One probe session: its events, its debug lines, which markers appeared."""

    events: list[dict]
    debug: list[str]
    markers: dict[str, bool]
    result: dict | None = None

    @property
    def init(self) -> dict:
        return next((e for e in self.events if e.get("type") == "system" and e.get("subtype") == "init"), {})

    @property
    def hook_events(self) -> int:
        return sum(1 for e in self.events if e.get("type") == "system"
                   and str(e.get("subtype") or "").startswith("hook_"))


class _Collect(Trace):
    """A Trace that keeps the parsed events in memory instead of on disk."""

    def __init__(self) -> None:
        super().__init__(None, Redactor({}))
        self.events: list[dict] = []

    def write(self, event: object | None, raw: str) -> None:
        if isinstance(event, dict):
            self.events.append(event)


PROBE_OUTPUT_STYLE = "Explanatory"
PROBE_SKILL = "jev-probe"
PROBE_ENV_NAME = "JEV_PROBE_ENV"
PROBE_PROMPT = "Reply with the single word ok.\n"


def build_probe_fixture(root: Path) -> dict[str, Path]:
    """A directory that plants what isolation must keep out: a project
    SessionStart hook, an `env` block and an output style in .claude/settings.json,
    a project .mcp.json server, a project skill, and CLAUDE.md and AGENTS.md
    sentinels. Each hook or server touches a marker file when it runs."""
    root = Path(root)
    (root / ".claude" / "skills" / PROBE_SKILL).mkdir(parents=True, exist_ok=True)
    markers = {"hook": root / ".hook-fired", "mcp": root / ".mcp-started"}
    for m in markers.values():
        m.unlink(missing_ok=True)
    (root / ".claude" / "settings.json").write_text(json.dumps({
        "hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": f"touch {markers['hook']}"}]}]},
        "env": {PROBE_ENV_NAME: "1"},
        "outputStyle": PROBE_OUTPUT_STYLE,
    }, indent=2), encoding="utf-8")
    (root / ".mcp.json").write_text(json.dumps({"mcpServers": {"jev-probe": {
        "command": "/bin/sh", "args": ["-c", f"touch {markers['mcp']}; sleep 2"]}}}, indent=2), encoding="utf-8")
    (root / ".claude" / "skills" / PROBE_SKILL / "SKILL.md").write_text(
        f"---\nname: {PROBE_SKILL}\ndescription: isolation probe sentinel\n---\nSay JEV-PROBE-SKILL.\n",
        encoding="utf-8")
    for memory in ("CLAUDE.md", "AGENTS.md"):
        (root / memory).write_text(f"JEV-PROBE-{memory} sentinel: reply with JEV-PROBE.\n", encoding="utf-8")
    return markers


def _names(items: object) -> set[str]:
    out: set[str] = set()
    for s in items if isinstance(items, list) else []:
        name = s.get("name") if isinstance(s, dict) else s
        if name:
            out.add(str(name))
    return out


def judge_probe(control: ProbeRun, isolated: ProbeRun, expected_tools: Iterable[str]) -> ProbeResult:
    """Pure. The control must SHOW what was planted — the hook, the MCP server,
    the output style and the skill — or the detectors are stale and nothing
    they say can be trusted. The isolated run must show none of it: its init
    passes `init_problems`, no hook or server ran, the planted `env` block is
    not in its settings env, its debug log shows the --settings rules applied,
    nothing skipped, and project memory (CLAUDE.md, AGENTS.md) off.

    Not judged, because nothing at $0 shows it: whether memory CONTENT reached
    the model, and user-scope settings (the probe's config dir is a scratch
    one). Those rest on the documented `--restricted`, `--safe-mode` and
    `--strict-mcp-config` semantics, and on the canary."""
    problems: list[str] = []
    c, i = control.init, isolated.init
    for run, label in ((control, "control"), (isolated, "isolated")):
        r = run.result or {}
        if not r or float(r.get("total_cost_usd") or 0) != 0 or r.get("modelUsage"):
            problems.append(f"{label}: the probe must run credential-free at $0 (got "
                            f"{'no result' if not r else '$' + str(r.get('total_cost_usd'))})")
    stale = []
    if not (control.hook_events or control.markers.get("hook")):
        stale.append("the planted SessionStart hook did not fire")
    if not any(isinstance(s, dict) and s.get("source") == "project" for s in c.get("mcp_servers") or []) \
            and not control.markers.get("mcp"):
        stale.append("the planted .mcp.json server was not attempted")
    if c.get("output_style") != PROBE_OUTPUT_STYLE:
        stale.append(f"init.output_style is {c.get('output_style')!r}, not the planted {PROBE_OUTPUT_STYLE!r}")
    if PROBE_SKILL not in _names(c.get("skills")):
        stale.append(f"init.skills does not list the planted {PROBE_SKILL!r}")
    if stale:
        problems.append("detector stale — the control run shows nothing it planted: " + "; ".join(stale))
    if isolated.hook_events or isolated.markers.get("hook"):
        problems.append("isolated: a project hook ran")
    if isolated.markers.get("mcp"):
        problems.append("isolated: the planted MCP server started")
    problems += [f"isolated: {p}" for p in init_problems(i, expected_tools)]
    if any("settingsEnv keys" in line and PROBE_ENV_NAME in line for line in isolated.debug):
        problems.append(f"isolated: the planted env block ({PROBE_ENV_NAME}) was applied")
    if not any("flagSettings" in line for line in isolated.debug):
        problems.append("isolated: no flagSettings line in the debug log (were the --settings rules applied?)")
    skipped = [line for line in isolated.debug if SETTINGS_SKIPPED_RX.search(line)]
    if skipped:
        problems.append(f"isolated: the --settings document did not load: {_one_line(skipped[0], 200)}")
    if not any(MEMORY_OFF_RX.search(line) for line in isolated.debug):
        problems.append("isolated: no 'project memory is off' line in the debug log (CLAUDE.md / AGENTS.md loaded?)")
    tools = set(i.get("tools") or [])
    facts = {"tools": sorted(tools), "permission_mode": i.get("permissionMode"),
             "cli_version": i.get("claude_code_version"), "control_style": c.get("output_style")}
    return ProbeResult(ok=not problems, problems=problems, facts=facts)


def probe_isolation(claude_bin: str, flags_for: Callable[[Path], list[str]], scratch: Path, *,
                    expected_tools: Iterable[str], timeout_s: float = 120.0) -> ProbeResult:
    """$0 and self-calibrating: the planted fixture, run plain (the control) and
    with the isolation flags. Credential-free — `probe_env`, the run's own
    environment minus the credential, with a scratch CLAUDE_CONFIG_DIR — and
    refused outright if that environment is logged in, because then it could
    spend."""
    scratch = Path(scratch)
    fixture = scratch / "fixture"
    markers = build_probe_fixture(fixture)
    env = probe_env(scratch)
    logged_in = _logged_in(claude_bin, env)
    if logged_in is None:
        return ProbeResult(False, [f"could not read the probe environment's auth status with {claude_bin}"], {})
    if logged_in:
        return ProbeResult(False, ["the probe environment is logged in — refusing: the probe must not spend"], {})

    def one(label: str, flags: list[str]) -> ProbeRun:
        for m in markers.values():
            m.unlink(missing_ok=True)
        debug = scratch / f"{label}.debug.log"
        argv = [claude_bin, *run_prefix(0.01, stream=True), *flags]
        if "--debug-file" not in flags:
            argv += ["--debug-file", str(debug)]
        sink = _Collect()
        inv = stream(argv, prompt=PROBE_PROMPT, cwd=fixture, env=env, timeout_s=timeout_s,
                     trace=sink, redactor=sink.redactor, cap_usd=0.01)
        events = sink.events
        time.sleep(0.5)
        debug_path = Path(flags[flags.index("--debug-file") + 1]) if "--debug-file" in flags else debug
        return ProbeRun(events=events, debug=reduce_debug_log(debug_path), result=inv.result,
                        markers={k: m.exists() for k, m in markers.items()})

    control = one("control", [])
    isolated = one("isolated", flags_for(scratch / "isolated.debug.log"))
    return judge_probe(control, isolated, expected_tools)


def at_least(version: tuple[int, int, int] | None, floor: tuple[int, int, int] = MIN_CLI) -> bool:
    return version is not None and version >= floor


def write_json(path: Path | str | None, obj: object) -> None:
    if not path:
        return
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")
