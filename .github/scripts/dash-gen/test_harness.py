#!/usr/bin/env python3
"""
Fixture tests for harness.py — the six-layer scorecard + trip-wire builder.

Guards the invariants that make the alarm panel trustworthy:

  * a MISSING or unparseable input must trip stale-data, never crash — the whole
    point of this wire is surviving the failure mode where a signal quietly
    stops being produced;
  * cost-spike must use the MEDIAN, so one runaway workflow cannot raise the
    baseline that would have flagged it;
  * external mirrors and low-run workflows must never appear as cost spikes;
  * every wire is reported armed-or-tripped — a quiet panel and a lost panel
    must not look the same;
  * thresholds come from fleet.yml `harness:` with the module defaults as
    fallback, so an absent block degrades to sane behaviour instead of zeroes.

Deliberately dependency-light — no network, no gh, no pytest. Needs only PyYAML:

    python3 .github/scripts/dash-gen/test_harness.py
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import harness  # noqa: E402

NOW = dt.datetime(2026, 8, 27, 12, 0, tzinfo=dt.timezone.utc)
CFG = {
    "scorecard": dict(harness.DEFAULT_SCORECARD),
    "trip_wires": dict(harness.DEFAULT_TRIP_WIRES),
}


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #
def wf(repo="hub", avg=2.0, runs=5, success=5, external=False, **kw) -> dict:
    return {
        "repo": repo,
        "workflow": kw.get("workflow", "ci"),
        "path": ".github/workflows/ci.yml",
        "avg_min": avg,
        "runs": runs,
        "success": success,
        "external": external,
    }


def usage(workflows=None, **totals) -> dict:
    base = {
        "generated_at": "2026-08-27 09:00 UTC",
        "totals": {
            "success_rate_pct": 90.0,
            "effectiveness_pct": 82.0,
            "total_min": 100.0,
            "waste_min": 10.0,
            "waste_hours": 0.2,
            **totals,
        },
        "workflows": workflows if workflows is not None else [wf()],
    }
    return base


def triage(failing=5) -> dict:
    return {
        "generated_at": "2026-08-27 09:00 UTC",
        "totals": {"failing_workflows": failing, "repos_red": 2},
    }


def pipeline() -> dict:
    return {
        "generated_at": "2026-08-27 09:00 UTC",
        "totals": {"pipeline_prs": 3, "stages": {"blocked": 4, "hold": 1}},
    }


def rotation(age=10, max_age=45) -> dict:
    return {
        "generated_at": "2026-08-24 22:00 UTC",
        "tokens": [
            {"name": "CLAUDE_CODE_OAUTH_TOKEN", "oldest_age_days": age, "max_age_days": max_age}
        ],
    }


def wires_by_id(wires: list[dict]) -> dict:
    return {w["id"]: w for w in wires}


# --------------------------------------------------------------------------- #
# tests
# --------------------------------------------------------------------------- #
def test_all_wires_reported_even_when_quiet():
    wires = harness.evaluate_trip_wires(CFG, usage(), triage(), pipeline(), rotation(), NOW)
    ids = {w["id"] for w in wires}
    assert ids == {
        "stale-data",
        "pass-rate-floor",
        "waste-ceiling",
        "cost-spike",
        "standing-failures",
        "credential-overdue",
    }, ids
    assert not any(w["tripped"] for w in wires), wires


def test_missing_input_trips_stale_data_not_crash():
    wires = harness.evaluate_trip_wires(CFG, {}, {}, {}, {}, NOW)
    w = wires_by_id(wires)["stale-data"]
    assert w["tripped"]
    missing = {d["source"] for d in w["detail"]}
    assert missing == {"actions_usage", "fleet_triage", "issue_pipeline", "token_rotation"}


def test_old_snapshot_trips_stale_data():
    old = usage()
    old["generated_at"] = "2026-08-20 09:00 UTC"  # 7 days before NOW, limit 3
    wires = harness.evaluate_trip_wires(CFG, old, triage(), pipeline(), rotation(), NOW)
    w = wires_by_id(wires)["stale-data"]
    assert w["tripped"]
    assert [d["source"] for d in w["detail"]] == ["actions_usage"]


def test_rotation_ledger_gets_weekly_slack():
    # 3 days old would trip a daily signal, but the rotation loop is weekly.
    wires = harness.evaluate_trip_wires(CFG, usage(), triage(), pipeline(), rotation(), NOW)
    assert not wires_by_id(wires)["stale-data"]["tripped"]


def test_cost_spike_uses_median_not_mean():
    # Nine 2-minute workflows and one 60-minute runaway: the mean (~7.8) times 3
    # would be ~23 and still flag it, but a SECOND 20-minute workflow would
    # escape a mean dragged up by the first. Against the median (2.0) both flag.
    flock = [wf(avg=2.0, workflow=f"w{i}") for i in range(9)]
    spike = wf(repo="big", avg=60.0, workflow="runaway")
    second = wf(repo="mid", avg=20.0, workflow="creeper")
    wires = harness.evaluate_trip_wires(
        CFG, usage(workflows=flock + [spike, second]), triage(), pipeline(), rotation(), NOW
    )
    w = wires_by_id(wires)["cost-spike"]
    assert w["tripped"]
    flagged = {d["workflow"] for d in w["detail"]}
    assert flagged == {"runaway", "creeper"}, flagged


def test_cost_spike_absolute_floor_quiets_tiny_fleets():
    # Median 1.0 → 3× = 3.0, but the 5-minute floor wins: a 4-minute workflow
    # is an outlier by multiple yet too cheap to be an alarm.
    flock = [wf(avg=1.0, workflow=f"w{i}") for i in range(9)]
    outlier = wf(repo="hub", avg=4.0, workflow="chunky")
    wires = harness.evaluate_trip_wires(
        CFG, usage(workflows=flock + [outlier]), triage(), pipeline(), rotation(), NOW
    )
    assert not wires_by_id(wires)["cost-spike"]["tripped"]


def test_cost_spike_ignores_external_and_low_run_workflows():
    flock = [wf(avg=2.0, workflow=f"w{i}") for i in range(5)]
    ext = wf(repo="skills", avg=90.0, workflow="mirror", external=True)
    rare = wf(repo="hub", avg=90.0, workflow="once", runs=1)
    wires = harness.evaluate_trip_wires(
        CFG, usage(workflows=flock + [ext, rare]), triage(), pipeline(), rotation(), NOW
    )
    assert not wires_by_id(wires)["cost-spike"]["tripped"]


def test_pass_rate_floor_and_waste_ceiling():
    bad = usage(success_rate_pct=60.0, waste_min=40.0, total_min=100.0)
    wires = harness.evaluate_trip_wires(CFG, bad, triage(), pipeline(), rotation(), NOW)
    byid = wires_by_id(wires)
    assert byid["pass-rate-floor"]["tripped"]
    assert byid["waste-ceiling"]["tripped"]


def test_standing_failures_threshold():
    wires = harness.evaluate_trip_wires(CFG, usage(), triage(failing=31), pipeline(), rotation(), NOW)
    assert wires_by_id(wires)["standing-failures"]["tripped"]
    wires = harness.evaluate_trip_wires(CFG, usage(), triage(failing=30), pipeline(), rotation(), NOW)
    assert not wires_by_id(wires)["standing-failures"]["tripped"]


def test_credential_overdue_uses_ledger_policy_plus_grace():
    # 61 days vs max_age 45 + grace 15 = 60 → tripped; 60 exactly → not.
    wires = harness.evaluate_trip_wires(CFG, usage(), triage(), pipeline(), rotation(age=61), NOW)
    assert wires_by_id(wires)["credential-overdue"]["tripped"]
    wires = harness.evaluate_trip_wires(CFG, usage(), triage(), pipeline(), rotation(age=60), NOW)
    assert not wires_by_id(wires)["credential-overdue"]["tripped"]


def test_scorecard_thresholds_and_cost_per_verified_run():
    sc = harness.build_scorecard(CFG, usage(), triage(), pipeline(), rotation())
    assert sc["completion_rate_pct"]["status"] == "ok"
    # 100 total minutes over 5 verified runs (the single fixture workflow).
    assert sc["cost_min_per_verified_run"]["value"] == 20.0
    assert sc["escalations_open"]["value"] == 5  # 4 blocked + 1 hold
    assert sc["oldest_credential_age_days"]["value"] == 10

    low = usage(success_rate_pct=50.0)
    sc = harness.build_scorecard(CFG, low, triage(), pipeline(), rotation())
    assert sc["completion_rate_pct"]["status"] == "warn"

    sc = harness.build_scorecard(CFG, {}, {}, {}, {})
    assert sc["completion_rate_pct"]["status"] == "unknown"
    assert sc["cost_min_per_verified_run"]["value"] is None


def test_config_falls_back_when_block_absent(tmp_path=None):
    cfg = harness.load_config(Path("/nonexistent/fleet.yml"))
    assert cfg["trip_wires"]["cost_spike_multiplier"] == harness.DEFAULT_TRIP_WIRES["cost_spike_multiplier"]
    assert cfg["scorecard"]["completion_rate_min_pct"] == harness.DEFAULT_SCORECARD["completion_rate_min_pct"]


# --------------------------------------------------------------------------- #
def main() -> int:
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ✓ {name}")
            except AssertionError as exc:
                failures += 1
                print(f"  ✗ {name}: {exc}")
    print(f"{'FAIL' if failures else 'OK'} — harness fixture tests")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
