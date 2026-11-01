#!/usr/bin/env python3
"""
File: tools/jev/loop.py
Description: JEV capability two's runner — `python3 -m tools.jev loop`, the
             local loop engine (#486, ADR 0002 P1). It runs a loop's agent step
             on this workstation exactly as CI does: the same planner
             (`tools/dash-gen scout`), the same prompt bytes (rendered from the
             step spec), the same allowlist, inside the § 13.8 posture of
             tools/jev/headless.py, in a hardened throwaway clone
             (tools/jev/workspace.py), with the loop's own logic in an adapter
             (tools/jev/adapters/). All policy comes from the spec, its
             `local:` block, `_data/fleet.yml` and the adapter; this module has
             no loop-specific code, writes only under the gitignored
             `.fleet/runs/` and the work root, and never commits or merges.
             THIS SLICE IS $0 (PR-B): `list`, `doctor` (the flag preflight and
             the self-calibrating isolation probe, credential-free), `plan`,
             `run --rehearse` (everything up to the model call: plan, tier 0,
             classify, clone, prompt, settings, flags, the flag preflight and
             `dash-gen ai-run --dry-run` on an empty stdin) and `show`. A `run`
             without --rehearse refuses: live attempts, the canary, the budget
             and publishing arrive in the next PR.
Author: bamr87
Created: 2026-10-31
Version: 0.1.0
Usage: python3 -m tools.jev loop list | doctor | plan <loop> | run <loop> --rehearse | show <run_id>|--latest
       (also `tools/dash loop …`; docs/JEV.md "The loop runner")
Dependencies: PyYAML; git and gh for the plan and the clone; the claude CLI
              for doctor and the rehearsal's preflight (no model request).
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
import platform
import re
import shutil
import sys
import tempfile
import uuid
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import adapters, headless
from . import workspace as wsp
from .adapters import REUSE_DAYS, Adapter, Item, PlanResult
from .common import HUB, JevError, Run, gh, git, hub_repo, is_bare_name, run
from .spec import (SPEC_ROOT, StepSpec, StepSpecError, fleet_value, load_fleet, load_spec, render_argv,
                   render_prompt, spec_files, values_from)

DASH_GEN = HUB / "tools" / "dash-gen"
RUN_SCHEMA = "jev-loop-run/v1"
ATTEMPT_SCHEMA = "jev-loop-attempt/v1"
KEEP_RUNS = 30
TIER = "t1"   # P1 has one tier, built from the spec's resolved values; P3 adds `local.tiers`
EXIT = {"ok": 0, "attention": 1, "usage": 2, "credential": 3, "host_unsafe": 4, "no_cli": 127, "interrupted": 130}
NEXT_PR = ("live attempts arrive in the next PR (#486, PR-C): this engine makes no model call yet — "
           "`loop run … --rehearse` does everything up to it at $0")
SANDBOX_EXEC = Path("/usr/bin/sandbox-exec")
TARGET_RX = re.compile(r"[A-Za-z0-9_.-]+")
DAY_RX = re.compile(r"\d{4}-\d{2}-\d{2}")
#: Hub paths whose state decides what an engine run does, besides the spec
#: directory and the adapter's own `sources`.
ENGINE_SOURCES = ("tools/jev/", "_data/fleet.yml")


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

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> Options:
        return cls(**{k: getattr(args, k) for k in cls.__dataclass_fields__ if hasattr(args, k)})


def option_refusal(opts: Options, *, verb: str) -> str | None:
    """Why these options cannot run at all; None when they can."""
    if verb == "run" and not opts.rehearse:
        return NEXT_PR
    if opts.apply and opts.scheduled:
        return ("--apply with --scheduled is refused: no unattended local filing until § 13.7 earned autonomy "
                "exists (the publish action is tier high, § 13.6)")
    if opts.apply and opts.rehearse:
        return "--apply with --rehearse is refused: a rehearsal files nothing"
    if opts.apply and opts.offline:
        return "--apply with --offline is refused: filing needs the live recheck and a live dedupe"
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
                        "validated_sha256": row["validated_sha256"]}
        if best is None:
            return None
        best["published"] = best["validated_sha256"] in published
        best.pop("_ts")
        return best


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
    """Why the work root cannot hold a workspace (host safety, exit 4); None when it can."""
    root = headless.work_root() if root is None else root
    if root.resolve().is_relative_to(HUB.resolve()):
        return f"the work root {root} is inside the hub tree (set JEV_WORK_ROOT outside it)"
    return None


def private_work_root() -> Path:
    root = headless.work_root()
    root.mkdir(parents=True, exist_ok=True)
    root.chmod(0o700)
    return root


def host_check(spec: StepSpec, posture: headless.Posture, fleet: dict, claude_bin: str, scratch: Path | None, *,
               live: bool, preflight: bool, probe_cache: bool = True, report: bool = False) -> HostReport:
    """What the host proves before an attempt. `live=False` (doctor, rehearse)
    reports a missing probe, canary or credential as a note; a live attempt
    (PR-C) refuses on each of them. `probe_cache=False` skips the cached
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
            rep.notes.append("flag preflight: every flag parses and the --settings document loads ($0)")
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
    if posture.name == "sandbox":
        canary = cached(".canary.json", key)
        rep.canary = "absent" if canary is None else ("ok" if canary.get("ok") else "failed")
        if rep.canary != "ok":
            gap(EXIT["host_unsafe"], f"canary: none passing for this CLI and posture template ({rep.canary}) — the "
                                     "one-time ≤ $0.10 canary (`loop doctor --live`, the maintainer's yes) arrives "
                                     "with live attempts")
    rep.auth, said = auth_choice(fleet, rep.claude)
    if rep.auth is None:
        gap(EXIT["credential"], f"credential: {said} — a live attempt exits 3")
    else:
        rep.notes.append(f"credential: {said} (the first present in CLAUDE_AUTH_ORDER; never retried with another)")
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


