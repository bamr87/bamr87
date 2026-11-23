"""
core_auth — the console's credential layer: a section of core's logic, in its
own file.

  AUTH       credentials supplied through the UI: held in this process's
             environment (which is what a job inherits), optionally written to
             the gitignored .env or handed to `gh auth login` over stdin, and
             never returned, logged, or placed in an argv.

The section's two switches, AUTH_WRITES and ENV_FILE, stay in core.py: tests
rebind both there, and core's `_keys_rotate` and `_secrets_push`,
core_adapters' `capabilities` and github_link.py read AUTH_WRITES from it.

core.py loads this module at its end and re-exports every name in it, so callers
keep writing `core.<name>`. What core owns (its paths, constants and helpers, the
OPS table, and every name a test or tools/evals.py rebinds) is read here as
`core.<name>` at the moment of the call, never copied, so rebinding one on core
reaches this code as it did when this was a section of core.py. To replace a
name DEFINED here, patch it on this module: this file calls its own names directly.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

if "core" not in sys.modules:  # the order is a rule, not luck: core loads this module at its end
    raise ImportError("core_auth is a section of core: import core, which loads it and re-exports its names")
import core  # noqa: E402


# --------------------------------------------------------------------------- #
# AUTH — credentials supplied through the UI, held for this console's jobs
# --------------------------------------------------------------------------- #
# The console used to be able to say it never held a credential: jobs inherited
# the environment and the UI only ever reported which NAMES were present. That
# is still the default, but "open the console and it tells you gh is not
# authenticated, now go find a terminal" is a dead end on the one surface meant
# to be self-sufficient. So the console can now RECEIVE a credential:
#
#   * values arrive only over the loopback-guarded API (Host allowlist +
#     optional DASH_CONSOLE_TOKEN), never in a URL, never in argv, never in a
#     job's command line, and are never returned, logged, or echoed back — the
#     status document reports presence and provenance only;
#   * a value set here lives in this PROCESS's environment, which is exactly
#     what a job inherits, and dies with the process;
#   * writing one to disk (.env, gitignored, 0600) is a separate, explicitly
#     confirmed step — the same confirm gate the GitHub-writing operations use;
#   * a GitHub token can be handed to `gh auth login --with-token` over STDIN
#     so the CLI's own credential store keeps it instead of this process;
#   * DASH_CONSOLE_AUTH=off refuses every credential write, for a console
#     fronted by anything less private than loopback.
# (AUTH_WRITES and ENV_FILE are core.py's: read here as core.AUTH_WRITES and core.ENV_FILE.)

# Printable, no whitespace — every credential the fleet uses is opaque ASCII.
SECRET_RX = re.compile(r"^[\x21-\x7e]{8,4096}$")
# What can be written to .env unquoted; anything else is single-quoted.
ENV_PLAIN_RX = re.compile(r"^[A-Za-z0-9_.:/@+=-]+$")

CREDENTIALS: dict[str, dict] = {
    "FLEET_TOKEN": {
        "label": "GitHub fine-grained PAT (fleet-wide)",
        "help": "Cross-repo PRs, fan-outs and secret writes. Needs contents + pull-requests + "
                "workflows write, and secrets:write for the rotation loop. GITHUB_TOKEN cannot "
                "stand in: GitHub fires no workflow events for refs it pushes.",
        "url": "https://github.com/settings/personal-access-tokens",
    },
    "GH_TOKEN": {
        "label": "GitHub token for the gh CLI",
        "help": "Read-only analytics work fine with this. Note that gh prefers it over its own "
                "stored login, so setting it here shadows a `gh auth login`.",
        "url": "https://github.com/settings/tokens",
    },
    "GITHUB_TOKEN": {
        "label": "GitHub token (Actions-style name)",
        "help": "Same role as GH_TOKEN; what the dash-gen generators read when GH_TOKEN is unset.",
        "url": "https://github.com/settings/tokens",
    },
    "GITHUB_OAUTH_CLIENT_ID": {
        "label": "GitHub OAuth App client ID",
        "help": "The console's own OAuth App (GitHub page → Connect). The ID alone runs the device flow — "
                "tick “Enable Device Flow” in the app. Register the callback as "
                "http://127.0.0.1/api/github/oauth/callback for the browser flow.",
        "url": "https://github.com/settings/applications/new",
    },
    "GITHUB_OAUTH_CLIENT_SECRET": {
        "label": "GitHub OAuth App client secret",
        "help": "Only the browser (redirect) flow needs it, and revoking a token on disconnect. The device "
                "flow works without it.",
        "url": "https://github.com/settings/developers",
    },
    "CLAUDE_CODE_OAUTH_TOKEN": {
        "label": "Claude Code OAuth token",
        "help": "Mint it in a terminal with a browser — `claude setup-token` — then paste it here. "
                "It is the fleet's canonical Claude credential (one-year lifetime, propagated "
                "weekly by token-rotation.yml).",
        "url": "https://docs.claude.com/en/docs/claude-code/github-actions",
    },
    "ANTHROPIC_API_KEY": {
        "label": "Anthropic API key",
        "help": "The fallback at every claude-code-action call site when the OAuth token is absent.",
        "url": "https://console.anthropic.com/settings/keys",
    },
    "CLAUDE_CONSOLE_TOKEN": {
        "label": "Claude Console admin credential",
        "help": "A service-account key NOT scoped to a workspace (or an sk-ant-admin key). `dash keys` reads "
                "the Console's workspaces and key expiry with it and disables a replaced key. It cannot "
                "create keys and must never reach a fleet repo.",
        "url": "https://platform.claude.com/settings/service-accounts",
    },
    "PHOENIX_API_KEY": {
        "label": "Phoenix API key",
        "help": "Only needed for a Phoenix instance that requires auth; forwarded by "
                "`lake export` and never shown.",
        "url": "https://docs.arize.com/phoenix",
    },
}

# Names this process set at runtime, so the UI can distinguish "you typed this"
# from "it was in the environment when the console started".
_SESSION_CREDS: set[str] = set()
_SCRUB_RX = re.compile(r"\b(gh[pousr]_[A-Za-z0-9]+|github_pat_[A-Za-z0-9_]+|sk-[A-Za-z0-9\-_]+)")


def _scrub(text: str) -> str:
    """Never let a tool's own output carry a credential into a response."""
    out = []
    for line in (text or "").splitlines():
        if re.search(r"Token:\s*\S", line):
            continue
        out.append(_SCRUB_RX.sub("«redacted»", line))
    return "\n".join(out).strip()


