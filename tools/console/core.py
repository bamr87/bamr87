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
  CONTRACT   a comment-preserving editor for the `harnesses:` block of
             _data/fleet.yml (ruamel round-trip), limited to declared scalar
             knobs. It edits the working tree and shows the git diff; the
             commit stays with the human — git is the database and the review
             gate, here as everywhere else in the dash.
"""
from __future__ import annotations

import datetime as dt
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
# var by name only, never a value or a prefix.
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
def capabilities() -> dict:
    tools = {name: shutil.which(name) is not None
             for name in ("git", "gh", "python3", "docker", "actionlint", "shellcheck", "bundle")}
    gh_auth = None
    if tools["gh"]:
        rc, _ = run_quiet(["gh", "auth", "status"], timeout=20)
        gh_auth = rc == 0
    # find_spec, not a bare import: `import ruamel.yaml` would rebind the local
    # name to the module object and leak it into the JSON response.
    has_ruamel = importlib.util.find_spec("ruamel.yaml") is not None
    has_otel = all(importlib.util.find_spec(m) is not None
                   for m in ("opentelemetry.sdk", "opentelemetry.exporter.otlp.proto.http"))
    return {
        "tools": tools,
        "gh_authenticated": gh_auth,
        "env_tokens": {name: bool(os.environ.get(name)) for name in TOKEN_ENV},
        "contract_editing": has_ruamel,
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
        env = {**os.environ, "PYTHONUNBUFFERED": "1", "FORCE_COLOR": "0", "NO_COLOR": "1"}
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
# CONTRACT — comment-preserving edits to fleet.yml `harnesses:`
# --------------------------------------------------------------------------- #
# The knobs the console may change, with their types. Anything else in the
# block (the kit name, comments, structure) is edited in a text editor + PR.
EDITABLE = {
    "baseline.require_mention_handler": bool,
    "baseline.require_agent_context": bool,
    "baseline.require_oauth_secret": bool,
    "throughput.max_scheduled_ai_per_day_fleet": int,
    "throughput.max_scheduled_ai_per_day_repo": int,
    "throughput.max_ai_crons_per_utc_hour": int,
    "budget.monthly_ai_usd": float,
    "budget.monthly_actions_minutes": int,
    "budget.trend_warn_pct": float,
    "inventory.max_workflow_files": int,
    "inventory.schedule_limit": int,
    "attention_max": int,
    "exempt": list,
}


def read_contract(fleet_path: Path = DATA / "fleet.yml") -> dict:
    fleet = load_yaml(fleet_path) or {}
    return {"harnesses": fleet.get("harnesses") or {}, "editable": sorted(EDITABLE)}


def _coerce(key: str, value):
    kind = EDITABLE[key]
    if kind is bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.lower() in ("true", "false"):
            return value.lower() == "true"
        raise ValueError(f"{key} must be true/false")
    if kind is int:
        try:
            n = int(value)
        except (TypeError, ValueError):
            raise ValueError(f"{key} must be an integer")
        if n < 0:
            raise ValueError(f"{key} must be >= 0")
        return n
    if kind is float:
        try:
            f = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"{key} must be a number")
        if f < 0:
            raise ValueError(f"{key} must be >= 0")
        return int(f) if f.is_integer() else f
    if kind is list:
        if isinstance(value, str):
            value = [v.strip() for v in value.split(",") if v.strip()]
        if not isinstance(value, list) or not all(isinstance(v, str) and NAME_RX.match(v) for v in value):
            raise ValueError(f"{key} must be a list of repo names")
        return value
    raise ValueError(key)


def update_contract(changes: dict, fleet_path: Path = DATA / "fleet.yml") -> dict:
    """Apply validated changes to fleet.yml's harnesses: block, preserving every
    comment (ruamel round-trip). Returns what changed plus the git diff."""
    try:
        from ruamel.yaml import YAML
    except ImportError:
        raise RuntimeError("contract editing needs ruamel.yaml (pip install ruamel.yaml)")
    unknown = sorted(set(changes) - set(EDITABLE))
    if unknown:
        raise ValueError(f"not editable from the console: {', '.join(unknown)}")
    yml = YAML(typ="rt")
    yml.preserve_quotes = True
    yml.width = 4096
    doc = yml.load(fleet_path.read_text())
    block = doc.get("harnesses")
    if block is None:
        raise ValueError("fleet.yml has no harnesses: block")
    applied = {}
    for key, value in changes.items():
        coerced = _coerce(key, value)
        parts = key.split(".")
        node = block
        for part in parts[:-1]:
            if part not in node:
                raise ValueError(f"fleet.yml harnesses.{key} is not declared; add it by hand first")
            node = node[part]
        if parts[-1] not in node:
            raise ValueError(f"fleet.yml harnesses.{key} is not declared; add it by hand first")
        if node[parts[-1]] != coerced:
            node[parts[-1]] = coerced
            applied[key] = coerced
    if applied:
        with fleet_path.open("w") as fh:
            yml.dump(doc, fh)
    rc, diff = run_quiet(["git", "diff", "--no-color", "--", str(fleet_path)])
    return {"applied": applied, "diff": diff if rc == 0 else ""}
