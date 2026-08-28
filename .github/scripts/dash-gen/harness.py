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

Inputs (all optional — a missing or degraded signal nulls that metric, never
crashes; the wire that watches for staleness is exactly how a missing input
becomes visible):

  _data/actions_usage.yml   cost / effectiveness / waste  (Layer 6)
  _data/fleet_triage.yml    standing open-state           (Layers 3+6)
  _data/issue_pipeline.yml  escalations + agent PRs       (Layer 3)
  _data/token_rotation.yml  credential ages               (Layer 5)

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
OUT_DEFAULT = REPO_ROOT / "_data" / "harness_health.yml"

# Mirrors the `harness:` block in _data/fleet.yml — that file is the contract,
# these are the fallbacks when a key (or the whole block) is absent.
DEFAULT_SCORECARD = {
    "completion_rate_min_pct": 80,
    "effectiveness_min_pct": 70,
}
DEFAULT_TRIP_WIRES = {
    "stale_data_days": 3,
    "pass_rate_floor_pct": 75,
    "waste_ceiling_pct": 30,
    "cost_spike_multiplier": 3.0,
    "cost_spike_min_runs": 3,
    "cost_spike_min_avg_min": 5.0,
    "standing_failures_max": 30,
    "credential_grace_days": 15,
}


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
    cfg = load_yaml(fleet_path).get("harness") or {}
    return {
        "scorecard": {**DEFAULT_SCORECARD, **(cfg.get("scorecard") or {})},
        "trip_wires": {**DEFAULT_TRIP_WIRES, **(cfg.get("trip_wires") or {})},
    }


def parse_generated_at(value: object) -> dt.datetime | None:
    """The generators all stamp '%Y-%m-%d %H:%M UTC'; tolerate ISO too."""
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
    ts = parse_generated_at(data.get("generated_at"))
    if ts is None:
        return None
    return round((now - ts).total_seconds() / 86400, 1)


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
        age = token.get("oldest_age_days") if isinstance(token, dict) else None
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
    stale = []
    for name, data in sources.items():
        if name == "token_rotation":
            limit = 10  # weekly loop: a fortnight-old ledger is one missed run
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
        age = token.get("oldest_age_days")
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
# entry point
# --------------------------------------------------------------------------- #
def run(args: argparse.Namespace) -> int:
    now = dt.datetime.now(dt.timezone.utc)
    cfg = load_config(Path(args.fleet))
    usage = load_yaml(Path(args.usage))
    triage = load_yaml(Path(args.triage))
    pipeline = load_yaml(Path(args.pipeline))
    rotation = load_yaml(Path(args.rotation))

    scorecard = build_scorecard(cfg, usage, triage, pipeline, rotation)
    wires = evaluate_trip_wires(cfg, usage, triage, pipeline, rotation, now)
    tripped = [w for w in wires if w["tripped"]]

    out = {
        "generated_at": now.strftime("%Y-%m-%d %H:%M UTC"),
        "sources": {
            name: {"present": bool(data), "age_days": source_age_days(data, now)}
            for name, data in (
                ("actions_usage", usage),
                ("fleet_triage", triage),
                ("issue_pipeline", pipeline),
                ("token_rotation", rotation),
            )
        },
        "scorecard": scorecard,
        "trip_wires": wires,
        "tripped_count": len(tripped),
        "note": (
            "Six-layer harness health: scorecard + trip wires computed offline from "
            "the committed fleet signals (docs/HARNESS.md). Thresholds live in "
            "_data/fleet.yml `harness:`. A tripped wire is an attention item; the "
            "doctor and issue-pipeline loops own the fixes."
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
        sys.stderr.write(f"Wrote {out_path} — {len(tripped)}/{len(wires)} trip wires tripped\n")
        for w in tripped:
            sys.stderr.write(f"  ⚠ {w['id']}: {w['summary']}\n")

    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out:
        with open(gh_out, "a") as fh:
            fh.write(f"tripped_count={len(tripped)}\n")
            fh.write(f"has_tripped={'true' if tripped else 'false'}\n")
    return 0


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--fleet", default=str(FLEET_DEFAULT), help="fleet.yml (harness: thresholds)")
    parser.add_argument("--usage", default=str(USAGE_DEFAULT), help="actions_usage.yml input")
    parser.add_argument("--triage", default=str(TRIAGE_DEFAULT), help="fleet_triage.yml input")
    parser.add_argument("--pipeline", default=str(PIPELINE_DEFAULT), help="issue_pipeline.yml input")
    parser.add_argument("--rotation", default=str(ROTATION_DEFAULT), help="token_rotation.yml input")
    parser.add_argument("--out", default=str(OUT_DEFAULT), help="output path")
    parser.add_argument("--quiet", action="store_true", help="suppress the summary lines")
    parser.set_defaults(func=run)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    add_arguments(ap)
    raise SystemExit(run(ap.parse_args()))