def ai_run_argv(ctx: RunContext, item: Item, *, cwd: Path, tmp: Path, flags: list[str], attempt_id: str,
                method: str | None, claude: str) -> list[str]:
    """The `tools/dash-gen ai-run` command a live attempt runs (PR-C executes it)."""
    d = ctx.item_dir(item)
    spec = ctx.spec
    argv = ["ai-run", "--stream", "--isolate", "--isolate-tmp", str(tmp),
            "--timeout", str(spec.timeout_minutes * 60), "--call-site", spec.call_site, "--repo", item.nwo,
            "--cwd", str(cwd), "--prompt-file", str(d / "prompt.txt"), "--trace", str(d / "trace.jsonl"),
            "--result-file", str(d / "result.json"), "--outcome-file", str(d / "outcome.json"),
            "--usage-limit", "skip", "--source", f"jev loop {spec.loop}/{spec.step}", "--claude-bin", claude]
    if method:
        argv += ["--auth-order", method]
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
# `loop run --rehearse`
# --------------------------------------------------------------------------- #
def rehearse_item(ctx: RunContext, item: Item, host: HostReport, posture: headless.Posture) -> dict:
    """Everything a live attempt does before the model call, at $0."""
    dirname = wsp.item_dirname(item.key)
    report: dict = {"key": item.key, "dir": dirname, "name": item.name, "status": "rehearsed", "reason": "",
                    "decision": "rehearsed"}
    row = {"run_id": ctx.run.run_id, "loop": ctx.spec.loop, "step": ctx.spec.step, "call_site": ctx.spec.call_site,
           "item": item.key, "dir": dirname, "nwo": item.nwo, "tier": TIER, "model": ctx.spec.resolved.model,
           "cost_usd": 0.0, "cost_source": "no-spend"}
    sha, why = (None, "offline: no HEAD read") if ctx.opts.offline else head_sha(item.nwo, item.branch)
    if why:
        print(f"jev loop: {why}", file=sys.stderr)
    t0 = ctx.adapter.tier0(ctx, item, sha)
    key = ctx.adapter.reuse_key(ctx, item, sha)
    row.update(head_sha=sha, reuse_key=key)
    if t0.action != "continue":
        report.update(status="skipped" if t0.action == "skip" else "reused", reason=t0.reason,
                      decision=f"tier0-{t0.action}")
        ctx.run.append_attempt({**row, "decision": report["decision"], "reason": t0.reason,
                                "reuse_from": str(t0.reuse_from) if t0.reuse_from else None})
        return report
    triage = ctx.adapter.classify(ctx, item)
    if triage.blocked:
        report.update(status="blocked", reason=triage.reason, decision="blocked")
        ctx.run.append_attempt({**row, "decision": "blocked", "reason": triage.reason})
        return report

    d = ctx.item_dir(item)
    d.mkdir(parents=True, exist_ok=True)
    attempt_id = str(uuid.uuid4())
    prompt = render_prompt(ctx.spec, values_from(ctx.spec, item.row))
    (d / "prompt.txt").write_text(prompt, encoding="utf-8")
    write_json(d / "settings.json", headless.settings_doc(posture))
    flags = headless.claude_flags(ctx.spec, posture, settings_path=d / "settings.json", session_id=attempt_id,
                                  debug_path=d / "debug.log")
    ws = None
    try:
        if not ctx.opts.offline:
            try:
                ws = wsp.clone(item.nwo, item.branch, run_id=ctx.run.run_id, brief_dir=ctx.spec.workspace.brief_dir,
                               dirname=dirname)
            except JevError as exc:
                report.update(status="failed", reason=str(exc))
                ctx.run.append_attempt({**row, "decision": "rehearsed", "attempt_id": attempt_id,
                                        "outcome": "failed", "reason": str(exc)})
                return report
            if sha and ws.head_sha != sha:
                # the branch moved between the read and the clone: tier 0 again, on what was cloned
                again = ctx.adapter.tier0(ctx, item, ws.head_sha)
                row.update(head_sha=ws.head_sha, reuse_key=ctx.adapter.reuse_key(ctx, item, ws.head_sha))
                if again.action != "continue":
                    report.update(status="skipped" if again.action == "skip" else "reused", reason=again.reason,
                                  decision=f"tier0-{again.action}")
                    ctx.run.append_attempt({**row, "decision": report["decision"], "reason": again.reason})
                    return report
            brief = brief_in_plan(ctx, item)
            if brief is not None:
                wsp.place(ws, brief, f"{ctx.spec.workspace.brief_dir}/{brief.name}")
            report["workspace"] = {"head_sha": ws.head_sha, "baseline_entries": len(ws.baseline),
                                   "baseline_sha256": _sha(json.dumps(ws.baseline, sort_keys=True))}
        cwd, tmp = (ws.path, ws.tmp) if ws else (d, d / "tmp")
        live = ai_run_argv(ctx, item, cwd=cwd, tmp=tmp, flags=flags, attempt_id=attempt_id,
                           method=host.auth.method if host.auth else None, claude=host.claude or ctx.opts.claude_bin)
        env_keys = set(headless.agent_env(os.environ, None, credential_value=None, tmp=tmp,
                                          gh_config_dir=tmp / "gh-none", work=ctx.work_root))
        if host.auth and host.auth.source != "login":
            env_keys.add(headless.CREDENTIAL_ENV[host.auth.method])
        write_json(d / "env-keys.json", sorted(env_keys))   # names only, never a value
        write_json(d / "argv.json", {"claude_flags": flags, "ai_run": [str(DASH_GEN), *live],
                                     "prompt_sha256": _sha(prompt), "prompt_bytes": len(prompt.encode("utf-8")),
                                     "settings_sha256": _sha(json.dumps(headless.settings_doc(posture),
                                                                        sort_keys=True))})
        if ws is not None:
            dry = dash_gen(rehearsal_argv(live), stdin="", timeout=120, env=ai_run_env(host.auth))
            said = headless.Redactor(os.environ).text((dry.err or "").strip())[-6000:]
            (d / "ai-run-dry.txt").write_text(said + "\n", encoding="utf-8")
            report["ai_run_dry"] = dry.code
            if dry.code == EXIT["credential"]:
                report["reason"] = "ai-run --dry-run: no usable Claude credential (a live attempt would exit 3)"
            elif dry.code != 0:
                report.update(status="failed", reason=f"ai-run --dry-run refused the planned argv (exit {dry.code}): "
                                                      f"{said[-300:]}")
            changed = wsp.tampered(ws)
            if changed:
                # no git runs in a tampered clone: it is destroyed uninspected (the finally below)
                (d / "tree.txt").write_text(f"not inspected: .git changed ({', '.join(changed)})\n",
                                            encoding="utf-8")
                report.update(status="failed", reason=f"the workspace was tampered with: {changed}", tampered=True)
            else:
                tree = wsp.tree_report(ws)
                (d / "tree.txt").write_text("\n".join([*(f"tracked {p}" for p in tree.tracked),
                                                       *(f"untracked {p}" for p in tree.untracked)]) + "\n",
                                            encoding="utf-8")
                if tree.tracked:
                    report.update(status="failed", reason=f"the fresh workspace is not clean: tracked {tree.tracked}")
        else:
            report["reason"] = report["reason"] or "offline: no clone, no ai-run dry run"
    except JevError as exc:   # this item's failure (git status, the brief, …): recorded, and the run goes on
        report.update(status="failed", reason=str(exc))
    finally:
        # a tampered clone is destroyed even with --keep-workspace: git run in it would run the agent's config
        if ws is not None and (not ctx.opts.keep_workspace or report.get("tampered")):
            wsp.destroy(ws)
        elif ws is not None:
            report["kept_workspace"] = str(ws.path)
    ctx.run.append_attempt({**row, "decision": "rehearsed", "attempt_id": attempt_id, "outcome": report["status"],
                            "reason": report["reason"]})
    report["attempt_id"] = attempt_id
    return report


