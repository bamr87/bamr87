#!/usr/bin/env python3
"""
core — the console's pure logic, kept free of any web framework so
test_console.py runs on a bare interpreter with only PyYAML.

Four things live here:

  STATE      one read of every committed fleet signal under _data/ — the same
             files the Jekyll boards render — folded into the single JSON
             document the front end paints from, plus git/working-tree facts.
  OPS        the operation ALLOWLIST. This is the console's whole security
             posture: it can run exactly these argv shapes and nothing else —
             no shell strings, no free-form commands, parameters validated by
             regex/range before they reach an argv. Everything is a tools/
             entrypoint the CLI and CI already run, so the console adds a
             surface, never a code path.
  JOBS       asynchronous subprocess jobs with on-disk logs that the UI tails.
             Operations that WRITE TO GITHUB (fan-out --apply, secret rotation,
             workflow dispatch) require an explicit confirm flag and are
             serialized behind one lock — the console mirrors the fleet's
             rules: dry-run by default, one remote write at a time, never a
             merge.
  CONFIG     a comment-preserving editor for _data/fleet.yml (ruamel
             round-trip), limited to the declared knobs of CONFIG_SECTIONS and
             spliced back one top-level block at a time so the diff covers only
             what the form touched. It edits the working tree and shows the git
             diff; the commit stays with the human — git is the database and
             the review gate, here as everywhere else in the dash.
  AUTH       credentials supplied through the UI: held in this process's
             environment (which is what a job inherits), optionally written to
             the gitignored .env or handed to `gh auth login` over stdin, and
             never returned, logged, or placed in an argv.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import io
import importlib.util
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.stderr.write("console requires PyYAML: pip install pyyaml\n")
    sys.exit(2)

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:  # the console imports its siblings by bare name
    sys.path.insert(0, _HERE)
import subscription  # noqa: E402  (sibling module; the console runs with its own dir on sys.path)

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA = REPO_ROOT / "_data"
TOOLS = REPO_ROOT / "tools"
DASH = str(TOOLS / "dash")
DASH_GEN = str(TOOLS / "dash-gen")
DASH_GEN_DIR = REPO_ROOT / ".github" / "scripts" / "dash-gen"
JOB_DIR = Path(os.environ.get("DASH_CONSOLE_JOBS") or (Path(tempfile.gettempdir()) / "dash-console"))
# The local data lake (dash-gen lake) and the Phoenix trace store it exports
# to — the other two services of the local stack (docs/HARNESS-OPS.md).
LAKE_DIR = Path(os.environ.get("DASH_LAKE_DIR") or (REPO_ROOT / ".dash-lake"))
PHOENIX_COLLECTOR = os.environ.get("PHOENIX_COLLECTOR_ENDPOINT") or "http://127.0.0.1:6006"
PHOENIX_UI = os.environ.get("PHOENIX_UI_URL") or PHOENIX_COLLECTOR

NAME_RX = re.compile(r"^[A-Za-z0-9._-]{1,64}$")          # repo / submodule names
KEY_RX = re.compile(r"^[a-z_][a-z0-9_.]{0,80}$")          # dotted fleet.yml keys
FIELD_RX = re.compile(r"^[A-Za-z0-9._,/: -]{0,120}$")     # gh workflow -f values

# The committed signals the console reads. Each is optional: a missing file is
# reported as absent, never a crash — the stale-data wire is the one that turns
# absence into an alarm.
SOURCES = {
    "harness_registry": "harness_registry.yml",
    "harness_health": "harness_health.yml",
    "fleet_triage": "fleet_triage.yml",
    "issue_pipeline": "issue_pipeline.yml",
    "token_rotation": "token_rotation.yml",
    "actions_usage": "actions_usage.yml",
    "ai_usage": "ai_usage.yml",
    "engagements": "engagements.yml",
}

# Secrets the fleet contract names — the console reports PRESENCE of the env
# var by name only, never a value or a prefix. The AUTH section below adds the
# ones the console itself can be handed (CREDENTIALS, a superset of these).
TOKEN_ENV = ["FLEET_TOKEN", "GH_TOKEN", "GITHUB_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY"]

# Workflows the console may dispatch through `gh workflow run`. The NAMES are
# the allowlist — a decision, kept here. The inputs each accepts are a FACT,
# read from the workflow's own `workflow_dispatch.inputs` (dispatch_inputs()):
# a hand-kept copy of them had drifted and refused every input of
# issue-pipeline, token-rotation, reconcile-registry and update-submodules.
DISPATCH_WORKFLOWS = ("fanout", "fleet-pulse", "issue-pipeline", "token-rotation", "repo-evolution", "repo-scout",
                      "build-dash", "reconcile-registry", "update-submodules", "backlog-fanout")


# --------------------------------------------------------------------------- #
# yaml + time helpers
# --------------------------------------------------------------------------- #
def load_yaml(path: Path):
    if not path.exists():
        return None
    try:
        with path.open() as fh:
            return yaml.safe_load(fh)
    except (yaml.YAMLError, OSError):
        return None


def parse_stamp(value) -> dt.datetime | None:
    """Generators stamp '%Y-%m-%d %H:%M UTC'; tolerate ISO too."""
    if not isinstance(value, str):
        return None
    for fmt in ("%Y-%m-%d %H:%M UTC", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"):
        try:
            ts = dt.datetime.strptime(value, fmt)
        except ValueError:
            continue
        return ts if ts.tzinfo else ts.replace(tzinfo=dt.timezone.utc)
    return None


def source_meta(data, now: dt.datetime) -> dict:
    if not isinstance(data, dict):
        return {"present": False, "generated_at": None, "age_days": None}
    # Most signals stamp themselves at the top. The engagement ledger stamps
    # summary.updated_at instead (moved only when content moves), which used to
    # render as "no stamp" on the Overview's freshness tiles.
    summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
    stamp = data.get("generated_at") or data.get("generated") or data.get("updated_at") or summary.get("updated_at")
    ts = parse_stamp(stamp)
    return {
        "present": True,
        "generated_at": stamp,
        "age_days": round((now - ts).total_seconds() / 86400, 1) if ts else None,
    }


def run_quiet(argv: list[str], timeout: int = 15, cwd: Path = REPO_ROOT) -> tuple[int, str]:
    # Its own process group, killed whole on a timeout: `git status` forks one
    # child per submodule, and killing only the parent left those running and
    # then defunct under a container PID 1 that never reaps them.
    try:
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                cwd=str(cwd), start_new_session=True)
    except FileNotFoundError:
        return 127, ""
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, 9)
        except (AttributeError, OSError):
            proc.kill()
        proc.communicate()
        return 127, ""
    return proc.returncode, (out or "") + (err or "")


# --------------------------------------------------------------------------- #
# STATE — the committed fleet, as one document
# --------------------------------------------------------------------------- #
# Every /api/state asks for this, and a plain `git status` walks all ~40
# submodule working trees: 17s over the Docker Desktop bind mount, past
# run_quiet's timeout, so the chip read "clean tree" while each poll stacked
# another walk. Dirt INSIDE a submodule is not the hub's to commit (a moved
# pointer still shows), and concurrent polls share one answer for a few seconds.
GIT_INFO_TTL = 10.0
_GIT_INFO: dict = {}
_GIT_INFO_LOCK = threading.Lock()


def git_info() -> dict:
    with _GIT_INFO_LOCK:
        if _GIT_INFO and time.monotonic() - _GIT_INFO["at"] < GIT_INFO_TTL:
            return _GIT_INFO["doc"]
        rc, branch = run_quiet(["git", "rev-parse", "--abbrev-ref", "HEAD"])
        rc2, sha = run_quiet(["git", "rev-parse", "--short", "HEAD"])
        rc3, porcelain = run_quiet(["git", "status", "--porcelain", "--ignore-submodules=dirty"])
        dirty = [line[3:] for line in porcelain.splitlines() if line.strip()] if rc3 == 0 else []
        doc = {
            # a status that failed or timed out is "unknown", never "clean"
            "available": rc == 0 and rc3 == 0,
            "branch": branch.strip() if rc == 0 else None,
            "head": sha.strip() if rc2 == 0 else None,
            "dirty": dirty[:50],
            "dirty_count": len(dirty),
        }
        _GIT_INFO.update(at=time.monotonic(), doc=doc)
        return doc


def describe_cron(cron: str) -> str:
    """Reuse dash-gen's cron helpers when importable (same repo, same math)."""
    try:
        sys.path.insert(0, str(DASH_GEN_DIR))
        import harness_registry  # noqa: WPS433
        return harness_registry.describe_cron(cron)
    except Exception:
        return cron


# The scheduled loops the control plane runs, tied to fleet.yml `schedule:`
# keys and to the committed outputs each one refreshes (freshness = liveness).
LOOPS = [
    {"id": "fleet_pulse", "title": "Fleet pulse — the daily loop", "workflow": "fleet-pulse",
     "schedule_key": "fleet_pulse", "doc": "docs/DAILY-ANALYSIS.md",
     "outputs": ["actions_usage", "ai_usage", "fleet_triage", "harness_registry", "harness_health"],
     "local_ops": ["triage", "actions", "ai-usage", "harnesses", "harness", "remediate", "refine-plan"]},
    {"id": "issue_pipeline", "title": "Issue pipeline — intake → implement → complete", "workflow": "issue-pipeline",
     "schedule_key": "issue_pipeline", "doc": "docs/ISSUE-PIPELINE.md",
     "outputs": ["issue_pipeline"], "local_ops": ["issues"]},
    {"id": "token_rotation", "title": "Token rotation — credentials", "workflow": "token-rotation",
     "schedule_key": "rotate_tokens", "doc": "docs/TOKEN-ROTATION.md",
     "outputs": ["token_rotation"], "local_ops": ["secrets-audit", "secrets-plan", "ai-auth", "keys-status",
                                                   "secrets-push", "ai-auth-sync", "keys-rotate",
                                                   "secrets-rotate"]},
    {"id": "repo_evolution", "title": "Repo evolution — proactive improvement", "workflow": "repo-evolution",
     "schedule_key": "repo_evolution", "doc": "docs/EVOLUTION.md",
     "outputs": [], "local_ops": ["targets", "refine-plan"]},
    {"id": "repo_scout", "title": "Repo scout — daily issue proposals", "workflow": "repo-scout",
     "schedule_key": "repo_scout", "doc": "docs/SCOUT.md",
     "outputs": [], "local_ops": ["scout", "refine-plan"]},
    {"id": "harness_fanout", "title": "Harness fan-out — mass deploy / update", "workflow": "fanout",
     "schedule_key": None, "doc": "docs/HARNESS-OPS.md",
     "outputs": [], "local_ops": ["gaps", "deploy-gaps"]},
    {"id": "reconcile_registry", "title": "Registry reconciliation", "workflow": "reconcile-registry",
     "schedule_key": "reconcile_registry", "doc": "docs/DASH.md", "outputs": [], "local_ops": ["reconcile"]},
    {"id": "update_submodules", "title": "Submodule pointer bump", "workflow": "update-submodules",
     "schedule_key": "update_submodules", "doc": "docs/SUBMODULES.md", "outputs": [], "local_ops": []},
    {"id": "build_dash", "title": "Build & deploy the dash (Pages)", "workflow": "build-dash",
     "schedule_key": "build_dash", "doc": "docs/DASH.md", "outputs": [], "local_ops": []},
    {"id": "backlog_fanout", "title": "Backlog fan-out — pending items → fleet PRs (dry run by default)",
     "workflow": "backlog-fanout", "schedule_key": "backlog_fanout", "doc": "docs/BACKLOG-FANOUT.md",
     "outputs": [], "local_ops": []},
]


# The agent steps a loop runs that ALSO run on this machine: every step spec
# under tools/jev/steps/ with a `local:` block (the JEV loop runner, docs/JEV.md).
# Read through tools.jev itself — never a list kept here — and cached for a
# minute, because /api/state is polled. Data only: no path of this machine.
COST_LABEL = "API-equivalent (estimate)"
CLAUDE_BIN = "claude"
_AGENT_STEPS: dict = {"at": 0.0, "steps": [], "error": None}


def agent_steps() -> list[dict]:
    """Every loop agent step the local runner can run, as data for the Loops
    page, the TUI and the `loop-run` form: loop, step, model, turn cap, the
    call-site dollar cap (API-equivalent, an estimate) and the kill switch. A
    spec that fails to load leaves the list empty and the reason recorded, so
    the state document never falls over on one broken spec."""
    now = time.time()
    if now - _AGENT_STEPS["at"] < 60:
        return [dict(s) for s in _AGENT_STEPS["steps"]]
    steps: list[dict] = []
    error = None
    try:
        if str(REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(REPO_ROOT))
        from tools.jev import loop as jev_loop
        fleet = jev_loop.load_fleet()
        for s in jev_loop.local_specs(fleet=fleet):
            sw = s.local.switch
            try:
                spec_path = str(s.path.relative_to(REPO_ROOT))
            except ValueError:
                spec_path = s.path.name
            steps.append({
                "id": f"{s.loop}/{s.step}", "loop": s.loop, "step": s.step, "call_site": s.call_site,
                "spec": spec_path, "adapter": s.local.adapter, "model": s.resolved.model,
                "max_turns": s.resolved.max_turns, "cap_usd": s.resolved.max_budget_usd, "cost_label": COST_LABEL,
                "switch": None if sw is None else {"config": sw.config, "variable": sw.variable,
                                                   "default": sw.default,
                                                   "config_value": jev_loop.fleet_value(fleet, sw.config)},
                "publish_tier": jev_loop.publish_tier(s), "on_budget_hit": s.local.on_budget_hit,
                # whether the step's filer files under apply today (spec.PUBLISH_CAN_APPLY); False = the
                # page disables apply and the op refuses it, naming bamr87/bamr87#488
                "can_apply": s.local.publish is not None and s.local.publish.can_apply,
            })
    except Exception as exc:  # noqa: BLE001 — a broken spec is reported, never raised into /api/state
        error = f"{type(exc).__name__}: {exc}"
    _AGENT_STEPS.update(at=now, steps=steps, error=error)
    return [dict(s) for s in steps]


def loop_cards(fleet: dict, sources: dict) -> list[dict]:
    schedule = (fleet or {}).get("schedule") or {}
    steps = agent_steps()
    cards = []
    for loop in LOOPS:
        cron = schedule.get(loop["schedule_key"]) if loop["schedule_key"] else None
        ages = [sources[o]["age_days"] for o in loop["outputs"]
                if o in sources and sources[o].get("age_days") is not None]
        missing = [o for o in loop["outputs"] if not sources.get(o, {}).get("present")]
        cards.append({
            **loop,
            # the loop's agent steps that run locally (`loop-run`), by the workflow stem
            "agent_steps": [s for s in steps if s["loop"] == loop["workflow"]],
            "cron": cron,
            "cron_human": describe_cron(cron) if cron else "dispatch only",
            "freshest_output_days": min(ages) if ages else None,
            "stalest_output_days": max(ages) if ages else None,
            "missing_outputs": missing,
        })
    return cards


def load_state(now: dt.datetime | None = None) -> dict:
    now = now or dt.datetime.now(dt.timezone.utc)
    fleet = load_yaml(DATA / "fleet.yml") or {}
    registry = load_yaml(DATA / "projects.yml") or []
    raw = {name: load_yaml(DATA / fname) for name, fname in SOURCES.items()}
    sources = {name: source_meta(data, now) for name, data in raw.items()}

    hr = raw["harness_registry"] if isinstance(raw["harness_registry"], dict) else {}
    health = raw["harness_health"] if isinstance(raw["harness_health"], dict) else {}
    triage = raw["fleet_triage"] if isinstance(raw["fleet_triage"], dict) else {}
    pipeline = raw["issue_pipeline"] if isinstance(raw["issue_pipeline"], dict) else {}
    rotation = raw["token_rotation"] if isinstance(raw["token_rotation"], dict) else {}
    actions = raw["actions_usage"] if isinstance(raw["actions_usage"], dict) else {}
    ai = raw["ai_usage"] if isinstance(raw["ai_usage"], dict) else {}

    return {
        "generated_at": now.strftime("%Y-%m-%d %H:%M UTC"),
        "repo_root": str(REPO_ROOT),
        "sources": sources,
        "contract": {
            "harnesses": fleet.get("harnesses") or {},
            "schedule": fleet.get("schedule") or {},
            "remediation": {k: v for k, v in (fleet.get("remediation") or {}).items() if k != "severity"},
            "issue_pipeline_tiers": ((fleet.get("issue_pipeline") or {}).get("tiers")) or {},
            "evolution": {k: (fleet.get("evolution") or {}).get(k)
                          for k in ("max_targets", "max_parallel", "max_turns", "enabled")},
            "harness": fleet.get("harness") or {},
            "hub": fleet.get("hub") or {},
        },
        "tokens": [
            {"name": t.get("name"), "scope": t.get("scope"), "required": bool(t.get("required")),
             "deprecated": bool(t.get("deprecated")), "used_by": t.get("used_by") or []}
            for t in (fleet.get("tokens") or []) if isinstance(t, dict)
        ],
        "registry": {
            "count": len(registry),
            "projects": [
                {"name": p.get("name"), "category": p.get("category"), "status": p.get("status"),
                 "submodule": bool(p.get("submodule_path")), "repo_url": p.get("repo_url"),
                 "auto_evolve": bool(p.get("auto_evolve"))}
                for p in registry if isinstance(p, dict)
            ],
        },
        "harnesses": hr,
        "health": health,
        "triage": {
            "generated_at": triage.get("generated_at"),
            "totals": triage.get("totals") or {},
            "inbox": (triage.get("inbox") or [])[:20],
            "inbox_total": len(triage.get("inbox") or []),
        },
        "pipeline": {"generated_at": pipeline.get("generated_at"), "totals": pipeline.get("totals") or {}},
        "rotation": {
            "generated_at": rotation.get("generated_at"),
            "tokens": [
                {k: t.get(k) for k in ("name", "scope", "oldest_age_days", "max_age_days", "counts", "attention")}
                for t in (rotation.get("tokens") or []) if isinstance(t, dict)
            ],
        },
        "usage": {
            "actions": {k: actions.get(k) for k in ("generated_at", "window_days", "totals", "by_day")},
            "ai": {k: ai.get(k) for k in ("generated", "window_days", "totals", "by_day")},
        },
        "subscription": _subscription_block(fleet, ai, now),
        "loops": loop_cards(fleet, sources),
        "git": git_info(),
    }


def _subscription_block(fleet: dict, ai: dict, now: dt.datetime) -> dict:
    """The CI ledger's API-equivalent dollars against the prorated Claude subscription
    (tools/console/subscription.py). Never added to the subscription fee."""
    budget = ((fleet.get("harnesses") or {}).get("budget")) or {}
    totals = ai.get("totals") or {}
    days = ai.get("window_days")
    windows = {}
    if isinstance(days, (int, float)) and days > 0:
        windows["ci_window"] = (totals.get("ci_accounted_usd"), float(days), f"CI ledger ({days}d, dash ai)")
    return subscription.model(budget, now, windows=windows)


# --------------------------------------------------------------------------- #
# CAPABILITIES — what this console can reach (names and booleans only)
# --------------------------------------------------------------------------- #
def _has_module(name: str) -> bool:
    """Is this optional dependency importable?

    find_spec, not a bare import: `import ruamel.yaml` would rebind the local
    name to the module object and leak it into the JSON response. But find_spec
    on a DOTTED name imports the parent first and RAISES ModuleNotFoundError
    when the parent is absent — the exact case this probe exists to report — so
    the miss has to be caught rather than compared against None.
    """
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, AttributeError, ValueError):
        return False


