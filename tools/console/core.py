#!/usr/bin/env python3
"""
core — the console's pure logic, kept free of any web framework so
test_console.py runs on a bare interpreter with only PyYAML.

This file is the front door of that logic. Two things live here, with the
paths, constants and helpers every section shares:

  STATE      one read of every committed fleet signal under _data/ — the same
             files the Jekyll boards render — folded into the single JSON
             document the front end paints from, plus git/working-tree facts.
  OPS        the operation ALLOWLIST. This is the console's whole security
             posture: it can run exactly these argv shapes and nothing else —
             no shell strings, no free-form commands, parameters validated by
             regex/range before they reach an argv. Everything is a tools/
             entrypoint the CLI and CI already run, so the console adds a
             surface, never a code path.

The rest lives in five sibling modules, loaded at the end of this file. Every
name of theirs is importable from here, as it was when they were sections of
this file, so a caller writes `core.<name>` and never names a sibling:

  core_adapters.py  the documents a page reads through dash-gen and fleetcore:
                    capabilities, lake, observability, project, content, nodes,
                    workflows, work, sprints, voices.
  core_jobs.py      JOBS: asynchronous subprocess jobs with on-disk logs, the
                    confirm gate, each job's derived status, startup health.
  core_config.py    CONFIG: the comment-preserving editor for _data/fleet.yml,
                    limited to the declared knobs of CONFIG_SECTIONS.
  core_auth.py      AUTH: credentials supplied through the UI (CREDENTIALS).
  core_refine.py    the Refine and Assist pages' documents, and the view of an
                    `assist` job.

What stays in this file, and why:

  * every name a test or tools/evals.py REBINDS on this module: REPO_ROOT,
    DATA, JOB_DIR, LAKE_DIR, WORK_QUEUE, ROADMAP, AUTH_WRITES, ENV_FILE,
    run_quiet, load_yaml, claude_unavailable, assistant_config. A sibling
    reads each as `core.<name>` when it is called, so there is one copy and
    rebinding it here reaches every reader, moved or not. (`auto_health`,
    which tests also replace, is core_jobs.py's: nothing in a sibling calls
    it, and app.py reaches it as `core.auto_health`, which is what they set);
  * the OPS table and every argv builder it names: tools/fleetcore/graph.py
    reads both from this file's source.

A name DEFINED in a sibling is another matter: this file only re-exports it,
so a test that replaces one patches the sibling that defines it. And `core` is
imported first: a sibling refuses to load before it.
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
if str(TOOLS) not in sys.path:  # tools/fleetcore, the core every surface shares
    sys.path.insert(0, str(TOOLS))
from fleetcore import assistlog  # noqa: E402  (the assistant's records, read back: page audit + ledger)
from fleetcore import yamlio  # noqa: E402
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
                      "weekly-closeout", "weekly-gather", "weekly-finalize", "build-dash", "reconcile-registry",
                      "update-submodules", "backlog-fanout", "jev-conflicts", "fleet-pm")


# --------------------------------------------------------------------------- #
# yaml + time helpers
# --------------------------------------------------------------------------- #
def load_yaml(path: Path):
    """A committed signal, parsed once per version of the file (fleetcore.yamlio):
    a request reads the same ten files the last one did. Absent or unreadable is None."""
    try:
        return yamlio.load(path)
    except (yaml.YAMLError, OSError):
        return None


def _dash_gen_on_path() -> None:
    """dash-gen's modules are imported by bare name. Once: these helpers run on
    every request, and an insert per call grew sys.path without bound."""
    if str(DASH_GEN_DIR) not in sys.path:
        sys.path.insert(0, str(DASH_GEN_DIR))


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


# The Overview's trend is the registry file's own git history: fleet-pulse
# commits _data/harness_registry.yml once a day, so each commit touching it is
# one day's reading, and the `totals:` and `trends:` blocks (two flat mappings
# near the top) are all a sparkline needs. They are sliced out by text before
# YAML sees them, so thirty 200 KB files cost a quarter of a second, once per
# HEAD; a shallow clone (the published page's build) yields one point and the
# page says so. Nothing new is committed: the ledger IS the file's history.
HISTORY_COMMITS = 45
HISTORY_TTL = 300.0
HISTORY_FILE = "_data/harness_registry.yml"
_HISTORY: dict = {}
_HISTORY_LOCK = threading.Lock()


def _top_block(text: str, key: str) -> dict:
    """The top-level mapping `key:` of a YAML document, parsed on its own ({} when absent or not a mapping)."""
    m = re.search(rf"^{re.escape(key)}:[^\n]*\n((?:[ \t][^\n]*\n|[ \t]*\n)*)", text, re.M)
    if not m:
        return {}
    try:
        doc = yaml.safe_load(f"{key}:\n{m.group(1)}") or {}
    except yaml.YAMLError:
        return {}
    block = doc.get(key) if isinstance(doc, dict) else None
    return block if isinstance(block, dict) else {}


def registry_history(limit: int = HISTORY_COMMITS) -> dict:
    """One point per day the registry was committed, oldest first (the latest commit of a day wins)."""
    with _HISTORY_LOCK:
        rc, head = run_quiet(["git", "log", "-1", "--format=%H", "--", HISTORY_FILE])
        head = head.strip()
        if rc != 0 or not head:
            return {"source": "none", "points": [], "reason": "no git history for the registry here"}
        cached = _HISTORY.get("doc")
        if cached and _HISTORY.get("head") == head and time.monotonic() - _HISTORY["at"] < HISTORY_TTL:
            return cached
        rc, log = run_quiet(["git", "log", f"-{int(limit)}", "--format=%H %cI", "--", HISTORY_FILE])
        points: list[dict] = []
        seen_days: set[str] = set()
        for line in (log.splitlines() if rc == 0 else []):
            sha, _, at = line.strip().partition(" ")
            day = at[:10]
            if not sha or day in seen_days:
                continue
            rc2, text = run_quiet(["git", "show", f"{sha}:{HISTORY_FILE}"], timeout=10)
            if rc2 != 0:
                continue
            seen_days.add(day)
            totals, trends = _top_block(text, "totals"), _top_block(text, "trends")
            ai = trends.get("ai_cost_usd") if isinstance(trends.get("ai_cost_usd"), dict) else {}
            mins = trends.get("actions_minutes") if isinstance(trends.get("actions_minutes"), dict) else {}
            points.append({
                "at": day, "commit": sha[:10],
                "attention": totals.get("attention"),
                "harnesses_graded": totals.get("harnesses_graded"),
                "harnesses_conformant": totals.get("harnesses_conformant"),
                "baseline_ok": totals.get("baseline_ok"),
                "ai_projected_monthly": ai.get("projected_monthly"),
                "actions_projected_monthly": mins.get("projected_monthly"),
            })
        points.reverse()
        doc = {"source": "git", "points": points, "days": len(points),
               "note": f"one point per day {HISTORY_FILE} was committed, oldest first; a shallow clone has one"}
        _HISTORY.update(at=time.monotonic(), head=head, doc=doc)
        return doc


def describe_cron(cron: str) -> str:
    """Reuse dash-gen's cron helpers when importable (same repo, same math)."""
    try:
        _dash_gen_on_path()
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
     "outputs": ["issue_pipeline"], "local_ops": ["issues", "evidence"]},
    {"id": "jev_conflicts", "title": "Merge conflicts — JEV's tiers (script, then a capped model, then a human)",
     "workflow": "jev-conflicts", "schedule_key": "jev_conflicts", "doc": "docs/JEV.md",
     "outputs": [], "local_ops": ["conflicts", "conflicts-resolve"]},
    {"id": "fleet_pm", "title": "PM review — issues, pull requests, roadmap and releases", "workflow": "fleet-pm",
     "schedule_key": "fleet_pm", "doc": "docs/PM.md", "outputs": [], "local_ops": ["pm"]},
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
    {"id": "weekly_closeout", "title": "Weekly close-out — Friday cleanup of open work", "workflow": "weekly-closeout",
     "schedule_key": "weekly_closeout", "doc": "docs/WEEKLY-CLOSEOUT.md",
     "outputs": [], "local_ops": ["triage", "decisions-refresh"]},
    {"id": "weekly_gather", "title": "Weekly gather — Saturday draft of next week's plan", "workflow": "weekly-gather",
     "schedule_key": "weekly_gather", "doc": "docs/WEEKLY-CLOSEOUT.md",
     "outputs": [], "local_ops": ["decisions"]},
    {"id": "weekly_finalize", "title": "Weekly finalize — Sunday week-ahead brief", "workflow": "weekly-finalize",
     "schedule_key": "weekly_finalize", "doc": "docs/WEEKLY-CLOSEOUT.md",
     "outputs": [], "local_ops": ["decisions"]},
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
            "repos_scanned": triage.get("repos_scanned"),
            "totals": triage.get("totals") or {},
            "inbox": (triage.get("inbox") or [])[:20],
            "inbox_total": len(triage.get("inbox") or []),
        },
        # the Overview's trends: the registry file's git history (registry_history)
        "history": registry_history(),
        "pipeline": {"generated_at": pipeline.get("generated_at"), "totals": pipeline.get("totals") or {}},
        "rotation": {
            "generated_at": rotation.get("generated_at"),
            "tokens": [
                {k: t.get(k) for k in ("name", "scope", "oldest_age_days", "max_age_days", "counts", "attention")}
                for t in (rotation.get("tokens") or []) if isinstance(t, dict)
            ],
        },
        "usage": {
            # `minutes_basis` says what the minutes ARE (job-minutes since
            # actions-usage/v2; absent = the v1 wall clock); `parity` sets them
            # against the billing meter, and the AI ledger against claude-cost's
            # result lines; `coverage` says whether the sweep saw the whole window.
            "actions": {**{k: actions.get(k) for k in ("generated_at", "window_days", "totals", "by_day",
                                                         "schema", "minutes_basis", "parity")},
                        "coverage": _coverage_summary(actions.get("coverage"))},
            "ai": {**{k: ai.get(k) for k in ("generated", "window_days", "totals", "by_day", "parity")},
                   "coverage": _coverage_summary(ai.get("coverage"))},
        },
        "subscription": _subscription_block(fleet, ai, now),
        "loops": loop_cards(fleet, sources),
        "git": git_info(),
    }


