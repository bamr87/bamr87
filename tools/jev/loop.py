#!/usr/bin/env python3
"""
File: tools/jev/loop.py
Description: JEV capability two's runner — `python3 -m tools.jev loop`, the
             local loop engine (#486, ADR 0002 P1). It runs a loop's agent step
             on this workstation exactly as CI does: the same planner
             (`tools/dash-gen scout`), the same prompt bytes (rendered from the
             step spec), the same allowlist and caps, inside the § 13.8 posture
             of tools/jev/headless.py, in a hardened throwaway clone
             (tools/jev/workspace.py), with the loop's own logic in an adapter
             (tools/jev/adapters/). All policy comes from the spec, its
             `local:` block, `_data/fleet.yml` and the adapter; this module has
             no loop-specific code, writes only under the gitignored
             `.fleet/runs/` and the work root, and never commits or merges.
             Verbs: `list`; `doctor` (the $0 flag preflight and isolation
             probe; `--live` adds the one-time ≤ $0.10 canary, the
             maintainer's § 10.5 yes); `plan` ($0, no clone); `run` (one
             attempt per item through `dash-gen ai-run --isolate`, held to the
             monthly `budget.loops` ceiling, then the dry-run preview with the
             exact issue bodies — and with `--apply`, typed by the maintainer,
             the filing in the same run; `--rehearse` stops before the model
             call at $0); `publish` (files a reviewed earlier dry run,
             idempotently); `show`; `budget`. Before each attempt the HOST
             builds the item's context pack (tools/jev/context.py: the lake,
             the code index, the telemetry, this loop's earlier attempts) and
             places it beside the brief in the clone, with a pointer in the
             clone's copy of the brief — the sealed agent only reads a file;
             `--context off` is the CI-identical run.
Author: bamr87
Created: 2026-10-31
Version: 0.2.0
Usage: python3 -m tools.jev loop list | doctor [--live] | plan <loop> | run <loop> [--rehearse|--apply]
                                   [--context auto|off|require] [--refresh-context]
                                   | publish <run_id> [--apply] | show <run_id>|--latest | budget
       (also `tools/dash loop …`; docs/JEV.md "The loop runner")
Dependencies: PyYAML; git and gh for the plan, the clone and the filing; the
              claude CLI, run only through `tools/dash-gen ai-run`.
"""
from __future__ import annotations

import argparse
import contextlib
import dataclasses
import datetime as dt
import fcntl
import hashlib
import json
import math
import os
import platform
import re
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from collections import deque
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from pathlib import Path
from types import SimpleNamespace

from . import adapters, headless
from . import context as cpack
from . import workspace as wsp
from .adapters import REUSE_DAYS, Adapter, Item, PlanResult, PublishPlan, Verdict
from .common import HUB, JevError, Run, dotenv_values, gh, git, hub_repo, is_bare_name, load_config, run
from .ledger import BudgetState, Ledger, budget_state
from .spec import (PUBLISH_REVIEWED_FLAGS, SPEC_ROOT, ContextSpec, StepSpec, StepSpecError, allowed_models,
                   fleet_value, load_fleet, load_spec, render_argv, render_prompt, spec_files, values_from)

DASH_GEN = HUB / "tools" / "dash-gen"
RUN_SCHEMA = "jev-loop-run/v1"
ATTEMPT_SCHEMA = "jev-loop-attempt/v1"
KEEP_RUNS = 30
TIER = "t1"   # P1 has one tier, built from the spec's resolved values; P3 adds `local.tiers`
EXIT = {"ok": 0, "attention": 1, "usage": 2, "credential": 3, "host_unsafe": 4, "no_cli": 127, "interrupted": 130}
PUBLISH_PLAN_SCHEMA = "jev-loop-publish-plan/v1"
PUBLISH_RESULT_SCHEMA = "jev-loop-publish-result/v1"
#: § 10.7: every AI dollar figure the engine prints carries this
COST_LABEL = "API-equivalent (estimate)"
#: the engine's backstop beyond the spec's wall clock (ai-run enforces the clock itself)
OUTER_GRACE_S = 120
#: the canary (`doctor --live`): the cheapest allowed model, a few turns, ten cents
CANARY_MODEL = "claude-haiku-5-5"
CANARY_TURNS = 12
CANARY_CAP_USD = 0.10
CANARY_TIMEOUT_S = 300
SANDBOX_EXEC = Path("/usr/bin/sandbox-exec")
TARGET_RX = re.compile(r"[A-Za-z0-9_.-]+")
DAY_RX = re.compile(r"\d{4}-\d{2}-\d{2}")
#: the backstop's SIGTERM-to-SIGKILL grace: ai-run's own SIGINT-first ladder needs well under it
BACKSTOP_KILL_S = 60
#: Hub paths whose state decides what an engine run does, besides the spec
#: directory and the adapter's own `sources`: the engine, its config, and the
#: executor that builds the agent's environment, credential and redactor.
ENGINE_SOURCES = ("tools/jev/", "_data/fleet.yml", ".github/scripts/dash-gen/ai_activity.py", "tools/dash-gen")
ALLOW_DIRTY_HELP = ("let --apply run with a dirty spec, adapter or engine (tools/jev/, _data/fleet.yml, ai-run, "
                    "tools/dash-gen)")
#: the engine's backstop beyond the planes' own --deadline-s (they bound themselves; a timeout is a plane problem)
CONTEXT_GRACE_S = 30
#: `--refresh-context`: the lake's LOCAL import of this machine's Claude Code
#: transcripts (claude_projects_dir() → the lake, nothing else written;
#: dash-gen fleet_lake cmd_sessions). Never `lake sync`, which reads GitHub.
REFRESH_ARGV = ("lake", "sessions")
#: `loop doctor`'s one code-index probe query (an Ollama embedding, local and $0). It
#: proves Qdrant and Ollama answer: a search that answers is an index that is UP,
#: hit or no hit (with no query the planes would not ask the index at all)
DOCTOR_QUERY = "the loop runner and its context pack"


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
        return f"--target {opts.target!r} is not a registry name"
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
# specs
# --------------------------------------------------------------------------- #
def local_specs(root: Path = SPEC_ROOT, fleet: dict | None = None) -> list[StepSpec]:
    """Every spec that has a `local:` block (a broken spec raises)."""
    fleet = load_fleet() if fleet is None else fleet
    out = []
    for p in spec_files(root):
        s = load_spec(p.parent.name, p.stem, root=root, fleet=fleet)
        if s.local is not None:
            out.append(s)
    return out


def load_step(loop: str, step: str | None = None, *, fleet: dict | None = None) -> StepSpec:
    """P0's load_spec; `step` may be omitted when the loop has exactly one local step."""
    fleet = load_fleet() if fleet is None else fleet
    if step is None:
        steps = [s for s in local_specs(fleet=fleet) if s.loop == loop]
        if len(steps) != 1:
            raise StepSpecError(f"loop {loop!r} has {len(steps)} step(s) with a local: block — name the step")
        spec = steps[0]
    else:
        spec = load_spec(loop, step, fleet=fleet)
    if spec.local is None:
        raise StepSpecError(f"{spec.loop}/{spec.step}: no local runner for this step yet "
                            "(its spec has no local: block)")
    if spec.workspace.cwd != "target" or spec.workspace.github_credential != "none":
        raise StepSpecError(f"{spec.loop}/{spec.step}: workspace cwd {spec.workspace.cwd!r} / github_credential "
                            f"{spec.workspace.github_credential!r} — P1 runs only cwd target with no credential (P3)")
    return spec


def publish_tier(spec: StepSpec) -> str | None:
    pub = spec.local.publish if spec.local else None
    if pub is None or not spec.risk:
        return None
    return str((spec.risk.get(pub.risk) or {}).get("tier"))


# --------------------------------------------------------------------------- #
# subprocess seams
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


def dash_gen(argv: list[str], *, timeout: int = 900, stdin: str | None = None, env: dict | None = None) -> Run:
    return run([str(DASH_GEN), *argv], cwd=HUB, env=deterministic_env() if env is None else env, timeout=timeout,
               stdin=stdin, inherit_env=False)