def capabilities() -> dict:
    tools = {name: shutil.which(name) is not None
             for name in ("git", "gh", "python3", "docker", "actionlint", "shellcheck", "bundle")}
    gh_auth = None
    if tools["gh"]:
        rc, _ = run_quiet(["gh", "auth", "status"], timeout=20)
        gh_auth = rc == 0
    has_ruamel = _has_module("ruamel.yaml")
    has_otel = all(_has_module(m)
                   for m in ("opentelemetry.sdk", "opentelemetry.exporter.otlp.proto.http"))
    return {
        "tools": tools,
        "gh_authenticated": gh_auth,
        "env_tokens": {name: bool(os.environ.get(name)) for name in CREDENTIALS},
        "contract_editing": has_ruamel,
        "config_editing": has_ruamel,
        "auth_writes": AUTH_WRITES,
        "console_token_required": bool(os.environ.get("DASH_CONSOLE_TOKEN")),
        "python": sys.version.split()[0],
        "job_dir": str(JOB_DIR),
        "lake_dir": str(LAKE_DIR),
        "lake_present": (LAKE_DIR / "fleet.sqlite").exists(),
        "otel_exporter": has_otel,
        "phoenix": {"collector": PHOENIX_COLLECTOR, "ui": PHOENIX_UI},
        # All three local planes in one key, so the Observe tab can render a
        # pane per plane without three round trips. Kept BESIDE the legacy
        # `phoenix` key rather than replacing it: anything already reading that
        # key keeps working, which is cheaper than finding every reader.
        "observability": observability_planes(probe=False),
    }


# --------------------------------------------------------------------------- #
# LAKE — the local data lake + trace export, read through dash-gen's module
# --------------------------------------------------------------------------- #
def _lake_module():
    sys.path.insert(0, str(DASH_GEN_DIR))
    import fleet_lake  # noqa: WPS433
    return fleet_lake


def lake_status(probe: bool = True) -> dict:
    """The /api/lake document: what the lake holds and whether Phoenix answers.
    Degrades to a 'not present' document rather than a 500."""
    try:
        return _lake_module().status_dict(LAKE_DIR, probe=probe, collector=PHOENIX_COLLECTOR, ui=PHOENIX_UI)
    except Exception as exc:  # the module is optional at import time
        return {"present": False, "lake_dir": str(LAKE_DIR), "error": f"{exc.__class__.__name__}: {exc}",
                "tables": {}, "repos": [], "agent_runs": {"count": 0}, "exports": {"count": 0},
                "phoenix": {"collector": PHOENIX_COLLECTOR, "ui": PHOENIX_UI, "reachable": None}}


# --------------------------------------------------------------------------- #
# OBSERVABILITY — the three local planes, read through dash-gen's module
# --------------------------------------------------------------------------- #
def _observe_module():
    sys.path.insert(0, str(DASH_GEN_DIR))
    import fleet_observe  # noqa: WPS433
    return fleet_observe


def _index_module():
    sys.path.insert(0, str(DASH_GEN_DIR))
    import fleet_index  # noqa: WPS433
    return fleet_index


def index_query(kind: str, query: str) -> dict:
    """Search or harmonize the code index. Never raises: a down store is a document."""
    query = (query or "").strip()
    if not query:
        return {"present": False, "error": "query is empty", "query": ""}
    if len(query) > 500:
        return {"present": False, "error": "query is longer than 500 characters", "query": query[:80]}
    try:
        mod = _index_module()
        fn = mod.harmonize if kind == "harmonize" else mod.search
        return fn(query)
    except Exception as exc:
        return {"present": False, "error": f"{exc.__class__.__name__}: {exc}", "query": query}


def index_coverage() -> dict:
    try:
        return _index_module().coverage()
    except Exception as exc:
        return {"present": False, "error": f"{exc.__class__.__name__}: {exc}", "projects": [], "missing": [],
                "blind_spots": [], "hub_chunks": 0}


def observability_planes(probe: bool = True) -> dict:
    """Per-plane identity and (optionally) reachability.

    Never raises. A plane that is down has to render as a pane with a Start
    button, not as a 500 that takes the whole tab with it — the same
    degrade-don't-explode contract lake_status() keeps.

    probe=False skips the network entirely, which is what /api/capabilities
    wants: that document is fetched on every page load.
    """
    try:
        fo = _observe_module()
        contract = fo.load_contract()
    except Exception as exc:
        return {"present": False, "error": f"{exc.__class__.__name__}: {exc}",
                "logs": {}, "metrics": {}, "traces": {}, "indexing": {}, "portal": {}}
    if probe:
        planes = fo.plane_status(contract)
    else:
        logs, metrics, traces = contract["logs"], contract["metrics"], contract["traces"]
        indexing = contract.get("indexing") or {}
        planes = {
            "logs": {"engine": logs.get("engine"), "url": logs.get("kibana"),
                     "elasticsearch": logs.get("elasticsearch"), "reachable": None},
            "metrics": {"engine": metrics.get("engine"), "url": metrics.get("grafana"),
                        "reachable": None, "datasources": metrics.get("datasources") or []},
            "traces": {"engine": traces.get("engine"), "url": traces.get("endpoint"),
                       "reachable": None},
            "indexing": {"engine": indexing.get("engine"), "url": indexing.get("qdrant"),
                         "embedder": indexing.get("embedder"), "model": indexing.get("model"),
                         "reachable": None, "embedder_reachable": None},
            "telemetry": {"engine": "otel-collector", "url": fo.claude_contract(contract)["endpoint"],
                          "prometheus": metrics.get("prometheus"), "reachable": None,
                          "prometheus_reachable": None},
        }
    planes["present"] = True
    planes["portal"] = contract.get("portal") or {}
    return planes


def observe_status() -> dict:
    """The /api/observability document: planes, dataset sizes, ship lag.

    This is the probing one — it is fetched when the Observe tab opens, not on
    every page load.
    """
    try:
        fo = _observe_module()
        contract = fo.load_contract()
        planes = fo.plane_status(contract)
        doc = {
            "present": True,
            "planes": planes,
            "portal": contract.get("portal") or {},
            "disk_budget_gb": contract["logs"]["disk_budget_gb"],
            "retention_days": contract["logs"]["retention_days"],
            "datasets": fo.dataset_stats(contract) if planes["logs"]["reachable"] else [],
            "embeds": observe_embeds(contract),
        }
        doc["bytes_total"] = sum(d.get("bytes") or 0 for d in doc["datasets"])
        doc["over_budget"] = doc["bytes_total"] > doc["disk_budget_gb"] * 1024 ** 3
        try:
            conn = _lake_module().connect(LAKE_DIR, create=False)
            row = conn.execute("SELECT COUNT(*) c, MAX(shipped_at) last FROM shipments "
                               "WHERE sink = ?", (fo.SINK,)).fetchone()
            doc["shipments"] = {"count": row[0], "last": row[1]}
            # Ship replays the lake, so an empty lake ships nothing — and a
            # zero ledger beside indexed documents means they came from an
            # earlier lake, not that shipping is broken.
            doc["lake_runs"] = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        except Exception:
            doc["shipments"] = {"count": 0, "last": None}
            doc["lake_runs"] = None
        return doc
    except Exception as exc:
        return {"present": False, "error": f"{exc.__class__.__name__}: {exc}",
                "planes": {}, "datasets": [], "embeds": {}, "shipments": {"count": 0, "last": None},
                "lake_runs": None}


def observe_embeds(contract: dict) -> dict:
    """The iframe URLs for the Observe tab.

    Built here rather than in the browser so the PINNED ids stay in one place —
    the contract — instead of being half in fleet.yml and half in a template
    string in index.html, which is how an embed ends up pointing at a dashboard
    that was renamed six months ago.
    """
    portal = contract.get("portal") or {}
    dash = portal.get("dashboards") or {}
    kibana = (contract.get("logs") or {}).get("kibana") or ""
    grafana = (contract.get("metrics") or {}).get("grafana") or ""
    logs_id = (dash.get("logs") or {}).get("id")
    metrics_uid = (dash.get("metrics") or {}).get("uid")
    out = {"enabled": bool(portal.get("embed"))}
    if kibana and logs_id:
        # embed=true strips Kibana's own chrome; the time range comes from the
        # dashboard's saved timeRestore rather than a _g we would have to keep
        # in step with it.
        out["logs"] = f"{kibana}/app/dashboards#/view/{logs_id}?embed=true&show-top-menu=false"
    if grafana and metrics_uid:
        out["metrics"] = f"{grafana}/d/{metrics_uid}/{metrics_uid}?kiosk&theme=dark"
        out["metrics_panel"] = f"{grafana}/d-solo/{metrics_uid}/{metrics_uid}?panelId=%s&theme=dark"
    out["traces"] = (contract.get("traces") or {}).get("endpoint") or ""
    return out


def frame_src() -> list[str]:
    """The CSP frame-src allowlist, stated once in _data/fleet.yml.

    A missing origin here is not an error anyone sees: the browser refuses the
    frame and writes one line to a console nobody has open.
    """
    try:
        contract = _observe_module().load_contract()
    except Exception:
        return []
    portal = contract.get("portal") or {}
    urls = list(portal.get("frame_src") or [])
    for url in ((contract.get("logs") or {}).get("kibana"),
                (contract.get("metrics") or {}).get("grafana"),
                (contract.get("traces") or {}).get("endpoint")):
        if url and url not in urls:
            urls.append(url)
    return urls


def lake_runs(limit: int = 50) -> list[dict]:
    try:
        return _lake_module().recent_runs(LAKE_DIR, limit=limit)
    except Exception:
        return []


def lake_lines() -> list[dict]:
    try:
        return _lake_module().lines(LAKE_DIR)
    except Exception:
        return []


def lake_review(days: int = 30, repo: str | None = None, limit: int = 10) -> dict:
    """The /api/lake/review document: local Claude Code sessions and CI agent
    runs unified — cost, turns, tools, failures, and the ranked findings."""
    try:
        return _lake_module().review(LAKE_DIR, days=days, repo=repo, limit=limit)
    except Exception as exc:
        return {"present": False, "error": f"{exc.__class__.__name__}: {exc}",
                "local": {}, "ci": {}, "totals": {}, "findings": []}


# --------------------------------------------------------------------------- #
# PROJECT — one registry project, every signal the console holds about it
# --------------------------------------------------------------------------- #
def project_detail(name: str) -> dict:
    """The drill-down document for one registry project: its registry entry,
    its harness deployment and crons, the attention findings that name it, and
    its runs + workflows in the local lake. Every piece already exists in a
    committed file or the lake; this only joins them on the project name, so
    the page never has to fetch five whole documents to show one repo.

    Raises KeyError for a name the registry does not carry.
    """
    if not NAME_RX.match(name or ""):
        raise ValueError("invalid project name")
    registry = load_yaml(DATA / "projects.yml") or []
    entry = next((p for p in registry if isinstance(p, dict) and p.get("name") == name), None)
    if entry is None:
        raise KeyError(name)
    hr = load_yaml(DATA / SOURCES["harness_registry"])
    hr = hr if isinstance(hr, dict) else {}
    # A run belongs to the project when its owner/name ends in /<name> — the
    # lake keys on GitHub's nwo, the registry on the bare name.
    owned = (lambda nwo: str(nwo or "").lower().endswith("/" + name.lower()))
    return {
        "name": name,
        "registry": {k: v for k, v in entry.items() if not str(k).startswith("_")},
        "harness": next((r for r in hr.get("repos") or [] if r.get("repo") == name), None),
        "schedule": [s for s in hr.get("schedule") or [] if s.get("repo") == name],
        "attention": [a for a in hr.get("attention") or [] if a.get("repo") == name],
        "lake_runs": [r for r in lake_runs(500) if owned(r.get("nwo"))][:60],
        "lake_lines": [w for w in lake_lines() if owned(w.get("nwo"))],
    }


README_NAMES = ("README.md", "readme.md", "README.markdown", "README.rst", "README")
README_CAP = 200_000  # characters; a README longer than this is cut and says so


def project_readme(name: str) -> dict:
    """A registry project's README, read from its submodule checkout on this
    machine — the first page of the repo app the console generates for a repo
    that has no frontend of its own (ADR 0005, phase F1).

    Local only. The public snapshot never calls this: a private repo's README
    checked out on the build machine must not reach the public site. The path
    comes from the registry's `submodule_path`, never from the request, and
    must sit under projects/.

    Raises KeyError for a name the registry does not carry.
    """
    if not NAME_RX.match(name or ""):
        raise ValueError("invalid project name")
    registry = load_yaml(DATA / "projects.yml") or []
    entry = next((p for p in registry if isinstance(p, dict) and p.get("name") == name), None)
    if entry is None:
        raise KeyError(name)
    sub = entry.get("submodule_path")
    if not sub:
        return {"present": False, "reason": "not a submodule of the hub"}
    projects = (REPO_ROOT / "projects").resolve()
    base = (REPO_ROOT / str(sub)).resolve()
    if projects != base.parent:
        return {"present": False, "reason": "its registry path is not directly under projects/"}
    for candidate in README_NAMES:
        path = base / candidate
        try:
            if not path.is_file() or path.is_symlink():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        return {"present": True, "path": f"{sub}/{candidate}", "markdown": text[:README_CAP],
                "truncated": len(text) > README_CAP}
    checked_out = base.is_dir() and any(base.iterdir())
    return {"present": False, "reason": "it has no README file" if checked_out else "not checked out on this machine"}


# --------------------------------------------------------------------------- #
# CONTENT — the content atlas + the editorial plan (docs/CONTENT-ATLAS.md)
# --------------------------------------------------------------------------- #
EDITORIAL = Path(os.environ.get("DASH_EDITORIAL_PLAN") or (DATA / "editorial.yml"))
CONTENT_VIEWS = ("all", "stale", "issues", "thin", "recent", "drafts", "unmapped")


def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _content_module():
    sys.path.insert(0, str(DASH_GEN_DIR))
    import content_atlas  # noqa: WPS433
    return content_atlas


def _content_inputs():
    ca = _content_module()
    return ca, ca.load_contract(DATA / "fleet.yml", DATA / "projects.yml"), ca.load_plan(EDITORIAL)


def content_report(site: str | None = None) -> dict:
    """The /api/content document: every declared site analyzed from the lake,
    plus the editorial plan's view of it. Degrades to a 'not present' document
    (with the declared sites, so the tab can offer the sync) rather than a 500."""
    try:
        ca, contract, plan = _content_inputs()
        declared = [{"name": s["name"], "repo": s.get("repo"), "live_url": s.get("live_url")}
                    for s in contract["sites"]]
    except Exception as exc:
        return {"present": False, "error": f"{exc.__class__.__name__}: {exc}", "declared": [], "sites": [],
                "overlap": [], "unsynced": [], "fleet": {}}
    if site is not None and site not in {s["name"] for s in declared}:
        raise ValueError(f"unknown site '{site}'")
    try:
        try:
            conn = ca.connect(LAKE_DIR, create=False)
        except FileNotFoundError:
            return {"present": False, "declared": declared, "sites": [], "overlap": [],
                    "unsynced": [s["name"] for s in declared], "fleet": {}}
        doc = ca.report(conn, contract, plan, site=site)
        doc.update(present=True, declared=declared, plan_path=_rel(EDITORIAL))
        return doc
    except Exception as exc:
        return {"present": False, "error": f"{exc.__class__.__name__}: {exc}", "declared": [], "sites": [],
                "overlap": [], "unsynced": [], "fleet": {}}


def content_documents(site: str, view: str = "all", q: str = "", limit: int = 200) -> list[dict]:
    if not NAME_RX.match(site or ""):
        raise ValueError("site must be a plain name")
    if view not in CONTENT_VIEWS and not re.match(r"^pillar:[a-z0-9][a-z0-9._-]{0,63}$", view or ""):
        raise ValueError(f"view must be one of {CONTENT_VIEWS} or pillar:<id>")
    ca, contract, plan = _content_inputs()
    try:
        conn = ca.connect(LAKE_DIR, create=False)
    except FileNotFoundError:
        return []
    return ca.documents(conn, site, view=view, q=str(q or "")[:120], limit=max(1, min(int(limit), 1000)),
                        contract=contract, plan=plan)


def _plan_diff() -> str:
    rc, diff = run_quiet(["git", "diff", "--no-color", "--", str(EDITORIAL)])
    if rc == 0 and not diff:
        # an untracked plan has no diff against HEAD; say so rather than show nothing
        rc2, out = run_quiet(["git", "ls-files", "--error-unmatch", str(EDITORIAL)])
        if rc2 != 0:
            return f"(new file: {_rel(EDITORIAL)} — not yet tracked)"
    return diff if rc == 0 else ""


def editorial_decide(site: str, action: str, key: str, fields: dict | None = None) -> dict:
    """Approve / reject a suggestion, add a directive, or move one — written to
    _data/editorial.yml in the working tree (comments preserved). The commit is
    the approval of record, and it stays with the human, as everywhere else."""
    ca, contract, plan = _content_inputs()
    suggestion = None
    if action in ("approve", "reject"):
        doc = content_report(site)
        a = (doc.get("sites") or [None])[0]
        suggestion = next((s for s in (a or {}).get("suggestions") or [] if s["key"] == key), None)
    result = ca.decide(EDITORIAL, site, action, key, contract, suggestion=suggestion, fields=fields or {})
    result["diff"] = _plan_diff()
    return result


def editorial_update(site: str, fields: dict) -> dict:
    ca, contract, _plan = _content_inputs()
    result = ca.update_site(EDITORIAL, site, contract, fields or {})
    result["diff"] = _plan_diff()
    return result


def content_brief(site: str) -> dict:
    doc = content_report(site)
    if not doc.get("sites"):
        raise ValueError(f"'{site}' is not in the atlas yet — run 'Content: sync' first")
    return {"site": site, "markdown": _content_module().render_brief(doc["sites"][0])}


# --------------------------------------------------------------------------- #
# WORKFLOWS — the hub's own GitHub Actions as one model (dash-gen
# workflow_atlas.py; docs/WORKFLOW-ATLAS.md): structure + lint from the
# checkout (also in the public snapshot), run health from the lake (local).
# --------------------------------------------------------------------------- #
def _atlas_module():
    sys.path.insert(0, str(DASH_GEN_DIR))
    import workflow_atlas  # noqa: WPS433
    return workflow_atlas


def _default_branch_text(rel: str) -> str | None:
    """A file as the hub's default branch holds it — what `gh workflow run`
    runs — from the last fetch; None when git cannot say."""
    branch = str(((load_yaml(DATA / "fleet.yml") or {}).get("hub") or {}).get("default_branch") or "main")
    rc, out = run_quiet(["git", "show", f"origin/{branch}:{rel}"], timeout=10)
    return out if rc == 0 and out.strip() else None


