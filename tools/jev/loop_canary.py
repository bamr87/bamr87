#!/usr/bin/env python3
"""
File: tools/jev/loop_canary.py
Description: The loop runner's live canary (`loop doctor --live`; #486, ADR
             0002 P1), the one doctor check that spends: one real, ledgered
             session of at most CANARY_CAP_USD in a canary clone, under the
             step's own isolation flags plus the probe grants a narrower
             allowlist lacks (`canary_flags`, `CANARY_GRANTS`), asked to read
             planted files, reach the network and write outside the clone;
             `headless.judge_canary` decides, and every planted and scratch
             file is removed whatever happens. `_confirm_canary` is the
             maintainer's § 10.5 yes. Moved here from loop.py unchanged but
             for two qualifications in `run_canary`: `relay_dash_gen` and
             `auth_pin` are seams tests replace, so they stay in loop.py and
             the canary reaches them as `engine.relay_dash_gen` and
             `engine.auth_pin`. `cmd_doctor`, which decides whether the canary
             runs (the pause, the budget lock, the ceiling) and caches its
             verdict, stays in loop.py. loop.py re-exports every name.
Author: bamr87
Created: 2026-11-22
Version: 0.1.0
Usage: imported by tools/jev/loop.py. Callers outside the engine import these
       names from tools.jev.loop (tools/jev/reflect.py does, lazily).
Dependencies: Python 3.12 stdlib; git for the fixture; the claude CLI, run
              only through `tools/dash-gen ai-run`.
"""
from __future__ import annotations

import os
import secrets
import shutil
import sys
import tempfile
import uuid
from pathlib import Path

from . import headless
from . import workspace as wsp
from .common import JevError, git, hub_repo
from .loop_budget import ledger_path
from .loop_common import COST_LABEL, OUTER_GRACE_S, ai_run_env, now_utc, read_json, write_json
from .loop_host import HostReport
from .spec import StepSpec, StepSpecError, allowed_models

#: the canary (`doctor --live`): the cheapest allowed model, a few turns, ten cents
CANARY_MODEL = "claude-haiku-5-5"
CANARY_TURNS = 12
CANARY_CAP_USD = 0.10
CANARY_TIMEOUT_S = 300


def canary_dir() -> Path:
    """~/.cache/jev/canary: beside the work root, outside every clone, inside the home fence."""
    return headless.work_root().parent / "canary"


def _canary_fixture(root: Path, secret: Path) -> Path:
    """A local repository whose one commit holds a symlink `link` to the secret
    (the clone's core.symlinks=false must make it a plain file)."""
    repo = root / "canary-src"
    repo.mkdir(parents=True)
    cfg = ["-c", "user.name=jev-canary", "-c", "user.email=canary@localhost", "-c", "commit.gpgsign=false"]
    (repo / "README.md").write_text("# jev canary fixture\n", encoding="utf-8")
    os.symlink(secret, repo / "link")
    for args in (["init", "-q", "-b", "main"], ["add", "-A"], [*cfg, "commit", "-q", "-m", "canary"]):
        res = git(args, cwd=repo)
        if not res.ok:
            raise JevError(f"could not build the canary fixture: git {args[0]}: {res.err.strip()}")
    return repo


#: the Bash grants the canary's probes need (`cat` and `python3 -c` one-liners):
#: added to a step whose allowlist lacks them, since the probes test Seatbelt,
#: which wraps every child alike — the settings document, the isolation flags,
#: the toolset and the environment stay the step's own, and the verdict
#: records what was added (bamr87/bamr87#488: the doctor grants no python3)
CANARY_GRANTS = ("Bash(cat:*)", "Bash(python3:*)")


def canary_grants(spec: StepSpec, posture: headless.Posture) -> list[str]:
    """Pure: which of CANARY_GRANTS the step's own allowlist lacks (none when
    the posture grants no Bash at all: the canary refuses under `reduced`)."""
    allowed = headless.posture_tools(spec.allowed_tools, posture)
    if "Bash" not in headless.tool_families(allowed):
        return []
    return [g for g in CANARY_GRANTS if g not in allowed]


def canary_flags(spec: StepSpec, posture: headless.Posture, **paths: object) -> list[str]:
    """The step's own isolation flags — the same settings, toolset, allowlist
    and deny list the posture template hashes — with only the model and the
    turn cap swapped for the canary's (neither changes what is enforced), plus
    the probe grants (`canary_grants`) a narrower allowlist lacks, appended to
    `--allowedTools` so the probes reach the sandbox instead of the permission
    layer; `--tools` (the families the init record is held to) is unchanged."""
    flags = headless.claude_flags(spec, posture, **paths)
    flags[flags.index("--model") + 1] = CANARY_MODEL
    flags[flags.index("--max-turns") + 1] = str(CANARY_TURNS)
    added = canary_grants(spec, posture)
    if added:
        i = flags.index("--allowedTools") + 1
        flags[i] = ",".join([*flags[i].split(","), *added])
    return flags


