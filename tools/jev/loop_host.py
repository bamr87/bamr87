#!/usr/bin/env python3
"""
File: tools/jev/loop_host.py
Description: The loop runner's gates and host checks (tools/jev/loop.py; #486,
             ADR 0002 P1). Gates: a step's kill switch read the way CI reads
             it (`gates`), `_data/fleet.yml` `switches:` (§ 17, the most
             restrictive level wins) and the fleet-wide pause
             `vars.FLEET_AGENTS_PAUSED`, which every run that could spend or
             file honours (`pause_gate`). The host: what it proves before an
             attempt (`host_check`: the work root, the CLI floor, the sandbox,
             the $0 flag preflight, the cached isolation probe and canary, the
             credential) as a `HostReport`, the cache keys those passes are
             stored under, and a branch's HEAD (`head_sha`); and after an
             attempt, why its session cannot be trusted to have run in that
             posture (`posture_breach`, checked before any output is read).
             Nothing here reaches a model. Moved here from loop.py unchanged
             but for one qualification: `sandbox_available` is a seam tests
             replace, so it stays in loop.py and `host_check` reaches it as
             `engine.sandbox_available`. loop.py re-exports every name.
Author: bamr87
Created: 2026-11-22
Version: 0.1.0
Usage: imported by tools/jev/loop.py (and loop_canary.py, for `HostReport`).
       Callers outside the engine import these names from tools.jev.loop.
Dependencies: Python 3.12 stdlib; gh for the switch and HEAD reads; the claude
              CLI for the flag preflight (stdin /dev/null, no model).
"""
from __future__ import annotations

import os
import re
import shutil
import sys
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from . import headless
from .common import JevError, gh, hub_repo
from .loop_common import EXIT, read_json, runs_dir, severest, write_json
from .spec import StepSpec, fleet_value

if TYPE_CHECKING:   # annotations only: the engine imports this module, never the reverse
    from .loop import RunContext

#: § 17's fleet-wide agent pause (bamr87/bamr87#511): any case of 'true' pauses
#: every agent step, as a workflow's `vars.FLEET_AGENTS_PAUSED != 'true'` reads it.
#: The engine only reads it (`gh variable get`), never sets it.
PAUSE_VARIABLE = "FLEET_AGENTS_PAUSED"
SANDBOX_EXEC = Path("/usr/bin/sandbox-exec")


# --------------------------------------------------------------------------- #
# gates: the kill switch, the switch map and the fleet-wide pause
# --------------------------------------------------------------------------- #
def gates(ctx: RunContext) -> tuple[int, str] | None:
    """The kill switch, read the way CI reads it — GitHub compares strings
    ignoring case, so 'True' arms an `== 'true'` gate and 'FALSE' trips a
    `!= 'false'` one. (exit code, message) to stop."""
    sw = ctx.spec.local.switch
    if sw is None:
        if ctx.opts.scheduled:   # AGENTS.md: every scheduled agent loop has a kill switch
            return EXIT["usage"], (f"--scheduled: {ctx.spec.loop}/{ctx.spec.step} declares no local.switch — a "
                                   "scheduled run refuses without a kill switch")
        return None
    if fleet_value(ctx.fleet, sw.config) is not True:
        return EXIT["ok"], f"disabled: _data/fleet.yml {sw.config} is false"
    if not ctx.opts.scheduled:
        print(f"jev loop: manual run — bypasses vars.{sw.variable} exactly as a workflow_dispatch does",
              file=sys.stderr)
        return None
    hub = hub_repo(ctx.fleet)
    res = gh(["variable", "get", sw.variable, "-R", hub])
    if res.ok:
        value: str | None = res.out.strip()
    elif "not found" in (res.err or "").lower():
        # gh says "not found" for any 404 — a repository this auth cannot see too.
        # Unset arms a default-on switch, so that reading needs the hub shown readable.
        if sw.default == "on" and not gh(["api", f"repos/{hub}", "--jq", ".full_name"]).ok:
            return EXIT["usage"], (f"--scheduled: vars.{sw.variable} reads as not found, but {hub} is not readable "
                                   "with this gh auth — a scheduled run refuses rather than guess its switch")
        value = None
    else:
        return EXIT["usage"], (f"--scheduled: cannot read vars.{sw.variable} ({(res.err or res.out).strip()[-200:]})"
                               " — a scheduled run refuses rather than guess its switch")
    v = value.lower() if value is not None else None
    armed = v == "true" if sw.default == "off" else v != "false"
    if not armed:
        return EXIT["ok"], f"switched off: vars.{sw.variable} is {value!r} (default {sw.default})"
    return None