def _new_record(ctx: RunContext, posture: headless.Posture) -> dict:
    spec = ctx.spec
    paths = [str(spec.path.parent.relative_to(HUB)) + "/", *ENGINE_SOURCES, *ctx.adapter.sources]
    return {
        "schema": RUN_SCHEMA, "run_id": ctx.run.run_id, "loop": spec.loop, "step": spec.step, "origin": "local",
        "mode": "rehearse" if ctx.opts.rehearse else "run", "status": "running", "started": iso(), "finished": None,
        "hub": hub_state(paths),
        "spec": {"path": str(spec.path.relative_to(HUB)) if spec.path.is_relative_to(HUB) else str(spec.path),
                 "sha256": spec.content_sha256, "template_sha256": spec.template_sha256, "call_site": spec.call_site},
        "posture": {"name": posture.name, "network": list(posture.network),
                    "template_sha256": headless.posture_template_sha(spec, posture)},
        "tier": {"name": TIER, "model": spec.resolved.model, "max_turns": spec.resolved.max_turns,
                 "cap_usd": spec.resolved.max_budget_usd},
        "publish": {"risk": spec.local.publish.risk if spec.local.publish else None, "tier": publish_tier(spec)},
        "options": asdict(ctx.opts), "items": [], "notes": [], "exit_code": None,
    }


