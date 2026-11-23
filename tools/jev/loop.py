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
             idempotently); `show`; `budget`. Every verb that could spend or
             file (`run`, `run --apply`, `publish --apply`, `doctor --live`),
             manual or scheduled, first honours the fleet-wide pause
             (`vars.FLEET_AGENTS_PAUSED`) and `_data/fleet.yml` `switches:`
             (§ 17, most restrictive level wins) and exits 5 when paused;
             `plan` and `--rehearse` still run. Before each attempt the HOST
             builds the item's context pack (tools/jev/context.py: the lake,
             the code index, the telemetry, this loop's earlier attempts) and
             places it beside the brief in the clone, with a pointer in the
             clone's copy of the brief — the sealed agent only reads a file;
             `--context off` is the CI-identical run.
             The engine is this module and seven siblings: loop_common.py
             (exit codes, clock and JSON helpers, the run's options, the
             subprocess environments), loop_budget.py (the monthly ceiling),
             loop_runs.py (the run directory and its history), loop_host.py
             (the gates and the host checks), loop_context.py (the engine's
             side of the context pack), loop_publish.py (the publish token,
             the preview, the filing) and loop_canary.py (the canary). Here:
             the specs, the subprocess seams, the run context, planning, one
             item's rehearsal or attempt, the run, the verbs and the CLI.
             This module is the facade: it re-exports every name a sibling
             defines. A seam tests replace (`DASH_GEN`, `dash_gen`,
             `relay_dash_gen`, `auth_pin`, `sandbox_available`, `hub_state`,
             `_fresh_dry`, `load_fleet`, …) is bound HERE only, and a sibling
             reaches it as `engine.<name>` (a lazy `from . import loop as
             engine`), so replacing it on this module replaces it everywhere.
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
import datetime as dt
import json
import math
import os
import platform
import re
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

from . import adapters, headless
from . import context as cpack
from . import sprints as sp
from . import workspace as wsp
from .adapters import REUSE_DAYS, Adapter, Item, PlanResult, PublishPlan, Verdict
from .common import HUB, JevError, Run, dotenv_values, gh, git, hub_repo, is_bare_name, load_config, run
from .ledger import BudgetState, Ledger, budget_state
# The engine's sibling modules. Each block lists the WHOLE of what that module defines, used below or not:
# `tools.jev.loop` is the facade callers and tests import, so a name dropped here leaves the engine's surface.
from .loop_budget import (LEDGER_VERSION, _budget_dict, _ledger_cost, _spend,  # noqa: F401 - re-exported
                          _sprint_budget, _unledgered_rows, _utc_month, budget_lock, budget_position, charge,
                          ledger_path, local_spend, loops_budget, record_unledgered, unledgered_path)
from .loop_canary import (CANARY_CAP_USD, CANARY_GRANTS, CANARY_MODEL, CANARY_TIMEOUT_S,  # noqa: F401 - re-exported
                          CANARY_TURNS, _canary_fixture, _confirm_canary, _plant, canary_dir, canary_flags,
                          canary_grants, run_canary)
from .loop_common import (COST_LABEL, DAY_RX, EXIT, OUTER_GRACE_S, SEVERITY, TARGET_RX,  # noqa: F401 - re-exported
                          Options, _sha, ai_run_env, deterministic_env, iso, now_utc, option_refusal, read_json,
                          runs_dir, severest, write_json)
from .loop_context import (CONTEXT_GRACE_S, REFRESH_ARGV, _finite, claude_projects_dir,  # noqa: F401 - re-exported
                           context_backstop, context_bits, context_mode, context_preview, context_request,
                           context_settings, context_status, host_ctx, item_pack, place_inputs, refresh_context)
from .loop_host import (PAUSE_VARIABLE, SANDBOX_EXEC, HostReport, _is_off, _map,  # noqa: F401 - re-exported
                        auth_choice, cache_key, cached, canary_key, gates, head_sha, host_check, map_paused, pause_gate,
                        posture_breach, private_work_root, repo_paused, resolve_claude, store, switch_entries,
                        work_root_problem)
