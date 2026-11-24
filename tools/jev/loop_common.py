#!/usr/bin/env python3
"""
File: tools/jev/loop_common.py
Description: The loop runner's shared ground (tools/jev/loop.py; #486, ADR
             0002 P1): what every part of the engine reads and no one part
             owns. The exit codes and their order of severity, the § 10.7
             cost label, the outer backstop's grace, the runs directory, the
             clock, hash and JSON helpers the run records are written with,
             the run's options and why a combination of them cannot run, and
             the two subprocess environments (the planner's and the filer's;
             `dash-gen ai-run`'s). Moved here from loop.py unchanged; loop.py
             re-exports every name, and nothing here imports the engine.
Author: bamr87
Created: 2026-11-22
Version: 0.1.0
Usage: imported by tools/jev/loop.py and its sibling loop_*.py modules.
       Callers outside the engine import these names from tools.jev.loop.
Dependencies: Python 3.12 stdlib.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from . import context as cpack
from . import headless
from . import workspace as wsp
from .common import HUB

EXIT = {"ok": 0, "attention": 1, "usage": 2, "credential": 3, "host_unsafe": 4, "paused": 5, "no_cli": 127,
        "interrupted": 130}
#: § 10.7: every AI dollar figure the engine prints carries this
COST_LABEL = "API-equivalent (estimate)"
#: the engine's backstop beyond the spec's wall clock (ai-run enforces the clock itself)
OUTER_GRACE_S = 120
#: `--target`: a registry name (scout), or a planner's own item key — the doctor's
#: marker key `owner/repo:.github/workflows/x.yml`, `owner/repo/workflow` or a file
#: stem. One token: no whitespace, no control character, never option-shaped.
TARGET_RX = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_./:@-]{0,199}")
DAY_RX = re.compile(r"\d{4}-\d{2}-\d{2}")


def runs_dir() -> Path:
    """`.fleet/runs/` (gitignored); JEV_RUNS_DIR overrides it."""
    return Path(os.environ.get("JEV_RUNS_DIR") or HUB / ".fleet" / "runs")


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def iso(t: dt.datetime | None = None) -> str:
    return (t or now_utc()).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


SEVERITY = (EXIT["no_cli"], EXIT["host_unsafe"], EXIT["credential"], EXIT["usage"], EXIT["paused"], EXIT["attention"])


def severest(codes: list[int]) -> int:
    return next((c for c in SEVERITY if c in codes), EXIT["ok"])


# --------------------------------------------------------------------------- #
# options
# --------------------------------------------------------------------------- #
@dataclass
class Options:
    target: str = "all"
    focus: str = ""
    day: str | None = None
    offline: bool = False
    plan_file: str | None = None
    item: str | None = None
    rehearse: bool = False
    apply: bool = False
    scheduled: bool = False
    fresh: bool = False
    max_items: int | None = None
    posture: str = "sandbox"
    keep_workspace: bool = False
    allow_dirty: bool = False
    run_id: str | None = None
    claude_bin: str = "claude"
    json: bool = False
    #: the context pack's mode for this run (None = the spec's local.context.mode)
    context: str | None = None
    refresh_context: bool = False

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> Options:
        return cls(**{k: getattr(args, k) for k in cls.__dataclass_fields__ if hasattr(args, k)})


def option_refusal(opts: Options, *, verb: str) -> str | None:
    """Why these options cannot run at all; None when they can."""
    if opts.apply and opts.scheduled:
        return ("--apply with --scheduled is refused: no unattended local filing until § 13.7 earned autonomy "
                "exists (the publish action is tier high, § 13.6)")
    if opts.apply and opts.rehearse:
        return "--apply with --rehearse is refused: a rehearsal files nothing"
    if opts.apply and opts.offline:
        return "--apply with --offline is refused: filing needs the live recheck and a live dedupe"
    if verb == "run" and opts.offline and not opts.rehearse:
        return "--offline is for `plan` and `run --rehearse`: a live attempt needs its clone and a live dedupe"
    if opts.posture == "reduced" and opts.scheduled:
        return "--posture reduced is an explicit fallback and is never scheduled"
    if bool(opts.plan_file) != bool(opts.item):
        return "--plan-file and --item go together (one row of a saved plan)"
    if opts.target != "all" and not TARGET_RX.fullmatch(opts.target or ""):
        return f"--target {opts.target!r} is not a registry name or a planner item key (one plain token)"
    if opts.day and not DAY_RX.fullmatch(opts.day):
        return f"--day {opts.day!r} is not YYYY-MM-DD"
    if any(c in (opts.focus or "") for c in "\0\r\n"):
        return "--focus is one line of text"
    if opts.max_items is not None and opts.max_items < 1:
        return "--max-items must be at least 1"
    if opts.run_id and not wsp.RUN_ID_RX.fullmatch(opts.run_id):
        return f"--run-id {opts.run_id!r} must match {wsp.RUN_ID_RX.pattern}"
    if opts.context is not None and opts.context not in cpack.MODES:
        return f"--context {opts.context!r} is not one of {', '.join(cpack.MODES)}"
    if opts.refresh_context and opts.scheduled:
        return ("--refresh-context with --scheduled is refused: the session import reads this account's ~/.claude "
                "transcripts, a hand-run step")
    if opts.refresh_context and opts.context == "off":
        return "--refresh-context with --context off is refused: there is no pack to refresh"
    return None


# --------------------------------------------------------------------------- #
# the two subprocess environments
# --------------------------------------------------------------------------- #
def deterministic_env() -> dict[str, str]:
    """The planner's and the filer's environment: the user's own (their gh auth
    reads GitHub), minus every Claude credential and auth override — those
    commands talk to no model — and with PYTHON pinned to this interpreter, so
    `tools/dash-gen` imports the same PyYAML."""
    drop = {*headless.CREDENTIAL_ENV.values(), *headless.AUTH_OVERRIDE_ENV}
    env = {k: v for k, v in os.environ.items() if k not in drop}
    env["PYTHON"] = sys.executable
    return env


def ai_run_env(auth: headless.AuthChoice | None) -> dict[str, str]:
    """`dash-gen ai-run`'s own environment: the user's, minus every GitHub and
    Claude secret, the SSH agent and the CLI's other auth inputs, plus the ONE
    chosen Claude credential (none for a stored login, which the CLI reads
    itself). PYTHONPATH stays — on the maintainer's Mac PyYAML imports only
    through it — and ai-run's --isolate builds claude's environment from scratch."""
    drop = {*headless.SECRET_ENV, *headless.AUTH_OVERRIDE_ENV, "SSH_AUTH_SOCK"}
    env = {k: v for k, v in os.environ.items() if k not in drop}
    env["PYTHON"] = sys.executable
    if auth is not None:
        value = headless.credential_value(auth, os.environ, headless.hub_dotenv())
        if value:
            env[headless.CREDENTIAL_ENV[auth.method]] = value
    return env