def _is_off(level: object) -> bool:
    """A `switches:` level that is off. An unquoted YAML `off` loads as False: off too."""
    state = level.get("state") if isinstance(level, dict) else None
    return state is False or (isinstance(state, str) and state.strip().lower() == "off")


def _map(fleet: dict, key: str) -> dict:
    sw = fleet.get("switches")
    level = sw.get(key) if isinstance(sw, dict) else None
    return level if isinstance(level, dict) else {}


def switch_entries(fleet: dict, spec: StepSpec) -> list[tuple[str, dict]]:
    """The step's `switches.loops` entries: the hub's own, for the step's
    workflow (`hub/repo-scout` for repo-scout.yml). [] for a workflow the map
    does not list (fanout.yml is dispatch-only)."""
    hub, wf = hub_repo(fleet), f".github/workflows/{spec.workflow_file}"
    return [(k, e) for k, e in _map(fleet, "loops").items()
            if isinstance(e, dict) and e.get("repo") == hub and e.get("workflow") == wf]


def repo_paused(fleet: dict, nwo: str) -> str | None:
    """Why `switches.repos[<nwo>]` pauses agent work on that repository, or None."""
    level = _map(fleet, "repos").get(nwo)
    if not _is_off(level):
        return None
    return f"switches.repos[{nwo}] is off" + (f": {level['reason']}" if level.get("reason") else "")


def map_paused(fleet: dict, spec: StepSpec) -> str | None:
    """Why `_data/fleet.yml` `switches:` pauses this step, or None (§ 17.2:
    the most restrictive level wins): the global level, the group and the
    loop entry of the step's workflow, then the hub's own repo level. A step
    with no entry (fanout) answers to the global and repo levels only. An
    `expires` date does not resume anything by itself; the drift check
    reports it."""
    levels = [("switches.global", _map(fleet, "global"))]
    for key, entry in switch_entries(fleet, spec):
        group = entry.get("group")
        levels += [(f"switches.groups.{group}", _map(fleet, "groups").get(group)), (f"switches.loops[{key}]", entry)]
    for name, level in levels:
        if _is_off(level):
            return f"{name} is off" + (f": {level['reason']}" if level.get("reason") else "")
    return repo_paused(fleet, hub_repo(fleet))


def pause_gate(fleet: dict, spec: StepSpec, *, repos: tuple[str, ...] = ()) -> tuple[int, str] | None:
    """The fleet-wide pause and the central switch map, honoured by every run
    that could spend or file — `run`, `run --apply`, `publish --apply` and the
    `doctor --live` canary, manual and scheduled alike (bamr87/bamr87#550,
    § 17). `plan`, `run --rehearse` and `doctor` without `--live` never call
    it. The map first (a file read), then `vars.FLEET_AGENTS_PAUSED` on the
    hub, read the way CI reads it; an unreadable variable refuses rather than
    guess. `repos` are the items' own repositories (`switches.repos`).
    (exit code, why) to stop: exit 5 paused, exit 2 unreadable."""
    why = map_paused(fleet, spec) or next(filter(None, (repo_paused(fleet, r) for r in repos)), None)
    if why is None:
        hub = hub_repo(fleet)
        res = gh(["variable", "get", PAUSE_VARIABLE, "-R", hub])
        if res.ok:
            value = res.out.strip()
            if value.lower() != "true":
                return None
            why = f"vars.{PAUSE_VARIABLE} is {value!r} on {hub}"
        elif "not found" not in (res.err or "").lower():
            return EXIT["usage"], (f"cannot read vars.{PAUSE_VARIABLE} ({(res.err or res.out).strip()[-200:]}) — "
                                   "refusing rather than guess the fleet-wide pause")
        elif gh(["api", f"repos/{hub}", "--jq", ".full_name"]).ok:
            return None   # unset: not paused
        else:
            # gh says "not found" for a repository this auth cannot see too
            return EXIT["usage"], (f"vars.{PAUSE_VARIABLE} reads as not found, but {hub} is not readable with this "
                                   "gh auth — refusing rather than guess the fleet-wide pause")
    return EXIT["paused"], (f"paused: {why} — nothing runs that could spend or file (§ 17); `loop plan` and "
                            "`run --rehearse` still do")