def _coverage_summary(cov) -> dict | None:
    """A sweep's coverage without its per-repo rows: was anything truncated or
    sampled, and which repos. The rows stay in the committed file."""
    if not isinstance(cov, dict):
        return None
    keep = ("truncated", "runs_missed", "truncated_repos", "sampled", "sampled_repos")
    out = {k: cov.get(k) for k in keep if k in cov}
    api = cov.get("api")
    if isinstance(api, dict):
        out["api_calls"] = api.get("calls_total")
    return out


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
# THE PAGE DOCUMENTS — capabilities, lake, observability, project, content,
# nodes, workflows, work, sprints and voices live in core_adapters.py. What
# stays here from those sections is what must: the two paths tests rebind on
# this module, and the argv builders the OPS table names.
# --------------------------------------------------------------------------- #
# CONTENT's own `_rel`. REFINE documents (core_refine.py) defines the name again
# and this file binds that one at its end, so every caller has always had that
# one and this definition is unreached: kept as it was, not removed by the split.
def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


# WORK's two files (the board itself is core_adapters.py): tests point both elsewhere
# by rebinding them here, so they have one home and the adapters read core.WORK_QUEUE.
WORK_QUEUE = Path(os.environ.get("DASH_WORK_QUEUE") or (DATA / "work_queue.yml"))
ROADMAP = DATA / "roadmap.yml"