def dispatch_inputs() -> dict[str, list[dict]]:
    """Each allowlisted workflow → the inputs its file declares (name, type,
    default, options), so the console's form and its validation follow the
    file. Read from the default branch, which is the file GitHub runs, else
    from the working tree; a file that cannot be read offers no inputs rather
    than breaking every other dispatch."""
    atlas = _atlas_module()
    out: dict[str, list[dict]] = {}
    for wf in DISPATCH_WORKFLOWS:
        path = REPO_ROOT / ".github" / "workflows" / f"{wf}.yml"
        text = _default_branch_text(_rel(path)) or (path.read_text(encoding="utf-8") if path.is_file() else None)
        if text is None:
            continue
        try:
            out[wf] = atlas.parse_workflow(_rel(path), text)["dispatch_inputs"]
        except Exception:  # one unreadable file must not take dispatch down for the other eight
            out[wf] = []
    return out


def dispatchable() -> dict[str, list[str]]:
    return {wf: sorted(i["name"] for i in inputs) for wf, inputs in dispatch_inputs().items()}


def workflow_atlas() -> dict:
    """The /api/workflows document: the atlas, joined with what only the
    console knows — which loop a workflow is, and whether it may dispatch it."""
    doc = _atlas_module().scan(REPO_ROOT)
    loops = {loop["workflow"]: loop["id"] for loop in LOOPS}
    for wf in doc["workflows"]:
        wf["loop"] = loops.get(wf["id"])
        wf["dispatchable"] = wf["id"] in DISPATCH_WORKFLOWS and "workflow_dispatch" in wf["triggers"]
    doc["kinds"] = _atlas_module().KINDS
    return doc


def workflow_health(days: int = 30) -> dict:
    """The /api/workflows/health document: the lake's runs of the hub per
    workflow, with each failure's cause and class. Local only."""
    atlas = _atlas_module()
    hub = str(((load_yaml(DATA / "fleet.yml") or {}).get("hub") or {}).get("repo") or atlas.HUB_DEFAULT)
    try:
        return atlas.lake_health(LAKE_DIR, hub, days, REPO_ROOT)
    except Exception as exc:
        return {"present": False, "error": f"{exc.__class__.__name__}: {exc}", "nwo": hub, "days": days,
                "workflows": [], "totals": {}, "classes": {}, "ghosts": [], "class_hints": atlas.CLASSES}


def workflow_lint(text: str, wid: str = "draft") -> dict:
    """Lint a draft workflow against the hub's fleet.yml (nothing is written).
    `wid` is the file stem it would have — its schedule key and call sites."""
    atlas = _atlas_module()
    if len(text) > 200_000:
        raise ValueError("a workflow draft is limited to 200 KB")
    if not atlas.ID_RX.match(wid or ""):
        raise ValueError("id must be lowercase letters, digits and dashes, starting with a letter")
    return atlas.lint_text(text, load_yaml(DATA / "fleet.yml") or {}, f".github/workflows/{wid}.yml")


def workflow_scaffold(params: dict) -> dict:
    """Preview a new workflow (the designer); `workflow-new` writes it."""
    atlas = _atlas_module()
    return atlas.scaffold(str(params.get("kind") or ""), str(params.get("id") or "").strip(),
                          str(params.get("name") or "").strip() or None, str(params.get("cron") or "").strip() or None,
                          str(params.get("purpose") or ""), REPO_ROOT)


# --------------------------------------------------------------------------- #
# WORK — the board of every open item and the order the loops take them in
# (dash-gen's work_board.py + work_queue.py; docs/WORK-BOARD.md)
# --------------------------------------------------------------------------- #
WORK_QUEUE = Path(os.environ.get("DASH_WORK_QUEUE") or (DATA / "work_queue.yml"))
ROADMAP = DATA / "roadmap.yml"
# Label moves this process made, newest per issue, overlaid on the board until
# the issue-pipeline snapshot is newer than the move — otherwise a card would
# snap back to its old lane the moment the move succeeds.
WORK_MOVES: dict[str, dict] = {}
_WORK_LOCK = threading.Lock()


def _work_module():
    sys.path.insert(0, str(DASH_GEN_DIR))
    import work_board  # noqa: WPS433
    return work_board


def work_inputs(local: bool = True) -> dict:
    return _work_module().load_inputs(REPO_ROOT, local=local, queue_path=WORK_QUEUE, roadmap_path=ROADMAP,
                                      moves=dict(WORK_MOVES))


def work_board(plan: dict | None = None, local: bool = True) -> dict:
    """The /api/work document; with a plan, the board as it would be (nothing written)."""
    doc = _work_module().build(work_inputs(local), plan)
    doc["queue_path"] = _rel(WORK_QUEUE)
    return doc


def work_item(key: str) -> dict:
    return _work_module().item_detail(work_inputs(), key)


def _work_diff() -> str:
    paths = [str(WORK_QUEUE), str(ROADMAP)]
    rc, diff = run_quiet(["git", "diff", "--no-color", "--", *paths])
    out = diff if rc == 0 else ""
    rc2, _ = run_quiet(["git", "ls-files", "--error-unmatch", str(WORK_QUEUE)])
    if rc2 != 0 and WORK_QUEUE.exists():
        out = f"(new file: {_rel(WORK_QUEUE)} — not yet tracked)\n" + WORK_QUEUE.read_text(encoding="utf-8") + out
    return out


def work_apply(plan: dict, confirm: bool = False, label_writer=None) -> dict:
    """Apply a board plan: issue label moves on GitHub (each through
    `label_writer`, i.e. github_link.act — fleet-scoped, logged), then the
    roadmap.yml edits and the work_queue.yml entries in the working tree.

    Nothing is committed: the diff comes back for the human to review and
    commit, as with every other console write. A plan that moves labels needs
    confirm=true. Keys for items that no longer exist are pruned."""
    wb = _work_module()
    with _WORK_LOCK:
        inp = work_inputs()
        board = wb.build(inp)
        resolved = wb.resolve_plan(board["items"], plan or {}, inp["queue"], inp["cfg"]["labels"]["state"])
        if not resolved["changes"]:
            raise ValueError("the plan changes nothing")
        if resolved["labels"] and not confirm:
            raise PermissionError("moving an issue changes its labels on GitHub — it needs confirm=true")
        if resolved["labels"] and label_writer is None:
            raise RuntimeError("no GitHub writer is available to this console")

        results: list[dict] = []
        for mv in resolved["labels"]:
            what = next(c["what"] for c in resolved["changes"] if c["key"] == mv["key"])
            try:
                entry = label_writer(mv["nwo"], mv["number"], mv["add"], mv["remove"])
                WORK_MOVES[mv["key"]] = {"lane": mv["to"], "at": entry.get("at")}
                results.append({"key": mv["key"], "target": "github", "what": what, "ok": True, "error": None})
            except Exception as exc:  # report it; the file half of the plan still applies
                results.append({"key": mv["key"], "target": "github", "what": what, "ok": False,
                                "error": _scrub(str(exc))})

        if resolved["roadmap"]:
            text = ROADMAP.read_text(encoding="utf-8")
            for ff, fields in resolved["roadmap"].items():
                text = wb.edit_roadmap(text, ff, status=fields.get("status"), priority=fields.get("priority"),
                                       reason=fields.get("reason"))
            ROADMAP.write_text(text, encoding="utf-8")
        q = resolved["queue"]
        stale = set(board["sources"]["work_queue"]["stale_keys"])
        pruned: list[str] = []
        if q["pins"] or q["unpin"] or q["priority"] or q["notes"] or stale:
            new = wb.preview_queue(inp["queue"], resolved)
            keys = {*new["order"], *new["priority"], *new["notes"]}
            new, pruned = wb.wq.prune(new, keys - stale)
            wb.wq.save(WORK_QUEUE, {**new, "updated_at": dt.date.today().isoformat()})
        for c in resolved["changes"]:
            if c["target"] != "github":
                results.append({**c, "ok": True, "error": None})
    return {"results": results, "pruned": pruned, "diff": _work_diff(), "board": work_board()}


def _content_sync(params: dict) -> list[str]:
    argv = [DASH_GEN, "content", "sync"]
    if str(params.get("target") or "").strip():
        argv += ["--site", _name(params)]
    if _flag(params, "no_fetch"):
        argv.append("--no-fetch")
    return argv


def _content_file(params: dict) -> list[str]:
    argv = [DASH_GEN, "content", "file", "--site", _name(params)]
    if _flag(params, "apply"):
        argv.append("--apply")
    return argv


# --------------------------------------------------------------------------- #
# OPS — the allowlist
# --------------------------------------------------------------------------- #
def _flag(params: dict, key: str) -> bool:
    v = params.get(key)
    return v is True or (isinstance(v, str) and v.lower() in ("1", "true", "yes", "on"))


def _days(params: dict) -> str:
    try:
        n = int(params.get("days", 14))
    except (TypeError, ValueError):
        raise ValueError("days must be an integer")
    if not 1 <= n <= 90:
        raise ValueError("days must be between 1 and 90")
    return str(n)


def _name(params: dict, key: str = "target") -> str:
    v = str(params.get(key) or "").strip()
    if not NAME_RX.match(v):
        raise ValueError(f"{key} must match {NAME_RX.pattern}")
    return v


def stack_projects() -> list[str]:
    """Projects with a compose stack of their own: the ones `tools/dash dev up`
    can start. Never the hub: `dash dev up hub` starts a second `fleet-hub`
    project that collides with the running core on its own ports."""
    ports = load_yaml(DATA / "ports.yml")
    projects = (ports or {}).get("projects") if isinstance(ports, dict) else None
    return sorted(k for k, v in (projects or {}).items() if isinstance(v, dict) and v.get("host") == "compose")


def _stack(params: dict) -> str:
    """The `target` of a dev-stack operation: one project from the port registry."""
    name = _name(params)
    if name not in stack_projects():
        raise ValueError(f"'{name}' has no compose stack in _data/ports.yml (known: {', '.join(stack_projects())})")
    return name


def _stack_exclusive(params: dict) -> str:
    """One start or stop per project at a time; different projects run side by side."""
    return f"stack:{params.get('target')}"


def _deploy(params: dict, target_mode: str) -> list[str]:
    argv = [DASH, "harnesses", "deploy"]
    argv += ["--gaps"] if target_mode == "gaps" else ["--target", _name(params)]
    artifacts = str(params.get("artifacts") or "").strip()
    if artifacts:
        if not re.match(r"^[a-z-]+(,[a-z-]+)*$", artifacts):
            raise ValueError("artifacts must be a comma-separated list of kit artifact names")
        argv += ["--artifacts", artifacts]
    if _flag(params, "upgrade"):
        argv.append("--upgrade")
    if _flag(params, "apply"):
        argv.append("--apply")
    return argv


def _dispatch(params: dict) -> list[str]:
    wf = str(params.get("workflow") or "").strip()
    inputs = dispatch_inputs()
    if wf not in inputs:
        raise ValueError(f"workflow must be one of {sorted(inputs)}")
    spec = {i["name"]: i for i in inputs[wf]}
    argv = ["gh", "workflow", "run", f"{wf}.yml"]
    fields = params.get("fields") or {}
    if not isinstance(fields, dict):
        raise ValueError("fields must be an object")
    for k, v in fields.items():
        if k not in spec:
            raise ValueError(f"{wf} does not accept input '{k}'")
        v = "true" if v is True else "false" if v is False else str(v)
        kind, options = spec[k]["type"], spec[k]["options"]
        if kind == "boolean" and v not in ("true", "false"):
            raise ValueError(f"input '{k}' is a boolean: true or false")
        if kind == "choice" and options and v not in options:
            raise ValueError(f"input '{k}' must be one of {options}")
        if kind == "number" and not re.fullmatch(r"-?\d+(\.\d+)?", v):
            raise ValueError(f"input '{k}' is a number")
        if not FIELD_RX.fullmatch(v):
            raise ValueError(f"input '{k}' has characters the console refuses to pass")
        argv += ["-f", f"{k}={v}"]
    return argv