# --------------------------------------------------------------------------- #
# the host: the CLI, the sandbox, the probe and canary caches, the credential
# --------------------------------------------------------------------------- #
def cache_key(cli: tuple[int, int, int] | None, spec: StepSpec, posture: headless.Posture) -> str:
    return f"{headless.version_str(cli)}|{headless.posture_template_sha(spec, posture)}"


def canary_key(cli: tuple[int, int, int] | None, spec: StepSpec, posture: headless.Posture,
               auth: headless.AuthChoice | None) -> str:
    """The canary's cache key: the probe's, plus the credential variable the
    session carries (`headless.credential_exposure`). A canary run on a stored
    login had no credential in claude's environment to hide from Bash, so its
    pass never unlocks a run that puts CLAUDE_CODE_OAUTH_TOKEN or
    ANTHROPIC_API_KEY there."""
    return f"{cache_key(cli, spec, posture)}|cred={headless.credential_exposure(auth) or 'none'}"


def cached(name: str, key: str) -> dict | None:
    """A cached probe (.probe.json) or canary (.canary.json) result for `key`."""
    entry = read_json(runs_dir() / name).get(key)
    return entry if isinstance(entry, dict) else None


def store(name: str, key: str, entry: dict) -> None:
    path = runs_dir() / name
    data = read_json(path)
    data[key] = entry
    write_json(path, data)


def resolve_claude(claude_bin: str) -> str | None:
    found = shutil.which(claude_bin)
    return str(Path(found).resolve()) if found else None


def auth_choice(fleet: dict, claude: str) -> tuple[headless.AuthChoice | None, str]:
    """The credential a live attempt would use — method and source, never the value."""
    try:
        order = headless.auth_order(fleet, os.environ)
        choice = headless.choose_auth(order, os.environ, headless.hub_dotenv(),
                                      lambda: headless.stored_login(claude, os.environ))
    except JevError as exc:   # NoCredential, or an unknown method in the order
        return None, str(exc)
    return choice, str(choice)


@dataclass
class HostReport:
    claude: str | None = None
    version: tuple[int, int, int] | None = None
    problems: list[tuple[int, str]] = field(default_factory=list)   # (exit code, why)
    notes: list[str] = field(default_factory=list)
    auth: headless.AuthChoice | None = None
    probe: str = "absent"
    canary: str = "absent"

    def refusal(self) -> tuple[int, str] | None:
        """The most severe problem: no CLI, then host safety, then the credential."""
        if not self.problems:
            return None
        code = severest([c for c, _w in self.problems])
        return code, "; ".join(why for c, why in self.problems if c == code)

    def as_dict(self) -> dict:
        return {"claude": self.claude, "version": headless.version_str(self.version),
                "problems": [why for _, why in self.problems], "notes": self.notes,
                "auth": {"method": self.auth.method, "source": self.auth.source} if self.auth else None,
                "probe": self.probe, "canary": self.canary}


def work_root_problem(root: Path | None = None) -> str | None:
    """Why the work root cannot hold a workspace (host safety, exit 4); None
    when it can (`headless.work_root_problem`: not in the hub, not in a Claude
    temp root)."""
    return headless.work_root_problem(root)


def private_work_root() -> Path:
    root = headless.work_root()
    root.mkdir(parents=True, exist_ok=True)
    root.chmod(0o700)
    return root