from .loop_publish import (NOTHING_FILED_RETRY, PUBLISH_PLAN_SCHEMA, PUBLISH_RESULT_SCHEMA,  # noqa: F401 - re-exported
                           _already_applied, _bodies, _file_sha, _plan_md, _publish_target, apply_item, apply_refusal,
                           item_values, preview, probe_publish_token, publish_env, publish_phase, publish_tier,
                           publish_token, publish_values, review_gap)
from .loop_runs import (ATTEMPT_SCHEMA, KEEP_RUNS, RUN_SCHEMA, History, LockHeld, RunDir,  # noqa: F401 - re-exported
                        _finish, _summary, _totals, prune, step_lock)
from .spec import (PATCH_OUTPUT, PUBLISH_REVIEWED_FLAGS, SPEC_ROOT, ContextSpec, StepSpec, StepSpecError,
                   allowed_models,
                   fleet_value, load_fleet, load_spec, render_argv, render_prompt, spec_files, values_from)

DASH_GEN = HUB / "tools" / "dash-gen"
TIER = "t1"   # P1 has one tier, built from the spec's resolved values; P3 adds `local.tiers`
#: the backstop's SIGTERM-to-SIGKILL grace: ai-run's own SIGINT-first ladder needs well under it
BACKSTOP_KILL_S = 60
#: Hub paths whose state decides what an engine run does, besides the spec
#: directory and the adapter's own `sources`: the engine, its config, and the
#: executor that builds the agent's environment, credential and redactor.
ENGINE_SOURCES = ("tools/jev/", "_data/fleet.yml", ".github/scripts/dash-gen/ai_activity.py", "tools/dash-gen")
ALLOW_DIRTY_HELP = ("let --apply run with a dirty spec, adapter or engine (tools/jev/, _data/fleet.yml, ai-run, "
                    "tools/dash-gen)")
#: `loop doctor`'s one code-index probe query (an Ollama embedding, local and $0). It
#: proves Qdrant and Ollama answer: a search that answers is an index that is UP,
#: hit or no hit (with no query the planes would not ask the index at all)
DOCTOR_QUERY = "the loop runner and its context pack"


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
    # Every workspace kind and credential posture the loader accepts runs here
    # the same way: the clone is the item's `nwo` (the adapter names the hub for
    # a `cwd: hub` step), and the agent's environment carries NO GitHub
    # credential under any posture — `fleet-write` describes what CI hands the
    # step; locally the engine's publish step holds the token (§ 13.8, ADR 0002 P3).
    return spec


# --------------------------------------------------------------------------- #
# subprocess seams
# --------------------------------------------------------------------------- #
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
# the planner's argv and the JSON it prints
# --------------------------------------------------------------------------- #
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
    #: _data/fleet.yml budget.sprints (tools/jev/sprints.py), loaded by the first attempt that asks
    sprints: list | None = None
    #: the sprint-scope switch, read at most once a run, and only for a sprint item
    sprint_switch: object | None = None
    #: what an expedite sprint's circuit breaker did in this run (run.json `events`)
    events: list[dict] = field(default_factory=list)

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
        """The spec's planner. A targeted call (the live recheck of one item)
        is routed into a scratch directory whatever the planner's flags, so the
        run's plan/plan.json — the rows `loop publish` finds its items in — is
        never overwritten by a one-target plan; `no_files` additionally asks a
        brief-writing planner to write none (its own flag)."""
        with tempfile.TemporaryDirectory(prefix="jev-plan-") as tmp:
            out_dir = Path(tmp) if (no_files or target is not None) else self.plan_dir
            res = dash_gen(planner_argv(self.spec, out_dir, self.opts, target=target, no_files=no_files))
        plan = parse_last_json(res.out)
        if res.code not in (0, 1) or plan is None:
            raise JevError(f"the planner exited {res.code}: {(res.err or res.out).strip()[-400:]}")
        return plan


# --------------------------------------------------------------------------- #
# the sandbox check, the hub's state, the ai-run argv and the plan's prompts
# --------------------------------------------------------------------------- #
def sandbox_available() -> bool:
    """P1's sandbox posture is Seatbelt: macOS with sandbox-exec."""
    return sys.platform == "darwin" and SANDBOX_EXEC.is_file()