def relay_dash_gen(argv: list[str], *, env: dict[str, str], timeout: float) -> Run:
    """`tools/dash-gen` with its stderr relayed line by line as it arrives — an
    attempt's condensed live stream (ai-run's tee) — and a tail kept for the
    record. At `timeout` (the spec's wall clock plus OUTER_GRACE_S: ai-run
    enforces the clock itself, this is the backstop) ai-run gets SIGTERM,
    which it turns into claude's SIGINT-first ladder, so the session still
    reports its cost; SIGKILL a minute later. An interrupt of the engine (a
    Ctrl-C, or the SIGTERM or SIGHUP `interrupt_on_signals` turns into one) is
    passed on to ai-run as SIGTERM — a signal that reached only the engine
    would otherwise leave ai-run and its session running, unledgered — and the
    engine then waits for ai-run's outcome and ledger row, through any further
    interrupt, before it stops the run. ai-run starts its ladder once, so the
    copy a Ctrl-C or a killpg already delivered changes nothing."""
    proc = subprocess.Popen(  # noqa: S603 - argv is a list, never a shell string
        [str(DASH_GEN), *argv], cwd=HUB, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    out: list[str] = []
    tail: deque[str] = deque(maxlen=200)

    def relay() -> None:
        assert proc.stderr is not None
        for line in proc.stderr:
            sys.stderr.write(line)
            tail.append(line)

    def collect() -> None:
        assert proc.stdout is not None
        out.append(proc.stdout.read())

    threads = [threading.Thread(target=relay, daemon=True), threading.Thread(target=collect, daemon=True)]
    for t in threads:
        t.start()

    def settle(grace: float) -> int:
        deadline = time.monotonic() + grace
        while True:
            try:
                return proc.wait(timeout=max(0.0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                proc.kill()
                return proc.wait()
            except KeyboardInterrupt:   # a second cancel: ai-run is already stopping; its record is still owed
                continue

    try:
        code = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.terminate()
        code = settle(BACKSTOP_KILL_S)
        tail.append(f"jev loop: the engine's backstop stopped ai-run after {timeout:g}s\n")
    except KeyboardInterrupt:
        if proc.poll() is None:
            with contextlib.suppress(ProcessLookupError):
                proc.terminate()
        settle(BACKSTOP_KILL_S)
        raise
    finally:
        for t in threads:
            t.join(timeout=5)
    return Run(code, "".join(out), "".join(tail))


# --------------------------------------------------------------------------- #
# the monthly ceiling (budget.loops) and the publish token
# --------------------------------------------------------------------------- #
def ledger_path() -> Path:
    """The AI ledger ai-run writes one row per invocation to (DASH_AI_LEDGER)."""
    return Path(os.environ.get("DASH_AI_LEDGER") or "~/.claude/ai-activity-ledger.json").expanduser()


def loops_budget(fleet: dict) -> tuple[float, int]:
    """`_data/fleet.yml` `budget.loops`: (monthly_usd, scheduled_stop_pct)."""
    b = ((fleet.get("budget") or {}).get("loops") or {})
    usd, pct = b.get("monthly_usd"), b.get("scheduled_stop_pct")
    if (not isinstance(usd, (int, float)) or isinstance(usd, bool) or not math.isfinite(usd) or usd <= 0
            or not isinstance(pct, int) or isinstance(pct, bool) or not 0 < pct <= 100):
        raise StepSpecError("_data/fleet.yml budget.loops needs a finite monthly_usd > 0 and scheduled_stop_pct in "
                            "1..100 — the local loops' monthly ceiling")
    return float(usd), pct


def _utc_month(ts: str) -> str | None:
    try:
        t = dt.datetime.fromisoformat(ts)
    except ValueError:
        return None
    return (t if t.tzinfo else t.replace(tzinfo=dt.UTC)).astimezone(dt.UTC).strftime("%Y-%m")


#: dash-gen ai_activity.LEDGER_VERSION (this package never imports dash-gen;
#: tools/test_jev_loop.py holds the two equal)
LEDGER_VERSION = 1


def unledgered_path(ledger: Path | None = None) -> Path:
    """Beside the AI ledger (never pruned with the runs): the engine's own
    charge for an attempt whose ai-run left no ledger row — it died, the
    backstop killed it, or its ledger write failed. budget_position counts
    each one whose attempt_id the ledger does not have, so a later run, and
    the canary, see that spend."""
    p = ledger or ledger_path()
    return p.with_name(p.name + ".loops-unledgered.jsonl")


def record_unledgered(ctx: RunContext, row: dict, attempt_id: str, cost: float, source: str) -> None:
    """Make an unledgered charge durable (under budget_lock, which the attempt
    holds); kept in this run's memory as well only if the file cannot take it."""
    line = {"timestamp": iso(), "origin": "local", "loop": ctx.spec.loop, "step": ctx.spec.step,
            "run_id": ctx.run.run_id, "attempt_id": attempt_id, "item": row.get("item"),
            "cost_usd": round(cost, 6), "cost_source": source}
    try:
        fd = os.open(unledgered_path(), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, sort_keys=True) + "\n")
    except OSError as exc:
        print(f"jev loop: ! could not record the unledgered ${cost:g} charge in {unledgered_path()} ({exc}) — "
              "only this run counts it", file=sys.stderr)
        ctx.unledgered.append((cost, source))


def budget_position(fleet: dict, *, scheduled: bool, path: Path | None = None,
                    month: str | None = None) -> BudgetState:
    """Where this UTC month stands against `budget.loops`, from the AI ledger's
    rows with `origin: local` and a `loop` field (a plain `dash ai run` has
    none, so hand runs never count against the loops) — the same BudgetState
    arithmetic as the conflict engine. A ledger that exists but cannot be read
    (not JSON, not an object, another version) refuses: an unreadable ledger is
    not an empty month, and ai_activity's writers refuse to overwrite one."""
    cap, pct = loops_budget(fleet)
    m = month or now_utc().strftime("%Y-%m")
    p = path or ledger_path()
    rows: dict = {}
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise JevError(f"the AI ledger {p} cannot be read ({exc}) — the monthly ceiling cannot be judged; repair "
                           "it in place (moved aside, the month would read as $0)") from exc
        if not isinstance(data, dict) or data.get("version") != LEDGER_VERSION:
            found = f"version {data.get('version')!r}" if isinstance(data, dict) else f"a JSON {type(data).__name__}"
            raise JevError(f"the AI ledger {p} is {found}, not version {LEDGER_VERSION} — the monthly ceiling cannot "
                           "be judged; migrate it in place (moved aside, the month would read as $0)")
        rows = data.get("runs") or {}
    spent = estimated = 0.0
    for rec in rows.values() if isinstance(rows, dict) else []:
        if not isinstance(rec, dict) or rec.get("origin") != "local" or not rec.get("loop"):
            continue
        if _utc_month(str(rec.get("timestamp") or "")) != m:
            continue
        cost = _ledger_cost(rec, p)
        spent += cost
        if rec.get("cost_source") == "estimated":
            estimated += cost
    ledgered = {str(r.get("attempt_id")) for r in (rows.values() if isinstance(rows, dict) else [])
                if isinstance(r, dict) and r.get("attempt_id")}
    for rec in _unledgered_rows(unledgered_path(p)):
        if str(rec.get("attempt_id")) in ledgered or _utc_month(str(rec.get("timestamp") or "")) != m:
            continue
        spent += rec["cost_usd"]
        if rec.get("cost_source") == "estimated":
            estimated += rec["cost_usd"]
    return BudgetState(month=m, spent_usd=round(spent, 4), estimated_usd=round(estimated, 4), cap_usd=cap,
                       stop_usd=round(cap * pct / 100.0, 4), scheduled=scheduled)


def _spend(value) -> float | None:
    """A spend figure the ceiling can add: finite and not negative. JSON reads
    `NaN` and `Infinity`, and one NaN would make every later comparison with
    the ceiling false, which reads as "fits"; a negative figure would give
    spend back."""
    try:
        cost = float(value)
    except (TypeError, ValueError):
        return None
    return cost if math.isfinite(cost) and cost >= 0 else None


def _ledger_cost(rec: dict, p: Path) -> float:
    """A ledger row's cost; an unreadable figure is charged at its cap, and one
    with no readable cap either refuses like an unreadable ledger."""
    cost = _spend(rec.get("total_cost_usd") or 0.0)
    if cost is None:
        cost = _spend(rec.get("cap_usd") or 0.0)
    if cost is None:
        raise JevError(f"the AI ledger {p} has a row ({rec.get('session_id') or rec.get('attempt_id') or '?'}) whose "
                       "cost and cap are both unreadable — the monthly ceiling cannot be judged; repair it in place")
    return cost


def _unledgered_rows(p: Path) -> list[dict]:
    """The engine's durable unledgered charges; a line that cannot be read
    refuses like an unreadable ledger (it is spend, not noise)."""
    try:
        text = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise JevError(f"{p} cannot be read ({exc}) — the monthly ceiling cannot be judged") from exc
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
            cost = _spend(rec["cost_usd"])
            if cost is None:
                raise ValueError(f"cost_usd {rec['cost_usd']!r} is not a finite figure of 0 or more")
            rec["cost_usd"] = cost
        except (ValueError, TypeError, KeyError) as exc:
            raise JevError(f"{p} line {n} cannot be read ({exc}) — the monthly ceiling cannot be judged; repair "
                           "the line, never drop it (it is this month's spend)") from exc
        out.append(rec)
    return out


def charge(state: BudgetState, cost: float, source: str | None) -> None:
    """This run's own spend, counted as it happens (the ledger has it too)."""
    state.spent_usd = round(state.spent_usd + cost, 4)
    if source == "estimated":
        state.estimated_usd = round(state.estimated_usd + cost, 4)


@contextlib.contextmanager
def budget_lock() -> Iterator[bool]:
    """Held from the ceiling check until ai-run has ledgered the attempt (or the
    canary), so concurrent runs — of any step, from any checkout of the hub —
    cannot each pass `affords()` on the same month. It lives beside the shared
    AI ledger, not under this checkout's runs directory. Never waits: True when
    this process holds it, False when another attempt does."""
    p = ledger_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.with_name(p.name + ".loops.lock").open("a") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            held = False
        else:
            held = True
        try:
            yield held
        finally:
            if held:
                fcntl.flock(fh, fcntl.LOCK_UN)


def publish_token() -> tuple[str | None, str]:
    """The token a filing runs with: FLEET_TOKEN from the environment, then from
    the hub .env (that one name only, never sourced), else the ambient gh
    login. Value and source; the value is never printed or recorded."""
    if os.environ.get("FLEET_TOKEN"):
        return os.environ["FLEET_TOKEN"], "env FLEET_TOKEN"
    dotenv = dotenv_values(("FLEET_TOKEN",), Path(os.environ.get("JEV_DOTENV") or HUB / ".env"))
    if dotenv.get("FLEET_TOKEN"):
        return dotenv["FLEET_TOKEN"], ".env FLEET_TOKEN"
    return None, "the ambient gh login"


def publish_env(token: str | None) -> dict[str, str]:
    """The filer's environment for an applied write: the deterministic one,
    plus GH_TOKEN in this subprocess only when a FLEET_TOKEN was chosen."""
    env = deterministic_env()
    if token:
        env["GH_TOKEN"] = token
    return env


def probe_publish_token() -> tuple[dict[str, str] | None, str]:
    """Probe the publish token with `gh api user` (a read) BEFORE anything
    spends or files — a token's presence proves nothing (AGENTS.md). Returns
    the apply environment and who it is, or None and why."""
    token, source = publish_token()
    res = gh(["api", "user", "--jq", ".login"], env={"GH_TOKEN": token} if token else None, timeout=60)
    login = res.out.strip()
    if not res.ok or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}(\[bot\])?", login):
        said = headless.Redactor(os.environ, {"FLEET_TOKEN": token or ""}).text((res.err or res.out).strip())[-200:]
        return None, f"the publish token ({source}) was refused by `gh api user`: {said or f'exit {res.code}'}"
    return publish_env(token), f"{login} ({source})"


def planner_argv(spec: StepSpec, plan_dir: Path, opts: Options, *, target: str | None = None,
                 no_files: bool = False) -> list[str]:
    """The spec's planner argv with the engine options mapped through planner.flags."""
    pl = spec.local.planner
    argv = render_argv(pl.argv, {"plan_dir": str(plan_dir)})
    wanted = {"target": target if target is not None else (opts.target if opts.target != "all" else None),
              "focus": opts.focus or None, "day": opts.day, "offline": opts.offline or None,
              "no_files": no_files or None}
    for key, value in wanted.items():
        if not value:
            continue
        flag = pl.flags.get(key)
        if flag is None:
            raise StepSpecError(f"{spec.loop}/{spec.step}: the planner takes no {key} (local.planner.flags)")
        argv.append(flag if value is True else f"{flag}={value}")
    return argv


def parse_last_json(text: str) -> dict | None:
    lines = [ln for ln in (text or "").strip().splitlines() if ln.strip()]
    try:
        out = json.loads(lines[-1]) if lines else None
    except ValueError:
        return None
    return out if isinstance(out, dict) else None


# --------------------------------------------------------------------------- #
# the run directory and its history
# --------------------------------------------------------------------------- #
class RunDir:
    """`.fleet/runs/<run_id>/` — run.json, attempts.jsonl, summary.md, plan/, items/."""

    def __init__(self, path: Path):
        self.path = path
        self.run_id = path.name

    @classmethod
    def new(cls, loop: str, step: str, run_id: str | None = None) -> RunDir:
        rid = run_id or f"{now_utc():%Y%m%dT%H%M%SZ}-{loop}-{step}-{uuid.uuid4().hex[:6]}"
        base = runs_dir()
        base.mkdir(parents=True, exist_ok=True)
        base.chmod(0o700)   # run records hold repository content, private repos' included
        path = base / rid
        try:
            path.mkdir(mode=0o700)
        except FileExistsError as exc:
            raise JevError(f"run {rid} already exists") from exc
        return cls(path)

    @classmethod
    def load(cls, run_id: str) -> RunDir:
        if not wsp.RUN_ID_RX.fullmatch(run_id or ""):
            raise JevError(f"{run_id!r} is not a run id")
        path = runs_dir() / run_id
        if not (path / "run.json").is_file():
            raise JevError(f"no run {run_id} under {runs_dir()}")
        return cls(path)

    def write_json(self, rel: str, obj: object) -> Path:
        p = self.path / rel
        write_json(p, obj)
        return p

    def append_attempt(self, row: dict) -> None:
        with (self.path / "attempts.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"schema": ATTEMPT_SCHEMA, "ts": iso(), **row}, sort_keys=True, default=str) + "\n")


class History:
    """Earlier runs' attempts.jsonl — tier 0's memory."""

    def __init__(self, base: Path | None = None):
        self.base = base or runs_dir()

    def rows(self) -> Iterator[tuple[str, dict]]:
        for f in sorted(self.base.glob("*/attempts.jsonl")):
            try:
                lines = f.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for line in lines:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict):
                    yield f.parent.name, row

    def completed(self, spec: StepSpec, item_key: str, reuse_key: str, *, within_days: int = REUSE_DAYS
                  ) -> dict | None:
        """The newest completed (`attempt`, outcome ok, validated) attempt of this
        item with this reuse key within `within_days`, and whether it was published.

        A publish is matched to the attempt by CONTENT, not by run: a later run
        that reused this attempt's outputs (tier 0) and filed them writes its
        `publish-apply` row in its own run directory. The row contract: every
        `publish-apply` row (`loop run --apply`, `loop publish --apply`) carries
        the `validated_sha256` of the file it published."""
        horizon = now_utc() - dt.timedelta(days=within_days)
        best: dict | None = None
        published: set[str] = set()
        for run_id, row in self.rows():
            if row.get("loop") != spec.loop or row.get("step") != spec.step or row.get("item") != item_key:
                continue
            if row.get("decision") == "publish-apply" and row.get("published") and row.get("validated_sha256"):
                published.add(str(row["validated_sha256"]))
            if (row.get("decision") != "attempt" or row.get("outcome") != "ok"
                    or row.get("reuse_key") != reuse_key or not row.get("validated_sha256")):
                continue
            try:
                ts = dt.datetime.strptime(str(row.get("ts")), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.UTC)
            except ValueError:
                continue
            if ts < horizon:
                continue
            item_dir = self.base / run_id / "items" / wsp.item_dirname(item_key)
            if best is None or ts >= best["_ts"]:
                best = {"_ts": ts, "run_id": run_id, "date": ts.date().isoformat(), "item_dir": str(item_dir),
                        "validated_sha256": row["validated_sha256"], "validated_rel": row.get("validated_rel")}
        if best is None:
            return None
        best["published"] = best["validated_sha256"] in published
        best.pop("_ts")
        return best

    def published_run(self, spec: StepSpec, item_key: str, validated_sha256: str) -> str | None:
        """The run that already filed these validated bytes for this item (a
        `publish-apply` row with `published`, whole or partial), or None — so
        two previews of one attempt (a tier-0 reuse) cannot both be filed."""
        for run_id, row in self.rows():
            if (row.get("loop") == spec.loop and row.get("step") == spec.step and row.get("item") == item_key
                    and row.get("decision") == "publish-apply" and row.get("published")
                    and row.get("validated_sha256") == validated_sha256):
                return run_id
        return None


def prune(keep: int = KEEP_RUNS, *, current: str | None = None) -> list[str]:
    """Remove the oldest run directories beyond `keep` (only ones this engine
    wrote) — every run ends with this, so the newest KEEP_RUNS runs are kept."""
    base = runs_dir()
    runs = []
    for d in base.iterdir() if base.is_dir() else []:
        meta = read_json(d / "run.json") if d.is_dir() else {}
        if meta.get("schema") == RUN_SCHEMA and d.name != current:
            runs.append((str(meta.get("started") or ""), d))
    runs.sort()
    gone = []
    for _, d in runs[: max(0, len(runs) - (keep - 1 if current else keep))]:
        shutil.rmtree(d, ignore_errors=False)
        gone.append(d.name)
    return gone


class LockHeld(JevError):
    """Another run of the same loop step holds its lock."""


@contextlib.contextmanager
def step_lock(spec: StepSpec) -> Iterator[None]:
    """One run per loop step at a time (a second one exits 2, it never waits)."""
    locks = runs_dir() / ".locks"
    locks.mkdir(parents=True, exist_ok=True)
    fh = (locks / f"{spec.loop}-{spec.step}.lock").open("w")
    try:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise LockHeld(f"{spec.loop}/{spec.step} is already running (lock {fh.name})") from exc
        yield
    finally:
        fh.close()


# --------------------------------------------------------------------------- #
# the context the adapter sees
# --------------------------------------------------------------------------- #
@dataclass
class RunContext:
    spec: StepSpec
    adapter: Adapter
    fleet: dict
    opts: Options
    plan_dir: Path
    history: History
    run: RunDir | None = None
    home: Path = field(default_factory=Path.home)
    hostname: str = field(default_factory=lambda: platform.node().split(".")[0])
    work_root: Path = field(default_factory=headless.work_root)
    #: the month against budget.loops; this run's own attempts are charged as they end
    budget: BudgetState | None = None
    #: the probed apply environment (GH_TOKEN only when FLEET_TOKEN was chosen); None = no --apply
    publish_env: dict[str, str] | None = None
    #: a spent usage window: the rest of the queue is skipped, never retried on another credential
    usage_limited: bool = False
    #: (exit code, why) once the run must stop: a rejected credential, an unproven sandbox, a cancel
    stop: tuple[int, str] | None = None
    #: this run's charges that reached no ledger row (ai-run left no outcome, or could not write its row):
    #: (cost, source), added back whenever the month is re-read
    unledgered: list[tuple[float, str]] = field(default_factory=list)
    #: the item being worked on, so an interrupt still records it (and its spend) in run.json
    inflight: dict | None = None

    def item_dir(self, item: Item) -> Path:
        base = self.run.path if self.run else self.plan_dir.parent
        return base / "items" / wsp.item_dirname(item.key)

    def bodies_dir(self, item: Item, *, apply: bool) -> Path:
        """The publish phase's own directory: the dry preview writes `bodies/`
        (what a person reviews) and the apply `filed/`, so filing never
        overwrites or renumbers the reviewed bytes."""
        return self.item_dir(item) / ("filed" if apply else "bodies")

    def run_ref(self) -> str:
        return f"local run {self.run.run_id if self.run else 'plan'} (tools/jev loop)"

    def dash_gen(self, argv: list[str], *, stdin: str | None = None) -> Run:
        if argv[:1] == ["context"]:
            # the planes bound themselves by --deadline-s; this is the backstop, and a timeout is a plane
            # problem (context.gather makes every plane section unavailable), never the run's
            return dash_gen(argv, stdin=stdin, timeout=context_backstop(argv))
        return dash_gen(argv, stdin=stdin)

    def planner(self, *, target: str | None = None, no_files: bool = False) -> dict:
        with tempfile.TemporaryDirectory(prefix="jev-plan-") as tmp:
            out_dir = Path(tmp) if no_files else self.plan_dir
            res = dash_gen(planner_argv(self.spec, out_dir, self.opts, target=target, no_files=no_files))
        plan = parse_last_json(res.out)
        if res.code not in (0, 1) or plan is None:
            raise JevError(f"the planner exited {res.code}: {(res.err or res.out).strip()[-400:]}")
        return plan


# --------------------------------------------------------------------------- #
# gates and the host
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


def sandbox_available() -> bool:
    """P1's sandbox posture is Seatbelt: macOS with sandbox-exec."""
    return sys.platform == "darwin" and SANDBOX_EXEC.is_file()


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
    if posture.name == "sandbox" and not sandbox_available():
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


def hub_state(paths: list[str]) -> dict:
    head = git(["rev-parse", "HEAD"], cwd=HUB)
    dirty = git(["status", "--porcelain=v1", "--", *paths], cwd=HUB)
    return {"head": head.out.strip() if head.ok else None,
            "dirty_paths": sorted({line[3:] for line in dirty.out.splitlines() if len(line) > 3})}


def item_values(ctx: RunContext, item: Item, *, validated: Path | str | None = None,
                apply: bool = False) -> dict[str, str]:
    """The argv tokens for one item. `{validated}` is the adapter's
    `Verdict.publish_file` (the engine never names an output file), so a
    publish without a verdict leaves it unfilled and render_argv refuses it."""
    out = {"plan_dir": str(ctx.plan_dir), "nwo": item.nwo, "name": item.name, "branch": item.branch,
           "item_dir": str(ctx.item_dir(item)), "bodies_dir": str(ctx.bodies_dir(item, apply=apply)),
           "run_ref": ctx.run_ref()}
    if validated is not None:
        out["validated"] = str(validated)
    return out


def auth_pin(auth: headless.AuthChoice | None) -> list[str]:
    """ai-run's flags for exactly this credential: its method, and the source
    it must come from (no fallback to the next source, which could carry a
    variable the canary never proved hidden)."""
    return ["--auth-order", auth.method, "--auth-source", auth.source] if auth else []


def ai_run_argv(ctx: RunContext, item: Item, *, cwd: Path, tmp: Path, flags: list[str], attempt_id: str,
                auth: headless.AuthChoice | None, claude: str) -> list[str]:
    """The `tools/dash-gen ai-run` command a live attempt runs. It carries the
    exact cap the ceiling was judged on (ai-run refuses one above the call
    site's, and never re-reads a higher one) and the exact credential source
    the host check chose and the canary was proved for (`auth_pin`)."""
    d = ctx.item_dir(item)
    spec = ctx.spec
    argv = ["ai-run", "--stream", "--isolate", "--isolate-tmp", str(tmp),
            "--timeout", str(spec.timeout_minutes * 60), "--call-site", spec.call_site, "--repo", item.nwo,
            "--cwd", str(cwd), "--prompt-file", str(d / "prompt.txt"), "--trace", str(d / "trace.jsonl"),
            "--result-file", str(d / "result.json"), "--outcome-file", str(d / "outcome.json"),
            "--usage-limit", "skip", "--source", f"jev loop {spec.loop}/{spec.step}", "--claude-bin", claude,
            "--ledger", str(ledger_path()), "--max-budget-usd", f"{spec.resolved.max_budget_usd:g}"]
    argv += auth_pin(auth)
    meta = {"origin": "local", "run_id": ctx.run.run_id if ctx.run else "plan", "attempt_id": attempt_id,
            "loop": spec.loop, "step": spec.step, "item": item.key, "tier": TIER}
    for k, v in meta.items():
        argv += ["--meta", f"{k}={v}"]
    return [*argv, "--", *flags]


#: ai-run options a rehearsal drops with their values: the prompt (so the CLI
#: sees an empty stdin) and the attempt's own artefacts (a dry run that wrote
#: outcome.json would look like an attempt that ran)
REHEARSAL_DROP = ("--prompt-file", "--outcome-file", "--result-file", "--trace")


def rehearsal_argv(live: list[str]) -> list[str]:
    """The live ai-run argv as a $0 dry run: `--dry-run`, and none of
    REHEARSAL_DROP — run on an empty stdin, so even if --dry-run were ever
    ignored, the CLI would answer "Input must be provided" and reach no model."""
    out, skip = ["ai-run", "--dry-run"], False
    for i, a in enumerate(live[1:], 1):
        if skip:
            skip = False
            continue
        if a == "--":
            out += live[i:]
            break
        if a in REHEARSAL_DROP:
            skip = True
            continue
        out.append(a)
    return out


def check_plan_prompts(spec: StepSpec, plan: dict) -> list[str]:
    """Every row the planner rendered a prompt for must render byte-equal here."""
    errs = []
    for row in plan.get("include") or []:
        if "prompt" not in row:
            continue
        try:
            mine = render_prompt(spec, values_from(spec, row))
        except StepSpecError as exc:
            errs.append(f"{row.get('name')}: {exc}")
            continue
        if mine != row["prompt"]:
            errs.append(f"{row.get('name')}: the planner's prompt (sha256 {_sha(str(row['prompt']))[:12]}) is not the "
                        f"spec's render (sha256 {_sha(mine)[:12]}) — refusing to run a prompt nobody reviewed")
    return errs


# --------------------------------------------------------------------------- #
# planning
# --------------------------------------------------------------------------- #
def obtain_plan(ctx: RunContext) -> tuple[dict | None, tuple[int, str] | None]:
    """The planner's JSON in ctx.plan_dir (or one row of a saved plan)."""
    ctx.plan_dir.mkdir(parents=True, exist_ok=True)
    if ctx.opts.plan_file:
        # `tools/dash loop` runs from the hub root: a relative path is the caller's
        src = Path(os.environ.get("JEV_CALLER_CWD") or ".") / ctx.opts.plan_file
        if not src.is_file():
            return None, (EXIT["usage"], f"--plan-file {src}: no such file")
        saved = read_json(src)
        shape = plan_shape_error(saved)
        if shape:
            return None, (EXIT["usage"], f"--plan-file {src}: {shape}")
        rows = [r for r in saved.get("include") or [] if ctx.opts.item in (r.get("name"), r.get("nwo"))]
        if len(rows) != 1:
            return None, (EXIT["usage"], f"--plan-file {src}: {len(rows)} row(s) named {ctx.opts.item!r}")
        name = rows[0].get("brief")
        if name is not None:
            if not is_bare_name(name):
                return None, (EXIT["usage"], f"--plan-file: the brief {name!r} is not a bare file name beside "
                                             "the plan")
            brief = src.parent / name
            if brief.is_symlink() or not brief.is_file():
                return None, (EXIT["usage"], f"--plan-file: the brief {brief} is not a regular file beside the plan")
            shutil.copyfile(brief, ctx.plan_dir / name)
        plan = {**saved, "include": rows, "count": 1, "skipped": [], "dropped": []}
    else:
        res = dash_gen(planner_argv(ctx.spec, ctx.plan_dir, ctx.opts))
        plan = parse_last_json(res.out)
        if res.code not in (0, 1) or plan is None:
            return None, (EXIT["usage"], f"the planner exited {res.code}: {(res.err or res.out).strip()[-400:]}")
        shape = plan_shape_error(plan)
        if shape:
            return None, (EXIT["usage"], f"the planner's plan: {shape}")
    write_json(ctx.plan_dir / "plan.json", plan)
    errs = check_plan_prompts(ctx.spec, plan)
    if errs:
        return None, (EXIT["usage"], "; ".join(errs))
    return plan, None


def plan_shape_error(plan: dict) -> str | None:
    """Why a plan is not readable (`include`, `skipped` and `dropped` must be
    lists of objects, or absent); None when it is. A hand-edited or truncated
    saved plan is a usage error, never a traceback that leaves a run at "running"."""
    if not plan:
        return "not a JSON object (or an empty one)"
    for key in ("include", "skipped", "dropped"):
        rows = plan.get(key)
        if rows is not None and (not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows)):
            return f"`{key}` must be a list of objects"
    return None