def host_check(spec: StepSpec, posture: headless.Posture, fleet: dict, claude_bin: str, scratch: Path | None, *,
               live: bool, preflight: bool, probe_cache: bool = True, report: bool = False) -> HostReport:
    """What the host proves before an attempt. `live=False` (doctor, rehearse)
    reports a missing probe, canary or credential as a note; a live attempt
    refuses on each of them. `probe_cache=False` skips the cached
    probe (doctor runs it afresh). A work root inside the hub is refused first
    (exit 4), before any CLI runs — except with `report=True` (`loop plan`,
    which exits on no host problem and writes nothing under the work root):
    the problem is recorded and the CLI, probe and credential are still read.
    The flag preflight runs in `scratch`, or with None in a throwaway directory
    under the work root — never inside the hub, where a session would reach
    the hub's CLAUDE.md. Nothing here reaches a model."""
    from . import loop as engine   # lazily: loop imports this module, and holds the seams tests replace
    rep = HostReport()
    inside = work_root_problem()
    if inside:
        rep.problems.append((EXIT["host_unsafe"], inside))
        if not report or preflight:
            return rep

    def gap(code: int, why: str) -> None:
        if live:
            rep.problems.append((code, why))
        else:
            rep.notes.append(why)

    rep.claude = resolve_claude(claude_bin)
    if rep.claude is None:
        rep.problems.append((EXIT["no_cli"], f"{claude_bin} is not on PATH (npm install -g @anthropic-ai/claude-code)"))
        return rep
    rep.version = headless.cli_version(rep.claude)
    if not headless.at_least(rep.version):
        rep.problems.append((EXIT["host_unsafe"], f"Claude Code {headless.version_str(rep.version)} is older than "
                                                  f"{headless.version_str(headless.MIN_CLI)} (--permission-prompts)"))
        return rep
    if posture.name == "sandbox" and not engine.sandbox_available():
        rep.problems.append((EXIT["host_unsafe"], f"no sandbox here ({SANDBOX_EXEC} on macOS) — `--posture reduced` "
                                                  "runs the agent without Bash"))
    if preflight:
        own = scratch is None
        scratch = Path(tempfile.mkdtemp(prefix=".preflight-", dir=private_work_root())) if own else scratch
        try:
            scratch.mkdir(parents=True, exist_ok=True)
            settings = scratch / "settings.json"
            write_json(settings, headless.settings_doc(posture))
            argv = [*headless.run_prefix(spec.resolved.max_budget_usd, stream=True),
                    *headless.claude_flags(spec, posture, settings_path=settings, session_id=str(uuid.uuid4()),
                                           debug_path=scratch / "preflight.debug.log")]
            problem = headless.preflight_parse(rep.claude, argv, cwd=scratch)
        finally:
            if own:
                shutil.rmtree(scratch, ignore_errors=True)
        if problem:
            rep.problems.append((EXIT["host_unsafe"], f"flag preflight: {problem}"))
        else:
            rep.notes.append("flag preflight: every flag parses and nothing reports the --settings document skipped "
                             "($0)")
    key = cache_key(rep.version, spec, posture)
    if probe_cache:
        probe = cached(".probe.json", key)
        rep.probe = "absent" if probe is None else ("ok" if probe.get("ok") else "failed")
        if rep.probe == "failed":
            rep.problems.append((EXIT["host_unsafe"], "the isolation probe failed for this CLI and posture "
                                                      "template: " + "; ".join(probe.get("problems") or [])[:400]))
        elif rep.probe == "absent":
            gap(EXIT["host_unsafe"], "isolation probe: not run for this CLI and posture template — "
                                     "`tools/dash loop doctor` ($0); a live attempt refuses without it")
    rep.auth, said = auth_choice(fleet, rep.claude)
    if rep.auth is None:
        gap(EXIT["credential"], f"credential: {said} — a live attempt exits 3")
    else:
        rep.notes.append(f"credential: {said} (the first present in CLAUDE_AUTH_ORDER; never retried with another)")
    if posture.name == "sandbox":
        canary = cached(".canary.json", canary_key(rep.version, spec, posture, rep.auth))
        rep.canary = "absent" if canary is None else ("ok" if canary.get("ok") else "failed")
        if rep.canary != "ok":
            carried = headless.credential_exposure(rep.auth) or "no credential variable"
            gap(EXIT["host_unsafe"], f"canary: none passing for this CLI, posture template and credential exposure "
                                     f"({carried}; {rep.canary}) — the one-time ≤ $0.10 canary under this same "
                                     "auth: `tools/dash loop doctor --live` (the maintainer's § 10.5 yes); a live "
                                     "sandbox-posture attempt refuses without it")
    return rep