def _workflow_new(params: dict) -> list[str]:
    atlas = _atlas_module()
    kind = _choice(params, "kind", tuple(atlas.KINDS), "")
    wid = str(params.get("id") or "").strip()
    if not atlas.ID_RX.match(wid):
        raise ValueError("id must be lowercase letters, digits and dashes, starting with a letter")
    argv = [DASH_GEN, "workflows", "new", "--kind", kind, "--id", wid, "--write"]
    name = str(params.get("name") or "").strip()
    if name:
        if not atlas.NAME_RX.match(name):
            raise ValueError("name must be one line without quotes, backticks, `$` or backslashes")
        argv += ["--name", name]
    cron = str(params.get("cron") or "").strip()
    if cron:
        if not CRON_RX.match(cron):
            raise ValueError("cron must be a 5-field cron expression")
        argv += ["--cron", cron]
    purpose = str(params.get("purpose") or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if purpose:
        if len(purpose) > 2000 or re.search(r"[\x00-\x08\x0b-\x1f\x7f]", purpose):
            raise ValueError("purpose is plain text, at most 2000 characters")
        argv += ["--purpose", purpose]
    return argv


#: a loop run id as the engine writes it (`<UTC stamp>-<loop>-<step>-<hex>`)
RUN_ID_RX = re.compile(r"[0-9]{8}T[0-9]{6}Z-[a-z0-9][a-z0-9-]{0,80}")
#: a run's item KEY as the engine's previews are keyed: `owner/repo`, or
#: `owner/repo:<path>` for the doctor's per-workflow items — never a bare name
ITEM_KEY_RX = re.compile(r"[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}(?::[A-Za-z0-9_./-]{1,200})?")


def _loop_run(params: dict) -> list[str]:
    """`tools/dash loop run <loop> [step] --target <name> --json [--rehearse] [--apply]`,
    or with `run_id`: `tools/dash loop publish <run_id> [--item <key>] --json [--apply]`.

    The loop and the step must name an agent step with a `local:` spec (what
    `agent_steps()` lists), the target is a registry name or `all` (today's
    sample). A live attempt spends (one capped attempt per item, held to
    `budget.loops`), so it is confirm-gated; `rehearse` stops before the model
    call at $0 and is not. `apply` files the reviewed preview through the
    engine's own publish gate — the OPS remote-write path, constitution § 11.8
    (amendment `ops-remote-write-path`): it is a GitHub write at tier high,
    refused without `confirm` by `JobManager.submit`, and the engine refuses
    it with `--scheduled` (which this op never passes), with `--rehearse`, and
    with a dirty engine. `run_id` publishes an earlier run's reviewed preview
    (`loop publish`); without `apply` that is the read-only "matches / differs"
    check.
    """
    steps = agent_steps()
    loop = str(params.get("loop") or "").strip()
    known = sorted({s["loop"] for s in steps})
    if loop not in known:
        raise ValueError(f"loop must be one of {known} (a loop whose agent step has a local: spec)")
    mine = [s["step"] for s in steps if s["loop"] == loop]
    step = str(params.get("step") or "").strip()
    if step and step not in mine:
        raise ValueError(f"{loop} has no local agent step {step!r}; its steps: {mine}")
    if not step and len(mine) != 1:
        raise ValueError(f"{loop} has {len(mine)} local agent steps — name one of {mine}")
    apply = _flag(params, "apply")
    if apply and _flag(params, "rehearse"):
        raise ValueError("apply with rehearse is refused: a rehearsal files nothing (the engine refuses it too)")
    if "scheduled" in params:
        raise ValueError("scheduled is never a console parameter: an unattended filing is refused by the engine "
                         "(--apply with --scheduled) until § 13.7 earned autonomy")
    chosen = next((s for s in steps if s["loop"] == loop and s["step"] == (step or s["step"])), None)
    if apply and chosen is not None and not chosen.get("can_apply", False):
        raise ValueError(f"apply is refused for {loop}/{chosen['step']}: its filer cannot file yet "
                         "(bamr87/bamr87#488's publish step) — run the dry run and review .fleet/runs/<run_id>/")
    target = str(params.get("target") or "all").strip()
    if target != "all" and not NAME_RX.match(target):
        raise ValueError(f"target must be 'all' or match {NAME_RX.pattern}")
    run_id = str(params.get("run_id") or "").strip()
    item = str(params.get("item") or "").strip()
    if item and not run_id:
        raise ValueError("item names a preview of an earlier run: pass run_id with it (a run takes target)")
    if run_id:
        if not RUN_ID_RX.fullmatch(run_id):
            raise ValueError(f"run_id must match {RUN_ID_RX.pattern}")
        if target != "all":
            raise ValueError("with run_id name the preview by item (its key: owner/repo, or owner/repo:path for "
                             "the doctor), not by target — a registry name matches no preview")
        if item and (not ITEM_KEY_RX.fullmatch(item) or ".." in item.split(":", 1)[-1].split("/")):
            raise ValueError(f"item must be a run's item key — owner/repo, or owner/repo:path (no '..'); "
                             f"not {item!r}")
        argv = [DASH, "loop", "publish", run_id, *(["--item", item] if item else []), "--json"]
    else:
        argv = [DASH, "loop", "run", loop, *([step] if step else []), "--target", target, "--json"]
        if _flag(params, "rehearse"):
            argv.append("--rehearse")
    if apply:
        argv.append("--apply")
    return argv


def _loop_exclusive(params: dict) -> str:
    """Two local runs of ONE loop never overlap (the engine holds the budget
    lock per attempt, but a queue of two would interleave their previews);
    different loops may run beside each other."""
    return f"loop:{str(params.get('loop') or '').strip()}"


def contract_secrets() -> list[dict]:
    """The token contract's live (non-deprecated) entries — names and scope only."""
    fleet = load_yaml(DATA / "fleet.yml") or {}
    return [{"name": t["name"], "scope": t.get("scope"), "required": bool(t.get("required"))}
            for t in (fleet.get("tokens") or [])
            if t.get("name") and not t.get("deprecated") and not t.get("managed_by")]


def _keys_rotate(params: dict) -> list[str]:
    """`dash keys rotate`: new Console keys in .env → the repos each workspace serves."""
    argv = [DASH, "keys", "rotate"]
    if _flag(params, "allow_long_lived"):
        argv.append("--allow-long-lived")
    if _flag(params, "apply"):
        if not AUTH_WRITES:
            raise PermissionError("credential writes are disabled (DASH_CONSOLE_AUTH=off)")
        argv.append("--apply")
    return argv


def _secrets_push(params: dict) -> list[str]:
    """`dash secrets push`: .env → hub → fleet. `secret` must name a contract entry."""
    argv = [DASH, "secrets", "push"]
    secret = str(params.get("secret") or "").strip()
    if secret:
        if secret not in {t["name"] for t in contract_secrets()}:
            raise ValueError(f"'{secret}' is not in the token contract (_data/fleet.yml tokens:)")
        argv += ["--only", secret]
    if _flag(params, "hub_only"):
        argv.append("--hub-only")
    if _flag(params, "apply"):
        if not AUTH_WRITES:
            raise PermissionError("credential writes are disabled (DASH_CONSOLE_AUTH=off)")
        argv.append("--apply")
    return argv


def _tests(params: dict) -> list[str]:
    # A constant script (no parameters reach it): the same loop
    # run-all-tests.sh's control-plane section performs.
    return ["bash", "-c",
            "set -e; for t in .github/scripts/dash-gen/test_*.py tools/console/test_*.py; do "
            "[ -e \"$t\" ] || continue; echo \"== $t\"; python3 \"$t\"; done"]


def _config_show(params: dict) -> list[str]:
    argv = [DASH, "config", "show"]
    key = str(params.get("key") or "").strip()
    if key:
        if not KEY_RX.match(key):
            raise ValueError("key must be a dotted lowercase fleet.yml path")
        argv.append(key)
    return argv


def _choice(params: dict, key: str, allowed: tuple[str, ...], default: str) -> str:
    v = str(params.get(key) or default).strip()
    if v not in allowed:
        raise ValueError(f"{key} must be one of {allowed}")
    return v


def _lake_sync(params: dict) -> list[str]:
    argv = [DASH_GEN, "lake", "sync", "--days", _days({"days": params.get("days", 7)})]
    if str(params.get("target") or "").strip():
        argv += ["--repo", _name(params)]
    argv += ["--jobs", _choice(params, "jobs", ("ai", "all", "none"), "ai")]
    argv += ["--logs", _choice(params, "logs", ("ai", "all", "none"), "ai")]
    return argv


def _lake_sessions(params: dict) -> list[str]:
    argv = [DASH_GEN, "lake", "sessions", "--days", _days({"days": params.get("days", 30)})]
    if str(params.get("target") or "").strip():
        argv += ["--repo", _name(params)]
    if _flag(params, "force"):
        argv.append("--force")
    return argv


def _lake_review(params: dict) -> list[str]:
    argv = [DASH_GEN, "lake", "review", "--days", _days({"days": params.get("days", 30)})]
    if str(params.get("target") or "").strip():
        argv += ["--repo", _name(params)]
    return argv


def _lake_export(params: dict) -> list[str]:
    argv = [DASH_GEN, "lake", "export", "--days", _days({"days": params.get("days", 7)})]
    if _flag(params, "local"):
        argv.append("--local")
    if _flag(params, "dry_run"):
        argv.append("--dry-run")
    if _flag(params, "force"):
        argv.append("--force")
    return argv


def _observe_ship(params: dict) -> list[str]:
    argv = [DASH_GEN, "observe", "ship", "--days", _days({"days": params.get("days", 7)})]
    if str(params.get("target") or "").strip():
        argv += ["--repo", _name(params)]
    if _flag(params, "dry_run"):
        argv.append("--dry-run")
    if _flag(params, "force"):
        argv.append("--force")
    return argv


# The log plane's services, named explicitly. A bare `--profile elk up`
# also starts every service in the DEFAULT profile, so "start the log plane"
# would bring up devenv, console, wiki and db as well and fight them for their
# ports. Held equal to the profile's membership by test_observe_contract.py.
# qdrant is the Kilo code index; it starts with the plane so status can see it.
ELK_SERVICES = ["elasticsearch", "logstash", "kibana", "filebeat", "grafana", "qdrant"]
# Claude Code's native OTel path (FF-0003) — the `metrics` profile's own
# services; grafana carries both profiles and is already named above.
METRICS_SERVICES = ["otel-collector", "prometheus"]


def _observe_compose(verb: str):
    """`docker compose --profile elk …` as argv, never a shell string.

    The verb is a literal from this module, not a parameter — there is no path
    by which a request body reaches the compose command line.
    """
    VERBS = {"up": ["up", "-d"], "stop": ["stop"]}
    assert verb in VERBS, verb

    def build(_params: dict) -> list[str]:
        return ["docker", "compose", "--profile", "elk", "--profile", "metrics", *VERBS[verb],
                *ELK_SERVICES, *METRICS_SERVICES]
    return build


def _observe_bootstrap(_params: dict) -> list[str]:
    return [str(TOOLS / "observability" / "bootstrap.sh")]


# id → (title, group, argv builder, needs_token, remote_write(params) -> bool, description)
# --------------------------------------------------------------------------- #
# REFINE + ASSIST — JEV capability three in the console (ADR 0004 P2,
# docs/HARNESS-REFINEMENT.md) and the in-page assistant. Every refine op is
# `tools/dash refine …` at $0; the assistant is one capped, read-only headless
# Claude Code session with the `fleet` MCP server attached (`dash-gen ai-run`),
# confirm-gated like a loop attempt because it spends.
# --------------------------------------------------------------------------- #
REFINE_STAGES = ("propose-invariant", "propose-domain", "compose", "select", "reflect")
REFINE_MODES = ("parallel", "sequential")
STAMP_RX = re.compile(r"^\d{8}T\d{6}Z-[a-z0-9][a-z0-9-]{0,80}$")
ASSIST_PROMPT = Path(_HERE) / "assist.prompt.txt"
ASSIST_MAX_CHARS = 4000
ASSIST_CONTEXT_CHARS = 300
#: the tools an assistant session may use: the fleet MCP server, and reading the hub checkout
ASSIST_ALLOWED = ("mcp__fleet", "Read", "Grep", "Glob")
ASSIST_DENIED = ("Bash", "Write", "Edit", "MultiEdit", "NotebookEdit", "WebFetch", "WebSearch", "Agent", "Task")
_REFINE_CACHE: dict = {"at": 0.0, "doc": None, "fleet_at": 0.0, "fleet": None}


def _jev():
    """tools.jev, imported from the hub root (the loop runner's precedent in agent_steps)."""
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from tools.jev import library, refine, spec, surface  # noqa: PLC0415
    return refine, surface, library, spec


def _refine_loops() -> list[str]:
    """The loops a refinement step can plan for: those with a local agent step."""
    return sorted({s["loop"] for s in agent_steps()})


def _refine_surface(params: dict) -> list[str]:
    """`tools/dash refine surface check` (the hub), `surface fleet --only <name>` for one registry
    repository, or `surface fleet` for every checked-out one (`target: fleet`)."""
    target = str(params.get("target") or "").strip()
    if not target or target in ("bamr87", "hub"):
        return [DASH, "refine", "surface", "check"]
    if target == "fleet":
        return [DASH, "refine", "surface", "fleet"]
    return [DASH, "refine", "surface", "fleet", "--only", _name(params)]


def _refine_plan(params: dict) -> list[str]:
    """`tools/dash refine plan <loop> [--step S] [--k N] [--mode M] [--target NAME]` — $0."""
    loop = str(params.get("loop") or "").strip()
    known = _refine_loops()
    if loop not in known:
        raise ValueError(f"loop must be one of {known} (a loop whose agent step has a local: spec)")
    argv = [DASH, "refine", "plan", loop]
    step = str(params.get("step") or "").strip()
    if step:
        if not NAME_RX.match(step):
            raise ValueError(f"step must match {NAME_RX.pattern}")
        argv += ["--step", step]
    k = params.get("k", 1)
    try:
        k = int(k)
    except (TypeError, ValueError) as exc:
        raise ValueError("k must be an integer") from exc
    if not 1 <= k <= 5:
        raise ValueError("k must be 1..5 (harness_refinement.k_max caps it lower)")
    argv += ["--k", str(k)]
    mode = str(params.get("mode") or "").strip()
    if mode:
        if mode not in REFINE_MODES:
            raise ValueError(f"mode must be one of {REFINE_MODES}")
        argv += ["--mode", mode]
    target = str(params.get("target") or "").strip()
    if target and target != "all":
        argv += ["--target", _name(params)]
    return argv


def _refine_evidence(params: dict) -> list[str]:
    """`tools/dash refine evidence <loop> --item KEY [--stage S] [--k N] [--run ID] --json` — $0,
    writes the redacted evidence tree under .fleet/refine/ (local disk, gitignored)."""
    loop = str(params.get("loop") or "").strip()
    known = _refine_loops()
    if loop not in known:
        raise ValueError(f"loop must be one of {known}")
    item = str(params.get("item") or "").strip()
    if not item or not ITEM_KEY_RX.fullmatch(item) or ".." in item.split(":", 1)[-1].split("/"):
        raise ValueError("item must be a run's item key — owner/repo, or owner/repo:path (no '..')")
    stage = str(params.get("stage") or "propose-invariant").strip()
    if stage not in REFINE_STAGES:
        raise ValueError(f"stage must be one of {REFINE_STAGES}")
    argv = [DASH, "refine", "evidence", loop, "--item", item, "--stage", stage]
    step = str(params.get("step") or "").strip()
    if step:
        if not NAME_RX.match(step):
            raise ValueError(f"step must match {NAME_RX.pattern}")
        argv += ["--step", step]
    try:
        k = int(params.get("k", 1))
    except (TypeError, ValueError) as exc:
        raise ValueError("k must be an integer") from exc
    if not 1 <= k <= 5:
        raise ValueError("k must be 1..5")
    argv += ["--k", str(k)]
    run_id = str(params.get("run_id") or "").strip()
    if run_id:
        if not RUN_ID_RX.fullmatch(run_id):
            raise ValueError(f"run_id must match {RUN_ID_RX.pattern}")
        argv += ["--run", run_id]
    return argv + ["--json"]


class AssistConfig(dict):
    """`_data/fleet.yml` `assistant:` as a dict with attribute access (enabled, model, max_turns,
    budget_usd, timeout_s), validated on every read."""

    __getattr__ = dict.__getitem__


def assistant_config(fleet: dict | None = None) -> AssistConfig:
    fleet = fleet if fleet is not None else (load_yaml(DATA / "fleet.yml") or {})
    raw = fleet.get("assistant") if isinstance(fleet, dict) else None
    if not isinstance(raw, dict):
        raise ValueError("_data/fleet.yml has no `assistant:` block (tools/console/README.md, The assistant)")
    want = {"enabled", "model", "max_turns", "budget_usd", "timeout_s"}
    missing, unknown = want - set(raw), set(raw) - want
    if missing or unknown:
        raise ValueError(f"_data/fleet.yml assistant: missing {sorted(missing)} / unknown {sorted(map(str, unknown))}")
    if not isinstance(raw["enabled"], bool):
        raise ValueError("_data/fleet.yml assistant.enabled: a boolean")
    allowed = (fleet.get("ai_models") or {}).get("allowed") or {}
    ids = {str(m) for ids in (allowed.values() if isinstance(allowed, dict) else [allowed]) for m in (ids or [])}
    if raw["model"] not in ids:
        raise ValueError(f"_data/fleet.yml assistant.model {raw['model']!r} is not an exact id in ai_models.allowed "
                         f"(constitution § 13.3)")
    for key in ("max_turns", "timeout_s"):
        v = raw[key]
        if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
            raise ValueError(f"_data/fleet.yml assistant.{key}: a positive integer")
    b = raw["budget_usd"]
    if isinstance(b, bool) or not isinstance(b, (int, float)) or not math.isfinite(b) or b <= 0:
        raise ValueError("_data/fleet.yml assistant.budget_usd: a finite positive number")
    return AssistConfig(enabled=raw["enabled"], model=str(raw["model"]), max_turns=int(raw["max_turns"]),
                        budget_usd=float(b), timeout_s=int(raw["timeout_s"]))


def assist_unavailable() -> str | None:
    """Why the assistant cannot run here: no claude CLI, or switched off in fleet.yml."""
    why = claude_unavailable()
    if why:
        return why
    try:
        cfg = assistant_config()
    except ValueError as exc:
        return str(exc)
    if not cfg.enabled:
        return "the assistant is off: _data/fleet.yml assistant.enabled is false"
    return None


def _assist_mcp_config() -> dict:
    """The one MCP server an assistant session gets: the Harness Console MCP layer over stdio, pointed
    at THIS console. The job inherits DASH_CONSOLE_TOKEN from the process environment, never argv."""
    url = os.environ.get("DASH_CONSOLE_URL") or "http://127.0.0.1:4001"
    return {"mcpServers": {"fleet": {"command": str(TOOLS / "console" / "mcp.sh"), "args": [],
                                     "env": {"DASH_CONSOLE_URL": url, "HARNESS_MCP_SKIP_INSTALL": "1"}}}}


def _assist(params: dict) -> list[str]:
    """`tools/dash-gen ai-run … -- <claude flags>`: one read-only headless session, the assistant's
    prompt (tools/console/assist.prompt.txt with the question and the page context filled) on stdin,
    the `fleet` MCP server as its only server (--strict-mcp-config), the hub checkout as its cwd,
    the result captured to a file the job page reads. Capped by assistant.budget_usd and recorded in
    the AI ledger by ai-run; never a write tool, never the network."""
    question = str(params.get("question") or "").strip()
    if not question:
        raise ValueError("question is required")
    if len(question) > ASSIST_MAX_CHARS or "\0" in question:
        raise ValueError(f"question must be at most {ASSIST_MAX_CHARS} characters, with no NUL")
    context = " ".join(str(params.get("context") or "").split())[:ASSIST_CONTEXT_CHARS] or "the console, no page named"
    cfg = assistant_config()
    if not cfg.enabled:
        raise ValueError("the assistant is off: _data/fleet.yml assistant.enabled is false")
    try:
        template = ASSIST_PROMPT.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"the assistant's prompt cannot be read: {exc}") from exc
    prompt = template.replace("{{CONTEXT}}", context).replace("{{QUESTION}}", question)
    d = JOB_DIR / "assist"
    d.mkdir(parents=True, exist_ok=True)
    ask_id = uuid.uuid4().hex[:12]
    prompt_file, result_file, outcome_file, mcp_file = (d / f"{ask_id}.prompt.txt", d / f"{ask_id}.result.json",
                                                        d / f"{ask_id}.outcome.json", d / f"{ask_id}.mcp.json")
    prompt_file.write_text(prompt, encoding="utf-8")
    mcp_file.write_text(json.dumps(_assist_mcp_config(), indent=1), encoding="utf-8")
    return [DASH_GEN, "ai-run", "--source", "console assist", "--repo", "bamr87/bamr87", "--cwd", str(REPO_ROOT),
            "--prompt-file", str(prompt_file), "--result-file", str(result_file), "--outcome-file", str(outcome_file),
            "--stream", "--timeout", str(cfg.timeout_s), "--max-budget-usd", f"{cfg.budget_usd:g}",
            "--usage-limit", "skip", "--",
            "--model", cfg.model, "--max-turns", str(cfg.max_turns), "--permission-mode", "dontAsk",
            "--setting-sources", "user", "--strict-mcp-config", "--mcp-config", str(mcp_file),
            "--allowedTools", *ASSIST_ALLOWED, "--disallowedTools", *ASSIST_DENIED]


def _argv_value(argv: list[str], flag: str) -> str | None:
    try:
        return argv[argv.index(flag) + 1]
    except (ValueError, IndexError):
        return None


def assist_job_fields(job: "Job") -> dict:
    """The structured view of an `assist` job: the question, the page context, and once the session
    ended its answer (the CLI's result text), turns, models and cost (API-equivalent (estimate)) from
    the result and outcome files ai-run wrote. Read defensively: a session that died leaves neither."""
    out = {"schema": "assist-job/v1", "question": str((job.params or {}).get("question") or ""),
           "context": str((job.params or {}).get("context") or ""), "answer": None, "turns": None,
           "cost_usd": None, "cost_source": None, "cost_label": COST_LABEL, "models": [], "outcome": None,
           "subtype": None}
    result_path = _argv_value(job.argv, "--result-file")
    outcome_path = _argv_value(job.argv, "--outcome-file")
    for label, path in (("result", result_path), ("outcome", outcome_path)):
        if not path:
            continue
        try:
            doc = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(doc, dict):
            continue
        if label == "result":
            out["answer"] = str(doc.get("result") or "") or None
            out["turns"] = doc.get("num_turns")
            out["subtype"] = doc.get("subtype")
            usage = doc.get("modelUsage")
            if isinstance(usage, dict):
                out["models"] = sorted(str(m) for m in usage)
            if isinstance(doc.get("total_cost_usd"), (int, float)):
                out["cost_usd"] = round(float(doc["total_cost_usd"]), 6)
        else:
            out["outcome"] = doc.get("kind")
            if isinstance(doc.get("cost_usd"), (int, float)):
                out["cost_usd"] = round(float(doc["cost_usd"]), 6)
            out["cost_source"] = doc.get("cost_source")
    return out


