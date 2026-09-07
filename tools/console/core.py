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

import datetime as dt
import io
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import uuid
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.stderr.write("console requires PyYAML: pip install pyyaml\n")
    sys.exit(2)

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

# Workflows the console may dispatch through `gh workflow run`, with the
# input names each accepts (anything else is refused before argv is built).
DISPATCHABLE = {
    "harness-fanout": {"target", "artifacts", "dry_run", "upgrade"},
    "fleet-pulse": {"days", "max_candidates", "dry_run", "skip_publish"},
    "issue-pipeline": set(),
    "token-rotation": set(),
    "repo-evolution": {"target", "dry_run", "force", "focus"},
    "standardize-fanout": {"target", "artifacts", "dry_run", "upgrade"},
    "schema-fanout": {"target", "dry_run"},
    "build-dash": set(),
    "reconcile-registry": set(),
    "refresh-dash": set(),
    "update-submodules": set(),
}


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
    stamp = data.get("generated_at") or data.get("generated")
    ts = parse_stamp(stamp)
    return {
        "present": True,
        "generated_at": stamp,
        "age_days": round((now - ts).total_seconds() / 86400, 1) if ts else None,
    }


def run_quiet(argv: list[str], timeout: int = 15, cwd: Path = REPO_ROOT) -> tuple[int, str]:
    try:
        out = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, cwd=str(cwd))
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return 127, ""
    return out.returncode, (out.stdout or "") + (out.stderr or "")


# --------------------------------------------------------------------------- #
# STATE — the committed fleet, as one document
# --------------------------------------------------------------------------- #
def git_info() -> dict:
    rc, branch = run_quiet(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    rc2, sha = run_quiet(["git", "rev-parse", "--short", "HEAD"])
    rc3, porcelain = run_quiet(["git", "status", "--porcelain"])
    dirty = [line[3:] for line in porcelain.splitlines() if line.strip()] if rc3 == 0 else []
    return {
        "available": rc == 0,
        "branch": branch.strip() if rc == 0 else None,
        "head": sha.strip() if rc2 == 0 else None,
        "dirty": dirty[:50],
        "dirty_count": len(dirty),
    }


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
     "local_ops": ["triage", "actions", "ai-usage", "harnesses", "harness", "remediate"]},
    {"id": "issue_pipeline", "title": "Issue pipeline — intake → implement → complete", "workflow": "issue-pipeline",
     "schedule_key": "issue_pipeline", "doc": "docs/ISSUE-PIPELINE.md",
     "outputs": ["issue_pipeline"], "local_ops": ["issues"]},
    {"id": "token_rotation", "title": "Token rotation — credentials", "workflow": "token-rotation",
     "schedule_key": "rotate_tokens", "doc": "docs/TOKEN-ROTATION.md",
     "outputs": ["token_rotation"], "local_ops": ["secrets-audit", "secrets-plan", "secrets-rotate"]},
    {"id": "repo_evolution", "title": "Repo evolution — proactive improvement", "workflow": "repo-evolution",
     "schedule_key": "repo_evolution", "doc": "docs/EVOLUTION.md",
     "outputs": [], "local_ops": ["targets"]},
    {"id": "harness_fanout", "title": "Harness fan-out — mass deploy / update", "workflow": "harness-fanout",
     "schedule_key": None, "doc": "docs/HARNESS-OPS.md",
     "outputs": [], "local_ops": ["gaps", "deploy-gaps"]},
    {"id": "reconcile_registry", "title": "Registry reconciliation", "workflow": "reconcile-registry",
     "schedule_key": "reconcile_registry", "doc": "docs/DASH.md", "outputs": [], "local_ops": ["reconcile"]},
    {"id": "refresh_dash", "title": "README / registry refresh", "workflow": "refresh-dash",
     "schedule_key": "refresh_dash", "doc": "docs/DASH.md", "outputs": [], "local_ops": ["readme"]},
    {"id": "update_submodules", "title": "Submodule pointer bump", "workflow": "update-submodules",
     "schedule_key": "update_submodules", "doc": "SUBMODULES.md", "outputs": [], "local_ops": []},
    {"id": "build_dash", "title": "Build & deploy the dash (Pages)", "workflow": "build-dash",
     "schedule_key": "build_dash", "doc": "docs/DASH.md", "outputs": [], "local_ops": []},
]