def hub_state(paths: list[str]) -> dict:
    head = git(["rev-parse", "HEAD"], cwd=HUB)
    dirty = git(["status", "--porcelain=v1", "--", *paths], cwd=HUB)
    return {"head": head.out.strip() if head.ok else None,
            "dirty_paths": sorted({line[3:] for line in dirty.out.splitlines() if len(line) > 3})}


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
# the context planes for `loop doctor` (the pack's engine side is loop_context.py)
# --------------------------------------------------------------------------- #
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


# --------------------------------------------------------------------------- #
# one item: rehearsal or attempt
# --------------------------------------------------------------------------- #
def usage_block(ctx: RunContext) -> tuple[str, str] | None:
    """(decision, why) for an item that would call the model after a usage
    window spent earlier in this run. Asked after tier 0, so a $0 reuse or
    skip (and its preview or filing, which reach gh, not Claude) still runs."""
    if ctx.usage_limited:
        return "usage-skip", "the usage window was spent earlier in this run (capacity, not a defect)"
    return None


def budget_block(ctx: RunContext, held: bool, item: Item | None = None) -> tuple[str, str] | None:
    """(decision, why) when the month cannot absorb this attempt's full cap,
    or (for `item`) an expedite sprint holds it (`sprint_block`). Asked just
    before the model call — after tier 0, so a $0 reuse is never blocked —
    under `budget_lock`, against a FRESH read of the ledger and the engine's
    unledgered charges (plus any this run could not write down), so another
    run's spend is seen."""
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
    return sprint_block(ctx, item, cap) if item is not None else None


def sprint_block(ctx: RunContext, item: Item, cap: float) -> tuple[str, str] | None:
    """(decision, why) when an expedite sprint holds this attempt
    (tools/jev/sprints.py): the item is in the active sprint's repositories and
    its switch is off on a --scheduled run (`sprint-off`), or the sprint's
    spend in every ledger plus this attempt's full cap crosses its ceiling
    (`budget-skip`). Inside the monthly ceiling, never instead of it. A tripped
    breaker is recorded once a run as an event in run.json; a sprint
    declaration that cannot be read stops the attempt (`budget-unreadable`)."""
    now = now_utc()
    try:
        if not _sprints_declared(ctx):
            return None
        verdict = sp.gate(ctx.sprints, repo=item.nwo, now=now, cost_usd=cap, switch=ctx.sprint_switch,
                          spend_of=lambda s: sp.spend(s, ai_ledger=ledger_path(), jev=Ledger.load(), ci=sp.ci_rows(),
                                                      pipeline=sp.pipeline_rows(), hub=hub_repo(ctx.fleet),
                                                      extra=ctx.unledgered))
    except (JevError, StepSpecError) as exc:
        return "budget-unreadable", f"sprint ceiling: {exc}"
    return _sprint_verdict(ctx, verdict, now)


def sprint_off(ctx: RunContext, item: Item) -> tuple[str, str] | None:
    """(`sprint-off`, why) for an item of the active sprint while its switch is
    off: asked before tier 0, so a stopped sprint's item is not even previewed."""
    now = now_utc()
    try:
        if not _sprints_declared(ctx):
            return None
        verdict = sp.switched_off(ctx.sprints, repo=item.nwo, now=now, switch=ctx.sprint_switch)
    except (JevError, StepSpecError) as exc:
        return "budget-unreadable", f"sprint switch: {exc}"
    return _sprint_verdict(ctx, verdict, now)


def _sprints_declared(ctx: RunContext) -> bool:
    """Load budget.sprints once a run (JevError when it cannot be read) and arm
    the once-a-run switch reader; False when no sprint is declared."""
    if ctx.sprints is None:
        ctx.sprints = sp.load_sprints(ctx.fleet)
    if ctx.sprints and ctx.sprint_switch is None:
        hub = hub_repo(ctx.fleet)
        ctx.sprint_switch = sp.once(lambda: sp.read_switch(scheduled=ctx.opts.scheduled, reader=sp.gh_reader(hub)))
    return bool(ctx.sprints)