OPS: dict[str, dict] = {
    # observe ----------------------------------------------------------------
    "harnesses": dict(title="Refresh harness inventory (live fleet scan)", group="observe",
                      argv=lambda p: [DASH_GEN, "harnesses", "--days", _days(p)], needs_token=True,
                      desc="Scan every registry repo + the hub for AI harnesses and crons; grade against fleet.yml `harnesses:`.",
                      params=["days"]),
    "harnesses-offline": dict(title="Refresh harness analytics (offline, reuse last scan)", group="observe",
                              argv=lambda p: [DASH_GEN, "harnesses", "--offline"], needs_token=False,
                              desc="Recompute trends/throughput/grading from committed data without touching GitHub."),
    "gaps": dict(title="List fan-out-deployable gap repos", group="observe",
                 argv=lambda p: [DASH_GEN, "harnesses", "--gaps"], needs_token=False,
                 desc="Repos missing a kit-deployable baseline artifact or running an upgradeable machine seed."),
    "harness": dict(title="Harness scorecard + trip wires (offline)", group="observe",
                    argv=lambda p: [DASH_GEN, "harness"], needs_token=False,
                    desc="The hub's own six-layer health from the committed signals (docs/HARNESS.md)."),
    "triage": dict(title="Fleet open-state triage snapshot", group="observe",
                   argv=lambda p: [DASH_GEN, "triage"], needs_token=True,
                   desc="Open issues / PRs / failing workflows across the fleet → _data/fleet_triage.yml."),
    "actions": dict(title="Actions usage analytics", group="observe",
                    argv=lambda p: [DASH_GEN, "actions", "--days", _days(p), "--quiet"], needs_token=True,
                    desc="Per-workflow cost / effectiveness / waste → _data/actions_usage.yml.", params=["days"]),
    "ai-usage": dict(title="Claude usage ledger", group="observe",
                     argv=lambda p: [DASH_GEN, "ai-usage", "--days", _days(p)], needs_token=True,
                     desc="Every claude-code-action run, Claude commit and PR in the window → _data/ai_usage.yml.",
                     params=["days"]),
    "daily": dict(title="Prior-day activity digest", group="observe",
                  argv=lambda p: [DASH_GEN, "daily", "--days", "1"], needs_token=True,
                  desc="The committed digest under _reports/daily/."),
    "health": dict(title="Live project health (monitor board)", group="observe",
                   argv=lambda p: [DASH_GEN, "health"], needs_token=True,
                   desc="Ephemeral per-project health → _data/project_health.yml (gitignored)."),
    "status": dict(title="Dash status (submodules, registry, drift)", group="observe",
                   argv=lambda p: [DASH, "status"], needs_token=False, desc="`tools/dash status`."),
    "audit": dict(title="Standardization conformance matrix", group="observe",
                  argv=lambda p: [DASH, "audit"], needs_token=False, desc="`tools/dash audit`."),
    "secrets-audit": dict(title="Secrets & variables audit (fleet vs GitHub)", group="observe",
                          argv=lambda p: [DASH, "secrets"], needs_token=True,
                          desc="Per-repo matrix of declared vs actual secrets/variables — names only, never values."),
    "secrets-plan": dict(title="Credential rotation plan (read-only)", group="observe",
                         argv=lambda p: [DASH, "secrets", "plan"], needs_token=True,
                         desc="Each repo's credential AGE and what a rotation would rewrite."),
    "config-show": dict(title="Show the fleet contract", group="observe",
                        argv=_config_show, needs_token=False, desc="`tools/dash config show [key]`.", params=["key"]),
    # plan ---------------------------------------------------------------------
    "remediate": dict(title="Build the remediation queue", group="plan",
                      argv=lambda p: [DASH_GEN, "remediate"], needs_token=True,
                      desc="Merge failing + expensive workflow signals into the doctor's ranked fix queue."),
    "issues": dict(title="Build the issue-pipeline queues", group="plan",
                   argv=lambda p: [DASH_GEN, "issues"], needs_token=True,
                   desc="Classify open issues into the three tiers → _data/issue_pipeline.yml + work orders."),
    "targets": dict(title="Plan the repo-evolution pass (offline)", group="plan",
                    argv=lambda p: [DASH_GEN, "targets", "--no-dedupe"], needs_token=False,
                    desc="Select auto_evolve opt-ins and write their briefs (no GitHub dedupe)."),
    "scout": dict(title="Plan today's repo-scout sample (offline)", group="plan",
                  argv=lambda p: [DASH_GEN, "scout", "--offline"], needs_token=False,
                  desc="Today's rotation over the owned, non-archived registry repos + their briefs (no backpressure check without GitHub)."),
    "loop-run": dict(title="Run a loop's agent step locally (dry run, or apply the reviewed preview)", group="plan",
                     argv=_loop_run, needs_token=True, needs="claude", exclusive=_loop_exclusive,
                     remote=lambda p: _flag(p, "apply") or (not _flag(p, "rehearse") and not p.get("run_id")),
                     confirm="spend",
                     desc="tools/dash loop run <loop> [step] --target <name> --json — the step's own spec, planner "
                          "and prompt bytes (what CI runs), one capped attempt per item inside the § 13.8 sandbox, "
                          "then the dry-run preview under .fleet/runs/<run_id>/. `rehearse` stops before the model "
                          "call ($0). A live attempt spends Claude budget (API-equivalent, an estimate; held to "
                          "budget.loops), so it asks first. `apply` files the reviewed preview through the engine's "
                          "publish gate — the OPS remote-write path (constitution § 11.8, amendment "
                          "ops-remote-write-path): a GitHub write at tier high behind confirm, the token probed with "
                          "`gh api user` first, never with --scheduled; `run_id` publishes an earlier run's preview "
                          "(`loop publish`, read-only without apply), `item` naming it by the preview's key "
                          "(owner/repo, or owner/repo:path for the doctor) when the run has several. A step whose "
                          "filer cannot file yet (bamr87/bamr87#488) refuses apply before anything runs.",
                     params=["loop", "step", "target", "rehearse", "apply", "run_id", "item"],
                     meta=lambda: {"agent_steps": agent_steps()}),
    "reconcile": dict(title="Reconcile registry vs GitHub (report only)", group="plan",
                      argv=lambda p: [DASH_GEN, "reconcile"], needs_token=True,
                      desc="Renames, url mismatches, 404s, branch drift — reported, never applied from here."),
    "readme": dict(title="Regenerate the README AUTO span", group="plan",
                   argv=lambda p: [DASH_GEN, "readme"], needs_token=False,
                   desc="Deterministic; commit the diff if it changed."),
    # verify -----------------------------------------------------------------
    "drift": dict(title="Drift gate (report)", group="verify",
                  argv=lambda p: [str(TOOLS / "check-drift.sh"), "--report"], needs_token=False,
                  desc="Registry/.gitmodules parity, README freshness, SCHEMA pyramid, action manifests."),
    "schema-lint": dict(title="SCHEMA.md pyramid lint", group="verify",
                        argv=lambda p: ["python3", str(TOOLS / "schema_lint.py"), "check", "."], needs_token=False,
                        desc="Errors and warnings fail, exactly as in CI."),
    "tests": dict(title="Control-plane fixture tests", group="verify", argv=_tests, needs_token=False,
                  desc="Every dash-gen and console test_*.py on a bare interpreter."),
    # lake (the local data lake + traces — writes only to disk and to Phoenix) ---
    "lake-sync": dict(title="Lake: extract GitHub data into the local lake", group="lake", exclusive="lake",
                      argv=_lake_sync, needs_token=True,
                      desc="dash-gen lake sync — runs → jobs → steps, run logs + claude-code-action facts, "
                           "issues, workflow files, .factory/** → .dash-lake/fleet.sqlite (gitignored).",
                      params=["days", "target", "jobs", "logs"]),
    "lake-sessions": dict(title="Lake: extract local Claude Code sessions", group="lake", exclusive="lake",
                          argv=_lake_sessions, needs_token=False,
                          desc="dash-gen lake sessions — this machine's ~/.claude transcripts → sessions, "
                               "turns and tool calls in the lake. Local disk only; no GitHub, no network.",
                          params=["days", "target", "force"]),
    "lake-review": dict(title="Lake: review Claude activity (both planes)", group="lake",
                        argv=_lake_review, needs_token=False,
                        desc="dash-gen lake review — local sessions + CI agent runs unified: cost, turns, "
                             "tool usage, failures, and ranked findings. Reads the lake, offline.",
                        params=["days", "target"]),
    "lake-status": dict(title="Lake: status", group="lake",
                        argv=lambda p: [DASH_GEN, "lake", "status"], needs_token=False,
                        desc="Tables, freshness, per-repo counts, the export ledger, Phoenix reachability."),
    "lake-export": dict(title="Lake: export traces to Phoenix", group="lake", exclusive="lake",
                        argv=_lake_export, needs_token=False,
                        desc="OpenInference spans for the lake's agent runs (and this machine's Claude Code "
                             "sessions with local) → Phoenix over OTLP/HTTP. Dry run writes export-preview.json.",
                        params=["days", "local", "dry_run", "force"]),
    # observe — the local LOG plane (docs/OBSERVABILITY.md). Writes to docker and
    # to Elasticsearch on this machine only; nothing here touches GitHub, which
    # is why none of it needs a token or a confirm except the destructive one.
    "observe-status": dict(title="Observe: plane health, dataset sizes, ship lag", group="observe",
                           argv=lambda p: [DASH_GEN, "observe", "status"], needs_token=False,
                           desc="Elasticsearch/Kibana, Grafana and Phoenix reachability; docs and bytes "
                                "per data stream against the disk budget; how many runs are unshipped."),
    "observe-up": dict(title="Observe: start the log + metrics stack", group="observe", needs="docker",
                       argv=_observe_compose("up"), needs_token=False,
                       desc="docker compose --profile elk --profile metrics up -d — Elasticsearch, "
                            "Logstash, Kibana, Filebeat, Grafana, Qdrant (the Kilo code index), and the "
                            "OTel collector + Prometheus that receive Claude Code's native telemetry. "
                            "Run 'bootstrap' after it to install ILM + dashboards."),
    # One project's dev stack, for the Apps page and the Desktop. Local only and
    # started by a person: nothing here runs on page load. `needs` keeps them
    # off where they cannot work — the console's own container has no socket on
    # purpose, so there the page shows the terminal command instead.
    "dev-up": dict(title="Dev stack: start one project", group="observe", needs="docker",
                   host_cmd="tools/dash dev up <project>", exclusive=_stack_exclusive,
                   argv=lambda p: [DASH, "dev", "up", _stack(p)], needs_token=False,
                   desc="tools/dash dev up <project> — starts that project's compose stack on the ports "
                        "_data/ports.yml allocates. Containers use the Docker VM's memory, so stop a stack "
                        "you are done with.",
                   params=["target"]),
    "dev-down": dict(title="Dev stack: stop one project (keeps its data)", group="observe", needs="docker",
                     host_cmd="tools/dash dev down <project>", exclusive=_stack_exclusive,
                     argv=lambda p: [DASH, "dev", "down", _stack(p)], needs_token=False,
                     desc="tools/dash dev down <project> — stops that project's compose stack. Its volumes stay.",
                     params=["target"]),
    "dev-logs": dict(title="Dev stack: the last lines of one project's logs", group="observe", needs="docker",
                     host_cmd="tools/dash dev logs <project>",
                     argv=lambda p: [DASH, "dev", "logs", _stack(p), "--once"], needs_token=False,
                     desc="The last 200 lines from each of the project's services, then the job ends. "
                          "To follow them live: tools/dash dev logs <project> in a terminal.",
                     params=["target"]),
    "observe-bootstrap": dict(title="Observe: install ILM policies + dashboards", group="observe",
                              argv=_observe_bootstrap, needs_token=False,
                              desc="Idempotent: PUTs the rendered ILM policies and index templates, "
                                   "imports the Kibana saved objects, reports Grafana's provisioning."),
    "observe-down": dict(title="Observe: stop the stack (keeps the data)", group="observe", needs="docker",
                         argv=_observe_compose("stop"), needs_token=False,
                         desc="Stops the elk profile. The volumes — and every indexed log line — survive."),
    "observe-ship": dict(title="Observe: ship Actions logs from the lake", group="observe", exclusive="lake",
                         argv=_observe_ship, needs_token=False,
                         desc="dash-gen observe ship — replays the lake's completed runs into Logstash as "
                              "ECS documents, carrying the same trace.id Phoenix uses. Extract first with "
                              "'Lake: extract GitHub data'. Dry run writes observe-preview.json.",
                         params=["days", "target", "dry_run", "force"]),
    # Delegates to the CLI rather than running compose itself: `down -v` would
    # take EVERY named volume in the file — db-data, wiki-data, phoenix-data
    # included — and the narrow teardown (remove the elk containers, then their
    # volumes by name) should exist in exactly one place.
    "observe-reset": dict(title="Observe: destroy the indices and volumes", group="observe", needs="docker",
                          argv=lambda p: [str(TOOLS / "dash"), "observe", "reset", "--yes"],
                          needs_token=False, remote=lambda p: True,
                          desc="Deletes every indexed log line, the Kilo code index, and the six elk "
                               "volumes — and nothing else. Irreversible: the lake can re-ship Actions "
                               "logs, but container logs and the code index only ever existed here."),
    "observe-verify": dict(title="Observe: re-render ILM + dashboards from the contract", group="verify",
                           argv=lambda p: [DASH_GEN, "observe", "verify"], needs_token=False,
                           desc="Offline diff of _data/fleet.yml `observability:` against the committed "
                                "tools/observability files, and resolves every pinned dashboard id."),
    # content — the content atlas (docs/CONTENT-ATLAS.md). sync/report write only
    # to the lake; `content-file` with apply opens issues in a site's repo.
    "content-sync": dict(title="Content: extract the content sites into the atlas", group="content", exclusive="lake",
                         argv=_content_sync, needs_token=False,
                         desc="dash-gen content sync — every fleet.yml `content.sites` entry (or one, by "
                              "target) from its local checkout or a cached blob-less clone → front matter, "
                              "body metrics and git history in the lake. Clones public repos without a token.",
                         params=["target", "no_fetch"]),
    "content-report": dict(title="Content: report (topics, aging, hygiene, suggestions)", group="content",
                           argv=lambda p: [DASH_GEN, "content", "report"] + (
                               ["--site", _name(p)] if str(p.get("target") or "").strip() else []),
                           needs_token=False, desc="The atlas as a terminal table; offline.",
                           params=["target"]),
    "content-brief": dict(title="Content: render a site's editorial brief", group="content",
                          argv=lambda p: [DASH_GEN, "content", "brief", "--site", _name(p)], needs_token=False,
                          desc="Narrative, pillar coverage and approved directives as Markdown.",
                          params=["target"]),
    "content-file": dict(title="Content: file approved directives as issues", group="content",
                         argv=_content_file, needs_token=True, remote=lambda p: _flag(p, "apply"),
                         desc="One issue per approved directive in the site's own repo, labelled "
                              "editorial:directive and deduped on a hidden marker — DRY RUN unless apply. "
                              "Records filed + the URL in _data/editorial.yml (commit it yourself).",
                         params=["target", "apply"]),
    # deploy (writes to GitHub — confirm-gated, serialized) ---------------------
    "deploy-gaps": dict(title="Deploy the agent-context kit to gap repos", group="deploy",
                        argv=lambda p: _deploy(p, "gaps"), needs_token=True,
                        remote=lambda p: _flag(p, "apply"),
                        desc="tools/dash harnesses deploy --gaps — DRY RUN unless apply; PRs only, additive-only.",
                        params=["artifacts", "upgrade", "apply"]),
    "deploy-target": dict(title="Deploy the kit to one repo", group="deploy",
                          argv=lambda p: _deploy(p, "target"), needs_token=True,
                          remote=lambda p: _flag(p, "apply"),
                          desc="tools/dash harnesses deploy --target <name> — DRY RUN unless apply.",
                          params=["target", "artifacts", "upgrade", "apply"]),
    "keys-status": dict(title="Anthropic API keys per workspace", group="observe",
                        argv=lambda p: [DASH, "keys", "status"], needs_token=False,
                        desc="tools/dash keys — each Console workspace's key found in .env, its expiry vs the "
                             "7-day policy, and the repos it serves. Reads the Admin API (CLAUDE_CONSOLE_TOKEN); "
                             "never a key value."),
    "keys-verify": dict(title="Verify API keys (one cheap call each)", group="observe",
                        argv=lambda p: [DASH, "keys", "verify"], needs_token=False,
                        desc="tools/dash keys verify — one minimal Messages call per key in .env, exactly as CI "
                             "makes it. A fraction of a cent per key."),
    "keys-watch": dict(title="Deployed API keys vs policy (the daily check)", group="observe",
                       argv=lambda p: [DASH, "keys", "watch"], needs_token=False,
                       desc="tools/dash keys watch — judges the keys the ledger says are DEPLOYED, as "
                            "api-keys.yml does every morning."),
    "keys-rotate": dict(title="Rotate API keys: .env → workspaces' repos", group="deploy",
                        argv=_keys_rotate, needs_token=True, remote=lambda p: _flag(p, "apply"),
                        desc="tools/dash keys rotate — verifies each new key, writes it hub-first to the repos its "
                             "workspace serves, then disables the key it replaced. DRY RUN unless apply.",
                        params=["allow_long_lived", "apply"]),
    "ai-auth": dict(title="AI auth order per repo (resolved)", group="observe",
                    argv=lambda p: [DASH, "config", "auth"] + (["--repo", _name(p)] if p.get("target") else []),
                    needs_token=True,
                    desc="tools/dash config auth — each repo's credential order, where it came from "
                         "(default / group / repo), which credentials it holds, and its CLAUDE_AUTH_ORDER.",
                    params=["target"]),
    "ai-auth-sync": dict(title="Project the AI auth order (CLAUDE_AUTH_ORDER)", group="deploy",
                         argv=lambda p: [DASH, "config", "auth", "sync"]
                         + (["--repo", _name(p)] if p.get("target") else [])
                         + (["--apply"] if _flag(p, "apply") else []),
                         needs_token=True, remote=lambda p: _flag(p, "apply"),
                         desc="Sets each repo's CLAUDE_AUTH_ORDER variable from ai_auth: — DRY RUN unless apply. "
                              "Secrets follow the order on the next secrets push / rotation.",
                         params=["target", "apply"]),
    "secrets-push": dict(title="Push .env secrets → hub → fleet", group="deploy",
                         argv=_secrets_push, needs_token=True, remote=lambda p: _flag(p, "apply"),
                         desc="tools/dash secrets push — reads the token contract's names from .env "
                              "(parsed, never sourced), writes the hub first, then fans the fleet-scoped "
                              "ones out. DRY RUN unless apply.",
                         params=["secret", "hub_only", "apply"]),
    "secrets-rotate": dict(title="Run the credential rotation loop now", group="deploy",
                           argv=lambda p: [DASH, "secrets", "rotate"] + (["--apply"] if _flag(p, "apply") else []),
                           needs_token=True, remote=lambda p: _flag(p, "apply"),
                           desc="Hub-first propagation of the fleet's Claude credential — DRY RUN unless apply.",
                           params=["apply"]),
    "config-sync": dict(title="Project canonical variables onto the fleet", group="deploy",
                        argv=lambda p: [DASH, "config", "sync"] + (["--apply"] if _flag(p, "apply") else []),
                        needs_token=True, remote=lambda p: _flag(p, "apply"),
                        desc="fleet.yml `variables:` → every repo's Actions variables — DRY RUN unless apply.",
                        params=["apply"]),
    "dispatch": dict(title="Dispatch a control-plane workflow in CI", group="deploy",
                     argv=_dispatch, needs_token=True, remote=lambda p: True,
                     desc="`gh workflow run <workflow>.yml -f key=value` for the allowlisted workflows; "
                          "the inputs and their types are read from each workflow file.",
                     params=["workflow", "fields"]),
    # workflows — the atlas (dash-gen workflow_atlas.py; docs/WORKFLOW-ATLAS.md)
    "workflows-lint": dict(title="Lint the hub's workflows and actions", group="verify",
                           argv=lambda p: [DASH_GEN, "workflows", "lint"], needs_token=False,
                           desc="The README standards and the AGENTS.md standing rules as checks; "
                                "fails on an error, exactly as test_workflow_atlas.py does in CI."),
    "workflow-new": dict(title="Scaffold a new workflow", group="plan", argv=_workflow_new, needs_token=False,
                         desc="Writes .github/workflows/<id>.yml from a template that passes every rule "
                              "(never overwrites) and prints the fleet.yml / README edits that go with it. "
                              "Commits nothing.",
                         params=["kind", "id", "name", "cron", "purpose"]),
    # refine — JEV capability three (docs/HARNESS-REFINEMENT.md): every op is $0 and
    # reads or writes local disk only; the model-backed stages are ADR 0004 P1.
    "refine-surface": dict(title="Refine: check a harness surface (context files, skills, agents, hooks, MCP)",
                           group="refine", argv=_refine_surface, needs_token=False,
                           desc="tools/dash refine surface check — the hub's own surface (exit 1 on an error); "
                                "`target` a registry name for one checked-out submodule, or `fleet` for every "
                                "checked-out one, one row each.",
                           params=["target"]),
    "refine-plan": dict(title="Refine: plan one Propose–Probe–Compose step", group="refine", argv=_refine_plan,
                        needs_token=False,
                        desc="tools/dash refine plan <loop> — the schedule (R = 4k rollouts, P = 3k sessions), the "
                             "ceiling from the step's own cap and harness_refinement.stage_usd against budget.loops, "
                             "the tunable files, the read-only hard rules, the domain's library. Never calls a model.",
                        params=["loop", "step", "k", "mode", "target"],
                        meta=lambda: {"loops": _refine_loops(), "agent_steps": agent_steps()}),
    "refine-evidence": dict(title="Refine: build the evidence tree a proposer would read", group="refine",
                            argv=_refine_evidence, needs_token=False,
                            desc="tools/dash refine evidence <loop> --item KEY — from this loop step's completed local "
                                 "attempts on the item (.fleet/runs): the brief, full redacted trajectories, "
                                 "deliverables, the tunable harness, the hard rules read-only, the domain's library and "
                                 "the rendered mission, under .fleet/refine/<stamp>/ (gitignored). $0.",
                            params=["loop", "step", "item", "stage", "k", "run_id"],
                            meta=lambda: {"loops": _refine_loops(), "stages": list(REFINE_STAGES)}),
    "refine-library-check": dict(title="Refine: check the experience library", group="refine",
                                 argv=lambda p: [DASH, "refine", "library", "check"], needs_token=False,
                                 desc="Every entry under _data/harness_library is well-formed and carries nothing "
                                      "private (exit 1 otherwise)."),
    "assist": dict(title="Ask the assistant (read-only, through the fleet MCP server)", group="refine", argv=_assist,
                   needs_token=False, needs="claude", gate=assist_unavailable, exclusive="assist",
                   remote=lambda p: True, confirm="spend",
                   desc="One headless Claude Code session (tools/console/assist.prompt.txt) with the `fleet` MCP "
                        "server attached, reading the hub checkout, answering the question from the fleet's own "
                        "data and citing its sources. Capped per answer by _data/fleet.yml assistant.budget_usd "
                        "(API-equivalent, an estimate) and recorded in the AI ledger; no write tool, no network, "
                        "no job it can start. It spends, so it asks first.",
                   params=["question", "context"]),
}


