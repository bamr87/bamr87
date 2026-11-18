#!/usr/bin/env python3
"""
harness — the six-layer harness health scorecard + trip wires.

The hub's control plane already implements most of the six-layer agent-harness
architecture (docs/HARNESS.md): guides (CLAUDE.md/AGENTS.md/SCHEMA.md), sensors
(drift gate, schema lint, per-repo CI), bounded agentic loops (fleet-pulse
doctor, issue pipeline, token rotation, repo evolution), file-based memory
(_data/*.yml ledgers, labels-as-state), and permissions (fleet.yml caps,
draft-PR-only, never-merge, human brake labels). What it lacked from Layer 6
(observability) were the two things the playbook calls REQUIRED before
unattended operation: a harness health scorecard and trip wires on aggregate
drift.

This module supplies both, deterministically and OFFLINE — it reads only the
committed signals the pulse job just refreshed and computes:

  SCORECARD  completion rate, effectiveness, waste, cost per verified run,
             standing failures, escalations — the "real metric" is verified
             completions, not model calls.

  TRIP WIRES aggregate-drift alarms evaluated against _data/fleet.yml
             `harness:` thresholds. The first wire, stale-data, exists because
             this fleet has already lived the failure it detects: the four
             pre-fleet-pulse data loops died silently for three weeks and
             nothing said so. A trip wire that fires is an ATTENTION item, not
             an action — the doctor/pipeline loops own the fixes; this is the
             alarm panel.

  AGENTIC    the agentic layer (constitution § 29, epic #773 phase E2, #776):
             wires on the agents' own inputs, judged against _data/fleet.yml
             `harness.agentic` and `harness.sources`. Each reports `tripped`
             as true, false or `unknown` (an input it needs is absent: never
             green, never an alarm), and stays in SHADOW for `shadow_days`
             after its `first_seen` (carried forward from the committed
             harness_health.yml): a shadowed wire is published but never
             counts in `tripped_count`. The groups so far:
               source-freshness     every harness.sources entry against its
                                    own `slo_days`, and a source with no
                                    writer (§ 29.4)
               measurement-coverage the hub is in the analytics, no repo was
                                    truncated, each parity block is within
                                    tolerance
               unknown-agent-cost   the share of agent runs whose cost could
                                    not be read

Inputs (all optional — a missing or degraded signal nulls that metric, never
crashes; the wire that watches for staleness is exactly how a missing input
becomes visible):

  _data/actions_usage.yml   cost / effectiveness / waste  (Layer 6) — job-minutes
                            since actions-usage/v2: the cost wires read cost,
                            the `slow` flag (analytics) reads the wall clock;
                            its `parity` and `coverage` blocks feed the
                            agentic layer
  _data/fleet_triage.yml    standing open-state           (Layers 3+6)
  _data/issue_pipeline.yml  escalations + agent PRs       (Layer 3)
  _data/token_rotation.yml  credential ages               (Layer 5)
  _data/ai_usage.yml        agent cost, its parity and coverage (agentic)
  _data/agents.yml          who reads a stale source      (agentic)
  harness.sources files     each committed `_data/*.yml` source, for its age;
                            a source that is not a committed file (the lake,
                            a live API) is `unknown`, never read from `~/`

Output: _data/harness_health.yml (committed, published by fleet-pulse.yml's
pulse job, rendered by the dash). With GITHUB_OUTPUT set it emits
`tripped_count` and `has_tripped` for the workflow summary to branch on.

Exit status is 0 even when wires trip — a tripped wire is data for a human and
for the next remediation pass, not a reason to kill the pulse that reports it.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.stderr.write("harness requires PyYAML: pip install pyyaml\n")
    sys.exit(2)

REPO_ROOT = Path(__file__).resolve().parents[3]
FLEET_DEFAULT = REPO_ROOT / "_data" / "fleet.yml"
USAGE_DEFAULT = REPO_ROOT / "_data" / "actions_usage.yml"
TRIAGE_DEFAULT = REPO_ROOT / "_data" / "fleet_triage.yml"
PIPELINE_DEFAULT = REPO_ROOT / "_data" / "issue_pipeline.yml"
ROTATION_DEFAULT = REPO_ROOT / "_data" / "token_rotation.yml"
CONFORMANCE_DEFAULT = REPO_ROOT / "_data" / "conformance.yml"
AI_USAGE_DEFAULT = REPO_ROOT / "_data" / "ai_usage.yml"
AGENTS_DEFAULT = REPO_ROOT / "_data" / "agents.yml"
OUT_DEFAULT = REPO_ROOT / "_data" / "harness_health.yml"

# Mirrors the `harness:` block in _data/fleet.yml — that file is the contract,
# these are the fallbacks when a key (or the whole block) is absent.
DEFAULT_SCORECARD = {
    "completion_rate_min_pct": 80,
    "effectiveness_min_pct": 70,
}
DEFAULT_TRIP_WIRES = {
    "stale_data_days": 3,
    "conformance_stale_days": 14,
    "pass_rate_floor_pct": 75,
    "waste_ceiling_pct": 30,
    "cost_spike_multiplier": 3.0,
    "cost_spike_min_runs": 3,
    "cost_spike_min_avg_min": 5.0,
    "standing_failures_max": 30,
    "credential_grace_days": 15,
}
DEFAULT_AGENTIC = {
    "shadow_days": 14,
    "parity_tolerance_pct": 5.0,
    "unknown_cost_max_pct": 25.0,
}

# A harness.sources path this module may read: one committed YAML file under
# _data/. Anything else (the lake, ~/.claude, a live API, a directory) is
# reported `unknown` — the agentic layer runs in CI and never reads the Mac.
COMMITTED_SOURCE_RX = re.compile(r"^_data/[A-Za-z0-9_][A-Za-z0-9_./-]*\.ya?ml$")
# The parity blocks E1 (#775) publishes, per analytics file.
PARITY_MEASURES = (("actions_usage", "actions_minutes"), ("ai_usage", "ai_ci_cost"))
UNKNOWN = "unknown"


# --------------------------------------------------------------------------- #
# config + input loading
# --------------------------------------------------------------------------- #
def load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with path.open() as fh:
            data = yaml.safe_load(fh)
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def load_config(fleet_path: Path) -> dict:
    fleet = load_yaml(fleet_path)
    cfg = fleet.get("harness") or {}
    hub = fleet.get("hub") if isinstance(fleet.get("hub"), dict) else {}
    sources = cfg.get("sources")
    return {
        "scorecard": {**DEFAULT_SCORECARD, **(cfg.get("scorecard") or {})},
        "trip_wires": {**DEFAULT_TRIP_WIRES, **(cfg.get("trip_wires") or {})},
        "agentic": {**DEFAULT_AGENTIC, **(cfg.get("agentic") or {})},
        "sources": sources if isinstance(sources, dict) else {},
        "hub_repo": hub.get("repo") if isinstance(hub.get("repo"), str) else None,
    }


def load_declared_sources(sources_cfg: dict, root: Path, preloaded: dict | None = None) -> dict:
    """Each `harness.sources` entry with an `slo_days`, as data to date.

    A path that is one committed `_data/*.yml` file is read (`preloaded`
    supplies the inputs this run already holds, keyed by source id, so a
    `--usage` override is judged as itself); `{}` means the file is missing.
    Any other path maps to None: not readable offline, reported `unknown`.
    """
    preloaded = preloaded or {}
    out: dict = {}
    for sid, spec in (sources_cfg or {}).items():
        if not isinstance(spec, dict) or not isinstance(spec.get("slo_days"), (int, float)):
            continue
        if sid in preloaded:
            out[sid] = preloaded[sid] or {}
            continue
        path = spec.get("path")
        if isinstance(path, str) and COMMITTED_SOURCE_RX.match(path) and ".." not in path:
            out[sid] = load_yaml(root / path)
        else:
            out[sid] = None
    return out


def parse_generated_at(value: object) -> dt.datetime | None:
    """The generators all stamp '%Y-%m-%d %H:%M UTC'; tolerate ISO too."""
    if isinstance(value, dt.datetime):  # an unquoted YAML timestamp
        return value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)
    if not isinstance(value, str):
        return None
    for fmt in ("%Y-%m-%d %H:%M UTC", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"):
        try:
            ts = dt.datetime.strptime(value, fmt)
        except ValueError:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=dt.timezone.utc)
        return ts
    return None


def source_age_days(data: dict, now: dt.datetime) -> float | None:
    # ai_usage.yml stamps `generated`, every other signal `generated_at`.
    ts = parse_generated_at(data.get("generated_at") or data.get("generated"))
    if ts is None:
        return None
    return round((now - ts).total_seconds() / 86400, 1)


def rotation_repo_state(row: dict, mode: object) -> tuple[object, object]:
    """(state, age_days) of one repo in the token-rotation ledger, AFTER the run.

    An `apply` run surveys first and writes second. Ledgers written before
    tools/fleet-config.py published post-write rows carry the pre-write
    `state`/`age_days` beside `action: written`, so a repo the run had just
    fixed read as missing or overdue for a week. A successful applied write
    means the repo now holds a fresh copy; a dry run's `written` only means
    "would write" and is read as observed.
    """
    if mode == "apply" and row.get("action") == "written":
        return "ok", 0
    return row.get("state"), row.get("age_days")


def rotation_oldest_age(token: dict, mode: object) -> object:
    """The token's oldest copy in days, over the post-run repo states.

    Recomputed from `repos` when the ledger lists them (so an old-shape apply
    ledger stops reporting a replaced copy's age); otherwise the token's own
    `oldest_age_days`.
    """
    repos = [r for r in token.get("repos") or [] if isinstance(r, dict)]
    if not repos:
        return token.get("oldest_age_days")
    ages = [age for age in (rotation_repo_state(r, mode)[1] for r in repos)
            if isinstance(age, (int, float))]
    return max(ages) if ages else None


def median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


# --------------------------------------------------------------------------- #
# scorecard
# --------------------------------------------------------------------------- #
def build_scorecard(cfg: dict, usage: dict, triage: dict, pipeline: dict, rotation: dict) -> dict:
    """The playbook's health scorecard, from the signals the fleet already keeps.

    Every metric carries its desired direction so the dash can render trend
    arrows without re-encoding policy, and `status` is only pass/fail where the
    contract declares a threshold — everything else is informational.
    """
    u_tot = usage.get("totals") or {}
    t_tot = triage.get("totals") or {}
    p_tot = pipeline.get("totals") or {}
    stages = p_tot.get("stages") or {}

    verified_runs = None
    workflows = usage.get("workflows")
    if isinstance(workflows, list) and workflows:
        verified_runs = sum(int(w.get("success") or 0) for w in workflows)
    cost_per_verified = None
    if verified_runs and u_tot.get("total_min"):
        cost_per_verified = round(float(u_tot["total_min"]) / verified_runs, 2)

    oldest_credential = None
    for token in rotation.get("tokens") or []:
        age = rotation_oldest_age(token, rotation.get("mode")) if isinstance(token, dict) else None
        if isinstance(age, (int, float)):
            oldest_credential = max(oldest_credential or 0, age)

    sc = cfg["scorecard"]

    def metric(value, direction, threshold=None, ok=None):
        entry = {"value": value, "direction": direction}
        if threshold is not None:
            entry["threshold"] = threshold
            entry["status"] = "unknown" if value is None else ("ok" if ok else "warn")
        return entry

    completion = u_tot.get("success_rate_pct")
    effectiveness = u_tot.get("effectiveness_pct")
    escalations = None
    if stages:
        escalations = int(stages.get("blocked") or 0) + int(stages.get("hold") or 0)

    return {
        "completion_rate_pct": metric(
            completion, "up", sc["completion_rate_min_pct"],
            completion is not None and completion >= sc["completion_rate_min_pct"],
        ),
        "effectiveness_pct": metric(
            effectiveness, "up", sc["effectiveness_min_pct"],
            effectiveness is not None and effectiveness >= sc["effectiveness_min_pct"],
        ),
        "waste_hours": metric(u_tot.get("waste_hours"), "down"),
        "cost_min_per_verified_run": metric(cost_per_verified, "down"),
        "standing_failures": metric(t_tot.get("failing_workflows"), "down"),
        "repos_red": metric(t_tot.get("repos_red"), "down"),
        "escalations_open": metric(escalations, "down"),
        "agent_prs_open": metric(p_tot.get("pipeline_prs"), "steady"),
        "oldest_credential_age_days": metric(oldest_credential, "down"),
    }


# --------------------------------------------------------------------------- #
# trip wires
# --------------------------------------------------------------------------- #
def evaluate_trip_wires(
    cfg: dict,
    usage: dict,
    triage: dict,
    pipeline: dict,
    rotation: dict,
    now: dt.datetime,
    conformance: dict | None = None,
) -> list[dict]:
    """Every wire is reported, tripped or not — an alarm panel that hides its
    armed-but-quiet wires can't be told apart from one that lost them."""
    tw = cfg["trip_wires"]
    wires: list[dict] = []

    def wire(wire_id: str, tripped: bool, summary: str, detail: list | None = None):
        entry = {"id": wire_id, "tripped": bool(tripped), "summary": summary}
        if detail:
            entry["detail"] = detail
        wires.append(entry)

    # 1. stale-data — the observability layer watching itself. This fleet's
    # data loops once died silently for three weeks; this wire is that
    # postmortem made permanent (the ratchet, applied to the harness itself).
    sources = {
        "actions_usage": usage,
        "fleet_triage": triage,
        "issue_pipeline": pipeline,
        "token_rotation": rotation,
    }
    # The UPS conformance snapshot (tools/conformance.py fleet --write) was
    # regenerated by hand until fleet-snapshots.yml (weekly, #775), so it once
    # sat 38 days old while this wire said "all fleet signals fresh" and the
    # repo-evolution brief read it as current. Weekly, it gets its own, longer
    # limit. None = not watched (callers that predate it); {} = the file is missing.
    if conformance is not None:
        sources["conformance"] = conformance
    stale = []
    for name, data in sources.items():
        if name == "token_rotation":
            limit = 10  # weekly loop: a fortnight-old ledger is one missed run
        elif name == "conformance":
            limit = tw["conformance_stale_days"]
        else:
            limit = tw["stale_data_days"]
        age = source_age_days(data, now)
        if not data:
            stale.append({"source": name, "age_days": None, "why": "missing"})
        elif age is None:
            stale.append({"source": name, "age_days": None, "why": "no generated_at"})
        elif age > limit:
            stale.append({"source": name, "age_days": age, "why": f"older than {limit}d"})
    wire(
        "stale-data",
        bool(stale),
        "a committed fleet signal stopped refreshing" if stale else "all fleet signals fresh",
        stale,
    )

    u_tot = usage.get("totals") or {}

    # 2. pass-rate-floor — fleet-wide quality regression.
    rate = u_tot.get("success_rate_pct")
    wire(
        "pass-rate-floor",
        rate is not None and rate < tw["pass_rate_floor_pct"],
        f"fleet workflow success rate {rate}% vs floor {tw['pass_rate_floor_pct']}%",
    )

    # 3. waste-ceiling — minutes ending in non-success, as a share of all minutes.
    waste_pct = None
    if u_tot.get("total_min"):
        waste_pct = round(100 * float(u_tot.get("waste_min") or 0) / float(u_tot["total_min"]), 1)
    wire(
        "waste-ceiling",
        waste_pct is not None and waste_pct > tw["waste_ceiling_pct"],
        f"wasted minutes {waste_pct}% of total vs ceiling {tw['waste_ceiling_pct']}%",
    )

    # 4. cost-spike — a workflow whose average run dwarfs the fleet median.
    # Median, not mean: one runaway is exactly what must not move the baseline.
    workflows = [
        w for w in (usage.get("workflows") or [])
        if not w.get("external")
        and int(w.get("runs") or 0) >= tw["cost_spike_min_runs"]
        and isinstance(w.get("avg_min"), (int, float))
    ]
    med = median([float(w["avg_min"]) for w in workflows])
    spikes = []
    if med:
        # The absolute floor keeps a fleet of tiny workflows honest: with a
        # sub-minute median, a bare multiple flags every ordinary CI run and
        # the wire never goes quiet again.
        threshold = max(med * tw["cost_spike_multiplier"], tw["cost_spike_min_avg_min"])
        spikes = sorted(
            (w for w in workflows if float(w["avg_min"]) >= threshold),
            key=lambda w: -float(w["avg_min"]),
        )[:5]
    wire(
        "cost-spike",
        bool(spikes),
        f"workflows averaging ≥{tw['cost_spike_multiplier']}× the fleet median ({med} min)"
        if med else "no usable per-workflow cost data",
        [
            {
                "repo": w.get("repo"),
                "workflow": w.get("workflow"),
                "path": w.get("path"),
                "avg_min": w.get("avg_min"),
                "runs": w.get("runs"),
            }
            for w in spikes
        ],
    )

    # 5. standing-failures — the backlog the doctor drains is growing past what
    # its caps can drain; the response is triage attention, not a bigger cap.
    failing = (triage.get("totals") or {}).get("failing_workflows")
    wire(
        "standing-failures",
        failing is not None and failing > tw["standing_failures_max"],
        f"{failing} standing red workflows vs max {tw['standing_failures_max']}",
    )

    # 6. credential-overdue — a fleet credential aged past its own rotation
    # policy plus grace; past this the weekly loop is asking for a human.
    overdue = []
    for token in rotation.get("tokens") or []:
        if not isinstance(token, dict):
            continue
        age = rotation_oldest_age(token, rotation.get("mode"))
        max_age = token.get("max_age_days")
        if isinstance(age, (int, float)) and isinstance(max_age, (int, float)):
            if age > max_age + tw["credential_grace_days"]:
                overdue.append(
                    {"name": token.get("name"), "oldest_age_days": age, "max_age_days": max_age}
                )
    wire(
        "credential-overdue",
        bool(overdue),
        "a fleet credential is past its rotation policy plus grace"
        if overdue else "credential ages within policy",
        overdue,
    )

    return wires


# --------------------------------------------------------------------------- #
# the agentic layer (constitution § 29; epic #773, phase E2: #776)
# --------------------------------------------------------------------------- #
def combine(states: list) -> object:
    """A wire's verdict from its checks: any trip trips it; otherwise one check
    that could not be read keeps it `unknown` (never green); else quiet."""
    if any(s is True for s in states):
        return True
    if any(s == UNKNOWN for s in states):
        return UNKNOWN
    return False


def _num(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _as_date(value: object) -> dt.date | None:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        try:
            return dt.date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _readers(agents: dict | None) -> dict[str, int]:
    """Source id -> how many registered agents read it (_data/agents.yml)."""
    counts: dict[str, int] = {}
    for agent in (agents or {}).get("agents") or []:
        if isinstance(agent, dict) and isinstance(agent.get("reads"), dict):
            for sid in agent["reads"]:
                counts[sid] = counts.get(sid, 0) + 1
    return counts


def wire_source_freshness(cfg: dict, sources: dict, now: dt.datetime, agents: dict | None) -> dict:
    """§ 29.4: a source with no writer is a defect, and so is one older than its
    SLO. Every `harness.sources` entry with an `slo_days` is dated against it;
    one that is not a committed file is `unknown` (and does not decide the
    verdict); a null writer trips whatever the source's SLO kind."""
    readers = _readers(agents)
    rows: list[dict] = []
    for sid, spec in (cfg.get("sources") or {}).items():
        if not isinstance(spec, dict):
            continue
        no_writer = not spec.get("writer")
        slo = _num(spec.get("slo_days"))
        if slo is None and not no_writer:
            continue  # on-change / live: a reviewed PR or the run itself keeps it current
        row: dict = {"source": sid, "path": spec.get("path")}
        if slo is not None:
            row["slo_days"] = spec["slo_days"]
        else:
            row["slo"] = spec.get("slo")
        state, why, age = "ok", [], None
        if slo is not None:
            data = sources.get(sid)
            if data is None:
                state, why = UNKNOWN, ["not a committed _data/*.yml file, so not read offline"]
            elif not data:
                state, why = "missing", ["missing"]
            else:
                age = source_age_days(data, now)
                if age is None:
                    state, why = "undated", ["no generated_at"]
                elif age > slo:
                    state, why = "stale", [f"older than {spec['slo_days']}d"]
        if no_writer:
            why.append("no writer")
            if state in ("ok", UNKNOWN):
                state = "no-writer"
        row["age_days"] = age
        row["state"] = state
        if why:
            row["why"] = "; ".join(why)
        if state not in ("ok", UNKNOWN) and readers.get(sid):
            row["readers"] = readers[sid]
        rows.append(row)

    bad = [r for r in rows if r["state"] not in ("ok", UNKNOWN)]
    unread = [r["source"] for r in rows if r["state"] == UNKNOWN]
    judged = len(rows) - len(unread)
    if bad:
        tripped: object = True
        summary = (f"{len(bad)} of {len(rows)} declared sources past their SLO or without a writer: "
                   + ", ".join(r["source"] for r in bad))
    elif not judged:
        tripped = UNKNOWN
        summary = ("no declared source with an SLO can be read offline" if rows
                   else "_data/fleet.yml declares no harness.sources with an slo_days")
    else:
        tripped = False
        summary = f"all {judged} readable declared sources within their SLO"
    if unread:
        summary += f" ({len(unread)} not readable offline: {', '.join(unread)})"
    return {"tripped": tripped, "summary": summary, "detail": rows}


def _is_hub(row: dict, hub: str) -> bool:
    return row.get("nwo") == hub or row.get("repo") in (hub, hub.split("/")[-1])


def wire_coverage_hub(cfg: dict, analytics: dict) -> dict:
    """The hub is not in the registry, so a collector that walks only the
    registry drops the fleet's largest spender (2026-11-07: the hub was
    missing from actions_usage.yml). Present = a `by_repo` row, or a
    `coverage.repos` row the collector read without an error."""
    hub = cfg.get("hub_repo")
    if not hub:
        return {"tripped": UNKNOWN, "summary": "_data/fleet.yml names no hub.repo to look for", "detail": []}
    rows, states = [], []
    for name, data in analytics.items():
        if not data:
            rows.append({"analytics": name, "state": UNKNOWN, "why": "missing"})
            states.append(UNKNOWN)
            continue
        cov = data.get("coverage") if isinstance(data.get("coverage"), dict) else {}
        listed = any(isinstance(r, dict) and _is_hub(r, hub) for r in data.get("by_repo") or [])
        scanned = any(isinstance(r, dict) and _is_hub(r, hub) and not r.get("error")
                      for r in cov.get("repos") or [])
        present = listed or scanned
        rows.append({"analytics": name, "state": "present" if present else "absent"})
        states.append(not present)
    tripped = combine(states)
    absent = [r["analytics"] for r in rows if r["state"] == "absent"]
    if tripped is True:
        summary = f"the hub ({hub}) is missing from {', '.join(absent)}"
    elif tripped == UNKNOWN:
        summary = "cannot tell whether the hub is measured: " + ", ".join(
            r["analytics"] for r in rows if r["state"] == UNKNOWN) + " missing"
    else:
        summary = f"the hub ({hub}) is in every analytics"
    return {"tripped": tripped, "summary": summary, "detail": rows}


def wire_coverage_complete(analytics: dict) -> dict:
    """No collector stopped short: no repo truncated, no run missed, no repo the
    collector could not read. An analytics file without a `coverage` block
    predates coverage reporting and is `unknown`."""
    rows, states = [], []
    for name, data in analytics.items():
        cov = data.get("coverage") if isinstance(data, dict) else None
        if not data or not isinstance(cov, dict) or not cov:
            rows.append({"analytics": name, "state": UNKNOWN,
                         "why": "missing" if not data else "no coverage block"})
            states.append(UNKNOWN)
            continue
        repos = [r for r in cov.get("repos") or [] if isinstance(r, dict)]
        truncated = sorted({str(x) for x in cov.get("truncated_repos") or []}
                           | {str(r.get("repo") or r.get("nwo")) for r in repos if r.get("truncated")})
        unread = sorted(str(r.get("repo") or r.get("nwo")) for r in repos if r.get("error"))
        missed = int(_num(cov.get("runs_missed")) or 0)
        incomplete = bool(cov.get("truncated")) or bool(truncated) or bool(unread) or missed > 0
        row: dict = {"analytics": name, "state": "incomplete" if incomplete else "complete"}
        if truncated:
            row["truncated_repos"] = truncated
        if unread:
            row["unread_repos"] = unread
        if missed:
            row["runs_missed"] = missed
        rows.append(row)
        states.append(incomplete)
    tripped = combine(states)
    if tripped is True:
        summary = "a collector stopped short: " + ", ".join(
            r["analytics"] for r in rows if r["state"] == "incomplete")
    elif tripped == UNKNOWN:
        summary = "coverage unknown for " + ", ".join(
            f"{r['analytics']} ({r['why']})" for r in rows if r["state"] == UNKNOWN)
    else:
        summary = "every collector read every repo in its window"
    return {"tripped": tripped, "summary": summary, "detail": rows}


def wire_coverage_parity(agentic: dict, analytics: dict) -> dict:
    """Each derived total against its own source (E1, #775): Actions minutes
    against the billing meter, the CI agent cost against the claude-cost
    result lines. A missing block or a null gap is `unknown`, never green."""
    tol = float(agentic["parity_tolerance_pct"])
    rows, states = [], []
    for name, measure in PARITY_MEASURES:
        data = analytics.get(name) or {}
        parity = data.get("parity") if isinstance(data.get("parity"), dict) else {}
        block = parity.get(measure)
        row: dict = {"analytics": name, "measure": measure, "tolerance_pct": tol}
        if not data:
            row.update(state=UNKNOWN, why="missing")
        elif not isinstance(block, dict):
            row.update(state=UNKNOWN, why=f"no parity.{measure} block")
        else:
            gap = _num(block.get("gap_pct"))
            row["gap_pct"] = gap
            if block.get("sampled"):
                row["sampled"] = True
            if gap is None:
                row.update(state=UNKNOWN, why=str(block.get("reason") or "gap_pct is null"))
            else:
                row["state"] = "out" if abs(gap) > tol else "within"
        rows.append(row)
        states.append(UNKNOWN if row["state"] == UNKNOWN else row["state"] == "out")
    tripped = combine(states)
    if tripped is True:
        summary = f"parity out of ±{tol:g}%: " + ", ".join(
            f"{r['measure']} {r['gap_pct']:+g}%" for r in rows if r["state"] == "out")
    elif tripped == UNKNOWN:
        summary = "parity unknown for " + ", ".join(
            f"{r['measure']} ({r['why']})" for r in rows if r["state"] == UNKNOWN)
    else:
        summary = f"every parity measure within ±{tol:g}%"
    return {"tripped": tripped, "summary": summary, "detail": rows}


def wire_unknown_agent_cost(agentic: dict, ai_usage: dict) -> dict:
    """§ 29.2: a run that reads $0 when its cost is unknown is a silent failure.
    Of the CI agent runs that spent (priced + estimated; no-spend runs are a
    real $0), the share whose cost could not be read from the run itself."""
    ceiling = float(agentic["unknown_cost_max_pct"])
    if not ai_usage:
        return {"tripped": UNKNOWN, "summary": "ai_usage.yml is missing", "detail": []}
    tot = ai_usage.get("totals") if isinstance(ai_usage.get("totals"), dict) else {}
    priced, unpriced = _num(tot.get("ci_priced_runs")), _num(tot.get("ci_unpriced_runs"))
    if priced is None or unpriced is None:
        return {"tripped": UNKNOWN, "detail": [],
                "summary": "ai_usage.yml totals carry no ci_priced_runs / ci_unpriced_runs"}
    runs = priced + unpriced
    if not runs:
        return {"tripped": UNKNOWN, "detail": [],
                "summary": "no CI agent run with spend in the window to judge"}
    pct = round(100 * unpriced / runs, 1)
    detail: list[dict] = [{
        "scope": "fleet", "agent_runs": int(runs), "unpriced_runs": int(unpriced),
        "unknown_pct": pct, "ceiling_pct": ceiling,
        "measured_usd": tot.get("ci_cost_usd"), "estimated_usd": tot.get("ci_estimated_usd"),
    }]
    worst = sorted(
        (r for r in ai_usage.get("by_repo") or []
         if isinstance(r, dict) and (_num(r.get("unpriced_runs")) or 0) > 0),
        key=lambda r: (-float(r["unpriced_runs"]), str(r.get("repo"))),
    )[:5]
    for r in worst:
        n = (_num(r.get("priced_runs")) or 0) + float(r["unpriced_runs"])
        detail.append({"scope": "repo", "repo": r.get("repo"), "agent_runs": int(n),
                       "unpriced_runs": int(r["unpriced_runs"]),
                       "unknown_pct": round(100 * float(r["unpriced_runs"]) / n, 1)})
    return {
        "tripped": pct > ceiling,
        "summary": f"{pct}% of {int(runs)} CI agent runs have no readable cost vs ceiling {ceiling:g}%",
        "detail": detail,
    }


def apply_shadow(wires: list[dict], previous: dict | None, now: dt.datetime, shadow_days: object) -> list[dict]:
    """Stamp each wire's `first_seen` (carried forward from the previous
    harness_health.yml, else today) and put it in shadow until `shadow_days`
    after it. A shadowed wire is published but never counts in tripped_count."""
    seen: dict[str, dt.date] = {}
    for w in (previous or {}).get("agentic") or []:
        if isinstance(w, dict) and w.get("id"):
            first = _as_date(w.get("first_seen"))
            if first:
                seen[str(w["id"])] = first
    today = now.date()
    days = int(_num(shadow_days) or 0)
    out = []
    for w in wires:
        first = min(seen.get(w["id"], today), today)  # a future stamp cannot stretch the shadow
        until = first + dt.timedelta(days=days)
        out.append({
            "id": w["id"], "group": w["group"], "tripped": w["tripped"],
            "shadow": today < until, "first_seen": first.isoformat(), "shadow_until": until.isoformat(),
            "summary": w["summary"], "detail": w.get("detail") or [],
        })
    return out


def evaluate_agentic_layer(
    cfg: dict,
    usage: dict,
    ai_usage: dict,
    sources: dict,
    now: dt.datetime,
    *,
    agents: dict | None = None,
    previous: dict | None = None,
) -> list[dict]:
    """The agentic layer's wires, every one reported. `sources` maps each
    `harness.sources` id to its parsed data ({} = missing, None = not readable
    offline); see load_declared_sources. Offline and deterministic."""
    agentic = {**DEFAULT_AGENTIC, **(cfg.get("agentic") or {})}
    analytics = {"actions_usage": usage or {}, "ai_usage": ai_usage or {}}
    built = [
        ("source-freshness", "source-freshness", wire_source_freshness(cfg, sources or {}, now, agents)),
        ("coverage-hub", "measurement-coverage", wire_coverage_hub(cfg, analytics)),
        ("coverage-complete", "measurement-coverage", wire_coverage_complete(analytics)),
        ("coverage-parity", "measurement-coverage", wire_coverage_parity(agentic, analytics)),
        ("unknown-agent-cost", "unknown-agent-cost", wire_unknown_agent_cost(agentic, ai_usage or {})),
    ]
    wires = [{"id": wid, "group": group, **body} for wid, group, body in built]
    return apply_shadow(wires, previous, now, agentic["shadow_days"])


def live_trips(agentic: list[dict]) -> list[dict]:
    """The agentic wires that count: tripped (not unknown) and out of shadow."""
    return [w for w in agentic if w.get("tripped") is True and not w.get("shadow")]


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #
def parse_now(value: object) -> dt.datetime:
    """`--now` pins the clock (fixture tests, a replay of a past day's signals)."""
    if isinstance(value, str) and value:
        ts = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        return ts if ts.tzinfo else ts.replace(tzinfo=dt.timezone.utc)
    return dt.datetime.now(dt.timezone.utc)


def run(args: argparse.Namespace) -> int:
    now = parse_now(getattr(args, "now", None))
    cfg = load_config(Path(args.fleet))
    usage = load_yaml(Path(args.usage))
    triage = load_yaml(Path(args.triage))
    pipeline = load_yaml(Path(args.pipeline))
    rotation = load_yaml(Path(args.rotation))
    conformance = load_yaml(Path(args.conformance))

    # The agentic layer's inputs. A caller that predates them (a Namespace
    # without the attribute) gets an empty input, never a read of the tree.
    def optional(name: str) -> dict:
        path = getattr(args, name, None)
        return load_yaml(Path(path)) if path else {}

    ai_usage = optional("ai_usage")
    agents = optional("agents")
    previous = optional("previous")
    sources = load_declared_sources(
        cfg["sources"], Path(getattr(args, "root", None) or REPO_ROOT),
        preloaded={
            "actions-usage": usage, "ai-usage": ai_usage, "fleet-triage": triage,
            "issue-pipeline": pipeline, "token-rotation": rotation,
            "conformance": conformance, "harness-health": previous,
        },
    )

    scorecard = build_scorecard(cfg, usage, triage, pipeline, rotation)
    wires = evaluate_trip_wires(cfg, usage, triage, pipeline, rotation, now, conformance=conformance)
    tripped = [w for w in wires if w["tripped"]]
    agentic = evaluate_agentic_layer(cfg, usage, ai_usage, sources, now, agents=agents, previous=previous)
    live = live_trips(agentic)
    shadowed = [w for w in agentic if w["tripped"] is True and w["shadow"]]
    unknown = [w for w in agentic if w["tripped"] == UNKNOWN]
    tripped_count = len(tripped) + len(live)

    out = {
        "generated_at": now.strftime("%Y-%m-%d %H:%M UTC"),
        "sources": {
            name: {"present": bool(data), "age_days": source_age_days(data, now)}
            for name, data in (
                ("actions_usage", usage),
                ("fleet_triage", triage),
                ("issue_pipeline", pipeline),
                ("token_rotation", rotation),
                ("conformance", conformance),
                ("ai_usage", ai_usage),
            )
        },
        "scorecard": scorecard,
        "trip_wires": wires,
        "agentic": agentic,
        "tripped_count": tripped_count,
        "note": (
            "Six-layer harness health: scorecard + trip wires computed offline from "
            "the committed fleet signals (docs/HARNESS.md), and the agentic layer "
            "(constitution § 29): wires on the agents' own inputs, each true, false "
            "or unknown, in shadow for harness.agentic.shadow_days after first_seen. "
            "tripped_count counts the trip wires and the agentic wires out of shadow. "
            "Thresholds live in _data/fleet.yml `harness:`. A tripped wire is an "
            "attention item; the doctor and issue-pipeline loops own the fixes."
        ),
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as fh:
        fh.write(
            "# GENERATED by .github/scripts/dash-gen (harness) — refreshed daily by "
            "fleet-pulse.yml. Edit the generator, not this file.\n"
        )
        yaml.safe_dump(out, fh, sort_keys=False, allow_unicode=True)

    if not args.quiet:
        sys.stderr.write(
            f"Wrote {out_path} — {len(tripped)}/{len(wires)} trip wires tripped; agentic layer: "
            f"{len(live)} tripped, {len(shadowed)} tripped in shadow, {len(unknown)} unknown "
            f"of {len(agentic)}\n"
        )
        for w in tripped + live:
            sys.stderr.write(f"  ⚠ {w['id']}: {w['summary']}\n")
        for w in shadowed:
            sys.stderr.write(f"  ~ {w['id']} (shadow until {w['shadow_until']}): {w['summary']}\n")
        for w in unknown:
            sys.stderr.write(f"  ? {w['id']}: {w['summary']}\n")

    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out:
        with open(gh_out, "a") as fh:
            fh.write(f"tripped_count={tripped_count}\n")
            fh.write(f"has_tripped={'true' if tripped_count else 'false'}\n")
    return 0


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--fleet", default=str(FLEET_DEFAULT), help="fleet.yml (harness: thresholds)")
    parser.add_argument("--usage", default=str(USAGE_DEFAULT), help="actions_usage.yml input")
    parser.add_argument("--triage", default=str(TRIAGE_DEFAULT), help="fleet_triage.yml input")
    parser.add_argument("--pipeline", default=str(PIPELINE_DEFAULT), help="issue_pipeline.yml input")
    parser.add_argument("--rotation", default=str(ROTATION_DEFAULT), help="token_rotation.yml input")
    parser.add_argument("--conformance", default=str(CONFORMANCE_DEFAULT),
                        help="conformance.yml input (UPS snapshot; watched by stale-data)")
    parser.add_argument("--ai-usage", dest="ai_usage", default=str(AI_USAGE_DEFAULT),
                        help="ai_usage.yml input (agent cost, its parity and coverage; agentic layer)")
    parser.add_argument("--agents", default=str(AGENTS_DEFAULT),
                        help="agents.yml input (who reads a stale source; agentic layer)")
    parser.add_argument("--previous", default=str(OUT_DEFAULT),
                        help="the committed harness_health.yml the agentic wires' first_seen is carried from")
    parser.add_argument("--root", default=str(REPO_ROOT),
                        help="checkout the harness.sources paths resolve against")
    parser.add_argument("--now", default=None,
                        help="pin the clock (ISO 8601, UTC if no offset): fixture tests and replays")
    parser.add_argument("--out", default=str(OUT_DEFAULT), help="output path")
    parser.add_argument("--quiet", action="store_true", help="suppress the summary lines")
    parser.set_defaults(func=run)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    add_arguments(ap)
    raise SystemExit(run(ap.parse_args()))