def _env_file_names(path: Path | None = None) -> set[str]:
    """Which credential names the .env file declares (names only — never read a value)."""
    path = path or core.ENV_FILE                    # resolved per call, so tests can redirect it
    if not path.exists():
        return set()
    names = set()
    try:
        for line in path.read_text().splitlines():
            m = re.match(r"^\s*(?:export\s+)?([A-Z][A-Z0-9_]*)\s*=", line)
            if m and m.group(1) in CREDENTIALS:
                names.add(m.group(1))
    except OSError:
        return set()
    return names


def _env_file_set_names(path: Path | None = None) -> set[str]:
    """Every name the .env file assigns a NON-EMPTY value — the value itself is never kept."""
    path = path or core.ENV_FILE
    names = set()
    try:
        for line in path.read_text().splitlines():
            m = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(\S?)", line)
            if m and m.group(2) and m.group(2) != "#":
                names.add(m.group(1))
    except OSError:
        return set()
    return names


def _env_file_upsert(name: str, value: str | None, path: Path | None = None) -> None:
    """Set (or, with value=None, remove) one name in the .env file, 0600."""
    path = path or core.ENV_FILE
    lines = path.read_text().splitlines() if path.exists() else []
    rx = re.compile(rf"^\s*(?:export\s+)?{re.escape(name)}\s*=")
    kept = [ln for ln in lines if not rx.match(ln)]
    if value is not None:
        if "'" in value:
            raise ValueError(f"{name} contains a quote the console will not write to .env")
        rendered = value if ENV_PLAIN_RX.match(value) else f"'{value}'"
        kept.append(f"{name}={rendered}")
    body = "\n".join(kept).rstrip("\n") + "\n" if kept else ""
    fd = os.open(str(path), os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(body)
    try:
        os.chmod(path, 0o600)
    except OSError:                            # pragma: no cover - unusual filesystems
        pass


def _gh_status() -> dict:
    """What `gh auth status` says, as fields — never as its raw text."""
    if not shutil.which("gh"):
        return {"cli": False, "authenticated": None, "account": None, "host": None,
                "scopes": [], "protocol": None, "env_token": None, "message":
                "the gh CLI is not installed in the console's environment"}
    rc, out = core.run_quiet(["gh", "auth", "status"], timeout=20)
    account = re.search(r"account\s+([A-Za-z0-9-]+)", out)
    host = re.search(r"Logged in to (\S+)", out)
    scopes = re.search(r"Token scopes:\s*(.+)", out)
    protocol = re.search(r"Git operations protocol:\s*(\S+)", out)
    return {
        "cli": True,
        "authenticated": rc == 0,
        "account": account.group(1) if account else None,
        "host": host.group(1) if host else None,
        "scopes": sorted({s.strip().strip("'\"") for s in scopes.group(1).split(",")}) if scopes else [],
        "protocol": protocol.group(1) if protocol else None,
        # gh prefers an environment token over its stored login, and refuses to
        # store one while it is set — worth saying out loud rather than letting
        # a login mysteriously not take.
        "env_token": next((n for n in ("GH_TOKEN", "GITHUB_TOKEN") if os.environ.get(n)), None),
        "message": _scrub(out),
    }


def auth_status() -> dict:
    """Presence and provenance of every credential — never a value or a prefix."""
    in_file = _env_file_names()
    supplied = _env_file_set_names() if core.ENV_FILE.exists() else set()
    creds = []
    for name, spec in CREDENTIALS.items():
        present = bool(os.environ.get(name))
        creds.append({
            "name": name, "label": spec["label"], "help": spec["help"], "url": spec["url"],
            "present": present,
            "source": ("session" if name in _SESSION_CREDS else "environment") if present else None,
            "in_env_file": name in in_file,
        })
    rc_tracked, tracked = core.run_quiet(["git", "ls-files", "--error-unmatch", str(core.ENV_FILE)])
    return {
        "credentials": creds,
        "github": _gh_status(),
        "claude": {"cli": shutil.which("claude") is not None,
                   "oauth": bool(os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")),
                   "api_key": bool(os.environ.get("ANTHROPIC_API_KEY")),
                   "mint": "claude setup-token"},
        "env_file": {"path": str(core.ENV_FILE), "exists": core.ENV_FILE.exists(),
                     "tracked_by_git": rc_tracked == 0, "names": sorted(in_file)},
        # What `dash secrets push` would take from .env: the contract's names,
        # each with its scope and whether the file supplies a value for it.
        "push": [{**t, "in_env_file": t["name"] in supplied} for t in core.contract_secrets()],
        "writes_enabled": core.AUTH_WRITES,
        "console_token_required": bool(os.environ.get("DASH_CONSOLE_TOKEN")),
    }


def _check_writes() -> None:
    if not core.AUTH_WRITES:
        raise PermissionError("credential writes are disabled (DASH_CONSOLE_AUTH=off)")


def set_credential(name: str, value: str, persist: bool = False, confirm: bool = False) -> dict:
    """Hold a credential for this console's jobs; optionally write it to .env.

    The value reaches the process environment — which is precisely what
    JobManager hands a subprocess — and nothing else, unless `persist` is asked
    for AND confirmed, because that one writes a secret to the disk of a repo.
    """
    _check_writes()
    if name not in CREDENTIALS:
        raise ValueError(f"unknown credential '{name}' — one of {sorted(CREDENTIALS)}")
    value = (value or "").strip()
    if not SECRET_RX.match(value):
        raise ValueError(f"{name} must be 8-4096 printable characters with no whitespace")
    if persist:
        if not confirm:
            raise PermissionError(f"writing {name} to {core.ENV_FILE.name} needs confirm=true")
        rc, _ = core.run_quiet(["git", "ls-files", "--error-unmatch", str(core.ENV_FILE)])
        if rc == 0:
            raise ValueError(f"{core.ENV_FILE} is tracked by git — the console will not write a "
                             "credential into a tracked file")
        _env_file_upsert(name, value)
    os.environ[name] = value
    _SESSION_CREDS.add(name)
    return auth_status()


def clear_credential(name: str, purge: bool = False) -> dict:
    """Drop a credential from this process (and, with purge, from .env)."""
    _check_writes()
    if name not in CREDENTIALS:
        raise ValueError(f"unknown credential '{name}'")
    os.environ.pop(name, None)
    _SESSION_CREDS.discard(name)
    if purge and core.ENV_FILE.exists():
        _env_file_upsert(name, None)
    return auth_status()


def gh_login(token: str) -> dict:
    """Hand a token to `gh auth login --with-token` over stdin.

    Stdin, not argv: a command line is visible to every process on the machine
    and would land in this console's own job log. The environment's GH_TOKEN /
    GITHUB_TOKEN are stripped for the call because gh refuses to store a login
    while either is set.
    """
    _check_writes()
    if not shutil.which("gh"):
        raise RuntimeError("the gh CLI is not installed in the console's environment")
    token = (token or "").strip()
    if not SECRET_RX.match(token):
        raise ValueError("the token must be 8-4096 printable characters with no whitespace")
    env = {k: v for k, v in os.environ.items() if k not in ("GH_TOKEN", "GITHUB_TOKEN")}
    try:
        proc = subprocess.run(
            ["gh", "auth", "login", "--hostname", "github.com",
             "--git-protocol", "https", "--with-token"],
            input=token, text=True, capture_output=True, timeout=60,
            cwd=str(core.REPO_ROOT), env=env)
    except subprocess.TimeoutExpired:
        raise RuntimeError("gh auth login timed out")
    ok = proc.returncode == 0
    return {"ok": ok, "message": _scrub((proc.stdout or "") + (proc.stderr or "")) or
            ("signed in" if ok else "gh refused the token"), "auth": auth_status()}


def gh_logout() -> dict:
    """Drop the gh CLI's stored login for github.com (never touches .env)."""
    _check_writes()
    if not shutil.which("gh"):
        raise RuntimeError("the gh CLI is not installed in the console's environment")
    try:
        proc = subprocess.run(["gh", "auth", "logout", "--hostname", "github.com"],
                              stdin=subprocess.DEVNULL, capture_output=True, text=True,
                              timeout=30, cwd=str(core.REPO_ROOT))
    except subprocess.TimeoutExpired:
        raise RuntimeError("gh auth logout timed out (it wanted an answer the console can't give)")
    return {"ok": proc.returncode == 0,
            "message": _scrub((proc.stdout or "") + (proc.stderr or "")) or "signed out",
            "auth": auth_status()}