def _summary(record: dict) -> str:
    lines = [f"# jev loop {record['loop']}/{record['step']} — {record['run_id']}", "",
             f"- mode: {record['mode']} · status: {record['status']} · exit {record['exit_code']}",
             f"- posture: {record['posture']['name']} (network none) · model {record['tier']['model']} · "
             f"turns {record['tier']['max_turns']} · cap ${record['tier']['cap_usd']:g} (API-equivalent, estimate)",
             "- spend: $0.00 (API-equivalent, estimate) — a rehearsal makes no model call", ""]
    if record.get("hub", {}).get("dirty_paths"):
        lines.append(f"- dirty at start: {', '.join(record['hub']['dirty_paths'])}")
    for n in record.get("notes") or []:
        lines.append(f"- {n}")
    lines += ["", "| Item | Status | Reason |", "| --- | --- | --- |"]
    lines += [f"| {i['key']} | {i['status']} | {i.get('reason') or ''} |" for i in record.get("items") or []]
    return "\n".join(lines) + "\n"


def _finish(ctx: RunContext, record: dict, code: int, status: str) -> int:
    record.update(status=status, exit_code=code, finished=iso())
    ctx.run.write_json("run.json", record)
    (ctx.run.path / "summary.md").write_text(_summary(record), encoding="utf-8")
    (runs_dir() / "LATEST").write_text(ctx.run.run_id + "\n", encoding="utf-8")
    prune(current=ctx.run.run_id)
    for i in record["items"]:
        print(f"  {i['status']:<9} {i['key']}  {i.get('reason') or ''}", file=sys.stderr)
    print(f"jev loop: {status} — $0.00 spent (API-equivalent, estimate); exit {code}", file=sys.stderr)
    if ctx.opts.json:
        print(json.dumps(record, indent=2, sort_keys=True, default=str))
    else:
        print(f"run: {ctx.run.path}")
    return code


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
            return _rehearse(ctx, record, posture)
        except KeyboardInterrupt:
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