def check_items(result: PlanResult) -> None:
    """One plan, distinct keys: two items sharing a key would share a run
    directory and a workspace."""
    keys = [i.key for i in result.items]
    dupes = sorted({k for k in keys if keys.count(k) > 1})
    if dupes:
        raise JevError(f"the plan holds item key(s) more than once: {', '.join(dupes)}")


def brief_in_plan(ctx: RunContext, item: Item) -> Path | None:
    """The item's brief, only as a regular file directly in the plan directory."""
    if item.brief is None:
        return None
    b = Path(item.brief)
    if b.is_symlink() or not b.is_file() or b.parent.resolve() != ctx.plan_dir.resolve():
        raise JevError(f"{item.key}: the brief {b} is not a regular file in the plan directory")
    return b


def explain_empty(ctx: RunContext, result: PlanResult) -> str:
    rows = [*result.skipped, *result.dropped]
    hit = next((r for r in rows if r.get("name") == ctx.opts.target), None)
    return f"{ctx.opts.target}: {hit['reason'] if hit else 'not in the plan'}"


# --------------------------------------------------------------------------- #
# the context pack (tools/jev/context.py): built on the host, read by the sealed agent
# --------------------------------------------------------------------------- #
def context_settings(spec: StepSpec) -> ContextSpec:
    """The spec's `local.context` (the loader always sets it; a LocalSpec made
    by hand without one gets the loader's defaults)."""
    if spec.local is not None and spec.local.context is not None:
        return spec.local.context
    return ContextSpec(mode=cpack.DEFAULT_MODE, file="context.md", providers=cpack.PROVIDERS,
                       max_chars=cpack.DEFAULT_MAX_CHARS, deadline_s=cpack.DEFAULT_DEADLINE_S, days=cpack.DEFAULT_DAYS)


def context_mode(ctx: RunContext) -> str:
    """`--context` when given, else the spec's mode."""
    return ctx.opts.context or context_settings(ctx.spec).mode


def context_backstop(argv: list[str]) -> int:
    """`dash-gen context`'s subprocess timeout: its own --deadline-s plus CONTEXT_GRACE_S."""
    said = next((a.split("=", 1)[1] for a in argv if a.startswith("--deadline-s=")), "")
    try:
        secs = cpack.check_deadline(said)
    except ValueError:
        secs = cpack.MAX_DEADLINE_S
    return int(math.ceil(secs)) + CONTEXT_GRACE_S


def _finite(value) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def context_status(statuses: dict[str, str]) -> str:
    """The attempt row's compact form: `history:ok,lake_ci:stale,…`."""
    return ",".join(f"{k}:{v}" for k, v in statuses.items())


def context_request(ctx: RunContext, item: Item) -> cpack.ContextRequest | None:
    """The adapter's request with the spec's window; None when it asks for no pack."""
    req = ctx.adapter.context_request(ctx, item)
    return None if req is None else dataclasses.replace(req, days=context_settings(ctx.spec).days)


def item_pack(ctx: RunContext, item: Item, report: dict, row: dict) -> cpack.Pack | None:
    """Build this item's pack into its run directory (`context.build`) and
    record it: `report["context"]`, and on `row` (every later attempt row) the
    pack's sha256 and a compact status. Mode 'off' builds and places nothing,
    and the adapter is not asked; an adapter that asks for no pack (None) is
    'none'. A plane that is down is a status in the pack, never an exception
    here; an error that does raise (a bad request, an unwritable run
    directory) is the engine's own and is not caught."""
    cs = context_settings(ctx.spec)
    mode = context_mode(ctx)
    req = cpack.ContextRequest(item.nwo, item.name, days=cs.days) if mode == "off" else context_request(ctx, item)
    if req is None:
        report["context"] = {"mode": mode, "sha256": None, "bytes": 0, "file": cs.file, "statuses": {},
                             "missing": [], "ages": {}, "elapsed_ms": 0,
                             "notes": ["context: the adapter asks for no pack for this item"],
                             "line": "context none (the adapter asks for no pack for this item)"}
        row.update(context_sha256=None, context_status="none")
        return None
    pack = cpack.build(ctx, item, req, mode=mode, sections=cs.providers, max_chars=cs.max_chars, file=cs.file,
                       deadline_s=cs.deadline_s)
    report["context"] = {"mode": pack.mode, "sha256": pack.sha256, "bytes": pack.bytes, "file": cs.file,
                         "statuses": dict(pack.sections), "missing": list(pack.missing),
                         "ages": {k: _finite(v) for k, v in pack.ages.items()}, "elapsed_ms": pack.elapsed_ms,
                         "notes": list(pack.notes), "queries": len(req.queries), "line": cpack.status_line(pack)}
    row.update(context_sha256=pack.sha256, context_status="off" if pack.path is None else context_status(pack.sections))
    return pack


def place_inputs(ctx: RunContext, ws: wsp.Workspace, brief: Path | None, pack: cpack.Pack | None) -> None:
    """The brief and (when one was built) the pack into the clone's brief
    directory, each as a NEW file (workspace.place_bytes: O_EXCL, no link
    followed). With a pack, the clone's copy of the brief is the plan's
    bytes + "\n" + `context.pointer` — written once, never placed and then
    rewritten. The plan directory's brief is never touched, so the adapter's
    reuse key, computed from it, and with it tier 0, are the same with or
    without a pack. Without one (mode off) the clone gets the plan's brief
    byte for byte, as it always did."""
    bd = ctx.spec.workspace.brief_dir
    built = pack is not None and pack.path is not None
    file = context_settings(ctx.spec).file
    if built and brief is not None and brief.name.lower() == file.lower():
        raise JevError(f"the brief {brief.name} and the context pack {file} would be one file in {bd}/")
    if brief is not None:
        data = brief.read_bytes()
        if built:
            data += b"\n" + cpack.pointer(bd, file).encode("utf-8")
        wsp.place_bytes(ws, data, f"{bd}/{brief.name}")
    if built:
        data = pack.path.read_bytes()
        if hashlib.sha256(data).hexdigest() != pack.sha256:
            raise JevError(f"the context pack {pack.path} changed since it was built")
        wsp.place_bytes(ws, data, f"{bd}/{file}", mode=0o600)


def context_preview(ctx: RunContext, item: Item) -> dict | None:
    """`loop plan`'s look at what this item's pack would hold: each
    section's status and age (no rows, nothing written anywhere), or None
    under mode 'off'."""
    mode = context_mode(ctx)
    if mode == "off":
        return None
    req = context_request(ctx, item)
    if req is None:
        return {"mode": mode, "statuses": {}, "ages": {}, "missing": [], "queries": 0, "would_block": False,
                "note": "the adapter asks for no pack for this item"}
    cs = context_settings(ctx.spec)
    doc = cpack.gather(ctx, req, sections=cs.providers, deadline_s=cs.deadline_s, item_key=item.key)
    secs = doc["sections"]
    statuses = {k: str(secs[k].get("status")) for k in secs}
    missing = [k for k in cpack.PLANE_SECTIONS if statuses.get(k) == "unavailable"]
    return {"mode": mode, "statuses": statuses, "ages": {k: _finite(secs[k].get("age_hours")) for k in secs},
            "missing": missing, "queries": len(req.queries), "would_block": mode == "require" and bool(missing)}


def context_bits(statuses: dict[str, str], ages: dict[str, float | None]) -> str:
    out = []
    for k, v in statuses.items():
        age = ages.get(k)
        out.append(f"{k} {v}" + (f"({age:.0f}h)" if v == "stale" and age is not None else ""))
    return " · ".join(out)


REFRESH_CMD_RX = re.compile(r"`(tools/dash [^`]+)`")


def doctor_planes(fleet: dict, spec: StepSpec) -> dict:
    """`loop doctor`'s context-planes section: each plane section's status
    and age for the hub (fleet.yml hub.repo — the hub is not in the
    registry), with the refresh command its note names. One `dash-gen
    context` call, read-only and $0 (one embedding of DOCTOR_QUERY)."""
    hub = hub_repo(fleet)
    with tempfile.TemporaryDirectory(prefix="jev-doctor-context-") as tmp:
        ctx = RunContext(spec=spec, adapter=adapters.get(spec.local.adapter), fleet=fleet, opts=Options(),
                         plan_dir=Path(tmp) / "plan", history=History())
        req = cpack.ContextRequest(hub, hub.split("/", 1)[1], (DOCTOR_QUERY,), days=context_settings(spec).days)
        doc = cpack.redact_obj(cpack.gather(ctx, req, sections=cpack.PLANE_SECTIONS,
                                            deadline_s=context_settings(spec).deadline_s, item_key=hub), ctx)
    out: dict = {"nwo": hub, "sections": {}, "problem": (doc.get("planes") or {}).get("problem")}
    for k, sec in doc["sections"].items():
        note = str(sec.get("note") or "")
        found = REFRESH_CMD_RX.search(note)
        entry = {"status": sec.get("status"), "age_hours": _finite(sec.get("age_hours")),
                 "as_of": sec.get("as_of"), "refresh": found.group(1) if found else None,
                 "note": " ".join(note.split())[:200]}
        if k == "index_code":   # the probe query was searched: answered is up, whether or not it hit
            entry["up"] = sec.get("status") in ("ok", "empty") and "holds no chunks" not in note
        out["sections"][k] = entry
    return out


def host_ctx() -> SimpleNamespace:
    """What `context.redact` reads to mask this machine, without a RunContext."""
    return SimpleNamespace(home=Path.home(), work_root=headless.work_root(), hostname=platform.node().split(".")[0])


# --------------------------------------------------------------------------- #
# one item: rehearsal or attempt
# --------------------------------------------------------------------------- #
def _file_sha(p: Path) -> str | None:
    try:
        return hashlib.sha256(Path(p).read_bytes()).hexdigest()
    except OSError:
        return None


def _bodies(d: Path) -> dict[str, str]:
    """name → sha256 of every body file a publish phase wrote in `d`."""
    return {p.name: _file_sha(p) or "" for p in sorted(d.glob("*.md"))} if d.is_dir() else {}


def usage_block(ctx: RunContext) -> tuple[str, str] | None:
    """(decision, why) for an item that would call the model after a usage
    window spent earlier in this run. Asked after tier 0, so a $0 reuse or
    skip (and its preview or filing, which reach gh, not Claude) still runs."""
    if ctx.usage_limited:
        return "usage-skip", "the usage window was spent earlier in this run (capacity, not a defect)"
    return None