def _sprint_verdict(ctx: RunContext, verdict, now: dt.datetime) -> tuple[str, str] | None:
    if verdict is None:
        return None
    if not any(e.get("sprint") == verdict.sprint.slug and e.get("decision") == verdict.decision for e in ctx.events):
        ctx.events.append(verdict.event(now))
    return verdict.decision, verdict.reason


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
    if live:
        # an expedite sprint's kill switch stops its loops outright, the $0 tier 0 included (§ 27.6)
        off = sprint_off(ctx, item)
        if off:
            report.update(status="skipped", decision=off[0], reason=off[1])
            ctx.run.append_attempt({**row, "decision": off[0], "reason": off[1]})
            return report
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
                               dirname=dirname, brief_file=ctx.spec.workspace.brief_file,
                               allow_commits=ctx.spec.local.harvest == "patch")
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
        # placed beside the brief; it can ask the planes nothing itself. The planes check the target's code hits
        # against this clone, the files the agent reads.
        pack = item_pack(ctx, item, report, row, target_dir=ws.path if ws is not None else None)
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
                blocked = budget_block(ctx, held, item)
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
    debug = headless.posture_lines(headless.reduce_debug_log(d / "debug.log"), outcome)
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
    flagged = False
    if kind in ("budget_hit", "max_turns"):
        # local.on_budget_hit: discard (JEV's rule) — CI's file job would file what the leg left behind.
        # publish-flagged (P3, evolve): a budget hit's edits are harvested and previewed FLAGGED as partial,
        # as CI's publish step marks such a body; a turn exhaustion is still discarded (CI's salvage
        # publishes only a reported success, which classifies as ok here). Any other value has no
        # behaviour here: fail closed rather than discard it silently.
        if spec.local.on_budget_hit == "publish-flagged" and kind == "budget_hit":
            flagged = True
            report.setdefault("flags", []).append(
                f"budget hit ({detail}): the pass was stopped MID-TASK — the preview is flagged PARTIAL "
                "(on_budget_hit publish-flagged); nothing is filed without --apply")
        elif spec.local.on_budget_hit not in ("discard", "publish-flagged"):
            return done("failed", f"{kind}: on_budget_hit {spec.local.on_budget_hit!r} has no engine behaviour — "
                                  "the output is left unread")
        else:
            return done("discarded", f"{kind}: {detail} — the partial output is discarded (on_budget_hit "
                                     f"{spec.local.on_budget_hit}); a rerun costs about one attempt")
    if kind == "interrupted":
        ctx.stop = (EXIT["interrupted"], f"interrupted: {detail}")
        return done("failed", f"interrupted: {detail}", EXIT["interrupted"])
    if kind != "ok" and not flagged:
        return done("failed", f"{kind}: {detail}")

    tree = wsp.tree_report(ws)
    _write_tree(d, tree)
    if spec.local.harvest == "patch":
        # the agent's edits ARE the output: one patch through the engine's own git, nothing discarded
        patch = wsp.diff_patch(ws, d / "outputs")
        harvested = {PATCH_OUTPUT: patch}
        if tree.tracked or tree.untracked:
            report.setdefault("flags", []).append(
                f"{len(tree.tracked)} tracked edit(s) and {len(tree.untracked)} new file(s) harvested as "
                f"{PATCH_OUTPUT} ({patch.reason}, {patch.size} bytes)")
    else:
        if tree.tracked:
            wsp.discard_tracked(ws)   # CI's "Verify the tree is untouched"
            report.setdefault("flags", []).append(f"tracked edits discarded: {', '.join(tree.tracked)}")
        if tree.untracked:
            report.setdefault("flags", []).append(f"untracked files outside {spec.workspace.brief_dir}/ left in "
                                                  f"the clone (ignored): {', '.join(tree.untracked[:10])}")
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
# publishing (loop_publish.py): the live dry run the filing and `loop publish` share
# --------------------------------------------------------------------------- #
def _fresh_dry(ctx: RunContext, item: Item, validated: Path) -> tuple[PublishPlan, dict[str, str]]:
    """The preview again, with a live dedupe, into a scratch directory: what
    a filing would write NOW, as body hashes."""
    verdict = Verdict(True, publish_file=validated)
    with tempfile.TemporaryDirectory(prefix=".fresh-", dir=ctx.item_dir(item)) as tmp:
        argv = publish_values(ctx, item, validated, apply=False, bodies_dir=Path(tmp))
        plan = ctx.adapter.publish(ctx, item, verdict, lambda: ctx.dash_gen(argv))
        return plan, _bodies(Path(tmp))