_DOCKER_CHECK: dict = {"at": 0.0, "reason": None}


def docker_unavailable() -> str | None:
    """Why `docker compose` cannot run from this process, or None if it can.

    The console's own container has the docker CLI but neither the compose
    plugin nor the daemon socket — on purpose: only the `tui` service is
    handed the socket. So observe-up/down/reset failed every time there, with
    "unknown flag: --profile" as the only explanation, behind buttons that
    looked live. Cached for a minute: it is asked on every /api/ops.
    """
    now = time.time()
    if now - _DOCKER_CHECK["at"] < 60:
        return _DOCKER_CHECK["reason"]
    reason = None
    if not shutil.which("docker"):
        reason = "no docker CLI in this process"
    elif run_quiet(["docker", "compose", "version"], timeout=10)[0] != 0:
        reason = "the docker CLI here has no compose plugin"
    elif run_quiet(["docker", "info", "--format", "{{.ServerVersion}}"], timeout=10)[0] != 0:
        reason = "no Docker daemon is reachable (this container is not given the socket)"
    _DOCKER_CHECK.update(at=now, reason=reason)
    return reason


def claude_unavailable() -> str | None:
    """Why the local loop runner cannot run from this process: no `claude` CLI
    on its PATH — the console container and the devenv image carry none, and
    the runner refuses to start without one (exit 127). Asked on every
    /api/ops; `shutil.which` is a PATH walk, so it is not cached."""
    if shutil.which(CLAUDE_BIN):
        return None
    return ("no `claude` CLI on this console's PATH (the console container and the devenv image have none)."
            " Run it from a host terminal instead: tools/dash loop run <loop> --target <name>")


def op_unavailable(op_id: str) -> str | None:
    """Why an operation cannot run here at all — independent of its params."""
    needs = (OPS.get(op_id) or {}).get("needs")
    if needs == "docker":
        why = docker_unavailable()
        if why:
            host = (OPS.get(op_id) or {}).get("host_cmd") or f"tools/dash observe {op_id.split('-', 1)[1]}"
            return f"{why}. Run it from a host terminal instead: {host}"
    if needs == "claude":
        why = claude_unavailable()
        if why:
            return why
    gate = (OPS.get(op_id) or {}).get("gate")
    if callable(gate):
        return gate()
    return None


def _exclusive_key(op_id: str, params: dict) -> str | None:
    """The key a job holds while queued or running: a fixed one (`lake`), or
    one computed from its parameters (`loop:<loop>`), or None."""
    exclusive = (OPS.get(op_id) or {}).get("exclusive")
    return exclusive(params) if callable(exclusive) else exclusive


def list_ops() -> list[dict]:
    out = []
    for op_id, op in OPS.items():
        exclusive = op.get("exclusive")
        out.append({
            "id": op_id, "title": op["title"], "group": op["group"], "desc": op.get("desc", ""),
            "needs_token": op["needs_token"], "params": op.get("params", []),
            "remote_write": "remote" in op,
            # what the confirm gate guards: a GitHub write (the default for a remote op) or Claude spend
            "confirm": op.get("confirm", "write" if "remote" in op else None),
            # a per-parameter key is reported by its family (`loop`): the key itself needs the params
            "exclusive": exclusive.__name__.lstrip("_").split("_")[0] if callable(exclusive) else exclusive,
            "unavailable": op_unavailable(op_id),
            # extra data the form needs (loop-run: the agent steps); never a local path or a value
            **(op["meta"]() if "meta" in op else {}),
        })
    return out


def build_argv(op_id: str, params: dict | None = None) -> tuple[list[str], bool]:
    """Resolve an operation to its argv. Returns (argv, remote_write)."""
    params = params or {}
    if op_id not in OPS:
        raise ValueError(f"unknown operation '{op_id}'")
    op = OPS[op_id]
    argv = op["argv"](params)
    remote = bool(op["remote"](params)) if "remote" in op else False
    return argv, remote


# --------------------------------------------------------------------------- #
# JOBS
# --------------------------------------------------------------------------- #
# A job in one of these states will never change again.
FINISHED_STATES = ("succeeded", "failed", "cancelled", "interrupted")


class JobUnavailable(RuntimeError):
    """An operation that cannot run in this process at all (see op_unavailable)."""


class JobConflict(RuntimeError):
    """A job that must run alone already is.

    Every op marked `exclusive="lake"` writes the one SQLite lake. Two of them
    at once used to mean the second died within seconds on "database is
    locked" — a double click on Extract, or an agent and a human both
    refreshing — so the console now says which job holds the lake instead.
    """
_JOB_ID_RX = re.compile(r"^[0-9a-f]{12}$")
ORPHAN_LOG_AGE_S = 86400


def _parse_ts(value) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return None


class Job:
    def __init__(self, op_id: str, argv: list[str], remote: bool, params: dict):
        self.id = uuid.uuid4().hex[:12]
        self.op = op_id
        self.title = OPS[op_id]["title"]
        self.argv = argv
        self.remote = remote
        self.params = params
        self.exclusive = _exclusive_key(op_id, params)
        self.status = "queued"
        self.created = dt.datetime.now(dt.timezone.utc)
        self.started: dt.datetime | None = None
        self.finished: dt.datetime | None = None
        self.exit_code: int | None = None
        self.log_path = JOB_DIR / f"{self.id}.log"
        self.proc: subprocess.Popen | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id, "op": self.op, "title": self.title, "argv": self.argv,
            "remote_write": self.remote, "status": self.status,
            "created": self.created.isoformat(),
            "started": self.started.isoformat() if self.started else None,
            "finished": self.finished.isoformat() if self.finished else None,
            "exit_code": self.exit_code, "log_path": str(self.log_path),
            # Validated operation parameters (names, flags, numbers — never a
            # credential value: secrets-push takes a secret's NAME), so the page
            # can show what a job ran with and offer to run it again.
            "params": self.params,
            # The operation's group (observe, plan, verify, lake, content,
            # deploy) — what the Jobs page groups and filters by.
            "group": (OPS.get(self.op) or {}).get("group"),
            # what its confirm guarded (a GitHub write, or Claude spend) and the key it holds while live
            # an applied loop-run is a GitHub write, whatever the op's default gate wording
            "confirm": ("write" if _flag(self.params or {}, "apply")
                        else (OPS.get(self.op) or {}).get("confirm", "write" if self.remote else None)),
            "exclusive": self.exclusive,
        }

    @classmethod
    def from_dict(cls, d: dict, job_dir: Path) -> "Job":
        """A job read back from the index — never re-run, only shown.

        Built without __init__ because an operation can have been renamed or
        removed since the job ran, and its history should still load.
        """
        job = cls.__new__(cls)
        job.id = str(d["id"])
        job.op = str(d.get("op") or "")
        job.title = str(d.get("title") or job.op)
        job.argv = list(d.get("argv") or [])
        job.remote = bool(d.get("remote_write"))
        job.params = dict(d.get("params") or {})
        job.status = str(d.get("status") or "interrupted")
        job.created = _parse_ts(d.get("created")) or dt.datetime.now(dt.timezone.utc)
        job.started = _parse_ts(d.get("started"))
        job.finished = _parse_ts(d.get("finished"))
        job.exit_code = d.get("exit_code")
        job.exclusive = d.get("exclusive")
        job.log_path = job_dir / f"{job.id}.log"
        job.proc = None
        return job


def job_env() -> dict:
    """The environment every job runs with.

    A job inherits this process's environment exactly as a terminal would —
    which is also how a credential handed to set_credential() reaches `gh` and
    the generators without ever touching an argv.

    PYTHON is what tools/dash-gen execs. Without it the generators ran on the
    system python3 while the console's own dependencies live in .venv-console,
    so `lake export` — whose OpenTelemetry SDK the console itself installs —
    died with ModuleNotFoundError on every real send. (The dry run returns
    before that import, which is why only the shipping path was broken, and why
    the UI looked fine until you unticked "dry run".) Handing jobs this
    interpreter makes what the console installs and what its jobs can import
    the same set.
    """
    return {**os.environ, "PYTHONUNBUFFERED": "1", "FORCE_COLOR": "0", "NO_COLOR": "1",
            "PYTHON": sys.executable}


def loop_job_fields(log_path: Path) -> dict:
    """The structured view of a `loop-run` job's log — the engine's `--json`
    run record when it printed one, else what its status lines say so far —
    from `tools/fleetcore/loopjob.py`, the one parser both surfaces use."""
    if str(TOOLS) not in sys.path:
        sys.path.insert(0, str(TOOLS))
    from fleetcore import loopjob
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    return loopjob.parse_log(text)


class JobManager:
    """Every job this runtime started, with history that survives a restart.

    The index (jobs.json beside the logs) is rewritten on every state change.
    Without it the list vanished with the process while the log files stayed
    in the job dir forever — including the logs of jobs evicted past
    max_jobs — so the directory only ever grew and the page only ever forgot.
    """

    def __init__(self, job_dir: Path = JOB_DIR, max_jobs: int = 200):
        self.job_dir = job_dir
        self.job_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.job_dir / "jobs.json"
        self.jobs: dict[str, Job] = {}
        self.order: list[str] = []
        self.max_jobs = max_jobs
        self._lock = threading.Lock()
        self._io_lock = threading.Lock()
        self._remote_lock = threading.Lock()   # one GitHub-writing job at a time
        self._load()

    # -- persistence --------------------------------------------------------
    def _load(self) -> None:
        try:
            rows = json.loads(self.index_path.read_text())
        except (OSError, ValueError):
            rows = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict) or not _JOB_ID_RX.match(str(row.get("id", ""))):
                continue
            job = Job.from_dict(row, self.job_dir)
            # A job that was queued or running when the last process died has
            # no process to finish it. Say so rather than show it spinning.
            if job.status not in FINISHED_STATES:
                job.status = "interrupted"
            self.jobs[job.id] = job
            self.order.append(job.id)
        # Logs nobody indexes: written by a console that predates the index,
        # or by one that died between the log and the index write. Only files
        # named like a job id, and only once they are a day old — a fresh
        # unindexed log can belong to ANOTHER live process on the same dir
        # (a test run inside the console container deleted the running
        # console's logs exactly that way).
        cutoff = time.time() - ORPHAN_LOG_AGE_S
        for log in self.job_dir.glob("*.log"):
            if _JOB_ID_RX.match(log.stem) and log.stem not in self.jobs:
                try:
                    if log.stat().st_mtime < cutoff:
                        log.unlink(missing_ok=True)
                except OSError:
                    pass
        with self._lock:
            self._evict()
        self._save()

    def _save(self) -> None:
        with self._lock:
            rows = [self.jobs[i].to_dict() for i in self.order if i in self.jobs]
        with self._io_lock:
            tmp = self.index_path.with_suffix(".json.tmp")
            try:
                tmp.write_text(json.dumps(rows))
                tmp.replace(self.index_path)
            except OSError:
                pass   # history is a convenience; a full /tmp must not fail a job

    def _evict(self) -> None:
        """Drop the oldest jobs past max_jobs — and their logs. Caller holds _lock."""
        while len(self.order) > self.max_jobs:
            old = self.jobs.pop(self.order.pop(0), None)
            if old is not None:
                old.log_path.unlink(missing_ok=True)

    def clear(self, statuses: tuple[str, ...] = FINISHED_STATES) -> dict:
        """Forget finished jobs in `statuses`, logs included. Never a live one."""
        bad = set(statuses) - set(FINISHED_STATES)
        if bad:
            raise ValueError(f"only finished jobs can be cleared, not {sorted(bad)}")
        removed = 0
        with self._lock:
            for jid in list(self.order):
                job = self.jobs.get(jid)
                if job is not None and job.status in statuses:
                    self.order.remove(jid)
                    self.jobs.pop(jid, None)
                    job.log_path.unlink(missing_ok=True)
                    removed += 1
        self._save()
        return {"removed": removed, "remaining": len(self.order)}

    def submit(self, op_id: str, params: dict | None = None, confirm: bool = False) -> Job:
        params = params or {}
        argv, remote = build_argv(op_id, params)
        if remote and not confirm:
            raise PermissionError(
                f"'{op_id}' with these parameters writes to GitHub or destroys local data — "
                "resubmit with confirm=true")
        why = op_unavailable(op_id)
        if why:
            raise JobUnavailable(f"'{op_id}' cannot run here: {why}")
        job = Job(op_id, argv, remote, params)
        job.log_path = self.job_dir / f"{job.id}.log"
        exclusive = job.exclusive
        with self._lock:
            if exclusive:
                holder = next((j for j in self.jobs.values() if j.status in ("queued", "running")
                               and getattr(j, "exclusive", None) == exclusive), None)
                if holder is not None:
                    what = (f"is already writing the {exclusive}" if exclusive == "lake"
                            else f"already holds {exclusive} (one local run of a loop at a time)")
                    raise JobConflict(
                        f"'{holder.op}' (job {holder.id}) {what} — wait for it to finish, then run '{op_id}'")
            self.jobs[job.id] = job
            self.order.append(job.id)
            self._evict()
        self._save()
        threading.Thread(target=self._run, args=(job,), daemon=True).start()
        return job

    def _run(self, job: Job) -> None:
        env = job_env()
        lock = self._remote_lock if job.remote else None
        if lock:
            lock.acquire()
        try:
            job.started = dt.datetime.now(dt.timezone.utc)
            job.status = "running"
            self._save()
            with job.log_path.open("w") as log:
                log.write(f"$ {' '.join(job.argv)}\n")
                log.flush()
                try:
                    job.proc = subprocess.Popen(
                        job.argv, cwd=str(REPO_ROOT), stdout=log, stderr=subprocess.STDOUT,
                        env=env, start_new_session=True,
                    )
                    job.exit_code = job.proc.wait()
                except FileNotFoundError as exc:
                    log.write(f"\n[console] cannot start: {exc}\n")
                    job.exit_code = 127
            if job.status == "cancelled":
                pass
            elif job.exit_code == 0:
                job.status = "succeeded"
            else:
                job.status = "failed"
        finally:
            job.finished = dt.datetime.now(dt.timezone.utc)
            if lock:
                lock.release()
            self._save()

    def list(self) -> list[dict]:
        with self._lock:
            return [self.jobs[i].to_dict() for i in reversed(self.order) if i in self.jobs]

    def get(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    def tail(self, job_id: str, offset: int = 0, limit: int = 200_000) -> dict:
        job = self.jobs.get(job_id)
        if job is None:
            raise KeyError(job_id)
        text, new_offset = "", offset
        if job.log_path.exists():
            with job.log_path.open("rb") as fh:
                fh.seek(offset)
                chunk = fh.read(limit)
                new_offset = offset + len(chunk)
                text = chunk.decode("utf-8", "replace")
        out = {"job": job.to_dict(), "text": text, "offset": new_offset,
               "done": job.status in FINISHED_STATES}
        if job.op == "loop-run":
            # parsed ONCE, here (tools/fleetcore/loopjob.py): the page and the
            # TUI render these fields rather than reading the raw lines
            out["loop"] = loop_job_fields(job.log_path)
        if job.op == "assist":
            out["assist"] = assist_job_fields(job)
        return out

    def cancel(self, job_id: str) -> Job:
        job = self.jobs.get(job_id)
        if job is None:
            raise KeyError(job_id)
        if job.proc and job.status == "running":
            job.status = "cancelled"
            try:
                os.killpg(os.getpgid(job.proc.pid), 15)
            except (ProcessLookupError, PermissionError):
                pass
            self._save()
        return job


# --------------------------------------------------------------------------- #
# STARTUP HEALTH — per-project health on a fresh clone
# --------------------------------------------------------------------------- #
# _data/project_health.yml is ephemeral (gitignored, fleetcore/fleet.py SOURCES):
# only `dash-gen health` writes it, so a fresh clone or a console left off for a
# week showed every row's health as blank and the red/amber/green KPIs as 0/0/0
# while triage said 20 repos were red. On startup the console now runs the same
# allowlisted `health` operation itself when the file is missing or older than
# the harness's stale_data_days — as an ordinary job (visible in the Jobs tab,
# cancellable), off the request path, and cancelled after a timeout so a slow or
# unauthenticated GitHub can never hold anything up. CONSOLE_AUTO_HEALTH=0 turns
# it off; CONSOLE_AUTO_HEALTH_TIMEOUT sets the timeout in seconds.
AUTO_HEALTH_TIMEOUT = 300


def health_refresh_reason(root: Path = REPO_ROOT, now: dt.datetime | None = None) -> str | None:
    """Why the health snapshot needs regenerating, or None when it is fresh."""
    if str(TOOLS) not in sys.path:
        sys.path.insert(0, str(TOOLS))
    from fleetcore import fleet as _fleet

    src = next((s for s in _fleet.read_sources(root, now=now) if s.name == "health"), None)
    if src is None or not src.present:
        return "missing"
    if src.age_days is None:
        return "undated"
    if src.stale:
        return f"stale ({src.age_days:.1f}d old, limit {_fleet.stale_days(root):g}d)"
    return None


def auto_health(jobs: "JobManager", root: Path = REPO_ROOT, now: dt.datetime | None = None,
                timeout: float | None = None) -> Job | None:
    """Start the `health` job when the snapshot is missing or stale. Never blocks,
    never raises: a failure to start is reported and the console carries on."""
    if (os.environ.get("CONSOLE_AUTO_HEALTH") or "1").strip().lower() in ("0", "off", "false", "no"):
        return None
    try:
        reason = health_refresh_reason(root, now)
    except Exception as exc:  # a broken signal file must not stop the console starting
        sys.stderr.write(f"[console] health check skipped: {exc}\n")
        return None
    if reason is None:
        return None
    if timeout is None:
        try:
            timeout = float(os.environ.get("CONSOLE_AUTO_HEALTH_TIMEOUT") or AUTO_HEALTH_TIMEOUT)
        except ValueError:
            timeout = AUTO_HEALTH_TIMEOUT
    try:
        job = jobs.submit("health")
    except Exception as exc:
        sys.stderr.write(f"[console] could not start the health job: {exc}\n")
        return None
    sys.stderr.write(f"[console] project health {reason} — generating it (job {job.id}, "
                     f"timeout {timeout:g}s)\n")

    def _expire() -> None:
        if job.status in ("queued", "running"):
            sys.stderr.write(f"[console] health job {job.id} exceeded {timeout:g}s — cancelled\n")
            jobs.cancel(job.id)

    timer = threading.Timer(timeout, _expire)
    timer.daemon = True
    timer.start()
    return job



# --------------------------------------------------------------------------- #
# CONFIG — comment-preserving edits to _data/fleet.yml
# --------------------------------------------------------------------------- #
# The contract is the control plane's own settings, so the console edits it the
# way the fleet edits anything else: an ALLOWLIST of declared knobs, validated
# by type, written back through a round trip that keeps every comment, and
# spliced so the diff covers only the blocks the form touched. Anything not
# listed here (structure, comments, the token contract, policy keys the file
# itself calls non-negotiable) stays a text-editor-and-PR change.
CRON_RX = re.compile(r"^[\d*/,\-]{1,24}( +[\dA-Za-z*/,\-]{1,24}){4}$")
VERSION_RX = re.compile(r"^[0-9][0-9A-Za-z.+\-]{0,31}$")
VALUE_RX = re.compile(r"^[A-Za-z0-9._/@:+\- ]{1,120}$")   # canonical variable values
SLUG_RX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/\-]{0,63}$")