def budget_block(ctx: RunContext, held: bool) -> tuple[str, str] | None:
    """(decision, why) when the month cannot absorb this attempt's full cap.
    Asked just before the model call — after tier 0, so a $0 reuse is never
    blocked — under `budget_lock`, against a FRESH read of the ledger and the
    engine's unledgered charges (plus any this run could not write down), so
    another run's spend is seen."""
    cap = ctx.spec.resolved.max_budget_usd
    if not held:
        return "budget-locked", ("another local loop attempt (or the canary) holds the budget lock — the month "
                               "cannot be judged while it spends; run again when it ends")
    try:
        state = budget_position(ctx.fleet, scheduled=ctx.opts.scheduled)
    except (JevError, StepSpecError) as exc:
        return "budget-unreadable", f"monthly ceiling: {exc}"
    for cost, source in ctx.unledgered:
        charge(state, cost, source)
    ctx.budget = state
    if not state.affords(cap):
        return "budget-skip", (f"monthly ceiling: {state.summary()}; this attempt may cost up to ${cap:g} "
                               f"({COST_LABEL})")
    return None


def run_item(ctx: RunContext, item: Item, host: HostReport, posture: headless.Posture) -> dict:
    """Everything one item does. A rehearsal stops before the model call, at
    $0; a live attempt goes on through ai-run, the posture checks, the
    harvest, validation, the dry-run preview and (with --apply) the filing."""
    live = not ctx.opts.rehearse
    dirname = wsp.item_dirname(item.key)
    report: dict = {"key": item.key, "dir": dirname, "name": item.name,
                    "status": "attempted" if live else "rehearsed", "reason": "",
                    "decision": "attempt" if live else "rehearsed", "code": EXIT["ok"]}
    row = {"run_id": ctx.run.run_id, "loop": ctx.spec.loop, "step": ctx.spec.step, "call_site": ctx.spec.call_site,
           "item": item.key, "dir": dirname, "nwo": item.nwo, "tier": TIER, "model": ctx.spec.resolved.model,
           "cost_usd": 0.0, "cost_source": "no-spend"}
    ctx.inflight = report
    sha, why = (None, "offline: no HEAD read") if ctx.opts.offline else head_sha(item.nwo, item.branch)
    if why:
        print(f"jev loop: {why}", file=sys.stderr)
    row.update(head_sha=sha, reuse_key=ctx.adapter.reuse_key(ctx, item, sha))
    t0 = ctx.adapter.tier0(ctx, item, sha)
    if t0.action != "continue":
        reused = _tier0(ctx, item, t0, report, row, live=live)
        if reused is not None:
            return reused
    if live:
        # after tier 0: a spent usage window stops model calls, not a $0 reuse or skip
        blocked = usage_block(ctx)
        if blocked:
            report.update(status="skipped", decision=blocked[0], reason=blocked[1])
            ctx.run.append_attempt({**row, "decision": blocked[0], "reason": blocked[1]})
            return report
    triage = ctx.adapter.classify(ctx, item)
    if triage.blocked:
        report.update(status="blocked", reason=triage.reason, decision="blocked")
        ctx.run.append_attempt({**row, "decision": "blocked", "reason": triage.reason})
        return report

    d = ctx.item_dir(item)
    d.mkdir(parents=True, exist_ok=True)
    attempt_id = str(uuid.uuid4())
    report["attempt_id"] = attempt_id
    prompt = render_prompt(ctx.spec, values_from(ctx.spec, item.row))
    (d / "prompt.txt").write_text(prompt, encoding="utf-8")
    write_json(d / "settings.json", headless.settings_doc(posture))
    flags = headless.claude_flags(ctx.spec, posture, settings_path=d / "settings.json", session_id=attempt_id,
                                  debug_path=d / "debug.log")
    ws = None
    try:
        brief = None
        if not ctx.opts.offline:
            try:
                ws = wsp.clone(item.nwo, item.branch, run_id=ctx.run.run_id, brief_dir=ctx.spec.workspace.brief_dir,
                               dirname=dirname)
            except JevError as exc:
                report.update(status="failed", reason=str(exc), code=EXIT["attention"])
                ctx.run.append_attempt({**row, "decision": report["decision"], "attempt_id": attempt_id,
                                        "outcome": "failed", "reason": str(exc)})
                return report
            if sha and ws.head_sha != sha:
                # the branch moved between the read and the clone: tier 0 again, on what was cloned
                row.update(head_sha=ws.head_sha, reuse_key=ctx.adapter.reuse_key(ctx, item, ws.head_sha))
                again = ctx.adapter.tier0(ctx, item, ws.head_sha)
                if again.action != "continue":
                    reused = _tier0(ctx, item, again, report, row, live=live)
                    if reused is not None:
                        return reused
            brief = brief_in_plan(ctx, item)
        # The context pack, built on the HOST now — after tier 0, the usage block, classify and the clone, before
        # the budget lock — into the item's run directory (offline: only there). The sealed agent reads the copy
        # placed beside the brief; it can ask the planes nothing itself.
        pack = item_pack(ctx, item, report, row)
        if pack is not None and pack.blocked:
            why = (f"context: mode require and {', '.join(pack.missing)} unavailable — the item does not run "
                   "(no budget lock, no ai-run, no spend)")
            report.update(status="failed", decision="context-blocked", reason=why, code=EXIT["attention"])
            ctx.run.append_attempt({**row, "decision": "context-blocked", "attempt_id": attempt_id, "reason": why})
            return report
        if ws is not None:
            place_inputs(ctx, ws, brief, pack)
            report["workspace"] = {"head_sha": ws.head_sha, "baseline_entries": len(ws.baseline),
                                   "baseline_sha256": _sha(json.dumps(ws.baseline, sort_keys=True))}
        cwd, tmp = (ws.path, ws.tmp) if ws else (d, d / "tmp")
        argv = ai_run_argv(ctx, item, cwd=cwd, tmp=tmp, flags=flags, attempt_id=attempt_id,
                           auth=host.auth, claude=host.claude or ctx.opts.claude_bin)
        env_keys = set(headless.agent_env(os.environ, None, credential_value=None, tmp=tmp,
                                          gh_config_dir=tmp / "gh-none", work=ctx.work_root))
        if headless.credential_exposure(host.auth):
            env_keys.add(str(headless.credential_exposure(host.auth)))
        write_json(d / "env-keys.json", sorted(env_keys))   # names only, never a value
        planned = {"claude_flags": flags, "ai_run": [str(DASH_GEN), *argv],
                   "prompt_sha256": _sha(prompt), "prompt_bytes": len(prompt.encode("utf-8")),
                   "settings_sha256": _sha(json.dumps(headless.settings_doc(posture), sort_keys=True))}
        if pack is not None and pack.path is not None:   # the prompt is the same bytes either way
            planned["context_sha256"] = pack.sha256
        write_json(d / "argv.json", planned)
        if live:
            with budget_lock() as held:
                blocked = budget_block(ctx, held)
                if blocked:
                    report.update(status="skipped", decision=blocked[0], reason=blocked[1])
                    ctx.run.append_attempt({**row, "decision": blocked[0], "attempt_id": attempt_id,
                                            "reason": blocked[1]})
                    return report
                try:
                    return attempt(ctx, item, ws, posture, argv, host, report, row)
                except JevError as exc:   # a git or harvest failure in the clone: the item's, not the run's
                    report.update(status="failed", reason=str(exc), code=EXIT["attention"])
                    ctx.run.append_attempt({**row, "decision": "attempt", "reason": str(exc), "status": "failed"})
                    return report
        _rehearsal_tail(ctx, item, ws, argv, host, report)
    except JevError as exc:   # this item's failure (git status, the brief, …): recorded, and the run goes on
        report.update(status="failed", reason=str(exc), code=EXIT["attention"])
    finally:
        # a tampered clone is destroyed even with --keep-workspace: git run in it would run the agent's config
        if ws is not None and (not ctx.opts.keep_workspace or report.get("tampered")):
            wsp.destroy(ws)
        elif ws is not None:
            report["kept_workspace"] = str(ws.path)
    ctx.run.append_attempt({**row, "decision": report["decision"], "attempt_id": attempt_id,
                            "outcome": report["status"], "reason": report["reason"]})
    return report


def _tier0(ctx: RunContext, item: Item, t0, report: dict, row: dict, *, live: bool) -> dict | None:
    """Record a tier-0 skip or reuse. A live reuse goes straight to the
    preview with the earlier attempt's validated copy; when that copy is gone
    or no longer matches its recorded sha, None — the item is attempted."""
    decision = f"tier0-{t0.action}"
    if t0.action == "reuse" and live:
        verdict = reuse_outputs(ctx, item, row)
        if verdict is None:
            print(f"jev loop: {item.key}: the reusable outputs are gone or changed — attempting afresh",
                  file=sys.stderr)
            return None
        report.update(status="reused", reason=t0.reason, decision=decision)
        row.update(validated_sha256=_file_sha(verdict.publish_file),
                   validated_rel=str(verdict.publish_file.relative_to(ctx.item_dir(item))))
        ctx.run.append_attempt({**row, "decision": decision, "reason": t0.reason,
                                "reuse_from": str(t0.reuse_from) if t0.reuse_from else None})
        try:
            return publish_phase(ctx, item, verdict, report, row)
        except JevError as exc:   # a planner or gh failure in the preview or the recheck: the item's, not the run's
            report.update(status="failed", reason=str(exc), code=EXIT["attention"])
            ctx.run.append_attempt({**row, "decision": decision, "reason": str(exc), "status": "failed"})
            return report
    report.update(status="skipped" if t0.action == "skip" else "reused", reason=t0.reason, decision=decision)
    ctx.run.append_attempt({**row, "decision": decision, "reason": t0.reason,
                            "reuse_from": str(t0.reuse_from) if t0.reuse_from else None})
    return report


def reuse_outputs(ctx: RunContext, item: Item, row: dict) -> Verdict | None:
    """The earlier attempt's validated copy, re-hashed against its recorded
    sha256 and copied into this run's item directory."""
    prior = ctx.history.completed(ctx.spec, item.key, row.get("reuse_key") or "")
    rel = (prior or {}).get("validated_rel")
    if not prior or not rel or Path(rel).is_absolute() or ".." in Path(rel).parts:
        return None
    src = Path(prior["item_dir"]) / rel
    if src.is_symlink() or not src.is_file() or _file_sha(src) != prior["validated_sha256"]:
        return None
    dest = ctx.item_dir(item) / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)
    return Verdict(True, publish_file=dest, facts={"reused_from": prior["run_id"]})


def _rehearsal_tail(ctx: RunContext, item: Item, ws, argv: list[str], host: HostReport, report: dict) -> None:
    """The planned ai-run command as `--dry-run` on an empty stdin, and the
    fresh clone held untampered and clean."""
    d = ctx.item_dir(item)
    if ws is None:
        report["reason"] = report["reason"] or "offline: no clone, no ai-run dry run"
        return
    dry = dash_gen(rehearsal_argv(argv), stdin="", timeout=120, env=ai_run_env(host.auth))
    said = headless.Redactor(os.environ).text((dry.err or "").strip())[-6000:]
    (d / "ai-run-dry.txt").write_text(said + "\n", encoding="utf-8")
    report["ai_run_dry"] = dry.code
    if dry.code == EXIT["credential"]:
        report["reason"] = "ai-run --dry-run: no usable Claude credential (a live attempt would exit 3)"
    elif dry.code != 0:
        report.update(status="failed", code=EXIT["attention"],
                      reason=f"ai-run --dry-run refused the planned argv (exit {dry.code}): {said[-300:]}")
    changed = wsp.tampered(ws)
    if changed:
        # no git runs in a tampered clone: it is destroyed uninspected (the caller's finally)
        (d / "tree.txt").write_text(f"not inspected: .git changed ({', '.join(changed)})\n", encoding="utf-8")
        report.update(status="failed", code=EXIT["attention"], reason=f"the workspace was tampered with: {changed}",
                      tampered=True)
        return
    tree = wsp.tree_report(ws)
    _write_tree(d, tree)
    if tree.tracked:
        report.update(status="failed", code=EXIT["attention"],
                      reason=f"the fresh workspace is not clean: tracked {tree.tracked}")