# CONTENT's two operations (OPS `content-sync`, `content-file`).
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


# VOICES' one operation (OPS `voices-pr`): it files the bytes core_adapters.voices_stage
# staged, found through `VOICES_PLAN_RX` and `voices_stage_dir`, which that module defines.
def _voices_pr(params: dict) -> list[str]:
    """`tools/voices.py pr --file <staged> --plan-id <id> [--apply]`. The staged
    bytes must exist (POST /api/voices/stage, which also runs the preview), so a
    filing is always the exact bytes someone reviewed; `scheduled` is never a
    console parameter, and the filer refuses `--scheduled` with `--apply` too."""
    if "scheduled" in params:
        raise ValueError("scheduled is never a console parameter: an unattended filing is refused (constitution "
                         "§ 11.8, until § 13.7 earned autonomy)")
    plan = str(params.get("plan_id") or "").strip()
    if not VOICES_PLAN_RX.fullmatch(plan):
        raise ValueError("plan_id must be the 16-hex id of a staged preview (the Voices page, or POST /api/voices/stage)")
    staged = voices_stage_dir() / f"{plan}.yml"
    if not staged.is_file():
        raise ValueError(f"no staged edit for plan {plan}: preview and stage it first (the Voices page)")
    argv = [sys.executable, str(TOOLS / "voices.py"), "pr", "--file", str(staged), "--plan-id", plan]
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


# owner/name, and a pull request as owner/name#number (the JEV conflict engine's --pr shape)
NWO_RX = re.compile(r"^[A-Za-z0-9_.-]{1,64}/[A-Za-z0-9_.-]{1,100}$")
PR_REF_RX = re.compile(r"^[A-Za-z0-9_.-]{1,64}/[A-Za-z0-9_.-]{1,100}#[0-9]{1,7}$")
# The choices an op's parameter takes, served to the page's form as a select
# (OpForm.tsx) and to `tools/dash ops show`; the argv builders below hold them.
CONFLICT_ACTIONS = ("scan", "triage", "budget")
PM_VIEWS = ("review", "plan", "roadmap", "releases", "status")


def _conflicts(params: dict) -> list[str]:
    """`tools/dash conflicts scan|triage|budget` — JEV's read-only half: list the
    fleet's conflicting pull requests, reproduce one in a throwaway clone and
    classify it, or print the month's spend against the cap. Nothing is pushed
    and no model is called (docs/JEV.md)."""
    action = str(params.get("action") or "scan").strip()
    if action not in CONFLICT_ACTIONS:
        raise ValueError(f"action must be one of {list(CONFLICT_ACTIONS)}")
    argv = [DASH, "conflicts", action]
    pr = str(params.get("pr") or "").strip()
    repo = str(params.get("repo") or "").strip()
    if action == "triage":
        if not PR_REF_RX.match(pr):
            raise ValueError("triage needs pr as owner/repo#number")
        argv += ["--pr", pr]
    elif pr:
        raise ValueError(f"pr applies to triage, not {action}")
    if repo:
        if action != "scan":
            raise ValueError("repo limits a scan; it does not apply here")
        if not NWO_RX.match(repo):
            raise ValueError("repo must be owner/name")
        argv += ["--repo", repo]
    return argv + (["--json"] if action != "budget" else [])


def _conflicts_resolve(params: dict) -> list[str]:
    """`tools/dash conflicts resolve --pr <ref>`, or `sweep` with no pr: JEV's
    tiers up to the first that settles each conflict — the script first, then
    a capped model — each a merge commit pushed to the pull request's branch,
    never a rebase, a force-push or a merge (constitution § 12.7). `dry_run`
    decides and reports and changes nothing; without it the job is a GitHub
    write, so it asks first."""
    pr = str(params.get("pr") or "").strip()
    if pr and not PR_REF_RX.match(pr):
        raise ValueError("pr must be owner/repo#number (blank = sweep every conflicting pull request)")
    argv = [DASH, "conflicts", "resolve", "--pr", pr] if pr else [DASH, "conflicts", "sweep"]
    return argv + (["--dry-run"] if _flag(params, "dry_run") else [])


# The PR queue's `who` values (tools/fleetcore/prqueue.py WHO; test_console.py holds the two equal).
PRQ_WHO = ("amr", "agent", "loop", "author")
PRQ_PLAN_RX = re.compile(r"^[0-9a-f]{16}$")


def _prs_queue(params: dict) -> list[str]:
    who = str(params.get("who") or "").strip()
    if who and who not in PRQ_WHO:
        raise ValueError(f"who must be one of {list(PRQ_WHO)}")
    return [DASH, "prs", "queue", "--limit", "500"] + (["--who", who] if who else [])


def _prs_apply(params: dict, op: str) -> list[str]:
    """`tools/dash prs apply --plan-id <id>`: the plan a person previewed, re-planned from live GitHub and
    refused when it moved; `--expect-op` keeps an agent plan off prs-act and the rest off prs-agent."""
    plan_id = str(params.get("plan_id") or "").strip()
    if not PRQ_PLAN_RX.fullmatch(plan_id):
        raise ValueError("plan_id must be the 16-hex id a plan returned (POST /api/prs/plan, or tools/dash prs plan)")
    return [DASH, "prs", "apply", "--plan-id", plan_id, "--expect-op", op] + (["--apply"] if _flag(params, "apply") else [])