def _f(kind: str, help: str = "", choices: tuple[str, ...] | None = None) -> dict:
    return {"kind": kind, "help": help, "choices": list(choices) if choices else None}


# Sections of _data/fleet.yml the console may edit, in file order. Each field's
# path is relative to its section; the fully qualified key (`section.a.b`) is
# what the API accepts.
CONFIG_SECTIONS: list[dict] = [
    {"key": "toolchain", "title": "Toolchain", "doc": "docs/DASH.md",
     "blurb": "Language versions reusable CI falls back to (caller input → repo vars.* → these).",
     "fields": {
         "node": _f("version", "Node major used by the reusable workflows"),
         "python": _f("version", "Python version"),
         "ruby": _f("version", "Ruby version"),
     }},
    {"key": "schedule", "title": "Schedule (UTC)", "doc": "docs/DAILY-ANALYSIS.md",
     "blurb": "Cron cadence of each control-plane loop. Editing here changes the CONTRACT — "
              "the workflow's own `on: schedule:` is what GitHub obeys, so change both.",
     "fields": {k: _f("cron", d) for k, d in (
         ("fleet_pulse", "gather → publish → remediate"),
         ("build_dash", "republish the Pages site after the data lands"),
         ("issue_pipeline", "intake → implement → complete"),
         ("reconcile_registry", "registry ↔ GitHub reconciliation"),
         ("update_submodules", "daily submodule pointer bump (published directly)"),
         ("rotate_tokens", "weekly credential rotation"),
         ("repo_evolution", "weekly proactive per-repo improvement pass"),
         ("repo_scout", "daily proactive issue proposals — a sample of repos a day"),
     )}},
    {"key": "remediation", "title": "Remediation — the doctor's guardrails", "doc": "docs/DAILY-ANALYSIS.md",
     "blurb": "Blast radius and eligibility of the daily auto-fix loop. Raising max_candidates "
              "without raising the doctor's --max-turns loses the whole day's queue.",
     "fields": {
         "max_candidates": _f("int", "candidates acted on per run"),
         "max_cross_repo": _f("int", "of those, how many may become submodule PRs"),
         "min_runs": _f("int", "ignore workflows with fewer runs in the window"),
         "min_priority": _f("float", "unflagged workflows at/above this are eligible"),
         "slow_avg_min": _f("int", "avg minutes/run that counts as long-running"),
         "slow_p95_min": _f("int", "p95 minutes/run that counts as long-running"),
         "window_days": _f("int", "analytics window"),
         "supersede_on_success": _f("bool", "latest green run drops a failing/flaky flag"),
         "interactive_dispatch_pct": _f("int", "≥ this % hand-dispatched ⇒ cost signals don't apply"),
         "stale_after_days": _f("int", "latest run older than this sorts below live candidates (0 = off)"),
     }},
    {"key": "issue_pipeline", "title": "Issue pipeline — the three tiers", "doc": "docs/ISSUE-PIPELINE.md",
     "blurb": "Per-tier caps, the evidence budget, and the autonomy default. `never_merge` is "
              "deliberately absent: no tier may ever merge.",
     "fields": {
         "enabled": _f("bool", "run the pipeline at all"),
         "tiers.intake.max_issues": _f("int", "issues enriched per run, fleet-wide"),
         "tiers.intake.max_per_repo": _f("int", "…so one noisy backlog can't consume the run"),
         "tiers.implement.max_issues": _f("int", "draft PRs opened per run"),
         "tiers.implement.max_cross_repo": _f("int", "of those, how many land outside the hub"),
         "tiers.complete.max_prs": _f("int", "pipeline PRs driven toward mergeable per run"),
         "evidence.enabled": _f("bool", "build evidence bundles in the virtual environment"),
         "evidence.max_runs": _f("int", "evidence bundles built per run"),
         "evidence.ttl_days": _f("int", "a bundle newer than this is reused"),
         "evidence.timeout_minutes": _f("int", "per phase (clone/install/lint/test/build)"),
         "evidence.screenshots": _f("bool", "capture a page screenshot for web stacks"),
         "readiness.min_score": _f("int", "below this T1 must not pass an issue on"),
         "autonomy.default": _f("choice", "what may proceed unattended", ("auto", "assisted")),
     }},
    {"key": "evolution", "title": "Repo evolution — the weekly proactive loop", "doc": "docs/EVOLUTION.md",
     "blurb": "One Opus agent and one draft PR per target. The model and the turn cap are not edited "
              "here: the step spec (tools/jev/steps/repo-evolution/evolve.yml) references evolution.model and "
              "evolution.max_turns, and the workflow carries both as literals that `python3 -m tools.jev steps "
              "check` holds equal, so a change is a pull request that moves fleet.yml and the workflow together.",
     "fields": {
         "enabled": _f("bool", "run the weekly pass"),
         "skip_when_open_pr": _f("bool", "one open evolution PR per repo is the backpressure"),
         "max_targets": _f("int", "repos evolved per run"),
         "max_parallel": _f("int", "concurrent agents (one OAuth account's rate limit)"),
         "signals.max_issues": _f("int", "issues quoted into each brief"),
         "signals.max_prs": _f("int", "PRs quoted into each brief"),
     }},
    {"key": "harness", "title": "Harness health — scorecard + trip wires", "doc": "docs/HARNESS.md",
     "blurb": "The hub watching itself: pass/fail lines and the aggregate-drift alarms "
              "`dash harness` computes offline from the committed signals.",
     "fields": {
         "scorecard.completion_rate_min_pct": _f("float", "fleet workflow success rate floor"),
         "scorecard.effectiveness_min_pct": _f("float", "minutes ending in success, as a share of all minutes"),
         "trip_wires.stale_data_days": _f("int", "a signal older than this is an alarm"),
         "trip_wires.conformance_stale_days": _f("int", "conformance.yml older than this is an alarm"),
         "trip_wires.pass_rate_floor_pct": _f("float", "fleet-wide quality regression"),
         "trip_wires.waste_ceiling_pct": _f("float", "non-success minutes / total minutes"),
         "trip_wires.cost_spike_multiplier": _f("float", "× the fleet MEDIAN run time = runaway"),
         "trip_wires.cost_spike_min_runs": _f("int", "ignore workflows with fewer runs"),
         "trip_wires.cost_spike_min_avg_min": _f("float", "…and anything cheaper than this on average"),
         "trip_wires.standing_failures_max": _f("int", "red-workflow backlog the doctor can't drain"),
         "trip_wires.credential_grace_days": _f("int", "past max_age + this, a credential is an alarm"),
     }},
    {"key": "harnesses", "title": "Harnesses — the fleet deployment contract", "doc": "docs/HARNESS-OPS.md",
     "blurb": "What every owned repo must carry, how much scheduled agent work the fleet may "
              "commit to, and what the projected spend may grow to before somebody is told.",
     "fields": {
         "baseline.require_mention_handler": _f("bool", "a claude-code-action workflow answering @claude"),
         "baseline.require_agent_context": _f("bool", "CLAUDE.md / AGENTS.md / copilot-instructions / .cursorrules"),
         "baseline.require_oauth_secret": _f("bool", "CLAUDE_CODE_OAUTH_TOKEN present per the rotation ledger"),
         "exempt": _f("list", "repo names excused from the baseline"),
         "throughput.max_scheduled_ai_per_day_fleet": _f("int", "estimated cron-driven AI runs/day, fleet-wide"),
         "throughput.max_scheduled_ai_per_day_repo": _f("int", "the same per repo"),
         "throughput.max_ai_crons_per_utc_hour": _f("int", "AI crons sharing one UTC hour"),
         "budget.monthly_ai_usd": _f("float", "projected monthly Claude CI spend ceiling"),
         "budget.monthly_actions_minutes": _f("int", "projected monthly Actions minutes ceiling"),
         "budget.trend_warn_pct": _f("float", "week-over-week growth beyond this is flagged"),
         "inventory.max_workflow_files": _f("int", "workflow files parsed per repo"),
         "inventory.schedule_limit": _f("int", "rows in the fleet schedule calendar"),
         "attention_max": _f("int", "findings surfaced per run"),
     }},
    {"key": "observability", "title": "Observability — the local planes and the code index", "doc": "docs/OBSERVABILITY.md",
     "blurb": "Retention, disk budget and the portal's pinned dashboards. Changing retention or "
              "rollover here changes only the CONTRACT — re-render and re-install with "
              "`dash observe verify --write` then `dash observe up`, or the cluster keeps expiring "
              "on the old schedule.",
     "fields": {
         "logs.retention_days.actions": _f("int", "days of GitHub Actions log lines"),
         "logs.retention_days.container": _f("int", "days of raw container stdout"),
         "logs.retention_days.app": _f("int", "days of UPS-OPS-10 structured lines"),
         "logs.rollover.max_primary_shard_size": _f("version", "roll an index over at this size"),
         "logs.rollover.max_age": _f("version", "…or this age, whichever comes first"),
         "logs.disk_budget_gb": _f("int", "`observe status` warns past this (ES stops writing at 95% disk)"),
         "logs.ship.batch": _f("int", "documents per bulk POST to Logstash"),
         "logs.ship.logs": _f("choice", "which runs to ship", ("all", "ai", "none")),
         "portal.embed": _f("bool", "embed Kibana + Grafana in the Observe tab, or link out only"),
     }},
    {"key": "ai_auth", "title": "AI auth order — which Claude credential each repo tries first",
     "doc": "docs/AI-INTEGRATION.md",
     "blurb": "The fleet-wide DEFAULT order. Groups and per-repo overrides are structure, so they "
              "are edited in the file by PR; `ai-auth` below shows what every repo resolves to. "
              "Saving here changes only the contract — project it with `ai-auth-sync`.",
     "fields": {
         "default": _f("choice", "tried in turn; the first present (and, for a key, accepted) wins",
                       ("oauth,api_key", "api_key,oauth", "oauth", "api_key")),
     }},
    {"key": "rotation", "title": "Token rotation", "doc": "docs/TOKEN-ROTATION.md",
     "blurb": "The weekly credential loop. `hub_first` is not offered here — the file calls it "
              "non-negotiable, and it is the rule that keeps a bad credential an incident "
              "rather than an outage.",
     "fields": {
         "enabled": _f("bool", "run the weekly pass"),
         "only_stale": _f("bool", "rewrite only what is missing or past max_age_days"),
         "max_repos": _f("int", "0 = no cap (fleet-wide consistency is the point)"),
         "max_failures": _f("int", "abort the remaining writes past this many failures"),
         "fail_on_unreachable": _f("bool", "treat a repo the token cannot see as fatal"),
         "variables.enabled": _f("bool", "propagate canonical repo variables in the same pass"),
         "variables.warn_on_fallback": _f("bool", "say so when the hub lacks a declared variable"),
     }},
    {"key": "variables", "title": "Canonical repository variables", "doc": "docs/TOKEN-ROTATION.md",
     "blurb": "The FALLBACK values (bamr87/bamr87's live settings are authoritative). "
              "Project them with `dash config sync --apply` or the weekly rotation.",
     "fields": {
         "NODE_VERSION": _f("value", "vars.NODE_VERSION"),
         "PYTHON_VERSION": _f("value", "vars.PYTHON_VERSION"),
         "RUBY_VERSION": _f("value", "vars.RUBY_VERSION"),
         "FLEET_HUB": _f("value", "owner/repo of the hub"),
     }},
]

# fully qualified key → field spec
CONFIG_FIELDS: dict[str, dict] = {
    f"{section['key']}.{path}": spec
    for section in CONFIG_SECTIONS for path, spec in section["fields"].items()
}

# Back-compat: the harnesses-relative knobs the Contract API has always taken.
EDITABLE = {path: spec["kind"] for path, spec in
            next(s for s in CONFIG_SECTIONS if s["key"] == "harnesses")["fields"].items()}


def _dig(node, parts: list[str]):
    """Walk a dotted path, returning (parent, leaf, present)."""
    for part in parts[:-1]:
        if not isinstance(node, dict) or part not in node:
            return None, parts[-1], False
        node = node[part]
    if not isinstance(node, dict) or parts[-1] not in node:
        return None, parts[-1], False
    return node, parts[-1], True


def read_config(fleet_path: Path = DATA / "fleet.yml") -> dict:
    """Every editable knob with its current value — the Config tab's document."""
    fleet = load_yaml(fleet_path) or {}
    sections = []
    for section in CONFIG_SECTIONS:
        block = fleet.get(section["key"])
        fields = []
        for path, spec in section["fields"].items():
            parent, leaf, present = _dig(block, path.split("."))
            fields.append({
                "path": path, "key": f"{section['key']}.{path}", "kind": spec["kind"],
                "help": spec["help"], "choices": spec["choices"],
                "value": parent[leaf] if present else None, "present": present,
            })
        sections.append({k: section[k] for k in ("key", "title", "blurb", "doc")} |
                        {"present": isinstance(block, dict), "fields": fields})
    return {"path": str(fleet_path.relative_to(REPO_ROOT)) if fleet_path.is_relative_to(REPO_ROOT)
            else str(fleet_path),
            "sections": sections, "editable": sorted(CONFIG_FIELDS)}


def read_contract(fleet_path: Path = DATA / "fleet.yml") -> dict:
    """The harnesses: block alone, in the shape the Contract API has always returned."""
    fleet = load_yaml(fleet_path) or {}
    return {"harnesses": fleet.get("harnesses") or {}, "editable": sorted(EDITABLE)}


def _coerce(key: str, value):
    """Validate one value against its declared kind. `key` is fully qualified,
    or harnesses-relative (the Contract API's older shape)."""
    spec = CONFIG_FIELDS.get(key) or CONFIG_FIELDS.get(f"harnesses.{key}")
    if spec is None:
        raise ValueError(key)
    kind = spec["kind"]
    if kind == "bool":
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.lower() in ("true", "false"):
            return value.lower() == "true"
        raise ValueError(f"{key} must be true/false")
    if kind == "int":
        try:
            n = int(value)
        except (TypeError, ValueError):
            raise ValueError(f"{key} must be an integer")
        if n < 0:
            raise ValueError(f"{key} must be >= 0")
        return n
    if kind == "float":
        try:
            f = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"{key} must be a number")
        if not math.isfinite(f):     # "inf" and "nan" parse; a .inf ceiling bounds nothing
            raise ValueError(f"{key} must be a finite number")
        if f < 0:
            raise ValueError(f"{key} must be >= 0")
        return int(f) if f.is_integer() else f
    if kind == "list":
        if isinstance(value, str):
            value = [v.strip() for v in value.split(",") if v.strip()]
        if not isinstance(value, list) or not all(isinstance(v, str) and NAME_RX.match(v) for v in value):
            raise ValueError(f"{key} must be a list of repo names")
        return _flow_seq(value)
    if kind == "choice":
        v = str(value).strip()
        if v not in (spec["choices"] or []):
            raise ValueError(f"{key} must be one of {spec['choices']}")
        return v
    if kind in ("cron", "version", "value", "slug"):
        v = str(value).strip()
        rx = {"cron": CRON_RX, "version": VERSION_RX, "value": VALUE_RX, "slug": SLUG_RX}[kind]
        if not rx.match(v):
            raise ValueError(f"{key} must match {rx.pattern}")
        return v
    raise ValueError(key)


def _flow_seq(items: list):
    """A list written inline (`exempt: [a, b]`), matching fleet.yml's own style.

    Not cosmetic: these keys carry a trailing `# comment`, and ruamel emits a
    BLOCK sequence's items after the comment paragraph that follows the key —
    so `exempt:` and its entries end up separated by the next section's
    comment. Still valid YAML, but it reads as though the comment owns the
    list. A flow sequence cannot be split from its key.
    """
    try:
        from ruamel.yaml.comments import CommentedSeq
    except ImportError:                       # pragma: no cover - plain list still works
        return items
    seq = CommentedSeq(items)
    seq.fa.set_flow_style()
    return seq


_AMBIGUOUS_SCALAR_RX = re.compile(
    r"^(-?\d+(\.\d+)?|true|false|yes|no|on|off|null|~)$", re.IGNORECASE)


def _styled(old, value: str):
    """Write a string back in the quoting style the file already used.

    `node: "20"` must not come back as `node: '20'` (a needless diff line) and a
    plain `FLEET_HUB: bamr87/bamr87` must not gain quotes it never had. A value
    YAML would read back as a number or a bool is quoted whatever the old style
    was — that is correctness, not cosmetics.
    """
    try:
        from ruamel.yaml.scalarstring import DoubleQuotedScalarString as DQ
        from ruamel.yaml.scalarstring import SingleQuotedScalarString as SQ
    except ImportError:                       # pragma: no cover
        return value
    if isinstance(old, DQ):
        return DQ(value)
    if isinstance(old, SQ):
        return SQ(value)
    return DQ(value) if _AMBIGUOUS_SCALAR_RX.match(value) else value


def update_config(changes: dict, fleet_path: Path = DATA / "fleet.yml") -> dict:
    """Apply validated changes to fleet.yml, preserving every comment (ruamel
    round-trip) and splicing back only the top-level blocks that changed.

    Keys are fully qualified (`remediation.max_candidates`); a bare key is read
    as harnesses-relative, which is what the older Contract API sends.
    """
    try:
        from ruamel.yaml import YAML
    except ImportError:
        raise RuntimeError("config editing needs ruamel.yaml (pip install ruamel.yaml)")
    resolved: dict[str, str] = {}
    for key in changes:
        if key in CONFIG_FIELDS:
            resolved[key] = key
        elif f"harnesses.{key}" in CONFIG_FIELDS:
            resolved[key] = f"harnesses.{key}"
        else:
            raise ValueError(f"not editable from the console: {key}")
    yml = YAML(typ="rt")
    yml.preserve_quotes = True
    yml.width = 4096
    # Match fleet.yml's own layout, or the round trip "fixes" the whole file:
    # ruamel's default puts a block sequence's dash at the parent's indent,
    # while this file indents it (`tokens:` / `  - name:`), so a one-field edit
    # came back as a 188-line reindent of every list in the document.
    yml.indent(mapping=2, sequence=4, offset=2)
    original = fleet_path.read_text()
    doc = yml.load(original)
    applied: dict[str, object] = {}
    touched: list[str] = []
    for key, full in resolved.items():
        coerced = _coerce(full, changes[key])
        parts = full.split(".")
        if parts[0] not in doc:
            raise ValueError(f"fleet.yml has no {parts[0]}: block")
        parent, leaf, present = _dig(doc[parts[0]], parts[1:])
        if not present:
            raise ValueError(f"fleet.yml {full} is not declared; add it by hand first")
        if isinstance(coerced, str):
            coerced = _styled(parent[leaf], coerced)
        if parent[leaf] != coerced:
            parent[leaf] = coerced
            applied[key] = str(coerced) if isinstance(coerced, str) else coerced
            if parts[0] not in touched:
                touched.append(parts[0])
    if applied:
        buf = io.StringIO()
        yml.dump(doc, buf)
        rewritten = buf.getvalue()
        text = original
        for block_key in touched:
            spliced = _splice_block(text, rewritten, block_key)
            if spliced is None:               # a shape we don't recognise
                text = rewritten
                break
            text = spliced
        fleet_path.write_text(text)
    rc, diff = run_quiet(["git", "diff", "--no-color", "--", str(fleet_path)])
    return {"applied": applied, "sections": touched, "diff": diff if rc == 0 else ""}