def _write_tree(d: Path, tree) -> None:
    (d / "tree.txt").write_text("\n".join([*(f"tracked {p}" for p in tree.tracked),
                                           *(f"untracked {p}" for p in tree.untracked)]) + "\n", encoding="utf-8")


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
    outcome) every call counts as executed."""
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
    bash = int(tool_uses.get("Bash") or 0)
    if bash and posture.name == "reduced":
        return f"Bash ran {bash} time(s) under the reduced posture, which grants none"
    denied = outcome.get("denied_tools")
    executed = bash - int(denied.get("Bash") or 0) if isinstance(denied, dict) else bash
    if executed > 0 and not headless.sandbox_engaged(debug):
        return (f"Bash executed {executed} time(s) but the debug log shows no sandbox engaged — the outputs are "
                "destroyed unread; re-run `tools/dash loop doctor` and the canary")
    fences = headless.sandbox_fence_problems(debug) if executed > 0 else []
    if fences:
        return f"Bash executed {executed} time(s) without its full sandbox: " + "; ".join(fences)
    return None


def attempt(ctx: RunContext, item: Item, ws, posture: headless.Posture, argv: list[str], host: HostReport,
            report: dict, row: dict) -> dict:
    """One model invocation through `tools/dash-gen ai-run`, then what the
    engine decides about it — in that order: tamper, posture, outcome, tree,
    harvest, validate, preview."""
    d = ctx.item_dir(item)
    spec = ctx.spec
    cap = spec.resolved.max_budget_usd
    try:
        res = relay_dash_gen(argv, env=ai_run_env(host.auth), timeout=spec.timeout_minutes * 60 + OUTER_GRACE_S)
    except KeyboardInterrupt:
        # ai-run had its minute to end the session and ledger it: record what it said, then stop the run
        said = read_json(d / "outcome.json")
        cost = float(said["cost_usd"]) if said.get("cost_usd") is not None else cap
        source = str(said.get("cost_source") or "estimated")
        if ctx.budget is not None:
            charge(ctx.budget, cost, source)
        if not said or said.get("ledger_error"):
            record_unledgered(ctx, row, report["attempt_id"], cost, source)
        kind = str(said.get("kind") or "interrupted")
        ctx.run.append_attempt({**row, "decision": "attempt", "attempt_id": report["attempt_id"],
                                "outcome": kind, "status": "interrupted", "cost_usd": cost, "cost_source": source})
        # cmd_run records this report (ctx.inflight) before it finishes the run
        report.update(status="interrupted", outcome=kind, cost_usd=cost, cost_source=source,
                      code=EXIT["interrupted"], reason="interrupted (Ctrl-C or a cancel) during the attempt")
        raise
    outcome = read_json(d / "outcome.json")
    if not outcome:
        # ai-run died before it classified (no outcome, so possibly no ledger row): charged at the cap here
        outcome = {"kind": "unparseable", "cost_usd": cap, "cost_source": "estimated",
                   "detail": f"ai-run exited {res.code} without an outcome, so claude may not have run: "
                             f"{res.err.strip()[-200:]}"}
        record_unledgered(ctx, row, report["attempt_id"], cap, "estimated")
    elif outcome.get("ledger_error"):
        record_unledgered(ctx, row, report["attempt_id"], float(outcome.get("cost_usd") or 0.0),
                          str(outcome.get("cost_source") or "reported"))
        report.setdefault("flags", []).append(f"this attempt is not in the AI ledger: {outcome['ledger_error']}")
    debug = headless.reduce_debug_log(d / "debug.log")
    (d / "debug-sandbox.txt").write_text("\n".join(debug) + "\n", encoding="utf-8")
    kind = str(outcome.get("kind"))
    cost = float(outcome.get("cost_usd") or 0.0)
    source = str(outcome.get("cost_source") or "reported")
    if ctx.budget is not None:
        charge(ctx.budget, cost, source)
    denials = int(outcome.get("permission_denials") or 0)
    row.update(attempt_id=report["attempt_id"], outcome=kind, cost_usd=cost, cost_source=source,
               turns=outcome.get("turns"), tool_uses=outcome.get("tool_uses") or {}, permission_denials=denials)
    report.update(outcome=kind, cost_usd=cost, cost_source=source, turns=outcome.get("turns"))
    if denials:
        report.setdefault("flags", []).append(f"{denials} permission denial(s) — allowlist drift? (#89)")

    def done(status: str, reason: str, code: int = EXIT["attention"]) -> dict:
        report.update(status=status, reason=reason, code=code)
        ctx.run.append_attempt({**row, "decision": "attempt", "reason": reason, "status": status})
        return report

    changed = wsp.tampered(ws)
    if changed:
        (d / "tree.txt").write_text(f"not inspected: .git changed ({', '.join(changed)})\n", encoding="utf-8")
        return done("failed", f"the workspace was tampered with: {changed} — destroyed with no git run in it")
    pinned = {"method": host.auth.method, "source": host.auth.source} if host.auth else None
    breach = ((f"the session ran under the credential {outcome['auth']}, not the one the host check chose and "
               f"the canary proved ({host.auth})") if "auth" in outcome and outcome["auth"] != pinned
              else posture_breach(spec, posture, outcome, debug, headless.read_events(d / "trace.jsonl")))
    if breach:
        ctx.stop = (EXIT["host_unsafe"], breach)
        return done("unsafe", breach, EXIT["host_unsafe"])
    detail = str(outcome.get("detail") or "")
    if kind == "usage_limit":
        ctx.usage_limited = True
        print("jev loop: ! Claude usage limit — the credential is VALID, do not rotate it (capacity, not a defect); "
              "the rest of the queue is skipped, nothing falls back to another credential (#348)", file=sys.stderr)
        return done("usage-limited", f"usage limit: {detail or 'HTTP 429'} (capacity; run again after the reset)",
                    EXIT["ok"])
    if kind == "credential_rejected":
        why = (f"the Claude credential ({host.auth}) was rejected: {detail} — `claude auth status`, or rotate "
               "CLAUDE_CODE_OAUTH_TOKEN (docs/TOKEN-ROTATION.md)")
        ctx.stop = (EXIT["credential"], why)
        return done("failed", why, EXIT["credential"])
    if kind in ("budget_hit", "max_turns"):
        # local.on_budget_hit: discard (JEV's rule) — CI's file job would file what the leg left behind.
        # Any other value (P3) has no behaviour here yet: fail closed rather than discard it silently.
        if spec.local.on_budget_hit != "discard":
            return done("failed", f"{kind}: on_budget_hit {spec.local.on_budget_hit!r} has no engine behaviour — "
                                  "the output is left unread")
        return done("discarded", f"{kind}: {detail} — the partial output is discarded (on_budget_hit "
                                 f"{spec.local.on_budget_hit}); a rerun costs about one attempt")
    if kind == "interrupted":
        ctx.stop = (EXIT["interrupted"], f"interrupted: {detail}")
        return done("failed", f"interrupted: {detail}", EXIT["interrupted"])
    if kind != "ok":
        return done("failed", f"{kind}: {detail}")

    tree = wsp.tree_report(ws)
    _write_tree(d, tree)
    if tree.tracked:
        wsp.discard_tracked(ws)   # CI's "Verify the tree is untouched"
        report.setdefault("flags", []).append(f"tracked edits discarded: {', '.join(tree.tracked)}")
    if tree.untracked:
        report.setdefault("flags", []).append(f"untracked files outside {spec.workspace.brief_dir}/ left in the "
                                              f"clone (ignored): {', '.join(tree.untracked[:10])}")
    harvested = {rel: wsp.harvest(ws, rel, d / "outputs") for rel in spec.workspace.outputs}
    verdict = ctx.adapter.validate(ctx, item, harvested, outcome)
    write_json(d / "validate.json", {"ok": verdict.ok, "problems": verdict.problems, "flags": verdict.flags,
                                     "facts": verdict.facts,
                                     "harvest": {r: {"reason": h.reason, "size": h.size, "sha256": h.sha256}
                                                 for r, h in harvested.items()}})
    report.setdefault("flags", []).extend(verdict.flags)
    if not verdict.ok or verdict.publish_file is None:
        return done("rejected", "; ".join(verdict.problems) or "the adapter gave no validated file")
    row.update(validated_sha256=_file_sha(verdict.publish_file),
               validated_rel=str(verdict.publish_file.relative_to(d)))
    ctx.run.append_attempt({**row, "decision": "attempt", "status": "validated"})
    report["facts"] = verdict.facts
    return publish_phase(ctx, item, verdict, report, row)


# --------------------------------------------------------------------------- #
# publishing: the dry-run preview, then (with --apply) the filing
# --------------------------------------------------------------------------- #
def publish_phase(ctx: RunContext, item: Item, verdict: Verdict, report: dict, row: dict) -> dict:
    """The preview always; the filing only with --apply (the maintainer's
    § 13.6 yes, typed on this command line) and only when the preview is
    publishable."""
    if ctx.spec.local.publish is None:
        report.update(status="validated")
        return report
    doc = preview(ctx, item, verdict)
    report.update(status="previewed", plan_id=doc["plan_id"], publishable=doc["publishable"],
                  would_file=len(doc["rows"]), reason=report.get("reason") or "; ".join(doc["blockers"]) or
                  ("nothing to file" if not doc["rows"] else f"{len(doc['rows'])} issue(s) previewed"))
    ctx.run.append_attempt({**row, "decision": "publish-preview", "plan_id": doc["plan_id"],
                            "publishable": doc["publishable"], "would_file": len(doc["rows"]), "cost_usd": 0.0,
                            "cost_source": "no-spend"})
    if not ctx.opts.apply:
        return report
    if not doc["publishable"]:
        report["reason"] = f"--apply: nothing filed — {report['reason']}"
        return report
    result = apply_item(ctx, item, doc)
    report.update(status=result["status"], reason=result["reason"], code=result["code"],
                  published=result.get("published", 0), urls=result.get("urls", []))
    return report


def publish_values(ctx: RunContext, item: Item, validated: Path, *, apply: bool,
                   bodies_dir: Path | None = None, reviewed: Path | None = None) -> list[str]:
    """The publish argv; with `apply`, the filer's apply flag and its reviewed
    flag naming `reviewed` (the preview's bodies), so the filing itself files
    no byte nobody reviewed and nothing it cannot dedupe."""
    pub = ctx.spec.local.publish
    values = item_values(ctx, item, validated=validated, apply=apply)
    if bodies_dir is not None:
        values["bodies_dir"] = str(bodies_dir)
    argv = render_argv(pub.argv, values)
    if not apply:
        return argv
    if reviewed is None:
        raise JevError("internal: an apply argv without the reviewed bodies")
    return [*argv, pub.apply_flag, PUBLISH_REVIEWED_FLAGS[argv[0]], str(reviewed)]


def preview(ctx: RunContext, item: Item, verdict: Verdict) -> dict:
    """The spec's publish argv WITHOUT its apply flag (a live dedupe read with
    the user's gh auth), into `items/<dir>/bodies/`: the exact bytes --apply
    would file, written down as publish-plan.json and publish-plan.md."""
    d = ctx.item_dir(item)
    argv = publish_values(ctx, item, verdict.publish_file, apply=False)
    plan = ctx.adapter.publish(ctx, item, verdict, lambda: ctx.dash_gen(argv))
    bodies = _bodies(ctx.bodies_dir(item, apply=False))
    vsha = _file_sha(verdict.publish_file)
    plan_id = _sha(json.dumps({"nwo": item.nwo, "validated_sha256": vsha, "argv": argv, "bodies": bodies},
                              sort_keys=True))[:16]
    labels = sorted({lab for r in plan.rows for lab in (r.get("labels") or [])})
    doc = {"schema": PUBLISH_PLAN_SCHEMA, "run_id": ctx.run.run_id, "plan_id": plan_id,
           "item": {"key": item.key, "name": item.name, "nwo": item.nwo, "branch": item.branch},
           "risk": ctx.spec.local.publish.risk, "tier": publish_tier(ctx.spec),
           "validated_rel": str(verdict.publish_file.relative_to(d)), "validated_sha256": vsha,
           "argv": argv, "apply_flag": ctx.spec.local.publish.apply_flag, "bodies": bodies,
           "rows": plan.rows, "blockers": plan.blockers, "failures": plan.failures,
           "publishable": plan.publishable and bool(bodies), "labels": labels,
           "flags": verdict.flags, "facts": verdict.facts, "created": iso()}
    write_json(d / "publish-plan.json", doc)
    (d / "publish-plan.md").write_text(_plan_md(doc, ctx.bodies_dir(item, apply=False)), encoding="utf-8")
    return doc


def _plan_md(doc: dict, bodies_dir: Path) -> str:
    item = doc["item"]
    lines = [f"# Publish plan {doc['plan_id']} — {item['nwo']}", "",
             f"- run: `{doc['run_id']}` · item `{item['key']}` · risk `{doc['risk']}` (tier {doc['tier']})",
             f"- validated file: `{doc['validated_rel']}` (sha256 {doc['validated_sha256']})",
             f"- publishable: {'yes' if doc['publishable'] else 'no'}"
             + (f" — blockers: {', '.join(doc['blockers'])}" if doc["blockers"] else ""), "",
             "## What `--apply` does", ""]
    if doc["labels"]:
        lines.append(f"1. `gh label create <name> -R {item['nwo']} --force` for {', '.join(doc['labels'])} — this "
                     "can refresh an existing label's colour and description.")
        lines.append(f"2. `gh issue create -R {item['nwo']}` once per body below, after a live recheck "
                     "(backpressure, the open-issue dedupe, the token probe); nothing else is written.")
    else:
        lines.append("Nothing: no proposal would be filed.")
    for f in doc["flags"]:
        lines.append(f"- flag: {f}")
    lines += ["", f"Publish this preview later: `tools/dash loop publish {doc['run_id']} --item {item['key']} "
              "--apply`", ""]
    for r in doc["rows"]:
        name = r.get("body_file") or ""
        body = (bodies_dir / name).read_text(encoding="utf-8") if name and (bodies_dir / name).is_file() else ""
        lines += [f"## {r.get('title')}", "", f"labels: {', '.join(r.get('labels') or [])} · body `{name}`", "",
                  "~~~~markdown", body.rstrip("\n"), "~~~~", ""]
    return "\n".join(lines) + "\n"


def _fresh_dry(ctx: RunContext, item: Item, validated: Path) -> tuple[PublishPlan, dict[str, str]]:
    """The preview again, with a live dedupe, into a scratch directory: what
    a filing would write NOW, as body hashes."""
    verdict = Verdict(True, publish_file=validated)
    with tempfile.TemporaryDirectory(prefix=".fresh-", dir=ctx.item_dir(item)) as tmp:
        argv = publish_values(ctx, item, validated, apply=False, bodies_dir=Path(tmp))
        plan = ctx.adapter.publish(ctx, item, verdict, lambda: ctx.dash_gen(argv))
        return plan, _bodies(Path(tmp))


def review_gap(ctx: RunContext, item: Item, doc: dict, fresh: PublishPlan, fresh_bodies: dict[str, str],
               validated: Path) -> str | None:
    """Why a live dry run would NOT file exactly what the preview showed, or
    None: a body whose hash is not among the reviewed ones, a title or label
    set nobody reviewed (labels come from `_data/fleet.yml` at filing time), a
    publish argv that is not the reviewed one, or bodies that cannot be
    compared. A live dedupe that only drops a reviewed issue is no gap."""
    unreviewed = sorted(n for n, s in fresh_bodies.items() if s not in set(doc["bodies"].values()))
    if unreviewed:
        return (f"a live dry run would file {len(unreviewed)} body(ies) that were not in the reviewed preview — run "
                "again and review the new preview")
    if fresh.rows and len(fresh_bodies) != len(fresh.rows):
        return (f"the live dry run wrote {len(fresh_bodies)} body file(s) for {len(fresh.rows)} issue(s), so the "
                "bytes cannot be compared")
    reviewed = {(r.get("title"), tuple(r.get("labels") or [])) for r in doc.get("rows") or []}
    moved = [str(r.get("title")) for r in fresh.rows if (r.get("title"), tuple(r.get("labels") or [])) not in reviewed]
    if moved:
        return f"a live dry run would file {moved[:3]} under a title or labels that were not reviewed"
    if publish_values(ctx, item, validated, apply=False) != doc.get("argv"):
        return "the publish argv is not the reviewed one (the spec or the run changed since the preview)"
    return None


#: The way on from an apply that filed nothing: its publish-result.json still
#: refuses a second apply of that preview, but it is not a publish, so tier 0
#: reuses the validated copy in a new run and previews it again.
NOTHING_FILED_RETRY = ("nothing was filed: run the loop again to retry (tier 0 reuses the validated copy at $0 "
                       "while HEAD and the brief are unchanged, and writes a new preview to apply)")


def _already_applied(result_path: Path) -> str:
    """Why a claimed publish-result.json refuses this apply — with the way on
    when the earlier apply filed nothing."""
    try:
        prior = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        prior = None
    if isinstance(prior, dict) and prior.get("status") == "publish-failed" and not prior.get("urls"):
        return f"already applied ({result_path.name} exists) and {NOTHING_FILED_RETRY}"
    return f"already applied ({result_path.name} exists) — a second apply is refused"


def apply_item(ctx: RunContext, item: Item, doc: dict) -> dict:
    """File a preview's bytes. Refused (exit 2) when it was already applied
    (here, or in another run that filed the same validated bytes), when the
    validated file or the reviewed bodies changed since the preview, or when a
    live dry run would now file anything that was not reviewed (`review_gap`); then
    the live recheck (the planner for this one target: issues enabled,
    backpressure); then the write, with GH_TOKEN in that subprocess only;
    then per-issue failure detection. publish-result.json is claimed with
    O_EXCL before the write, so a second or concurrent apply is refused."""
    d = ctx.item_dir(item)
    result_path = d / "publish-result.json"

    def refused(why: str) -> dict:
        return {"status": "publish-refused", "reason": why, "code": EXIT["usage"]}

    if ctx.publish_env is None:
        return refused("no probed publish token (internal: --apply without the token probe)")
    if result_path.exists():
        return refused(_already_applied(result_path))
    elsewhere = ctx.history.published_run(ctx.spec, item.key, str(doc.get("validated_sha256")))
    if elsewhere:
        return refused(f"already published in run {elsewhere} (the same validated bytes) — a second apply is refused")
    if not doc.get("publishable"):
        return refused("the preview is not publishable: " + ("; ".join(doc.get("blockers") or []) or "nothing to file"))
    validated = d / doc["validated_rel"]
    if validated.is_symlink() or _file_sha(validated) != doc["validated_sha256"]:
        return refused("the validated file changed since the preview")
    if _bodies(ctx.bodies_dir(item, apply=False)) != doc["bodies"]:
        return refused("the reviewed bodies changed since the preview")
    why = ctx.adapter.recheck(ctx, item)
    if why:
        return {"status": "publish-skipped", "reason": f"live recheck: {why}", "code": EXIT["attention"]}
    verdict = Verdict(True, publish_file=validated)
    fresh, fresh_bodies = _fresh_dry(ctx, item, validated)
    if fresh.blockers:
        return {"status": "publish-skipped", "reason": f"live recheck: {', '.join(fresh.blockers)}",
                "code": EXIT["attention"]}
    gap = review_gap(ctx, item, doc, fresh, fresh_bodies, validated)
    if gap:
        return refused(f"changed since the preview: {gap}")
    if not fresh.rows:
        return {"status": "publish-skipped", "reason": "nothing left to file after the live dedupe", "code": EXIT["ok"]}
    try:
        fd = os.open(result_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return refused("already applied (a concurrent apply claimed it)")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump({"schema": PUBLISH_RESULT_SCHEMA, "status": "applying", "plan_id": doc["plan_id"], "at": iso()}, fh)
    apply_argv = publish_values(ctx, item, validated, apply=True, reviewed=ctx.bodies_dir(item, apply=False))
    env = ctx.publish_env
    filed = ctx.adapter.publish(ctx, item, verdict, lambda: dash_gen(apply_argv, env=env), apply=True)
    urls = [r["url"] for r in filed.rows if r.get("url")]
    stray = sorted(n for n, s in _bodies(ctx.bodies_dir(item, apply=True)).items()
                   if s not in set(doc["bodies"].values()))
    status = ("published" if urls and not filed.failures and not filed.blockers
              else "partial" if urls else "publish-failed")
    reason = (f"filed {len(urls)} issue(s)" + (f"; FAILED: {', '.join(filed.failures)}" if filed.failures else "")
              + (f"; {', '.join(filed.blockers)}" if filed.blockers else "")
              + (f"; filed bodies not in the preview: {stray}" if stray else "")
              + (f"; {NOTHING_FILED_RETRY}" if status == "publish-failed" else ""))
    write_json(result_path, {"schema": PUBLISH_RESULT_SCHEMA, "status": status, "plan_id": doc["plan_id"],
                             "validated_sha256": doc["validated_sha256"], "urls": urls, "failures": filed.failures,
                             "blockers": filed.blockers, "stray_bodies": stray, "at": iso()})
    ctx.run.append_attempt({"run_id": ctx.run.run_id, "loop": ctx.spec.loop, "step": ctx.spec.step,
                            "call_site": ctx.spec.call_site, "item": item.key, "dir": wsp.item_dirname(item.key),
                            "nwo": item.nwo, "decision": "publish-apply", "plan_id": doc["plan_id"],
                            "validated_sha256": doc["validated_sha256"], "published": bool(urls),
                            "filed": len(urls), "failures": filed.failures, "status": status,
                            "cost_usd": 0.0, "cost_source": "no-spend"})
    return {"status": status, "reason": reason, "code": EXIT["ok"] if status == "published" else EXIT["attention"],
            "published": len(urls), "urls": urls}


def _new_record(ctx: RunContext, posture: headless.Posture) -> dict:
    spec = ctx.spec
    paths = [str(spec.path.parent.relative_to(HUB)) + "/", *ENGINE_SOURCES, *ctx.adapter.sources]
    return {
        "schema": RUN_SCHEMA, "run_id": ctx.run.run_id, "loop": spec.loop, "step": spec.step, "origin": "local",
        "mode": "rehearse" if ctx.opts.rehearse else ("apply" if ctx.opts.apply else "run"), "status": "running",
        "started": iso(), "finished": None,
        "hub": hub_state(paths),
        "spec": {"path": str(spec.path.relative_to(HUB)) if spec.path.is_relative_to(HUB) else str(spec.path),
                 "sha256": spec.content_sha256, "template_sha256": spec.template_sha256, "call_site": spec.call_site},
        "posture": {"name": posture.name, "network": list(posture.network),
                    "template_sha256": headless.posture_template_sha(spec, posture)},
        "tier": {"name": TIER, "model": spec.resolved.model, "max_turns": spec.resolved.max_turns,
                 "cap_usd": spec.resolved.max_budget_usd},
        "publish": {"risk": spec.local.publish.risk if spec.local.publish else None, "tier": publish_tier(spec),
                    "on_budget_hit": spec.local.on_budget_hit},
        "context": {**asdict(context_settings(spec)), "mode": context_mode(ctx),
                    "mode_from": "--context" if ctx.opts.context else "spec"},
        "options": asdict(ctx.opts), "items": [], "notes": [], "exit_code": None, "usage_limited": False,
        "budget": {}, "totals": {},
    }


def _budget_dict(state: BudgetState | None) -> dict:
    if state is None:
        return {}
    return {"month": state.month, "spent_usd": state.spent_usd, "estimated_usd": state.estimated_usd,
            "cap_usd": state.cap_usd, "ceiling_usd": state.ceiling_usd, "scheduled": state.scheduled,
            "label": COST_LABEL}


def _totals(record: dict) -> dict:
    items = record.get("items") or []
    spent = round(sum(float(i.get("cost_usd") or 0) for i in items), 4)
    estimated = round(sum(float(i.get("cost_usd") or 0) for i in items if i.get("cost_source") == "estimated"), 4)
    return {"spent_usd": spent, "estimated_usd": estimated, "label": COST_LABEL,
            "attempts": sum(1 for i in items if i.get("outcome")),
            "published": sum(int(i.get("published") or 0) for i in items)}


def _summary(record: dict) -> str:
    t = record.get("totals") or {}
    spend = (f"- spend: ${t.get('spent_usd', 0):.2f} ({COST_LABEL})"
             + (f", ${t['estimated_usd']:.2f} of it charged at the cap" if t.get("estimated_usd") else "")
             + (" — a rehearsal makes no model call" if record["mode"] == "rehearse" else ""))
    lines = [f"# jev loop {record['loop']}/{record['step']} — {record['run_id']}", "",
             f"- mode: {record['mode']} · status: {record['status']} · exit {record['exit_code']}",
             f"- posture: {record['posture']['name']} (network none) · model {record['tier']['model']} · "
             f"turns {record['tier']['max_turns']} · cap ${record['tier']['cap_usd']:g} ({COST_LABEL})", spend]
    b = record.get("budget") or {}
    if b.get("after"):
        a = b["after"]
        lines.append(f"- month {a['month']}: ${a['spent_usd']:.2f} of the ${a['cap_usd']:g} budget.loops ceiling "
                     f"({COST_LABEL}; this run stops at ${a['ceiling_usd']:g})")
    if record.get("usage_limited"):
        lines.append("- usage limit reached: the credential is valid (capacity, not a defect); the rest was skipped")
    lines.append("")
    if record.get("hub", {}).get("dirty_paths"):
        lines.append(f"- dirty at start: {', '.join(record['hub']['dirty_paths'])}")
    for n in record.get("notes") or []:
        lines.append(f"- {n}")
    lines += ["", "| Item | Status | Cost | Reason |", "| --- | --- | --- | --- |"]
    for i in record.get("items") or []:
        cost = f"${float(i['cost_usd']):.4f} ({i.get('cost_source')})" if i.get("outcome") else "$0"
        lines.append(f"| {i['key']} | {i['status']} | {cost} | {i.get('reason') or ''} |")
    for i in record.get("items") or []:
        if i.get("plan_id"):
            lines.append(f"\nPreview `{i['key']}`: `items/{i['dir']}/publish-plan.md` (plan {i['plan_id']})")
    for i in record.get("items") or []:
        line = (i.get("context") or {}).get("line")
        if line:
            lines.append(f"\nContext `{i['key']}`: {line}")
    return "\n".join(lines) + "\n"


def _finish(ctx: RunContext, record: dict, code: int, status: str) -> int:
    record.update(status=status, exit_code=code, finished=iso(), usage_limited=ctx.usage_limited,
                  totals=_totals(record))
    if ctx.budget is not None:
        record.setdefault("budget", {})["after"] = _budget_dict(ctx.budget)
    ctx.run.write_json("run.json", record)
    (ctx.run.path / "summary.md").write_text(_summary(record), encoding="utf-8")
    (runs_dir() / "LATEST").write_text(ctx.run.run_id + "\n", encoding="utf-8")
    prune(current=ctx.run.run_id)
    for i in record["items"]:
        print(f"  {i['status']:<14} {i['key']}  {i.get('reason') or ''}", file=sys.stderr)
        for f in i.get("flags") or []:
            print(f"  {'':<14} ! {f}", file=sys.stderr)
        if (i.get("context") or {}).get("line"):
            print(f"  {'':<14} · {i['context']['line']}", file=sys.stderr)
    t = record["totals"]
    print(f"jev loop: {status} — ${t['spent_usd']:.2f} spent ({COST_LABEL}); exit {code}", file=sys.stderr)
    if ctx.opts.json:
        print(json.dumps(record, indent=2, sort_keys=True, default=str))
    else:
        print(f"run: {ctx.run.path}")
    return code


@contextlib.contextmanager
def interrupt_on_signals() -> Iterator[None]:
    """SIGTERM and SIGHUP (a console cancel's killpg, a closed terminal) end the
    run like a Ctrl-C: the clone is destroyed, the in-flight attempt's cost is
    recorded and run.json ends `interrupted` (exit 130) instead of dying at
    `running`. A SIGHUP inherited ignored (`nohup`) stays ignored. The previous
    handlers come back afterwards."""
    if threading.current_thread() is not threading.main_thread():
        yield
        return

    def interrupt(signum: int, _frame: object) -> None:
        raise KeyboardInterrupt(f"signal {signum}")
    saved = {sig: signal.signal(sig, interrupt) for sig in headless.honoured_signals((signal.SIGTERM, signal.SIGHUP))}
    try:
        yield
    finally:
        for sig, handler in saved.items():
            signal.signal(sig, handler)


def cmd_run(args: argparse.Namespace) -> int:
    opts = Options.from_args(args)
    refused = option_refusal(opts, verb="run")
    if refused:
        print(f"jev loop: {refused}", file=sys.stderr)
        return EXIT["usage"]
    fleet = load_fleet()
    spec = load_step(args.loop, args.step, fleet=fleet)
    adapter = adapters.get(spec.local.adapter)
    posture = headless.Posture(opts.posture)
    with step_lock(spec):
        try:
            rd = RunDir.new(spec.loop, spec.step, opts.run_id)
        except JevError as exc:   # a reused --run-id: a usage error, and no record is written
            print(f"jev loop: {exc}", file=sys.stderr)
            return EXIT["usage"]
        ctx = RunContext(spec=spec, adapter=adapter, fleet=fleet, opts=opts, plan_dir=rd.path / "plan",
                         history=History(), run=rd)
        record = _new_record(ctx, posture)
        rd.write_json("run.json", record)
        print(f"run: {rd.path}" if opts.json else f"jev loop: run {rd.run_id}", file=sys.stderr)
        try:
            with interrupt_on_signals():
                return _run(ctx, record, posture)
        except KeyboardInterrupt:
            if ctx.inflight is not None and not any(i is ctx.inflight for i in record["items"]):
                # the item in flight (and whatever it spent) belongs in the record's totals
                if ctx.inflight.get("status") != "interrupted":
                    ctx.inflight.update(status="interrupted", code=EXIT["interrupted"],
                                        reason=ctx.inflight.get("reason") or "interrupted before the attempt")
                record["items"].append(ctx.inflight)
            return _finish(ctx, record, EXIT["interrupted"], "interrupted")
        except (JevError, StepSpecError) as exc:
            record["notes"].append(str(exc))
            return _finish(ctx, record, EXIT["usage"], "refused")
        except OSError as exc:   # a file the run needed: the record still ends, never stuck at "running"
            record["notes"].append(f"{type(exc).__name__}: {exc}")
            return _finish(ctx, record, EXIT["attention"], "failed")
        except Exception as exc:   # a bug: the record ends "failed" first, then the traceback
            record["notes"].append(f"{type(exc).__name__}: {exc}")
            _finish(ctx, record, EXIT["attention"], "failed")
            raise


def claude_projects_dir() -> Path:
    """This operator's Claude Code transcripts: `$CLAUDE_CONFIG_DIR/projects`,
    else `~/.claude/projects`. Read from the ENGINE's environment and passed
    as `--claude-dir`: the planes' environment (deterministic_env) drops
    CLAUDE_CONFIG_DIR with every other auth override, and the lake would
    fall back to ~/.claude."""
    base = os.environ.get("CLAUDE_CONFIG_DIR")
    return (Path(base).expanduser() if base else Path.home() / ".claude") / "projects"


def refresh_context(ctx: RunContext, record: dict) -> None:
    """`--refresh-context`, once per run, before the first pack: the lake's
    LOCAL session import (`tools/dash-gen lake sessions`: this machine's
    Claude Code transcripts, from `claude_projects_dir()`, into the lake,
    nothing else written), never `lake sync`. A failed import, or one that
    found no transcripts, is a note, never the run's failure — the pack then
    reads the lake as it is (stale is reported, never fatal)."""
    if context_mode(ctx) == "off":
        record["notes"].append("--refresh-context: nothing to refresh, the context pack is off for this step")
        return
    argv = [*REFRESH_ARGV, f"--claude-dir={claude_projects_dir()}", f"--days={context_settings(ctx.spec).days}",
            "--json"]
    res = ctx.dash_gen(argv)
    doc = cpack.parse_document(res.out) or {}
    counts = {k: doc[k] for k in ("scanned", "sessions", "turns", "tool_calls", "skipped")
              if isinstance(doc.get(k), int) and not isinstance(doc.get(k), bool)}
    shown = [cpack.redact(a, ctx) for a in argv]   # the transcript directory is under the home
    record["context_refresh"] = {"argv": shown, "exit": res.code, **counts}
    said = " ".join(cpack.redact((res.err or res.out or "").strip()[-400:], ctx).split())[-200:]
    if res.code != 0:
        record["notes"].append(f"--refresh-context: `tools/dash-gen {' '.join(shown)}` exited {res.code}"
                               + (f": {said}" if said else "") + " — the pack reads the lake as it is")
    elif not counts:   # `lake sessions --json` prints nothing when the directory is missing
        record["notes"].append(f"--refresh-context: the lake's local session import found no transcripts at "
                               f"{cpack.redact(str(claude_projects_dir()), ctx)}" + (f" ({said})" if said else "")
                               + " — the pack reads the lake as it is")
    else:
        record["notes"].append(f"--refresh-context: the lake's local session import read {counts.get('scanned', '?')}"
                               f" transcript(s), {counts.get('sessions', '?')} new or changed")


def _run(ctx: RunContext, record: dict, posture: headless.Posture) -> int:
    """The run, in order: gates, the --apply refusals, the ceiling, the host,
    the publish token (all $0 and before anything spends), the plan, then the
    items one by one."""
    live = not ctx.opts.rehearse
    stop = gates(ctx)
    if stop:
        record["notes"].append(stop[1])
        return _finish(ctx, record, stop[0], "disabled" if stop[0] == 0 else "refused")
    dirty = record["hub"]["dirty_paths"]
    if dirty and ctx.opts.apply and not ctx.opts.allow_dirty:
        record["notes"].append(f"--apply refused: spec, adapter or engine paths are dirty ({', '.join(dirty)}) — "
                               "commit them, or pass --allow-dirty to file from an uncommitted engine")
        return _finish(ctx, record, EXIT["usage"], "refused")
    if dirty:
        record["notes"].append(f"spec, adapter or engine paths were dirty at start ({', '.join(dirty)})"
                               + (" — filing anyway: --allow-dirty" if ctx.opts.apply
                                  else " — a later --apply refuses this without --allow-dirty"))
    try:
        ctx.budget = budget_position(ctx.fleet, scheduled=ctx.opts.scheduled)
        record["budget"] = {"before": _budget_dict(ctx.budget)}
    except (JevError, StepSpecError) as exc:
        if live:
            raise
        record["notes"].append(f"budget: {exc}")
    if live and ctx.budget.exhausted:
        # not a stop: tier 0 can still reuse or skip at $0; an item that would spend is skipped
        record["notes"].append(f"monthly ceiling reached — {ctx.budget.summary()} ({COST_LABEL}); only $0 "
                               "tier-0 work can run")
    host = host_check(ctx.spec, posture, ctx.fleet, ctx.opts.claude_bin, None, live=live, preflight=True)
    record["host"] = host.as_dict()
    record["notes"] += host.notes
    refusal = host.refusal()
    if refusal:
        record["notes"].append(refusal[1])
        return _finish(ctx, record, refusal[0], "refused")
    if ctx.opts.apply:
        ctx.publish_env, who = probe_publish_token()
        if ctx.publish_env is None:
            record["notes"].append(f"--apply refused before any spend: {who}")
            return _finish(ctx, record, EXIT["attention"], "refused")
        record["notes"].append(f"--apply: files as {who}, after the preview, in this run (the § 13.6 yes is "
                               "this command line)")
    plan, stop = obtain_plan(ctx)
    if stop:
        record["notes"].append(stop[1])
        return _finish(ctx, record, stop[0], "refused")
    result = ctx.adapter.items(ctx, plan)
    check_items(result)
    record["plan"] = {**result.meta, "count": len(result.items), "skipped": result.skipped, "dropped": result.dropped}
    for r in [*result.skipped, *result.dropped]:
        # `item` is the item key where the adapter knows it (scout: the nwo), as on every other row
        ctx.run.append_attempt({"run_id": ctx.run.run_id, "loop": ctx.spec.loop, "step": ctx.spec.step,
                                "item": r.get("key") or r.get("name"), "name": r.get("name"),
                                "decision": "planned-skip", "reason": r.get("reason"),
                                "cost_usd": 0.0, "cost_source": "no-spend"})
    if not result.items:
        explicit = ctx.opts.target != "all" or ctx.opts.item
        record["notes"].append(explain_empty(ctx, result) if explicit else "nothing planned today")
        return _finish(ctx, record, EXIT["attention"] if explicit else EXIT["ok"], "empty")
    if ctx.opts.refresh_context:
        refresh_context(ctx, record)
    for n, item in enumerate(result.items):
        if ctx.stop is not None:
            record["items"].append({"key": item.key, "dir": wsp.item_dirname(item.key), "status": "skipped",
                                    "reason": f"the run stopped: {ctx.stop[1][:160]}"})
            continue
        if ctx.opts.max_items is not None and n >= ctx.opts.max_items:
            record["items"].append({"key": item.key, "dir": wsp.item_dirname(item.key), "status": "skipped",
                                    "reason": f"--max-items {ctx.opts.max_items}"})
            continue
        record["items"].append(run_item(ctx, item, host, posture))
        ctx.inflight = None
        record.setdefault("budget", {})["after"] = _budget_dict(ctx.budget)
        ctx.run.write_json("run.json", record)
    if ctx.stop is not None:
        record["notes"].append(ctx.stop[1])
        return _finish(ctx, record, ctx.stop[0], "stopped")
    code = severest([int(i.get("code") or 0) for i in record["items"]])
    ceiling = live and {i.get("decision") for i in record["items"]} == {"budget-skip"}
    status = ("rehearsed" if not live else "usage-limited" if ctx.usage_limited else "ceiling" if ceiling
              else "done")
    return _finish(ctx, record, code, status)


# --------------------------------------------------------------------------- #
# `loop plan`
# --------------------------------------------------------------------------- #
def cmd_plan(args: argparse.Namespace) -> int:
    opts = Options.from_args(args)
    refused = option_refusal(opts, verb="plan")
    if refused:
        print(f"jev loop: {refused}", file=sys.stderr)
        return EXIT["usage"]
    fleet = load_fleet()
    spec = load_step(args.loop, args.step, fleet=fleet)
    adapter = adapters.get(spec.local.adapter)
    posture = headless.Posture(opts.posture)
    with tempfile.TemporaryDirectory(prefix="jev-loop-plan-") as tmp:
        ctx = RunContext(spec=spec, adapter=adapter, fleet=fleet, opts=opts, plan_dir=Path(tmp) / "plan",
                         history=History())
        out: dict = {"loop": spec.loop, "step": spec.step, "posture": posture.name, "items": [], "notes": []}
        stop = gates(ctx)
        if stop:
            out["notes"].append(stop[1])
            return _print_plan(out, opts, stop[0])
        host = host_check(spec, posture, fleet, opts.claude_bin, None, live=False, preflight=False, report=True)
        out["host"] = host.as_dict()
        try:
            state = budget_position(fleet, scheduled=opts.scheduled)
            out["budget"] = {**_budget_dict(state), "affords_one_attempt": state.affords(spec.resolved.max_budget_usd)}
        except (JevError, StepSpecError) as exc:
            out["notes"].append(f"budget: {exc}")
        plan, stop = obtain_plan(ctx)
        if stop:
            out["notes"].append(stop[1])
            return _print_plan(out, opts, stop[0])
        result = adapter.items(ctx, plan)
        check_items(result)
        out["plan"] = {**result.meta, "count": len(result.items), "skipped": result.skipped, "dropped": result.dropped}
        if not result.items and (opts.target != "all" or opts.item):
            out["notes"].append(explain_empty(ctx, result))
            return _print_plan(out, opts, EXIT["attention"])
        settings = headless.settings_doc(posture)
        for item in result.items:
            sha, why = (None, "") if opts.offline else head_sha(item.nwo, item.branch)
            t0 = adapter.tier0(ctx, item, sha)
            triage = adapter.classify(ctx, item)
            decision = (f"tier0-{t0.action}: {t0.reason}" if t0.action != "continue" else
                        f"blocked: {triage.reason}" if triage.blocked else "attempt")
            prompt = render_prompt(spec, values_from(spec, item.row))
            flags = headless.claude_flags(spec, posture, settings_path=Path("<item_dir>/settings.json"),
                                          session_id="<attempt uuid>", debug_path=Path("<item_dir>/debug.log"))
            filing = None
            if spec.local.publish:
                # a plan has no run directory yet: the paths are shown as placeholders
                where = f"<run_dir>/items/{wsp.item_dirname(item.key)}"
                filing = render_argv(spec.local.publish.argv, {
                    **item_values(ctx, item), "item_dir": where, "bodies_dir": f"{where}/bodies",
                    "run_ref": "local run <run_id> (tools/jev loop)",
                    "validated": f"{where}/<the adapter's validated file>"})
            entry = {"key": item.key, "branch": item.branch, "head_sha": sha, "decision": decision,
                     "dedupe": item.row.get("dedupe"), "prompt_sha256": _sha(prompt),
                     "settings_sha256": _sha(json.dumps(settings, sort_keys=True)),
                     "claude_flags": flags, "dry_filing": filing, "note": why or None}
            preview = context_preview(ctx, item)   # statuses and ages only; nothing is written anywhere
            if preview is not None:
                entry["context"] = preview
            out["items"].append(entry)
    return _print_plan(out, opts, EXIT["ok"])


def _print_plan(out: dict, opts: Options, code: int) -> int:
    if opts.json:
        print(json.dumps(out, indent=2, sort_keys=True, default=str))
        return code
    for n in out["notes"]:
        print(f"note: {n}")
    host = out.get("host") or {}
    if host:
        print(f"host: claude {host.get('version') or 'missing'} · probe {host.get('probe')} · canary "
              f"{host.get('canary')} · auth {(host.get('auth') or {}).get('method') or 'none'}")
        for why in host.get("problems") or []:
            print(f"host problem: {why}")
    b = out.get("budget") or {}
    if b:
        print(f"budget.loops {b['month']}: ${b['spent_usd']:.2f} of ${b['cap_usd']:g} (this run stops at "
              f"${b['ceiling_usd']:g}; {COST_LABEL}){'' if b['affords_one_attempt'] else ' — an attempt would not fit'}")
    for i in out["items"]:
        print(f"{i['key']} @ {i['branch']}  →  {i['decision']}")
        if i.get("note"):
            print(f"    note: {i['note']}")
        print(f"    prompt sha256 {i['prompt_sha256'][:16]} · settings sha256 {i['settings_sha256'][:16]} · "
              f"dedupe {i['dedupe']}")
        print(f"    claude {' '.join(i['claude_flags'][:4])} … ({len(i['claude_flags'])} args)")
        if i["dry_filing"]:
            print(f"    dry filing: tools/dash-gen {' '.join(i['dry_filing'])}")
        c = i.get("context")
        if c:
            print(f"    context ({c['mode']}): {context_bits(c['statuses'], c['ages']) or c.get('note') or '-'}"
                  + (f" — a run fails this item before any spend: {', '.join(c['missing'])} unavailable"
                     if c.get("would_block") else ""))
    plan = out.get("plan") or {}
    for r in [*plan.get("skipped", []), *plan.get("dropped", [])]:
        print(f"skip {r.get('name')}: {r.get('reason')}")
    print("spend: $0.00 (API-equivalent, estimate) — `loop plan` never clones and never calls a model")
    return code


# --------------------------------------------------------------------------- #
# `loop doctor`, `loop list`, `loop show`
# --------------------------------------------------------------------------- #
SEVERITY = (EXIT["no_cli"], EXIT["host_unsafe"], EXIT["credential"], EXIT["usage"], EXIT["attention"])


def severest(codes: list[int]) -> int:
    return next((c for c in SEVERITY if c in codes), EXIT["ok"])


# --------------------------------------------------------------------------- #
# the live canary — `loop doctor --live`, the one doctor check that spends
# --------------------------------------------------------------------------- #
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


def canary_flags(spec: StepSpec, posture: headless.Posture, **paths: object) -> list[str]:
    """The step's own isolation flags — the same settings, toolset, allowlist
    and deny list the posture template hashes — with only the model and the
    turn cap swapped for the canary's (neither changes what is enforced)."""
    flags = headless.claude_flags(spec, posture, **paths)
    flags[flags.index("--model") + 1] = CANARY_MODEL
    flags[flags.index("--max-turns") + 1] = str(CANARY_TURNS)
    return flags


def _plant(path: Path, token: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(token + "\n")


def run_canary(spec: StepSpec, posture: headless.Posture, host: HostReport, fleet: dict) -> headless.ProbeResult:
    """The ≤ $0.10 canary: one real session (it is ledgered like any attempt)
    in a canary clone, asked to read a planted secret (inside the home fence,
    and a second copy in a denied private path outside it) with `cat` and with
    python, reach the network, write outside the clone with a sandboxed command
    and with the Write tool, count the SECRET_ENV variables it can see, and read
    a committed symlink. It runs under the run's own credential, so its pass
    is cached for that exposure. `headless.judge_canary` decides; the secrets
    and every scratch file are removed whatever happens."""
    if CANARY_MODEL not in allowed_models(fleet):
        raise StepSpecError(f"the canary model {CANARY_MODEL} is not in _data/fleet.yml ai_models.allowed (§ 13.3)")
    cdir = canary_dir()
    cdir.mkdir(parents=True, exist_ok=True)
    cdir.chmod(0o700)
    token = secrets.token_hex(16)
    outside_root = next((Path(p).resolve() for p in headless.private_read_paths() if Path(p).is_dir()), None)
    outside_dir = Path(tempfile.mkdtemp(prefix="jev-canary-", dir=outside_root)) if outside_root else None
    plant = headless.CanaryPlant(token=token, secret=str(cdir / "secret.txt"), written=str(cdir / "written.txt"),
                                 write_tool=str(cdir / "written-by-write.txt"),
                                 outside=str(outside_dir / "secret.txt") if outside_dir else None)
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
        argv += auth_pin(host.auth)
        for k, v in {"origin": "local", "run_id": run_id, "attempt_id": attempt_id, "loop": spec.loop,
                     "step": spec.step, "item": "canary", "tier": "canary"}.items():
            argv += ["--meta", f"{k}={v}"]
        relay_dash_gen([*argv, "--", *flags], env=ai_run_env(host.auth), timeout=CANARY_TIMEOUT_S + OUTER_GRACE_S)
        expected = headless.tool_families(headless.posture_tools(spec.allowed_tools, posture))
        return headless.judge_canary(
            headless.read_events(d / "trace.jsonl"), headless.reduce_debug_log(d / "debug.log"),
            read_json(d / "outcome.json"), plant=plant, left_behind=[str(t) for t in targets if t.exists()],
            expected_tools=expected, credential_env=headless.credential_exposure(host.auth),
            # ai-run's trace Redactor has the HOME it was given: the same one, so the same `~` paths
            redact=headless.Redactor(ai_run_env(host.auth)).text)
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


def cmd_doctor(args: argparse.Namespace) -> int:
    """$0 host checks; runs the credential-free isolation probe and caches it.
    `--live` then runs the canary (≤ $0.10) for each step whose checks passed."""
    posture = headless.Posture(args.posture)
    fleet = load_fleet()
    if args.live:
        why = ("the canary proves the sandbox, and --posture reduced has none" if posture.name != "sandbox"
               else _confirm_canary(args.yes))
        if why:
            print(f"jev loop: doctor --live refused: {why}", file=sys.stderr)
            return EXIT["usage"]
    ignored = git(["check-ignore", "-q", ".fleet/runs/x"], cwd=HUB).ok
    report: dict = {"posture": posture.name, "runs_dir_ignored": ignored, "steps": []}
    codes = [] if ignored else [EXIT["host_unsafe"]]
    inside = work_root_problem()
    if inside:
        # host safety, like every other refusal of a workspace inside the hub
        print(f"jev loop: {inside}", file=sys.stderr)
        if args.json:
            print(json.dumps({**report, "work_root_inside_hub": str(headless.work_root()),
                              "exit": EXIT["host_unsafe"]}, indent=2, sort_keys=True))
        return EXIT["host_unsafe"]
    root = private_work_root()
    for spec in local_specs(fleet=fleet):
        scratch = Path(tempfile.mkdtemp(prefix=".doctor-", dir=root))
        try:
            host = host_check(spec, posture, fleet, args.claude_bin, scratch / "preflight", live=False,
                              preflight=True, probe_cache=False)
            probe_problems: list[str] = []
            if host.claude and not any(c in (EXIT["no_cli"], EXIT["host_unsafe"]) for c, _w in host.problems):
                settings = scratch / "probe-settings.json"
                write_json(settings, headless.settings_doc(posture))
                expected = headless.tool_families(headless.posture_tools(spec.allowed_tools, posture))
                result = headless.probe_isolation(
                    host.claude,
                    lambda debug, s=spec: headless.claude_flags(s, posture, settings_path=settings,
                                                                session_id=str(uuid.uuid4()), debug_path=debug),
                    scratch / "probe", expected_tools=expected)
                store(".probe.json", cache_key(host.version, spec, posture),
                      {"ok": result.ok, "problems": result.problems, "facts": result.facts, "at": iso()})
                host.probe = "ok" if result.ok else "failed"
                probe_problems = result.problems
                if not result.ok:
                    host.problems.append((EXIT["host_unsafe"], "the isolation probe failed"))
            else:
                host.probe = "not run (a check above failed)"
            canary_problems: list[str] = []
            if args.live and host.probe == "ok" and not host.problems:
                if host.auth is None:
                    host.problems.append((EXIT["credential"], "the canary needs a Claude credential"))
                else:
                    with budget_lock() as held:
                        why = None if held else "another local loop attempt holds the budget lock"
                        if why is None and not budget_position(fleet, scheduled=False).affords(CANARY_CAP_USD):
                            why = f"budget.loops would not fit ${CANARY_CAP_USD:g} ({COST_LABEL})"
                        if why:
                            # the maintainer asked for it: a canary that did not run is not a clean doctor
                            host.problems.append((EXIT["attention"], f"canary not run: {why}"))
                        else:
                            verdict = run_canary(spec, posture, host, fleet)
                            store(".canary.json", canary_key(host.version, spec, posture, host.auth),
                                  {"ok": verdict.ok, "problems": verdict.problems, "facts": verdict.facts,
                                   "auth": {"method": host.auth.method, "source": host.auth.source},
                                   "credential_env": headless.credential_exposure(host.auth), "at": iso()})
                            host.canary = "ok" if verdict.ok else "failed"
                            canary_problems = verdict.problems
                            if not verdict.ok:
                                host.problems.append((EXIT["host_unsafe"],
                                                      "the canary failed: the sandbox did not enforce"))
            refusal = host.refusal()
            code = refusal[0] if refusal else EXIT["ok"]
            codes.append(code)
            report["steps"].append({"step": f"{spec.loop}/{spec.step}", **host.as_dict(),
                                    "probe_problems": probe_problems, "canary_problems": canary_problems,
                                    "exit": code})
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
    report["exit"] = worst = severest(codes)
    specs = local_specs(fleet=fleet)
    if specs and args.context != "off":
        try:
            report["context_planes"] = doctor_planes(fleet, specs[0])
        # a diagnostic section, never a reason for doctor to fail: its exit code stays the host checks'
        except Exception as exc:  # noqa: BLE001
            said = cpack.redact(" ".join(f"{type(exc).__name__}: {exc}".split()), host_ctx())
            report["context_planes"] = {"problem": said[:300], "sections": {}}
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, default=str))
        return worst
    print(f".fleet/runs git-ignored: {'yes' if ignored else 'NO — add it to .gitignore'}")
    for e in report["steps"]:
        auth = e.get("auth") or {}
        print(f"{e['step']}: claude {e.get('version') or 'missing'} · probe {e.get('probe')} · canary {e.get('canary')}"
              f" · auth {auth.get('method', 'none')}/{auth.get('source', '-')} · exit {e['exit']}")
        for p in e.get("problems") or []:
            print(f"  ✗ {p}")
        for p in e.get("probe_problems") or []:
            print(f"  ✗ probe: {p}")
        for p in e.get("canary_problems") or []:
            print(f"  ✗ canary: {p}")
        for n in e.get("notes") or []:
            print(f"  · {n}")
    planes = report.get("context_planes")
    if planes is not None:
        print(f"context planes ({planes.get('nwo') or 'the hub'}; read-only, informational — never this exit code):")
        if planes.get("problem"):
            print(f"  · {planes['problem']}")
        for k, sec in (planes.get("sections") or {}).items():
            age = sec.get("age_hours")
            status = "up" if sec.get("up") else sec.get("status")
            line = f"  · {k} {status}" + (f" ({age:.0f} h old)" if age is not None else "")
            if status == "unavailable" and sec.get("note"):
                line += f" — {sec['note']}"   # the reason first: "no lake at …", and the note's own remedy
            elif status == "up":
                line += f" — the search answered; {sec['note']}" if sec.get("note") else " — the search answered"
            elif status != "ok":
                line += (f" — refresh: {sec['refresh']}" if sec.get("refresh") else
                         f" — {sec['note']}" if sec.get("note") else "")
            print(line)
    if args.live:
        print(f"spend: the canary is ledgered like any attempt (≤ ${CANARY_CAP_USD:.2f}, {COST_LABEL}); every other "
              "check runs credential-free or with stdin /dev/null")
    else:
        print(f"spend: $0.00 ({COST_LABEL}) — every doctor check runs credential-free or with stdin /dev/null")
    return worst


def cmd_list(args: argparse.Namespace) -> int:
    fleet = load_fleet()
    rows = []
    for s in local_specs(fleet=fleet):
        sw = s.local.switch
        rows.append({"step": f"{s.loop}/{s.step}", "adapter": s.local.adapter, "model": s.resolved.model,
                     "max_turns": s.resolved.max_turns, "cap_usd": s.resolved.max_budget_usd,
                     "switch": None if sw is None else {
                         "config": sw.config, "config_value": fleet_value(fleet, sw.config),
                         "variable": sw.variable, "default": sw.default},
                     "publish_tier": publish_tier(s), "on_budget_hit": s.local.on_budget_hit,
                     "postures": ["sandbox", "reduced"]})
    if args.json:
        print(json.dumps(rows, indent=2, sort_keys=True))
        return 0
    for r in rows:
        sw = r["switch"] or {}
        print(f"{r['step']}  adapter {r['adapter']} · {r['model']} · {r['max_turns']} turns · "
              f"${r['cap_usd']:g} cap (API-equivalent, estimate) · {sw.get('config')}={sw.get('config_value')} · "
              f"vars.{sw.get('variable')} default {sw.get('default')} · publish tier {r['publish_tier']}")
    if not rows:
        print("no step spec has a local: block yet")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    run_id = args.run_id
    try:
        if args.latest or not run_id:
            try:
                run_id = (runs_dir() / "LATEST").read_text(encoding="utf-8").strip()
            except OSError as exc:
                raise JevError(f"no runs yet under {runs_dir()}") from exc
        rd = RunDir.load(run_id)
    except JevError as exc:   # a missing or malformed run id is a usage error
        print(f"jev loop: {exc}", file=sys.stderr)
        return EXIT["usage"]
    if args.json:
        print((rd.path / "run.json").read_text(encoding="utf-8"), end="")
        return 0
    summary = rd.path / "summary.md"
    print(summary.read_text(encoding="utf-8") if summary.is_file() else json.dumps(read_json(rd.path / "run.json"),
                                                                                  indent=2))
    return 0


# --------------------------------------------------------------------------- #
# `loop publish`, `loop budget`
# --------------------------------------------------------------------------- #
def _publish_target(rd: RunDir, record: dict, key: str | None) -> tuple[dict | None, Item | None, str]:
    """The preview to publish, and its item rebuilt from the run's own plan."""
    plans: dict[str, dict] = {}
    for p in sorted((rd.path / "items").glob("*/publish-plan.json")):
        doc = read_json(p)
        if doc.get("schema") == PUBLISH_PLAN_SCHEMA and doc.get("run_id") == rd.run_id:
            plans[str((doc.get("item") or {}).get("key"))] = doc
    if key is None and len(plans) != 1:
        return None, None, (f"run {rd.run_id} has {len(plans)} preview(s)"
                            + (f" — name one with --item ({', '.join(sorted(plans))})" if plans else ""))
    doc = plans.get(key) if key is not None else next(iter(plans.values()))
    if doc is None:
        return None, None, f"run {rd.run_id} has no preview for {key!r} ({', '.join(sorted(plans)) or 'none'})"
    meta = doc["item"]
    rows = [r for r in read_json(rd.path / "plan" / "plan.json").get("include") or [] if r.get("nwo") == meta["nwo"]]
    item = Item(key=meta["key"], name=meta["name"], nwo=meta["nwo"], branch=meta["branch"],
                row=rows[0] if rows else {}, brief=None)
    return doc, item, ""


def cmd_publish(args: argparse.Namespace) -> int:
    """File a reviewed earlier dry run (`--apply`), or say whether a live dry
    run would still file exactly the reviewed bytes (without it, read-only)."""
    try:
        rd = RunDir.load(args.run_id)
    except JevError as exc:
        print(f"jev loop: {exc}", file=sys.stderr)
        return EXIT["usage"]
    record = read_json(rd.path / "run.json")
    fleet = load_fleet()
    spec = load_step(str(record.get("loop")), str(record.get("step")), fleet=fleet)
    if spec.local.publish is None:
        print(f"jev loop: {spec.loop}/{spec.step} declares no publish step", file=sys.stderr)
        return EXIT["usage"]
    doc, item, why = _publish_target(rd, record, args.item)
    if doc is None or item is None:
        print(f"jev loop: {why}", file=sys.stderr)
        return EXIT["usage"]
    if args.plan_id and args.plan_id != doc["plan_id"]:
        print(f"jev loop: --plan-id {args.plan_id} is not this preview's ({doc['plan_id']})", file=sys.stderr)
        return EXIT["usage"]
    adapter = adapters.get(spec.local.adapter)
    opts = Options(target=item.name, apply=args.apply, allow_dirty=args.allow_dirty, json=args.json)
    with step_lock(spec):
        ctx = RunContext(spec=spec, adapter=adapter, fleet=fleet, opts=opts, plan_dir=rd.path / "plan",
                         history=History(), run=rd)
        if not args.apply:
            validated = ctx.item_dir(item) / doc["validated_rel"]
            fresh, bodies = _fresh_dry(ctx, item, validated)
            gap = review_gap(ctx, item, doc, fresh, bodies, validated)
            same = not fresh.blockers and gap is None
            out = {"plan_id": doc["plan_id"], "publishable": doc["publishable"], "would_file_now": len(fresh.rows),
                   "matches_review": same, "differs": gap, "blockers_now": fresh.blockers,
                   "plan": str(ctx.item_dir(item) / "publish-plan.md")}
            if args.json:
                print(json.dumps(out, indent=2, sort_keys=True))
            else:
                print((ctx.item_dir(item) / "publish-plan.md").read_text(encoding="utf-8"), end="")
                print(f"\nlive dry run now: {len(fresh.rows)} would file · "
                      f"{'matches the reviewed bytes' if same else 'DIFFERS from the reviewed bytes'}"
                      f"{' · ' + gap if gap else ''}"
                      f"{' · ' + ', '.join(fresh.blockers) if fresh.blockers else ''}")
            return EXIT["ok"]
        paths = [str(spec.path.parent.relative_to(HUB)) + "/", *ENGINE_SOURCES, *adapter.sources]
        dirty = sorted({*((record.get("hub") or {}).get("dirty_paths") or []), *hub_state(paths)["dirty_paths"]})
        if dirty and not args.allow_dirty:
            print(f"jev loop: --apply refused: spec, adapter or engine paths were or are dirty ({', '.join(dirty)}) "
                  "— commit them, or pass --allow-dirty", file=sys.stderr)
            return EXIT["usage"]
        ctx.publish_env, who = probe_publish_token()
        if ctx.publish_env is None:
            print(f"jev loop: --apply refused: {who}", file=sys.stderr)
            return EXIT["attention"]
        print(f"jev loop: publishing plan {doc['plan_id']} of run {rd.run_id} to {item.nwo} as {who}",
              file=sys.stderr)
        result = apply_item(ctx, item, doc)
        for entry in record.get("items") or []:
            if entry.get("key") == item.key and result["status"] != "publish-refused":
                # a refusal changes nothing, so it leaves the item's record as it was
                entry.update(status=result["status"], reason=result["reason"],
                             published=result.get("published", 0), urls=result.get("urls", []))
        record.setdefault("publishes", []).append({"at": iso(), "item": item.key, "plan_id": doc["plan_id"],
                                                    "status": result["status"]})
        rd.write_json("run.json", record)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"{result['status']}: {result['reason']}")
        for u in result.get("urls") or []:
            print(f"  {u}")
    return int(result["code"])