def head_sha(nwo: str, branch: str) -> tuple[str | None, str]:
    """The branch head, read with the user's gh auth. '' = an empty repository
    (GitHub's 409 "Git Repository is empty."); None = unread, with why. A 422
    "No commit found" is a branch that does not exist — registry drift, said
    so, and the clone then fails the item loudly, as CI's checkout would."""
    res = gh(["api", f"repos/{nwo}/commits/{branch}", "--jq", ".sha"])
    if res.ok and re.fullmatch(r"[0-9a-f]{40}", res.out.strip()):
        return res.out.strip(), ""
    err = (res.err or res.out).strip()
    if re.search(r"Git Repository is empty|HTTP 409", err, re.I):
        return "", ""
    if re.search(r"No commit found|HTTP 422", err, re.I):
        return None, (f"{nwo} has no branch `{branch}` (HTTP 422) — registry branch drift? check "
                      "_data/projects.yml and .gitmodules")
    return None, f"could not read {nwo}@{branch} HEAD ({err[-160:]}) — tier 0 reuse is off for this item"


# --------------------------------------------------------------------------- #
# after an attempt: did the session run in the posture the probe and the canary proved
# --------------------------------------------------------------------------- #
def posture_breach(spec: StepSpec, posture: headless.Posture, outcome: dict, debug: list[str],
                   events: list[dict]) -> str | None:
    """Why this attempt's session cannot be trusted to have run in the posture
    the probe and the canary proved — None when it can. Checked BEFORE any
    output is read: a breach destroys the outputs unread and stops the run.

    A session with no init record is unverifiable only if there is evidence it
    ran: a reported cost, a result kind, a tool use or a trace event. A cap
    ESTIMATE alone (the wall clock before init, an ai-run that died) is
    accounting, not evidence: that attempt fails as attention instead. Bash
    calls the permission layer denied never ran, so only executed ones need
    the sandbox line (and its fences); without per-tool denials (an older
    outcome) every call counts as executed. `debug` is `headless.posture_lines`:
    the reduced debug log plus the sandbox runtime's stderr lines the outcome
    carries, since 2.1.308 logs the per-command line only there (#560,
    decision 4c: the document's read-fence line AND the per-command line,
    each failing closed)."""
    applied = headless.user_settings_env_keys(debug)
    if applied:
        return (f"a user settings env block was applied to the session ({', '.join(applied)}): a settings file "
                "was read")
    init = headless.init_event(events)
    expected = headless.tool_families(headless.posture_tools(spec.allowed_tools, posture))
    kind = outcome.get("kind")
    tool_uses = outcome.get("tool_uses") or {}
    if init is not None:
        problems = headless.init_problems(init, expected)
        if problems:
            return "the session's init is not the probed posture: " + "; ".join(problems)
    elif ((outcome.get("cost_source") == "reported" and float(outcome.get("cost_usd") or 0) > 0)
          or kind in ("ok", "budget_hit", "max_turns") or tool_uses or events):
        return "the session reported a result or tool use but left no init record, so its posture cannot be checked"
    if init is not None and posture.name == "sandbox":
        fence = headless.settings_fence_problems(debug)
        if fence:
            return "the --settings document is not proven applied to this session: " + "; ".join(fence)
    bash = int(tool_uses.get("Bash") or 0)
    if bash and posture.name == "reduced":
        return f"Bash ran {bash} time(s) under the reduced posture, which grants none"
    denied = outcome.get("denied_tools")
    executed = bash - int(denied.get("Bash") or 0) if isinstance(denied, dict) else bash
    if executed > 0 and not headless.sandbox_engaged(debug):
        return (f"Bash executed {executed} time(s) but no sandbox engaged: neither the debug log nor the sandbox "
                f"runtime's stderr ({headless.SANDBOX_DEBUG_ENV}) shows a wrapped command — the outputs are "
                "destroyed unread; re-run `tools/dash loop doctor` and the canary")
    fences = headless.sandbox_fence_problems(debug) if executed > 0 else []
    if fences:
        return f"Bash executed {executed} time(s) without its full sandbox: " + "; ".join(fences)
    return None