def _pm(params: dict) -> list[str]:
    view = str(params.get("view") or "review").strip()
    if view not in PM_VIEWS:
        raise ValueError(f"view must be one of {list(PM_VIEWS)}")
    return [DASH, "pm", view]


def _evidence(params: dict) -> list[str]:
    repo = str(params.get("repo") or "").strip()
    if not NWO_RX.match(repo):
        raise ValueError("repo must be owner/name")
    try:
        number = int(str(params.get("number") or "").strip())
    except ValueError:
        raise ValueError("number must be an issue number")
    if not 1 <= number <= 9_999_999:
        raise ValueError("number must be an issue number")
    return [DASH, "evidence", repo, str(number)]


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
#: appended to the prompt when the person's open page is attached (the page tools and their rules)
ASSIST_PAGE_PROMPT = Path(_HERE) / "assist.page.txt"
ASSIST_MAX_CHARS = 4000
ASSIST_CONTEXT_CHARS = 300
#: a conversation is replayed into each later message's prompt: this many characters of it at most,
#: newest exchanges first kept, each earlier answer cut to ASSIST_HISTORY_ANSWER_CHARS
ASSIST_HISTORY_CHARS = 12_000
ASSIST_HISTORY_ANSWER_CHARS = 2_000
ASSIST_ID_RX = re.compile(r"^[0-9a-f]{12}$")
ASSIST_PAGE_ACCESS = ("off", "look", "act")
#: where a console CAN start a session: on the host, beside the Claude Code CLI (the Docker console holds :4001)
ASSIST_HOST_COMMAND = "CONSOLE_PORT=4010 tools/dash console"
#: the lines of a session's condensed tee (tools/jev/headless.py condensed) the dock shows while it runs
ASSIST_ACTIVITY_MAX = 40
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
    budget_usd, timeout_s, conversation_messages, page_access, fleet_pages), validated on every read."""

    __getattr__ = dict.__getitem__


def assistant_config(fleet: dict | None = None) -> AssistConfig:
    fleet = fleet if fleet is not None else (load_yaml(DATA / "fleet.yml") or {})
    raw = fleet.get("assistant") if isinstance(fleet, dict) else None
    if not isinstance(raw, dict):
        raise ValueError("_data/fleet.yml has no `assistant:` block (tools/console/README.md, The assistant)")
    want = {"enabled", "model", "max_turns", "budget_usd", "timeout_s", "conversation_messages", "page_access",
            "fleet_pages"}
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
    for key in ("max_turns", "timeout_s", "conversation_messages"):
        v = raw[key]
        if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
            raise ValueError(f"_data/fleet.yml assistant.{key}: a positive integer")
    b = raw["budget_usd"]
    if isinstance(b, bool) or not isinstance(b, (int, float)) or not math.isfinite(b) or b <= 0:
        raise ValueError("_data/fleet.yml assistant.budget_usd: a finite positive number")
    for key in ("page_access", "fleet_pages"):
        if raw[key] not in ASSIST_PAGE_ACCESS:
            # YAML reads a bare `off` as false: the value is quoted in fleet.yml, and a boolean is said plainly here
            raise ValueError(f"_data/fleet.yml assistant.{key}: one of {', '.join(ASSIST_PAGE_ACCESS)} "
                             f"(quoted — a bare off is a YAML boolean), got {raw[key]!r}")
    return AssistConfig(enabled=raw["enabled"], model=str(raw["model"]), max_turns=int(raw["max_turns"]),
                        budget_usd=float(b), timeout_s=int(raw["timeout_s"]),
                        conversation_messages=int(raw["conversation_messages"]), page_access=str(raw["page_access"]),
                        fleet_pages=str(raw["fleet_pages"]))


def assistant_page_access() -> str:
    """The ceiling on what an assistant session may do to an open page (page_bridge.CEILINGS): `off` when
    the assistant itself is off or its configuration cannot be read — a broken config never widens access."""
    try:
        cfg = assistant_config()
    except ValueError:
        return "off"
    return cfg.page_access if cfg.enabled else "off"


def assistant_fleet_pages() -> str:
    """The same ceiling for pages of the fleet's other sites and apps (templates/assistant/fleet-assist.js,
    ADR 0014): `off` refuses every such page, `look` lets a paired session read one, `act` lets the person
    on that page choose. Off when the assistant is off or its configuration cannot be read."""
    try:
        cfg = assistant_config()
    except ValueError:
        return "off"
    return cfg.fleet_pages if cfg.enabled else "off"


def assist_unavailable() -> str | None:
    """Why this console cannot START an assistant session: no claude CLI on its PATH, or switched off in
    fleet.yml. A paired Claude Code session needs neither — it brings its own CLI — so the page bridge is
    reported apart from this (assist_doc `page`)."""
    if claude_unavailable():
        return ("this console has no `claude` CLI on its PATH (the console container and the devenv image carry "
                "none), so it cannot start an assistant session itself. Run a console on the host, where Claude "
                f"Code is installed — `{ASSIST_HOST_COMMAND}`, then http://127.0.0.1:4010/ — or "
                "pair a Claude Code session on this machine with this page from the assistant dock")
    try:
        cfg = assistant_config()
    except ValueError as exc:
        return str(exc)
    if not cfg.enabled:
        return "the assistant is off: _data/fleet.yml assistant.enabled is false"
    return None


def _assist_mcp_config(page: str | None = None) -> dict:
    """The one MCP server an assistant session gets: the Harness Console MCP layer over stdio, pointed
    at THIS console. The job inherits DASH_CONSOLE_TOKEN from the process environment, never argv.

    Its write surface is pinned here rather than inherited: no broad writes, no legacy console_run, and
    only the `page` scope — and that only when the person's page is attached. `page` is that page's
    bridge session id (page_bridge.py), a capability this one process holds; with it the layer registers
    the page tools, whose every action still passes the ceiling, the dock's mode and the page's own rules."""
    url = os.environ.get("DASH_CONSOLE_URL") or "http://127.0.0.1:4001"
    env = {"DASH_CONSOLE_URL": url, "HARNESS_MCP_SKIP_INSTALL": "1", "HARNESS_MCP_ALLOW_WRITES": "0",
           "HARNESS_MCP_FLEET_COMPAT": "0", "HARNESS_MCP_SCOPES": "page" if page else "",
           "HARNESS_MCP_PAGE_SESSION": page or ""}
    return {"mcpServers": {"fleet": {"command": str(TOOLS / "console" / "mcp.sh"), "args": [], "env": env}}}


def _assist_dir() -> Path:
    d = JOB_DIR / "assist"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _conversation_path(conversation: str) -> Path:
    return _assist_dir() / f"conv-{conversation}.json"


def assist_conversation(conversation: str) -> dict:
    """One conversation's record: its id and its messages in order (each an ask id and the question).
    ValueError when the id is malformed or names no conversation this console holds."""
    if not ASSIST_ID_RX.match(str(conversation)):
        raise ValueError("conversation must be an id this console issued")
    try:
        doc = json.loads(_conversation_path(conversation).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("no such conversation — it was cleared with the console's job history; "
                         "start a new one") from exc
    if not isinstance(doc, dict) or not isinstance(doc.get("asks"), list):
        raise ValueError("that conversation's record is unreadable — start a new one")
    return doc


def _assist_history(doc: dict) -> str:
    """The conversation so far, for a later message's prompt: each exchange's question and the answer the
    session gave (the CLI's result text, cut to ASSIST_HISTORY_ANSWER_CHARS), oldest first, the oldest
    dropped until it fits ASSIST_HISTORY_CHARS. An exchange whose session left no answer says so."""
    d = _assist_dir()
    blocks: list[str] = []
    for ask in doc.get("asks") or []:
        ask_id = str((ask or {}).get("id") or "")
        if not ASSIST_ID_RX.match(ask_id):
            continue
        answer = ""
        try:
            result = json.loads((d / f"{ask_id}.result.json").read_text(encoding="utf-8"))
            answer = str(result.get("result") or "") if isinstance(result, dict) else ""
        except (OSError, ValueError):
            answer = ""
        if len(answer) > ASSIST_HISTORY_ANSWER_CHARS:
            answer = answer[:ASSIST_HISTORY_ANSWER_CHARS] + " […cut]"
        blocks.append(f"THE PERSON: {str(ask.get('question') or '').strip()}\n"
                      f"YOU: {answer.strip() or '(that session ended without an answer)'}")
    while blocks and sum(len(b) + 2 for b in blocks) > ASSIST_HISTORY_CHARS:
        blocks.pop(0)
    return "\n\n".join(blocks)


def _assist(params: dict) -> list[str]:
    """`tools/dash-gen ai-run … -- <claude flags>`: one read-only headless session, the assistant's
    prompt (tools/console/assist.prompt.txt with the question and the page context filled) on stdin,
    the `fleet` MCP server as its only server (--strict-mcp-config), the hub checkout as its cwd,
    the result captured to a file the job page reads. Capped by assistant.budget_usd and recorded in
    the AI ledger by ai-run; never a write tool, never the network.

    Two optional parameters make it the docked assistant (web/src/assist/): `conversation` continues an
    earlier exchange — every message is still its own capped session, with the conversation so far
    replayed into its prompt from this console's own records, never from the request — and `page` is
    the bridge session of the page the person has open, which attaches the page tools and their rules
    (assist.page.txt). A conversation holds assistant.conversation_messages messages at most."""
    question = str(params.get("question") or "").strip()
    if not question:
        raise ValueError("question is required")
    if len(question) > ASSIST_MAX_CHARS or "\0" in question:
        raise ValueError(f"question must be at most {ASSIST_MAX_CHARS} characters, with no NUL")
    context = " ".join(str(params.get("context") or "").split())[:ASSIST_CONTEXT_CHARS] or "the console, no page named"
    cfg = assistant_config()
    if not cfg.enabled:
        raise ValueError("the assistant is off: _data/fleet.yml assistant.enabled is false")
    page = str(params.get("page") or "").strip()
    if page:
        import page_bridge  # noqa: PLC0415 — stdlib only; core stays importable without it being loaded first
        if cfg.page_access == "off":
            raise ValueError("page access is off: _data/fleet.yml assistant.page_access is off")
        if not page_bridge.SID_RX.match(page) or not page_bridge.BRIDGE.has(page):
            raise ValueError("that page is not sharing itself with the assistant any more — reopen the dock")
    conversation = str(params.get("conversation") or "").strip()
    record = assist_conversation(conversation) if conversation else {"id": uuid.uuid4().hex[:12], "asks": []}
    if len(record["asks"]) >= cfg.conversation_messages:
        raise ValueError(f"this conversation has reached {cfg.conversation_messages} messages "
                         "(_data/fleet.yml assistant.conversation_messages) — start a new one")
    try:
        template = ASSIST_PROMPT.read_text(encoding="utf-8")
        page_rules = ASSIST_PAGE_PROMPT.read_text(encoding="utf-8") if page else ""
    except OSError as exc:
        raise ValueError(f"the assistant's prompt cannot be read: {exc}") from exc
    history = _assist_history(record)
    prompt = (template.replace("{{PAGE}}", page_rules.strip() or "No page is attached to this session: you "
                               "cannot see or change what the person has open, only what they told you above.")
              .replace("{{HISTORY}}", history or "This is the first message of the conversation.")
              .replace("{{CONTEXT}}", context).replace("{{QUESTION}}", question))
    d = _assist_dir()
    ask_id = uuid.uuid4().hex[:12]
    prompt_file, result_file, outcome_file, mcp_file = (d / f"{ask_id}.prompt.txt", d / f"{ask_id}.result.json",
                                                        d / f"{ask_id}.outcome.json", d / f"{ask_id}.mcp.json")
    prompt_file.write_text(prompt, encoding="utf-8")
    # 0600: with a page attached this file names the page's bridge session, a capability.
    mcp_file.touch(mode=0o600, exist_ok=True)
    mcp_file.write_text(json.dumps(_assist_mcp_config(page or None), indent=1), encoding="utf-8")
    record["asks"].append({"id": ask_id, "question": question, "page": bool(page),
                           "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")})
    _conversation_path(record["id"]).write_text(json.dumps(record, indent=1), encoding="utf-8")
    # The conversation rides on the job's params: the page reads it back to send the next message. The
    # page's session id does not — a job's params are shown to every API client, and that id is the
    # capability to drive someone's browser; the record keeps only that a page was attached.
    params["conversation"] = record["id"]
    if page:
        params["page"] = "attached"
    return [DASH_GEN, "ai-run", "--source", "console assist", "--repo", "bamr87/bamr87", "--cwd", str(REPO_ROOT),
            "--prompt-file", str(prompt_file), "--result-file", str(result_file), "--outcome-file", str(outcome_file),
            "--stream", "--timeout", str(cfg.timeout_s), "--max-budget-usd", f"{cfg.budget_usd:g}",
            "--usage-limit", "skip", "--",
            "--model", cfg.model, "--max-turns", str(cfg.max_turns), "--permission-mode", "dontAsk",
            "--setting-sources", "user", "--strict-mcp-config", "--mcp-config", str(mcp_file),
            "--allowedTools", *ASSIST_ALLOWED, "--disallowedTools", *ASSIST_DENIED]


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
                     agent="loop:*",
                     remote=lambda p: _flag(p, "apply") or (not _flag(p, "rehearse") and not p.get("run_id")),
                     confirm="spend",
                     # a model attempt's stream is quiet while one tool call (a test suite, a build) runs
                     stall_s=600,
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
    "voices-pr": dict(title="Voices: file an edit of the voice model as a draft PR", group="content",
                      argv=_voices_pr, needs_token=True, remote=lambda p: _flag(p, "apply"),
                      desc="tools/voices.py pr — the edit staged from the Voices page, by its plan id. DRY RUN "
                           "unless apply: the diff against origin/main and the branch it would push. With apply "
                           "(the OPS remote-write path, constitution § 11.8): the token probed with `gh api user`, "
                           "the plan re-checked against a fresh main, one chore/voices-* branch and one draft PR "
                           "that changes only _data/voices/voices.yml; refused with an open voices PR, a dirty "
                           "engine or --scheduled.",
                      params=["plan_id", "apply"]),
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
    "graph-check": dict(title="Fleet graph: build it and print the findings", group="verify",
                        argv=lambda p: [DASH, "graph", "check"], needs_token=False,
                        desc="Every registry, atlas, inventory and surface joined into one graph (docs/FLEET-GRAPH.md), "
                             "then its checks: a source nobody writes, a scheduled workflow with no switch entry, an API "
                             "route no MCP tool reaches, a command no operation runs. Offline, $0; fails on an error."),
    "learn-status": dict(title="Outcome learning: what happened to each loop's output (shadow)", group="observe",
                         argv=lambda p: [DASH, "learn", "status"], needs_token=False,
                         desc="Landed, rejected, stale, working and young per loop from the local lake, the landing "
                              "estimate and the backlog advice (docs/LEARNING.md). Shadow only: steers nothing. $0."),
    "learn-plan": dict(title="Outcome learning: where each loop's next slots would pay (shadow)", group="plan",
                       argv=lambda p: [DASH, "learn", "plan"], needs_token=False,
                       desc="The share of the next slots each repo would get (Thompson sampling, seeded by the date) "
                            "beside what the loop filed lately, and the replay test. Prints a plan; changes nothing. $0."),
    "decisions": dict(title="Decision queue: what waits on Amr across the fleet", group="observe",
                      argv=lambda p: [DASH, "decisions", "queue", "--repos"], needs_token=True,
                      desc="needs-amr items, pull requests awaiting ratification, failing or major Dependabot pull "
                           "requests and ready-to-merge pull requests, with the per-repo inventory, from the local "
                           "index (docs/DECISION-INDEX.md). Reads GitHub only when the index is past its TTL, inside "
                           "decisions.budget_s; a partial answer says so. Read-only, $0."),
    "decisions-refresh": dict(title="Decision queue: read GitHub now", group="observe",
                              argv=lambda p: [DASH, "decisions", "refresh"], needs_token=True,
                              desc="Reads every open pull request and gate-labelled issue of the fleet again under "
                                   "decisions.refresh_budget_s and rewrites the index; fails unless the read finished "
                                   "clean, so a scheduled run cannot hide a stale index. Read-only, $0."),
    # The PR queue (docs/PR-QUEUE.md): every open pull request, who moves it next, and bulk actions. A
    # plan is made from live GitHub by POST /api/prs/plan (or `tools/dash prs plan`) and writes only its
    # plan file; these two apply a plan by its id, after re-planning and refusing one that moved.
    "prs": dict(title="PR queue: every open pull request, who moves it next", group="observe",
                argv=_prs_queue, needs_token=True,
                desc="tools/dash prs — every open pull request of the hub and the registry repos with its checks "
                     "collapsed per check (a cancelled run followed by a success is green), the review gate "
                     "(§ 12.3, closeout.py's rules), the repo's merge method and who moves it next "
                     "(docs/PR-QUEUE.md). Read-only, $0.",
                params=["who"], meta=lambda: {"choices": {"who": ["", *PRQ_WHO]}}),
    "prs-refresh": dict(title="PR queue: read GitHub now", group="observe",
                        argv=lambda p: [DASH, "prs", "refresh"], needs_token=True,
                        desc="Reads the decision index and every pull request's checks, files and triage comment "
                             "again under pr_queue.refresh_budget_s. Read-only, $0."),
    "prs-act": dict(title="PR queue: apply a reviewed bulk action", group="plan",
                    argv=lambda p: _prs_apply(p, "prs-act"), needs_token=True, exclusive="prs",
                    remote=lambda p: _flag(p, "apply"),
                    desc="tools/dash prs apply --plan-id <id> — re-plans the action from live GitHub and refuses a "
                         "plan whose pull requests moved since the preview (§ 11.4); with `apply` it runs each "
                         "pull request's op once: mark ready, update branch (a base merge, never a force-push), "
                         "re-run cancelled or failed checks one at a time, post or edit the next-action comment, "
                         "add needs-amr; close and merge only while pr_queue.close / pr_queue.merge are enabled "
                         "(off until an amendment says a merge the maintainer confirms here is his own). Without "
                         "apply it only says whether the preview still matches. A GitHub write, so it asks first.",
                    params=["plan_id", "apply"]),
    "prs-agent": dict(title="PR queue: a capped local Claude Code session per pull request", group="plan",
                      argv=lambda p: _prs_apply(p, "prs-agent"), needs_token=True, needs="claude", exclusive="prs",
                      agent="local:pr-queue-agent",
                      remote=lambda p: _flag(p, "apply"), confirm="spend",
                      desc="tools/dash prs apply --plan-id <id> for an `agent` plan (local:pr-queue-agent, § 10.9): "
                           "for each pull request, a clone of its head outside the hub, one headless session "
                           "(ai-run --isolate: no GitHub credential; pr_queue.agent's model, turns and dollars, "
                           "API-equivalent, an estimate) that fixes its failing checks or the requested changes, "
                           "an edit to a path the repo keeps agents out of refused, then one commit pushed without "
                           "force and needs-amr added (a model's change is gated). Spends, so it asks first.",
                      params=["plan_id", "apply"]),
    "agents": dict(title="Agent inventory: every agent against the efficacy contract (check)", group="observe",
                   argv=lambda p: [DASH, "agents", "--check"], needs_token=False,
                   desc="tools/dash agents --check — every CI agent step, JEV loop step, conflict tier and LaunchAgent "
                        "with its owner, trigger, switch, cap, model, KPIs and contract gaps, held against the committed "
                        "_data/agents.yml (drift check (p); docs/AGENT-EFFICACY.md). Offline, $0; rewrites nothing."),
    "pm": dict(title="PM review: issues, pull requests, roadmap and releases against the Fleet project", group="observe",
               argv=_pm, needs_token=True,
               desc="tools/dash pm <view> (docs/PM.md). `review` reads every open issue and pull request of the "
                    "registry repos, their comments and releases and the Fleet project, and writes only local files; "
                    "`plan` is the Fleet project ops that review proposes (applied only by `dash projects apply` "
                    "behind § 11's confirm), `roadmap` its roadmap status edits, `releases` the release trains, "
                    "`status` the committed headline. Read-only, $0.",
               params=["view"], meta=lambda: {"choices": {"view": list(PM_VIEWS)}}),
    "conflicts": dict(title="Merge conflicts: scan the fleet, triage one, or the month's budget", group="plan",
                      argv=_conflicts, needs_token=True,
                      desc="tools/dash conflicts scan|triage|budget — JEV's read-only half (docs/JEV.md): every open "
                           "pull request GitHub reports as conflicting (`repo` limits it to one), one reproduced in a "
                           "throwaway clone and classified to the tier that would settle it (`pr` owner/repo#number), "
                           "or the conflict engine's spend against its cap. Pushes nothing, calls no model.",
                      params=["action", "pr", "repo"], meta=lambda: {"choices": {"action": list(CONFLICT_ACTIONS)}}),
    "conflicts-resolve": dict(title="Merge conflicts: resolve one pull request, or sweep them all", group="plan",
                              argv=_conflicts_resolve, needs_token=True, exclusive="conflicts",
                              remote=lambda p: not _flag(p, "dry_run"),
                              stall_s=600,   # a model tier is quiet while the repo's own checks run
                              desc="tools/dash conflicts resolve --pr <owner/repo#number>, or `sweep` with no pr: JEV's "
                                   "tiers up to the first that settles each conflict — the script, then a capped model "
                                   "in this local session (tier caps in _data/fleet.yml budget.jev; API-equivalent, an "
                                   "estimate) — each a merge commit pushed to the pull request's branch after the "
                                   "repo's own checks pass; never a rebase, a force-push or a merge (§ 12.7), and a "
                                   "model's resolution carries needs-amr. `dry_run` decides and reports and changes "
                                   "nothing; without it the job writes to GitHub, so it asks first.",
                              params=["pr", "dry_run"]),
    "evidence": dict(title="Issue pipeline: build one issue's evidence bundle", group="plan",
                     argv=_evidence, needs_token=True,
                     desc="tools/dash evidence <owner/repo> <number> — the intake tier's evidence for one issue, built in "
                          "an isolated virtual environment (docs/ISSUE-PIPELINE.md): the reproduction, logs and a "
                          "screenshot where the repo has a page. Writes local files only; no model, $0.",
                     params=["repo", "number"]),
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
    "assist": dict(title="Ask the assistant (through the fleet MCP server; no write tool)", group="refine", argv=_assist,
                   needs_token=False, needs="claude", gate=assist_unavailable, exclusive="assist",
                   remote=lambda p: True, confirm="spend", agent=assistlog.AGENT,
                   desc="One headless Claude Code session (tools/console/assist.prompt.txt) with the `fleet` MCP "
                        "server attached, reading the hub checkout, answering the question from the fleet's own "
                        "data and citing its sources. Capped per answer by _data/fleet.yml assistant.budget_usd "
                        "(API-equivalent, an estimate) and recorded in the AI ledger; no write tool, no network, "
                        "no job it can start. It spends, so it asks first. From the docked assistant a message "
                        "continues a conversation and carries the page the person has open: the session can then "
                        "read that page and, as far as assistant.page_access and the dock's mode allow, navigate, "
                        "click and type in it — never inside a confirming dialog, never in a secret field.",
                   params=["question", "context", "conversation", "page"]),
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
            # an operation that starts a Claude session names its entry in the agent inventory
            # (_data/agents.yml, constitution § 29); `loop:*` is whichever loop step the parameters pick
            "agent": op.get("agent"),
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
# AUTH — the credential layer is core_auth.py. Its two switches stay here: tests
# rebind both on this module, and AUTH_WRITES is read by `_keys_rotate` and
# `_secrets_push` above, by core_adapters' `capabilities` and by github_link.py.
# DASH_CONSOLE_AUTH=off refuses every credential write, for a console fronted by
# anything less private than loopback.
# --------------------------------------------------------------------------- #
AUTH_WRITES = (os.environ.get("DASH_CONSOLE_AUTH", "on").strip().lower()
               not in ("0", "off", "false", "no"))
ENV_FILE = Path(os.environ.get("DASH_CONSOLE_ENV_FILE") or (REPO_ROOT / ".env"))


# --------------------------------------------------------------------------- #
# THE SIBLING MODULES — the sections that moved out of this file
# --------------------------------------------------------------------------- #
# Loaded last, when every name above exists: each sibling reads this module as
# `core.<name>` (a few at import time, for default arguments; the rest when called).
# Every name a sibling defines is bound here too, private ones included, so
# `core.<name>` answers for all of them as it did before the split. `_rel` is
# re-bound to core_refine's, which is the definition that already won in this file.
from core_adapters import (  # noqa: E402,F401
    _has_module, capabilities, _lake_module, lake_status, _observe_module, _index_module, index_query,
    index_coverage, observability_planes, observe_status, observe_embeds, frame_src, lake_runs, lake_lines,
    lake_review, lake_recall, project_detail, README_NAMES, README_CAP, project_readme, EDITORIAL, CONTENT_VIEWS,
    _content_module, _content_inputs, content_report, content_documents, _plan_diff, editorial_decide,
    editorial_update, content_brief, NODES_TTL, NODES_PROBE_TIMEOUT, _NODES, _NODES_LOCK, _fleet_nodes, nodes_doc,
    _atlas_module, _default_branch_text, dispatch_inputs, dispatchable, workflow_atlas, workflow_health,
    workflow_lint, workflow_scaffold, WORK_MOVES, _WORK_LOCK, _work_module, work_inputs, work_board, work_item,
    _work_diff, work_apply, _sprint_module, sprints_doc, VOICES_PLAN_RX, _voices, voices_stage_dir, voices_doc,
    voices_preview, voices_stage,
)
from core_jobs import (  # noqa: E402,F401
    FINISHED_STATES, JobUnavailable, JobConflict, _JOB_ID_RX, ORPHAN_LOG_AGE_S, _parse_ts, Job, job_env,
    loop_job_fields, JOB_STATES, STALL_S, LONG_STEP_MIN_RUNS, LONG_STEP_RUNS, LONG_STEP_FLOOR_S, stall_threshold,
    _utc, _since, _mtime, _p90, collector_lag, JobManager, AUTO_HEALTH_TIMEOUT, health_refresh_reason, auto_health,
)
from core_config import (  # noqa: E402,F401
    CRON_RX, VERSION_RX, VALUE_RX, SLUG_RX, _f, CONFIG_SECTIONS, CONFIG_FIELDS, EDITABLE, _dig, read_config,
    read_contract, _coerce, _flow_seq, _AMBIGUOUS_SCALAR_RX, _styled, update_config, update_contract,
    _top_level_block, _splice_block,
)
from core_auth import (  # noqa: E402,F401
    SECRET_RX, ENV_PLAIN_RX, CREDENTIALS, _SESSION_CREDS, _SCRUB_RX, _scrub, _env_file_names, _env_file_set_names,
    _env_file_upsert, _gh_status, auth_status, _check_writes, set_credential, clear_credential, gh_login, gh_logout,
)
from core_refine import (  # noqa: E402,F401,F811
    _argv_value, _ACTIVITY_RX, assist_activity, assist_job_fields, _rel, _runs_dir, _refine_dir, _load_json,
    _jsonable, refine_surface_hub, refine_fleet_surface, refine_plans, refine_library, refine_evidence_list,
    refine_reviews, REVIEW_FILE_RX, MAX_TEXT_CHARS, refine_review_file, refine_evidence_doc, refine_evidence_file,
    refine_library_add, refine_doc, assist_doc, page_audit_path, assist_agent, _shown, assist_activity_doc,
)