def loop_cards(fleet: dict, sources: dict) -> list[dict]:
    schedule = (fleet or {}).get("schedule") or {}
    cards = []
    for loop in LOOPS:
        cron = schedule.get(loop["schedule_key"]) if loop["schedule_key"] else None
        ages = [sources[o]["age_days"] for o in loop["outputs"]
                if o in sources and sources[o].get("age_days") is not None]
        missing = [o for o in loop["outputs"] if not sources.get(o, {}).get("present")]
        cards.append({
            **loop,
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
        "loops": loop_cards(fleet, sources),
        "git": git_info(),
    }


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
    if wf not in DISPATCHABLE:
        raise ValueError(f"workflow must be one of {sorted(DISPATCHABLE)}")
    argv = ["gh", "workflow", "run", f"{wf}.yml"]
    fields = params.get("fields") or {}
    if not isinstance(fields, dict):
        raise ValueError("fields must be an object")
    for k, v in fields.items():
        if k not in DISPATCHABLE[wf]:
            raise ValueError(f"{wf} does not accept input '{k}'")
        v = "true" if v is True else "false" if v is False else str(v)
        if not FIELD_RX.match(v):
            raise ValueError(f"input '{k}' has characters the console refuses to pass")
        argv += ["-f", f"{k}={v}"]
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


# id → (title, group, argv builder, needs_token, remote_write(params) -> bool, description)
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
    "lake-sync": dict(title="Lake: extract GitHub data into the local lake", group="lake",
                      argv=_lake_sync, needs_token=True,
                      desc="dash-gen lake sync — runs → jobs → steps, run logs + claude-code-action facts, "
                           "issues, workflow files, .factory/** → .dash-lake/fleet.sqlite (gitignored).",
                      params=["days", "target", "jobs", "logs"]),
    "lake-sessions": dict(title="Lake: extract local Claude Code sessions", group="lake",
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
    "lake-export": dict(title="Lake: export traces to Phoenix", group="lake",
                        argv=_lake_export, needs_token=False,
                        desc="OpenInference spans for the lake's agent runs (and this machine's Claude Code "
                             "sessions with local) → Phoenix over OTLP/HTTP. Dry run writes export-preview.json.",
                        params=["days", "local", "dry_run", "force"]),
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
                     desc="`gh workflow run <workflow>.yml -f key=value` for the allowlisted workflows.",
                     params=["workflow", "fields"]),
}


def list_ops() -> list[dict]:
    return [
        {"id": op_id, "title": op["title"], "group": op["group"], "desc": op.get("desc", ""),
         "needs_token": op["needs_token"], "params": op.get("params", []),
         "remote_write": "remote" in op}
        for op_id, op in OPS.items()
    ]


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
class Job:
    def __init__(self, op_id: str, argv: list[str], remote: bool, params: dict):
        self.id = uuid.uuid4().hex[:12]
        self.op = op_id
        self.title = OPS[op_id]["title"]
        self.argv = argv
        self.remote = remote
        self.params = params
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
        }


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


class JobManager:
    def __init__(self, job_dir: Path = JOB_DIR, max_jobs: int = 200):
        self.job_dir = job_dir
        self.job_dir.mkdir(parents=True, exist_ok=True)
        self.jobs: dict[str, Job] = {}
        self.order: list[str] = []
        self.max_jobs = max_jobs
        self._lock = threading.Lock()
        self._remote_lock = threading.Lock()   # one GitHub-writing job at a time

    def submit(self, op_id: str, params: dict | None = None, confirm: bool = False) -> Job:
        params = params or {}
        argv, remote = build_argv(op_id, params)
        if remote and not confirm:
            raise PermissionError(
                f"'{op_id}' with these parameters writes to GitHub — resubmit with confirm=true")
        job = Job(op_id, argv, remote, params)
        job.log_path = self.job_dir / f"{job.id}.log"
        with self._lock:
            self.jobs[job.id] = job
            self.order.append(job.id)
            while len(self.order) > self.max_jobs:
                old = self.order.pop(0)
                self.jobs.pop(old, None)
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
        return {"job": job.to_dict(), "text": text, "offset": new_offset,
                "done": job.status in ("succeeded", "failed", "cancelled")}

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
         ("refresh_dash", "README AUTO span refresh PR"),
         ("reconcile_registry", "registry ↔ GitHub reconciliation"),
         ("update_submodules", "weekly submodule pointer bump PR"),
         ("rotate_tokens", "weekly credential rotation"),
         ("repo_evolution", "weekly proactive per-repo improvement pass"),
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
     "blurb": "One Opus agent and one draft PR per target. max_turns is wired into the workflow "
              "through the plan, so this is the only place it is stated.",
     "fields": {
         "enabled": _f("bool", "run the weekly pass"),
         "skip_when_open_pr": _f("bool", "one open evolution PR per repo is the backpressure"),
         "max_targets": _f("int", "repos evolved per run"),
         "max_parallel": _f("int", "concurrent agents (one OAuth account's rate limit)"),
         "max_turns": _f("int", "per-repo turn budget — set above observed demand, not at it"),
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
         "FLEET_CI_WORKFLOW": _f("value", "the reusable CI workflow reference"),
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