def cmd_budget(args: argparse.Namespace) -> int:
    """The month against budget.loops, beside JEV conflicts' budget.jev."""
    fleet = load_fleet()
    loops = budget_position(fleet, scheduled=args.scheduled)
    conflicts = budget_state(load_config(fleet), Ledger.load(), scheduled=args.scheduled, month=loops.month)
    ceiling = (((fleet.get("harnesses") or {}).get("budget") or {}).get("monthly_ai_usd"))
    out = {"label": f"{COST_LABEL} — a throughput ceiling under OAuth, not an invoice",
           "loops": {**_budget_dict(loops), "ledger": str(ledger_path())},
           "jev_conflicts": _budget_dict(conflicts), "monthly_ai_usd": ceiling}
    if args.json:
        print(json.dumps(out, indent=2, sort_keys=True))
        return EXIT["ok"]
    print(f"loops (budget.loops)        {loops.summary()}")
    print(f"jev conflicts (budget.jev)  {conflicts.summary()}")
    if ceiling is not None:
        print(f"both inside harnesses.budget.monthly_ai_usd ${float(ceiling):g}")
    print(f"{out['label']}")
    return EXIT["ok"]


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument("loop", help="the loop (the workflow stem, e.g. repo-scout)")
    p.add_argument("step", nargs="?", default=None, help="the step (optional when the loop has one local step)")
    p.add_argument("--target", default="all", metavar="NAME|all", help="one registry name, or today's sample")
    p.add_argument("--focus", default="", metavar="TEXT", help="operator focus, quoted into every brief")
    p.add_argument("--day", default=None, metavar="YYYY-MM-DD", help="the rotation day")
    p.add_argument("--offline", action="store_true",
                   help="no GitHub reads (no backpressure, no HEAD, no clone) — --scheduled still reads its switch")
    p.add_argument("--plan-file", default=None, metavar="PLAN.json", help="take one row of a saved plan")
    p.add_argument("--item", default=None, metavar="NAME", help="the row of --plan-file")
    p.add_argument("--scheduled", action="store_true",
                   help="behave as a scheduled run: honour the repo variable kill switch")
    p.add_argument("--fresh", action="store_true", help="bypass tier-0 reuse")
    p.add_argument("--posture", choices=("sandbox", "reduced"), default="sandbox",
                   help="sandbox (Bash in Seatbelt, the default) or reduced (no Bash; never scheduled)")
    p.add_argument("--claude-bin", default="claude", metavar="BIN")
    p.add_argument("--context", choices=cpack.MODES, default=None,
                   help="the context pack: auto (build it, note a missing plane), off (none: the CI-identical run) "
                        "or require (a missing plane fails the item before any spend); default the spec's "
                        "local.context.mode")
    p.add_argument("--json", action="store_true", help="print the result as JSON on stdout")