def _plant(path: Path, token: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(token + "\n")


def run_canary(spec: StepSpec, posture: headless.Posture, host: HostReport, fleet: dict) -> headless.ProbeResult:
    """The ≤ $0.10 canary: one real session (it is ledgered like any attempt)
    in a canary clone, asked to read a planted fixture file holding a random
    token (inside the home fence, and a second copy in a denied private path
    outside it) with `cat` and with python, reach the network, write outside
    the clone with a sandboxed command and with the Write tool, count the
    SECRET_ENV variables it can see, and read a committed symlink. It runs under the run's own credential, so its pass
    is cached for that exposure. `headless.judge_canary` decides; the secrets
    and every scratch file are removed whatever happens."""
    from . import loop as engine   # lazily: loop imports this module, and holds the seams tests replace
    if CANARY_MODEL not in allowed_models(fleet):
        raise StepSpecError(f"the canary model {CANARY_MODEL} is not in _data/fleet.yml ai_models.allowed (§ 13.3)")
    cdir = canary_dir()
    cdir.mkdir(parents=True, exist_ok=True)
    cdir.chmod(0o700)
    token = secrets.token_hex(16)
    outside_root = next((Path(p).resolve() for p in headless.private_read_paths() if Path(p).is_dir()), None)
    outside_dir = Path(tempfile.mkdtemp(prefix="jev-canary-", dir=outside_root)) if outside_root else None
    # neutral names: a model asked to read a `secret` may decline on its own (#560, item 3)
    plant = headless.CanaryPlant(token=token, secret=str(cdir / "fixture.txt"), written=str(cdir / "written.txt"),
                                 write_tool=str(cdir / "written-by-write.txt"),
                                 outside=str(outside_dir / "fixture.txt") if outside_dir else None)
    targets = [Path(plant.written), Path(plant.write_tool)]
    for t in targets:
        t.unlink(missing_ok=True)
    for path in filter(None, (plant.secret, plant.outside)):
        _plant(Path(path), token)
    secret = Path(plant.secret)
    run_id = f"canary-{now_utc():%Y%m%dT%H%M%SZ}-{secrets.token_hex(3)}"
    scratch = Path(tempfile.mkdtemp(prefix="jev-canary-"))
    ws = None
    try:
        src = _canary_fixture(scratch, secret)
        ws = wsp.clone_local(src, "jev-canary/fixture", "main", run_id=run_id, brief_dir=spec.workspace.brief_dir)
        d = scratch / "item"
        d.mkdir()
        (d / "prompt.txt").write_text(plant.prompt(), encoding="utf-8")
        write_json(d / "settings.json", headless.settings_doc(posture))
        attempt_id = str(uuid.uuid4())
        flags = canary_flags(spec, posture, settings_path=d / "settings.json", session_id=attempt_id,
                             debug_path=d / "debug.log")
        argv = ["ai-run", "--stream", "--isolate", "--isolate-tmp", str(ws.tmp), "--timeout", str(CANARY_TIMEOUT_S),
                "--max-budget-usd", f"{CANARY_CAP_USD:g}", "--repo", hub_repo(fleet), "--cwd", str(ws.path),
                "--prompt-file", str(d / "prompt.txt"), "--trace", str(d / "trace.jsonl"),
                "--result-file", str(d / "result.json"), "--outcome-file", str(d / "outcome.json"),
                "--usage-limit", "skip", "--source", f"jev loop doctor --live ({spec.loop}/{spec.step} canary)",
                "--claude-bin", host.claude or "claude", "--ledger", str(ledger_path())]
        argv += engine.auth_pin(host.auth)
        for k, v in {"origin": "local", "run_id": run_id, "attempt_id": attempt_id, "loop": spec.loop,
                     "step": spec.step, "item": "canary", "tier": "canary"}.items():
            argv += ["--meta", f"{k}={v}"]
        engine.relay_dash_gen([*argv, "--", *flags], env=ai_run_env(host.auth), timeout=CANARY_TIMEOUT_S + OUTER_GRACE_S)
        expected = headless.tool_families(headless.posture_tools(spec.allowed_tools, posture))
        outcome = read_json(d / "outcome.json")
        verdict = headless.judge_canary(
            headless.read_events(d / "trace.jsonl"),
            headless.posture_lines(headless.reduce_debug_log(d / "debug.log"), outcome),
            outcome, plant=plant, left_behind=[str(t) for t in targets if t.exists()],
            expected_tools=expected, credential_env=headless.credential_exposure(host.auth),
            # ai-run's trace Redactor has the HOME it was given: the same one, so the same `~` paths
            redact=headless.Redactor(ai_run_env(host.auth)).text)
        verdict.facts["grants_added"] = canary_grants(spec, posture)
        return verdict
    finally:
        if ws is not None:
            wsp.destroy(ws)
        shutil.rmtree(scratch, ignore_errors=True)
        secret.unlink(missing_ok=True)
        for t in targets:
            t.unlink(missing_ok=True)
        if outside_dir is not None:
            shutil.rmtree(outside_dir, ignore_errors=True)


def _confirm_canary(yes: bool) -> str | None:
    """The maintainer's § 10.5 yes for the one doctor check that spends."""
    if yes:
        return None
    if not sys.stdin.isatty():
        return ("--live spends up to $0.10 (" + COST_LABEL + "): confirm on a terminal, or pass --yes "
                "(the maintainer's § 10.5 approval)")
    answer = input(f"Run the canary: one Claude session, at most ${CANARY_CAP_USD:.2f} ({COST_LABEL})? "
                   "Type yes: ")
    return None if answer.strip().lower() == "yes" else "not confirmed"