# --------------------------------------------------------------------------- #
# `loop run`
# --------------------------------------------------------------------------- #
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
    if opts.apply:
        refused = apply_refusal(spec)
        if refused:
            print(f"jev loop: {refused}", file=sys.stderr)
            return EXIT["usage"]
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


def _run(ctx: RunContext, record: dict, posture: headless.Posture) -> int:
    """The run, in order: the pause (a live run only), gates, the --apply
    refusals, the ceiling, the host, the publish token (all $0 and before
    anything spends), the plan, then the items one by one."""
    live = not ctx.opts.rehearse
    stop = pause_gate(ctx.fleet, ctx.spec) if live else None
    if stop:
        record["notes"].append(stop[1])
        return _finish(ctx, record, stop[0], "paused" if stop[0] == EXIT["paused"] else "refused")
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
    # switches.repos: an item whose own repository is paused is held back at $0, before its clone
    held = [{"key": i.key, "name": i.name, "reason": f"paused: {why}"}
            for i in result.items if live and (why := repo_paused(ctx.fleet, i.nwo))]
    result.items = [i for i in result.items if i.key not in {h["key"] for h in held}]
    record["plan"] = {**result.meta, "count": len(result.items), "skipped": result.skipped, "dropped": result.dropped}
    if held:
        record["plan"]["paused"] = held
    rows = [*((r, "planned-skip") for r in [*result.skipped, *result.dropped]), *((h, "paused-skip") for h in held)]
    for r, decision in rows:
        # `item` is the item key where the adapter knows it (scout: the nwo), as on every other row
        ctx.run.append_attempt({"run_id": ctx.run.run_id, "loop": ctx.spec.loop, "step": ctx.spec.step,
                                "item": r.get("key") or r.get("name"), "name": r.get("name"),
                                "decision": decision, "reason": r.get("reason"),
                                "cost_usd": 0.0, "cost_source": "no-spend"})
    if held:
        reasons = "; ".join(sorted({h["reason"] for h in held}))
        if not result.items:
            record["notes"].append(f"every planned item's repository is paused ({reasons}) — nothing ran (§ 17)")
            return _finish(ctx, record, EXIT["paused"], "paused")
        record["notes"].append(f"{len(held)} item(s) held back ({reasons})")
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
        paused = map_paused(fleet, spec)   # a plan runs while paused; it says a live run would not (no gh read)
        if paused:
            out["notes"].append(f"paused: {paused} — a live run or an --apply exits {EXIT['paused']} (§ 17)")
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
    chosen = local_specs(fleet=fleet)
    if getattr(args, "loop", None):
        chosen = [s for s in chosen if s.loop == args.loop and (args.step is None or s.step == args.step)]
        if not chosen:
            print(f"jev loop: no step spec with a local: block for {args.loop}"
                  f"{'/' + args.step if args.step else ''} (`loop list`)", file=sys.stderr)
            return EXIT["usage"]
    for spec in chosen:
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
                paused = pause_gate(fleet, spec)   # the canary is a model call: it honours the pause too
                if paused:
                    host.problems.append((paused[0], f"canary not run: {paused[1]}"))
                elif host.auth is None:
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
                            if verdict.ok:
                                # the host check's note was written before the canary ran
                                host.notes = [n for n in host.notes if not n.startswith("canary: none passing")]
                                host.notes.append(
                                    f"canary: passed — {verdict.facts.get('sandbox_lines', 0)} sandboxed command "
                                    f"line(s), fences {verdict.facts.get('fences') or {}}; cached for this CLI, "
                                    "posture template and credential exposure")
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
                     "can_apply": s.local.publish is not None and s.local.publish.can_apply,
                     "postures": ["sandbox", "reduced"]})
    if args.json:
        print(json.dumps(rows, indent=2, sort_keys=True))
        return 0
    for r in rows:
        sw = r["switch"]
        gate = (f"{sw['config']}={sw['config_value']} · vars.{sw['variable']} default {sw['default']}" if sw
                else "no switch (dispatch-only: a manual run; --scheduled is refused)")
        apply = "" if r["can_apply"] else " · --apply refused (#488: the filer cannot file yet)"
        print(f"{r['step']}  adapter {r['adapter']} · {r['model']} · {r['max_turns']} turns · "
              f"${r['cap_usd']:g} cap (API-equivalent, estimate) · {gate} · publish tier {r['publish_tier']}{apply}")
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
    if args.apply:
        refused = apply_refusal(spec)
        if refused:
            print(f"jev loop: {refused}", file=sys.stderr)
            return EXIT["usage"]
    doc, item, why = _publish_target(rd, record, args.item)
    if doc is None or item is None:
        print(f"jev loop: {why}", file=sys.stderr)
        return EXIT["usage"]
    if args.plan_id and args.plan_id != doc["plan_id"]:
        print(f"jev loop: --plan-id {args.plan_id} is not this preview's ({doc['plan_id']})", file=sys.stderr)
        return EXIT["usage"]
    if args.apply:
        stop = pause_gate(fleet, spec, repos=(item.nwo,))
        if stop:
            print(f"jev loop: --apply refused: {stop[1]}", file=sys.stderr)
            return stop[0]
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
    """The month against budget.loops, beside JEV conflicts' budget.jev and
    the active expedite sprint's ceiling (budget.sprints), and whether the two
    monthly caps together fit inside harnesses.budget.monthly_ai_usd: exit 1
    (attention) when they do not, when that ceiling is not a finite number
    above 0 and so cannot be judged, or when the sprint cannot be."""
    fleet = load_fleet()
    loops = budget_position(fleet, scheduled=args.scheduled)
    sprint = _sprint_budget(fleet)
    # load_config refuses a sprint declaration that bounds nothing; budget.jev's month does not depend on it,
    # so that declaration is reported on the sprint line (exit 1) rather than ending the whole readout
    jev_fleet = fleet if "error" not in sprint else {
        **fleet, "budget": {k: v for k, v in (fleet.get("budget") or {}).items() if k != "sprints"}}
    conflicts = budget_state(load_config(jev_fleet), Ledger.load(), scheduled=args.scheduled, month=loops.month)
    ceiling = (((fleet.get("harnesses") or {}).get("budget") or {}).get("monthly_ai_usd"))
    limit = (float(ceiling) if isinstance(ceiling, (int, float)) and not isinstance(ceiling, bool)
             and math.isfinite(ceiling) and ceiling > 0 else None)
    together = round(loops.cap_usd + conflicts.cap_usd, 4)
    inside = limit is not None and together <= limit
    out = {"label": f"{COST_LABEL} — a throughput ceiling under OAuth, not an invoice",
           "loops": {**_budget_dict(loops), "ledger": str(ledger_path())},
           "jev_conflicts": _budget_dict(conflicts),
           "sprint": sprint,
           "monthly_ai_usd": limit if limit is not None or ceiling is None else str(ceiling),
           "caps_usd": together, "inside_monthly_ai_usd": inside}
    code = EXIT["ok"] if inside and "error" not in sprint else EXIT["attention"]
    if args.json:
        print(json.dumps(out, indent=2, sort_keys=True))
        return code
    print(f"loops (budget.loops)        {loops.summary()}")
    print(f"jev conflicts (budget.jev)  {conflicts.summary()}")
    print(f"sprint (budget.sprints)     {sprint['line']}")
    if inside:
        print(f"both inside harnesses.budget.monthly_ai_usd ${limit:g} (${together:g} together)")
    elif limit is None:
        print(f"the fleet ceiling cannot be judged: harnesses.budget.monthly_ai_usd is {ceiling!r}, not a finite "
              "number above 0")
    else:
        print(f"EXCEED harnesses.budget.monthly_ai_usd ${limit:g}: budget.loops ${loops.cap_usd:g} + budget.jev "
              f"${conflicts.cap_usd:g} = ${together:g}")
    print(f"{out['label']}")
    return code


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
                              "--live adds the one-time canary (≤ $0.10); every local step, or the one named")
    doc.add_argument("loop", nargs="?", default=None, help="only this loop's step(s) (default: every local step)")
    doc.add_argument("step", nargs="?", default=None, help="only this step of the loop")
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