def update_contract(changes: dict, fleet_path: Path = DATA / "fleet.yml") -> dict:
    """The harnesses-scoped half of update_config (the Contract API's shape)."""
    unknown = sorted(k for k in changes if f"harnesses.{k}" not in CONFIG_FIELDS)
    if unknown:
        raise ValueError(f"not editable from the console: {', '.join(unknown)}")
    result = update_config({f"harnesses.{k}": v for k, v in changes.items()}, fleet_path)
    return {"applied": {k.split(".", 1)[1]: v for k, v in result["applied"].items()},
            "diff": result["diff"]}


def _top_level_block(text: str, key: str) -> tuple[int, int] | None:
    """Line span [start, end) of a top-level `key:` block, its comments included."""
    lines = text.splitlines(keepends=True)
    start = next((i for i, ln in enumerate(lines) if ln.startswith(f"{key}:")), None)
    if start is None:
        return None
    for i in range(start + 1, len(lines)):
        # the next top-level key ends the block; blanks and indented lines don't
        if lines[i][:1] not in (" ", "\t", "\n", "#") and lines[i].strip():
            return start, i
    return start, len(lines)


def _splice_block(original: str, rewritten: str, key: str) -> str | None:
    """Put only `key:`'s block from the rewritten document back into the original.

    Even correctly configured, a ruamel round trip renormalises things it was
    never asked to touch — here it re-joined two hand-wrapped `used_by:` flow
    lists in the read-only `tokens:` block. The console's promise is that saving
    shows you a diff you can read and commit, so the write is confined to the
    blocks the form edited; everything else stays byte-identical. Returns None
    when either document's shape isn't recognisable, so the caller can fall
    back to the whole round trip rather than guess.
    """
    a, b = _top_level_block(original, key), _top_level_block(rewritten, key)
    if not a or not b:
        return None
    src, dst = original.splitlines(keepends=True), rewritten.splitlines(keepends=True)
    return "".join(src[:a[0]] + dst[b[0]:b[1]] + src[a[1]:])


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
AUTH_WRITES = (os.environ.get("DASH_CONSOLE_AUTH", "on").strip().lower()
               not in ("0", "off", "false", "no"))
ENV_FILE = Path(os.environ.get("DASH_CONSOLE_ENV_FILE") or (REPO_ROOT / ".env"))

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
    path = path or ENV_FILE                    # resolved per call, so tests can redirect it
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
    path = path or ENV_FILE
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
    path = path or ENV_FILE
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
    rc, out = run_quiet(["gh", "auth", "status"], timeout=20)
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
    supplied = _env_file_set_names() if ENV_FILE.exists() else set()
    creds = []
    for name, spec in CREDENTIALS.items():
        present = bool(os.environ.get(name))
        creds.append({
            "name": name, "label": spec["label"], "help": spec["help"], "url": spec["url"],
            "present": present,
            "source": ("session" if name in _SESSION_CREDS else "environment") if present else None,
            "in_env_file": name in in_file,
        })
    rc_tracked, tracked = run_quiet(["git", "ls-files", "--error-unmatch", str(ENV_FILE)])
    return {
        "credentials": creds,
        "github": _gh_status(),
        "claude": {"cli": shutil.which("claude") is not None,
                   "oauth": bool(os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")),
                   "api_key": bool(os.environ.get("ANTHROPIC_API_KEY")),
                   "mint": "claude setup-token"},
        "env_file": {"path": str(ENV_FILE), "exists": ENV_FILE.exists(),
                     "tracked_by_git": rc_tracked == 0, "names": sorted(in_file)},
        # What `dash secrets push` would take from .env: the contract's names,
        # each with its scope and whether the file supplies a value for it.
        "push": [{**t, "in_env_file": t["name"] in supplied} for t in contract_secrets()],
        "writes_enabled": AUTH_WRITES,
        "console_token_required": bool(os.environ.get("DASH_CONSOLE_TOKEN")),
    }


def _check_writes() -> None:
    if not AUTH_WRITES:
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
            raise PermissionError(f"writing {name} to {ENV_FILE.name} needs confirm=true")
        rc, _ = run_quiet(["git", "ls-files", "--error-unmatch", str(ENV_FILE)])
        if rc == 0:
            raise ValueError(f"{ENV_FILE} is tracked by git — the console will not write a "
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
    if purge and ENV_FILE.exists():
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
            cwd=str(REPO_ROOT), env=env)
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
                              timeout=30, cwd=str(REPO_ROOT))
    except subprocess.TimeoutExpired:
        raise RuntimeError("gh auth logout timed out (it wanted an answer the console can't give)")
    return {"ok": proc.returncode == 0,
            "message": _scrub((proc.stdout or "") + (proc.stderr or "")) or "signed out",
            "auth": auth_status()}



# --------------------------------------------------------------------------- #
# REFINE documents — /api/refine, /api/refine/evidence/…, /api/refine/library, /api/assist
# --------------------------------------------------------------------------- #
def _rel(path, base: Path = REPO_ROOT) -> str:
    """A path as hub-relative text; an outside one by name only (never a local absolute path in a document)."""
    try:
        return str(Path(path).resolve().relative_to(base.resolve()))
    except (ValueError, OSError):
        return Path(str(path)).name


def _runs_dir() -> Path:
    return Path(os.environ.get("JEV_RUNS_DIR") or REPO_ROOT / ".fleet" / "runs")


def _refine_dir() -> Path:
    return Path(os.environ.get("JEV_REFINE_DIR") or REPO_ROOT / ".fleet" / "refine")


def _load_json(path: Path):
    """A JSON file's document, or None (missing, unreadable, not JSON)."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _jsonable(obj):
    """dataclasses and Paths in a plan → JSON values."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return _jsonable(dataclasses.asdict(obj))
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, Path):
        return _rel(obj)
    return obj


def refine_surface_hub(fleet: dict) -> dict:
    _R, Sf, _L, _SP = _jev()
    rep = Sf.check(REPO_ROOT, fleet=fleet)
    return {"root": "bamr87/bamr87", **rep.to_dict()}


def refine_fleet_surface(fleet: dict, *, max_age_s: float = 300.0) -> dict:
    """`refine surface fleet` over every checked-out submodule, cached (it reads ~45 trees)."""
    now = time.time()
    if _REFINE_CACHE["fleet"] is not None and now - _REFINE_CACHE["fleet_at"] < max_age_s:
        return _REFINE_CACHE["fleet"]
    R, _Sf, _L, _SP = _jev()
    try:
        doc = R.fleet_surfaces(fleet=fleet)
    except Exception as exc:  # noqa: BLE001 — a sweep that fails is reported, never raised into the page
        doc = {"schema": "jev-fleet-surface/v1", "repos": [], "totals": {}, "error": f"{type(exc).__name__}: {exc}"}
    _REFINE_CACHE.update(fleet_at=now, fleet=doc)
    return doc


def refine_plans(fleet: dict, *, budget: bool) -> list[dict]:
    """One k=1 plan per loop with a local agent step, in the configured mode; a loop whose plan fails
    is a row with its error, never a missing page."""
    R, _Sf, _L, _SP = _jev()
    rows = []
    for st in agent_steps():
        loop, step = st["loop"], st["step"]
        try:
            p = R.plan(loop, step=step, k=1, budget=budget, fleet=fleet)
            lib = dict(p["library"])
            lib["root"] = _rel(lib.get("root", ""))
            rows.append({"loop": loop, "step": p["step"], "call_site": p["call_site"], "k": p["k"], "mode": p["mode"],
                         "identity": p["identity"], "cost": p["cost"], "budget": p["budget"] if budget else {"available": False},
                         "tunable": p["tunable"], "hard_rules": p["hard_rules"], "library": lib,
                         "proposer": p["proposer"], "model_backed": p["model_backed"], "steps": p["steps"],
                         "finals": p["finals"], "error": None})
        except Exception as exc:  # noqa: BLE001
            rows.append({"loop": loop, "step": step, "error": f"{type(exc).__name__}: {exc}"[:400]})
    return rows


def refine_library(fleet: dict, *, local: bool) -> dict:
    R, _Sf, L, _SP = _jev()
    root = L.root(fleet)
    entries = []
    problems: list[str] = []
    try:
        for loop, domain, e in L.all_entries(root):
            entries.append({"loop": loop, "domain": domain, **e.to_dict(),
                            "has_diff": (L.Library(root, loop, domain).entry_dir(e.id) / L.DIFF_FILE).is_file()})
    except Exception as exc:  # noqa: BLE001
        problems.append(f"{type(exc).__name__}: {exc}"[:300])
    uncommitted: list[str] = []
    if local:
        code, out = run_quiet(["git", "status", "--porcelain", "--", _rel(root)], timeout=20)
        if code == 0:
            uncommitted = [line[3:].strip() for line in out.splitlines() if line.strip()]
    return {"root": _rel(root), "entries": entries, "count": len(entries), "problems": problems,
            "uncommitted": uncommitted, "schema": L.SCHEMA_ID}


def refine_evidence_list() -> list[dict]:
    """Every evidence tree under .fleet/refine, newest first, by its manifest (never a local path)."""
    base = _refine_dir()
    rows = []
    if not base.is_dir():
        return rows
    for d in sorted((p for p in base.iterdir() if p.is_dir() and STAMP_RX.match(p.name)), reverse=True):
        m = _load_json(d / "evidence.json")
        if not isinstance(m, dict):
            continue
        rows.append({"stamp": d.name, "loop": m.get("loop"), "step": m.get("step"), "item": m.get("item"),
                     "domain": m.get("domain"), "stage": m.get("stage"), "k": m.get("k"),
                     "generated_at": m.get("generated_at"), "files": len(m.get("files") or {}),
                     "rollouts": [r.get("label") for r in (m.get("rollouts") or []) if isinstance(r, dict)],
                     "library_entries": m.get("library_entries"), "redacted": m.get("redacted")})
    return rows


def refine_reviews(*, local: bool) -> list[dict]:
    """The review queue: every local loop-run attempt whose dry-run preview (`publish-plan.md`) has not
    been filed — what `loop-run` with run_id + apply would file after a person reads it. From
    .fleet/runs (local only): run.json's items and attempts.jsonl's publish-apply rows."""
    if not local:
        return []
    base = _runs_dir()
    if not base.is_dir():
        return []
    steps = {(s["loop"], s["step"]): s for s in agent_steps()}
    published: set[tuple[str, str, str, str]] = set()
    runs: list[tuple[str, dict, list[dict]]] = []
    for d in sorted((p for p in base.iterdir() if p.is_dir() and (p / "run.json").is_file()), reverse=True):
        meta = _load_json(d / "run.json")
        if not isinstance(meta, dict):
            continue
        rows: list[dict] = []
        try:
            for line in (d / "attempts.jsonl").read_text(encoding="utf-8").splitlines():
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if isinstance(r, dict):
                    rows.append(r)
        except OSError:
            pass
        for r in rows:
            if r.get("decision") == "publish-apply" and r.get("published") and r.get("validated_sha256"):
                published.add((str(r.get("loop")), str(r.get("step")), str(r.get("item")), str(r["validated_sha256"])))
        runs.append((d.name, meta, rows))
    out = []
    for run_id, meta, rows in runs:
        loop, step = str(meta.get("loop") or ""), str(meta.get("step") or "")
        for it in meta.get("items") or []:
            if not isinstance(it, dict) or it.get("status") != "previewed" or not it.get("publishable"):
                continue
            key = str(it.get("key") or "")
            attempt = next((r for r in rows if r.get("decision") == "attempt" and r.get("item") == key), {})
            sha = str(attempt.get("validated_sha256") or "")
            if sha and (loop, step, key, sha) in published:
                continue
            item_dir = str(it.get("dir") or "")
            bodies_dir = base / run_id / "items" / item_dir / "bodies"
            bodies = []
            if item_dir and bodies_dir.is_dir():
                for b in sorted(bodies_dir.glob("*.md")):
                    # the filer names each body by its issue title's slug (NN-<slug>.md)
                    title = re.sub(r"^\d+-", "", b.stem).replace("-", " ").strip()
                    bodies.append({"file": b.name, "title": title[:160]})
            st = steps.get((loop, step)) or {}
            out.append({"run_id": run_id, "loop": loop, "step": step, "item": key, "name": it.get("name"),
                        "dir": item_dir, "status": it.get("status"), "reason": it.get("reason"),
                        "would_file": (it.get("facts") or {}).get("would_file") if isinstance(it.get("facts"), dict) else None,
                        "plan_id": it.get("plan_id"), "cost_usd": it.get("cost_usd"), "cost_label": COST_LABEL,
                        "finished": meta.get("finished"), "head_sha": attempt.get("head_sha"),
                        "can_apply": bool(st.get("can_apply")), "publish_tier": st.get("publish_tier"),
                        "bodies": bodies, "preview": f"items/{item_dir}/publish-plan.md" if item_dir else None})
    return out


REVIEW_FILE_RX = re.compile(r"^(?:summary\.md|items/[A-Za-z0-9._-]+/(?:publish-plan\.md|bodies/[A-Za-z0-9._-]+\.md))$")
MAX_TEXT_CHARS = 200_000


def refine_review_file(run_id: str, rel: str) -> dict:
    """A reviewed preview's text: the run's summary, an item's publish-plan.md or one body (local only)."""
    if not RUN_ID_RX.fullmatch(run_id or ""):
        raise ValueError("run_id is not a run id")
    if not REVIEW_FILE_RX.match(rel or ""):
        raise ValueError("path must be summary.md, items/<dir>/publish-plan.md or items/<dir>/bodies/<name>.md")
    p = _runs_dir() / run_id / rel
    if p.is_symlink() or not p.is_file():
        raise ValueError(f"no {rel} in run {run_id}")
    text = p.read_text(encoding="utf-8", errors="replace")
    return {"run_id": run_id, "path": rel, "text": text[:MAX_TEXT_CHARS], "truncated": len(text) > MAX_TEXT_CHARS}


def refine_evidence_doc(stamp: str) -> dict:
    if not STAMP_RX.match(stamp or ""):
        raise ValueError("stamp is not an evidence tree id")
    d = _refine_dir() / stamp
    m = _load_json(d / "evidence.json")
    if not d.is_dir() or not isinstance(m, dict):
        raise ValueError(f"no evidence tree {stamp}")
    files = sorted(m.get("files") or {})
    return {"stamp": stamp, "manifest": {k: v for k, v in m.items() if k != "files"}, "files": files,
            "bytes": {k: (m["files"][k] or {}).get("bytes") for k in files}}


def refine_evidence_file(stamp: str, rel: str) -> dict:
    doc = refine_evidence_doc(stamp)
    if rel not in doc["files"]:
        raise ValueError(f"{rel} is not a file of evidence tree {stamp}")
    p = _refine_dir() / stamp / rel
    if p.is_symlink() or not p.is_file():
        raise ValueError(f"{rel} is gone from evidence tree {stamp}")
    text = p.read_text(encoding="utf-8", errors="replace")
    return {"stamp": stamp, "path": rel, "text": text[:MAX_TEXT_CHARS], "truncated": len(text) > MAX_TEXT_CHARS}


def refine_library_add(payload: dict) -> dict:
    """Write one experience entry on the working tree (the human-gated inbox): validated and
    leak-checked by tools.jev.library, never committed from here."""
    R, _Sf, L, SP = _jev()
    if not isinstance(payload, dict):
        raise ValueError("a JSON object")
    fields = {k: str(payload.get(k) or "").strip() for k in ("loop", "step", "domain", "item", "run_id", "adopted",
                                                               "date", "source", "cue", "lesson", "evidence",
                                                               "confidence", "notes")}
    edits = payload.get("edits") or []
    if not isinstance(edits, list):
        raise ValueError("edits must be a list")
    entry = L.Entry(loop=fields["loop"], step=fields["step"], domain=L.domain_dir(fields["domain"]), item=fields["item"],
                    run_id=fields["run_id"], adopted=fields["adopted"],
                    date=fields["date"] or dt.date.today().isoformat(), source=fields["source"] or "human",
                    cue=fields["cue"], lesson=fields["lesson"], evidence=fields["evidence"],
                    confidence=fields["confidence"], notes=fields["notes"],
                    edits=[L.Edit.from_dict(e) for e in edits if isinstance(e, dict)])
    diff = payload.get("diff")
    if diff is not None and not isinstance(diff, str):
        raise ValueError("diff must be text")
    fleet = SP.load_fleet()
    root = L.root(fleet)
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from tools.jev import loop as jev_loop  # noqa: PLC0415
    try:
        d = L.Library(root, entry.loop, entry.domain).add(entry, diff=diff or None, ctx=jev_loop.host_ctx())
    except L.LibraryError as exc:
        raise ValueError(str(exc)) from exc
    return {"path": _rel(d), "entry": entry.to_dict(), "uncommitted": True,
            "next": "review it, then commit on a branch: a lesson reaches main by a pull request"}


def refine_doc(*, local: bool = True, max_age_s: float = 60.0) -> dict:
    """The Refine page's document: the hub's surface check, the fleet sweep, one plan per loop, the
    library, the evidence trees and the review queue. Local paths never appear; the public snapshot
    gets no evidence, reviews or ledger position."""
    now = time.time()
    if local and _REFINE_CACHE["doc"] is not None and now - _REFINE_CACHE["at"] < max_age_s:
        return _REFINE_CACHE["doc"]
    R, _Sf, _L, SP = _jev()
    fleet = SP.load_fleet()
    try:
        cfg = _jsonable(R.config(fleet))
        cfg_error = None
    except Exception as exc:  # noqa: BLE001
        cfg, cfg_error = None, f"{type(exc).__name__}: {exc}"[:300]
    doc = {
        "schema": "refine-doc/v1", "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "local": local, "config": cfg, "config_error": cfg_error,
        "surface": refine_surface_hub(fleet),
        "fleet_surface": refine_fleet_surface(fleet),
        "plans": refine_plans(fleet, budget=local),
        "library": refine_library(fleet, local=local),
        "evidence": refine_evidence_list() if local else [],
        "reviews": refine_reviews(local=local),
        "missions": {name: R.mission_sha256(name)[:12] for name in R.MISSIONS},
        "stages": list(REFINE_STAGES), "modes": list(REFINE_MODES), "cost_label": COST_LABEL,
    }
    doc = _jsonable(doc)
    if local:
        _REFINE_CACHE.update(at=now, doc=doc)
    return doc


def assist_doc(*, local: bool = True) -> dict:
    """The Assist page's document: the assistant's configuration and why it cannot run here, if it cannot."""
    try:
        cfg = dict(assistant_config())
        error = None
    except ValueError as exc:
        cfg, error = None, str(exc)
    return {"schema": "assist-doc/v1", "config": cfg, "config_error": error, "cost_label": COST_LABEL,
            "unavailable": (assist_unavailable() if local else "The assistant runs on the operator's machine."),
            "mcp_server": "fleet", "allowed_tools": list(ASSIST_ALLOWED), "denied_tools": list(ASSIST_DENIED),
            "prompt_sha256": hashlib.sha256(ASSIST_PROMPT.read_bytes()).hexdigest()[:12] if ASSIST_PROMPT.is_file() else None,
            "max_question_chars": ASSIST_MAX_CHARS, "local": local}