def _rehearse(ctx: RunContext, record: dict, posture: headless.Posture) -> int:
    stop = gates(ctx)
    if stop:
        record["notes"].append(stop[1])
        return _finish(ctx, record, stop[0], "disabled" if stop[0] == 0 else "refused")
    host = host_check(ctx.spec, posture, ctx.fleet, ctx.opts.claude_bin, None, live=False, preflight=True)
    record["host"] = host.as_dict()
    record["notes"] += host.notes
    refusal = host.refusal()
    if refusal:
        record["notes"].append(refusal[1])
        return _finish(ctx, record, refusal[0], "refused")
    if record["hub"]["dirty_paths"]:
        dirty = ", ".join(record["hub"]["dirty_paths"])
        record["notes"].append(f"spec, adapter or engine paths were dirty at start ({dirty})"
                               " — a later --apply refuses this without --allow-dirty")
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
    for n, item in enumerate(result.items):
        if ctx.opts.max_items is not None and n >= ctx.opts.max_items:
            record["items"].append({"key": item.key, "dir": wsp.item_dirname(item.key), "status": "skipped",
                                    "reason": f"--max-items {ctx.opts.max_items}"})
            continue
        record["items"].append(rehearse_item(ctx, item, host, posture))
        ctx.run.write_json("run.json", record)
    failed = any(i["status"] == "failed" for i in record["items"])
    return _finish(ctx, record, EXIT["attention"] if failed else EXIT["ok"], "rehearsed")


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
            out["items"].append({"key": item.key, "branch": item.branch, "head_sha": sha, "decision": decision,
                                 "dedupe": item.row.get("dedupe"), "prompt_sha256": _sha(prompt),
                                 "settings_sha256": _sha(json.dumps(settings, sort_keys=True)),
                                 "claude_flags": flags, "dry_filing": filing, "note": why or None})
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
    for i in out["items"]:
        print(f"{i['key']} @ {i['branch']}  →  {i['decision']}")
        if i.get("note"):
            print(f"    note: {i['note']}")
        print(f"    prompt sha256 {i['prompt_sha256'][:16]} · settings sha256 {i['settings_sha256'][:16]} · "
              f"dedupe {i['dedupe']}")
        print(f"    claude {' '.join(i['claude_flags'][:4])} … ({len(i['claude_flags'])} args)")
        if i["dry_filing"]:
            print(f"    dry filing: tools/dash-gen {' '.join(i['dry_filing'])}")
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


def cmd_doctor(args: argparse.Namespace) -> int:
    """$0 host checks; runs the credential-free isolation probe and caches it."""
    posture = headless.Posture(args.posture)
    fleet = load_fleet()
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
            refusal = host.refusal()
            code = refusal[0] if refusal else EXIT["ok"]
            codes.append(code)
            report["steps"].append({"step": f"{spec.loop}/{spec.step}", **host.as_dict(),
                                    "probe_problems": probe_problems, "exit": code})
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
    report["exit"] = worst = severest(codes)
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
        for n in e.get("notes") or []:
            print(f"  · {n}")
    print("spend: $0.00 (API-equivalent, estimate) — every doctor check runs credential-free or with stdin "
          "/dev/null")
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
    p.add_argument("--json", action="store_true", help="print the result as JSON on stdout")


def add_arguments(ap: argparse.ArgumentParser) -> None:
    sub = ap.add_subparsers(dest="action", required=True)
    ls = sub.add_parser("list", help="every step spec with a local: block")
    ls.add_argument("--json", action="store_true")
    doc = sub.add_parser("doctor",
                         help="$0 host checks: CLI floor, sandbox, credential, flag preflight, isolation probe")
    doc.add_argument("--posture", choices=("sandbox", "reduced"), default="sandbox")
    doc.add_argument("--claude-bin", default="claude", metavar="BIN")
    doc.add_argument("--json", action="store_true")
    pl = sub.add_parser("plan", help="what a run would do, per item — never clones, never calls a model")
    _common(pl)
    rn = sub.add_parser("run", help="run the step locally (this slice: --rehearse only, $0)")
    _common(rn)
    rn.add_argument("--rehearse", action="store_true",
                    help="everything up to the model call — plan, tier 0, clone, prompt, flags, preflight — at $0")
    rn.add_argument("--apply", action="store_true", help="publish after the preview (the § 13.6 yes; next PR)")
    rn.add_argument("--max-items", type=int, default=None, metavar="N")
    rn.add_argument("--keep-workspace", action="store_true", help="keep the clone for inspection")
    rn.add_argument("--allow-dirty", action="store_true", help="let --apply run with a dirty spec or adapter")
    rn.add_argument("--run-id", default=None, metavar="ID")
    sh = sub.add_parser("show", help="a run's summary (or run.json with --json)")
    sh.add_argument("run_id", nargs="?", default=None)
    sh.add_argument("--latest", action="store_true")
    sh.add_argument("--json", action="store_true")


def main(args: argparse.Namespace) -> int:
    handlers = {"list": cmd_list, "doctor": cmd_doctor, "plan": cmd_plan, "run": cmd_run, "show": cmd_show}
    try:
        return handlers[args.action](args)
    except JevError as exc:   # StepSpecError, LockHeld, no gh, a bad plan: usage, spec or config (exit 2)
        print(f"jev loop: {exc}", file=sys.stderr)
        return EXIT["usage"]