def add_arguments(ap: argparse.ArgumentParser) -> None:
    sub = ap.add_subparsers(dest="action", required=True)
    ls = sub.add_parser("list", help="every step spec with a local: block")
    ls.add_argument("--json", action="store_true")
    doc = sub.add_parser("doctor",
                         help="$0 host checks: CLI floor, sandbox, credential, flag preflight, isolation probe; "
                              "--live adds the one-time canary (≤ $0.10)")
    doc.add_argument("--posture", choices=("sandbox", "reduced"), default="sandbox")
    doc.add_argument("--live", action="store_true",
                     help=f"also run the canary: one ledgered session, ≤ ${CANARY_CAP_USD:.2f} ({COST_LABEL}), "
                          "proving the sandbox enforces (the maintainer's § 10.5 yes)")
    doc.add_argument("--yes", action="store_true", help="--live without the terminal confirmation")
    doc.add_argument("--claude-bin", default="claude", metavar="BIN")
    doc.add_argument("--context", choices=cpack.MODES, default=None,
                     help="off skips the informational context-planes section (it never changes the exit code)")
    doc.add_argument("--json", action="store_true")
    pl = sub.add_parser("plan", help="what a run would do, per item — never clones, never calls a model")
    _common(pl)
    rn = sub.add_parser("run", help="run the step locally: one capped attempt per item, then the dry-run preview")
    _common(rn)
    rn.add_argument("--rehearse", action="store_true",
                    help="everything up to the model call — plan, tier 0, clone, prompt, flags, preflight — at $0")
    rn.add_argument("--apply", action="store_true",
                    help="after the preview, file it in this run (typed by the maintainer, this is the § 13.6 yes; "
                         "refused with --scheduled)")
    rn.add_argument("--max-items", type=int, default=None, metavar="N")
    rn.add_argument("--keep-workspace", action="store_true", help="keep the clone for inspection")
    rn.add_argument("--allow-dirty", action="store_true", help=ALLOW_DIRTY_HELP)
    rn.add_argument("--run-id", default=None, metavar="ID")
    rn.add_argument("--refresh-context", action="store_true",
                    help="before the first pack, run the lake's local session import (`tools/dash-gen lake sessions`: "
                         "~/.claude transcripts into the lake, never a GitHub sync); refused with --scheduled")
    pb = sub.add_parser("publish", help="file a reviewed earlier dry run (--apply); without it, re-check its bytes")
    pb.add_argument("run_id")
    pb.add_argument("--item", default=None, metavar="KEY", help="the item to publish (when the run has several)")
    pb.add_argument("--apply", action="store_true", help="file the reviewed preview (idempotent: once per preview)")
    pb.add_argument("--plan-id", default=None, metavar="ID", help="refuse unless the preview has this plan id")
    pb.add_argument("--allow-dirty", action="store_true", help=ALLOW_DIRTY_HELP)
    pb.add_argument("--json", action="store_true")
    sh = sub.add_parser("show", help="a run's summary (or run.json with --json)")
    sh.add_argument("run_id", nargs="?", default=None)
    sh.add_argument("--latest", action="store_true")
    sh.add_argument("--json", action="store_true")
    bg = sub.add_parser("budget", help="this month against budget.loops, beside JEV conflicts' budget.jev")
    bg.add_argument("--scheduled", action="store_true", help="judge it as a scheduled run would (the stop line)")
    bg.add_argument("--json", action="store_true")


def main(args: argparse.Namespace) -> int:
    handlers = {"list": cmd_list, "doctor": cmd_doctor, "plan": cmd_plan, "run": cmd_run, "publish": cmd_publish,
                "show": cmd_show, "budget": cmd_budget}
    try:
        return handlers[args.action](args)
    except JevError as exc:   # StepSpecError, LockHeld, no gh, a bad plan: usage, spec or config (exit 2)
        print(f"jev loop: {exc}", file=sys.stderr)
        return EXIT["usage"]
