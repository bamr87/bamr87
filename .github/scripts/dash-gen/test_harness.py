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


def conformance(generated_at="2026-08-20T04:32:44Z") -> dict:
    return {"generated_at": generated_at, "summary": {}}


def test_conformance_snapshot_watched_with_its_own_limit():
    # 7 days old: stale for a daily signal (3d), fresh for conformance (14d).
    wires = harness.evaluate_trip_wires(CFG, usage(), triage(), pipeline(), rotation(), NOW,
                                        conformance=conformance())
    assert not wires_by_id(wires)["stale-data"]["tripped"], wires_by_id(wires)["stale-data"]


def test_old_conformance_snapshot_trips_stale_data():
    # The real incident: generated 2026-09-07, still there 38 days later.
    wires = harness.evaluate_trip_wires(CFG, usage(), triage(), pipeline(), rotation(), NOW,
                                        conformance=conformance("2026-07-20T04:32:44Z"))
    w = wires_by_id(wires)["stale-data"]
    assert w["tripped"] and w["summary"] != "all fleet signals fresh"
    assert [(d["source"], d["why"]) for d in w["detail"]] == [("conformance", "older than 14d")], w


def test_missing_conformance_snapshot_trips_but_unwatched_does_not():
    w = wires_by_id(harness.evaluate_trip_wires(CFG, usage(), triage(), pipeline(), rotation(), NOW,
                                                conformance={}))["stale-data"]
    assert w["tripped"] and w["detail"][0] == {"source": "conformance", "age_days": None, "why": "missing"}
    # callers that do not pass it keep the old four-source behaviour
    assert not wires_by_id(harness.evaluate_trip_wires(CFG, usage(), triage(), pipeline(), rotation(),
                                                       NOW))["stale-data"]["tripped"]


def test_conformance_limit_comes_from_fleet_yml():
    cfg = {"scorecard": CFG["scorecard"], "trip_wires": {**CFG["trip_wires"], "conformance_stale_days": 5}}
    w = wires_by_id(harness.evaluate_trip_wires(cfg, usage(), triage(), pipeline(), rotation(), NOW,
                                                conformance=conformance()))["stale-data"]
    assert w["tripped"] and w["detail"][0]["why"] == "older than 5d"
    live = harness.load_config(harness.FLEET_DEFAULT)["trip_wires"]
    assert live["conformance_stale_days"] == 14, live


def test_unquoted_yaml_timestamp_is_still_dated():
    stamp = dt.datetime(2026, 8, 26, 4, 0)  # what yaml.safe_load makes of an unquoted ISO stamp
    assert harness.source_age_days({"generated_at": stamp}, NOW) is not None


def test_run_writes_conformance_into_sources(tmp_path=None):
    import argparse
    import tempfile
    import yaml
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        (d / "conf.yml").write_text("generated_at: '2026-01-01T00:00:00Z'\n")
        out = d / "out.yml"
        ns = argparse.Namespace(fleet=str(d / "none.yml"), usage=str(d / "u.yml"), triage=str(d / "t.yml"),
                                pipeline=str(d / "p.yml"), rotation=str(d / "r.yml"),
                                conformance=str(d / "conf.yml"), out=str(out), quiet=True)
        assert harness.run(ns) == 0
        doc = yaml.safe_load(out.read_text())
        assert doc["sources"]["conformance"]["present"] is True
        stale = wires_by_id(doc["trip_wires"])["stale-data"]["detail"]
        assert any(x["source"] == "conformance" for x in stale), stale


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


def old_shape_apply_ledger(mode="apply", action="written") -> dict:
    """The committed 2026-11-02 shape: the survey's PRE-write state and age beside
    `action: written`, and a token-level oldest age taken from the replaced copy."""
    return {
        "generated_at": "2026-08-24 22:00 UTC",
        "mode": mode,
        "tokens": [{
            "name": "RELEASE_PLEASE_TOKEN", "oldest_age_days": 86, "max_age_days": 45,
            "repos": [
                {"nwo": "bamr87/a", "state": "ok", "age_days": 3, "action": "none"},
                {"nwo": "bamr87/b", "state": "stale", "age_days": 86, "action": action},
                {"nwo": "bamr87/c", "state": "missing", "age_days": None, "action": action},
            ],
        }],
    }


def test_credential_overdue_ignores_a_copy_the_apply_run_replaced():
    wires = harness.evaluate_trip_wires(CFG, usage(), triage(), pipeline(),
                                        old_shape_apply_ledger(), NOW)
    assert not wires_by_id(wires)["credential-overdue"]["tripped"]
    sc = harness.build_scorecard(CFG, usage(), triage(), pipeline(), old_shape_apply_ledger())
    assert sc["oldest_credential_age_days"]["value"] == 3


def test_credential_overdue_still_trips_on_a_dry_run_or_a_failed_write():
    for ledger in (old_shape_apply_ledger(mode="dry-run"),        # "written" = would write
                   old_shape_apply_ledger(action="failed")):      # the old copy is still there
        w = wires_by_id(harness.evaluate_trip_wires(CFG, usage(), triage(), pipeline(), ledger, NOW))
        assert w["credential-overdue"]["tripped"]
        assert w["credential-overdue"]["detail"][0]["oldest_age_days"] == 86


def test_rotation_repo_state_reads_an_applied_write_as_fresh():
    row = {"state": "missing", "age_days": None, "action": "written"}
    assert harness.rotation_repo_state(row, "apply") == ("ok", 0)
    assert harness.rotation_repo_state(row, "dry-run") == ("missing", None)
    assert harness.rotation_repo_state(dict(row, action="failed"), "apply") == ("missing", None)
    # A token without repo rows (the fixtures above) keeps its own oldest age.
    assert harness.rotation_oldest_age({"oldest_age_days": 10}, "apply") == 10


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


def test_a_v2_snapshot_is_judged_on_job_minutes():
    """actions-usage/v2 prices job-minutes and keeps the wall clock beside them
    (`wall_min`, `wall_avg_min`). The scorecard and the cost wires are COST
    signals, so they read the job-minute fields — a ten-job matrix finishing
    in 2 minutes costs 40 and is a cost spike against a 2-minute median —
    and the extra v2 blocks (parity, coverage, sampled/truncated) are ignored."""
    flock = [dict(wf(avg=2.0, workflow=f"w{i}"), wall_avg_min=1.0) for i in range(9)]
    matrix = dict(wf(repo="wide", avg=40.0, workflow="matrix"), wall_avg_min=2.0)
    v2 = usage(workflows=flock + [matrix], total_min=400.0, waste_min=50.0, wall_min=150.0,
               sampled=True, truncated=False, job_runs_estimated=12)
    v2.update(schema="actions-usage/v2", minutes_basis="job-minutes",
              parity={"actions_minutes": {"gap_pct": -3.2}}, coverage={"truncated": False})
    wires = wires_by_id(harness.evaluate_trip_wires(CFG, v2, triage(), pipeline(), rotation(), NOW))
    assert {d["workflow"] for d in wires["cost-spike"]["detail"]} == {"matrix"}
    assert not wires["waste-ceiling"]["tripped"]            # 50 / 400 = 12.5%
    assert not wires["stale-data"]["tripped"]
    sc = harness.build_scorecard(CFG, v2, triage(), pipeline(), rotation())
    assert sc["cost_min_per_verified_run"]["value"] == 8.0   # 400 job-minutes / 50 verified runs


def test_config_falls_back_when_block_absent(tmp_path=None):
    cfg = harness.load_config(Path("/nonexistent/fleet.yml"))
    assert cfg["trip_wires"]["cost_spike_multiplier"] == harness.DEFAULT_TRIP_WIRES["cost_spike_multiplier"]
    assert cfg["scorecard"]["completion_rate_min_pct"] == harness.DEFAULT_SCORECARD["completion_rate_min_pct"]


# --------------------------------------------------------------------------- #
# the agentic layer (constitution § 29, #776): source freshness, measurement
# coverage, unknown agent cost — each wire true / false / unknown, in shadow
# for harness.agentic.shadow_days after its first_seen
# --------------------------------------------------------------------------- #
HUB = "bamr87/bamr87"
AGENTIC_IDS = {"source-freshness", "coverage-hub", "coverage-complete", "coverage-parity",
               "unknown-agent-cost"}
DECLARED = {
    "fleet-config": {"path": "_data/fleet.yml", "writer": "maintainer (reviewed PR)", "slo": "on-change"},
    "actions-usage": {"path": "_data/actions_usage.yml", "writer": "fleet-pulse.yml", "slo_days": 3},
    "conformance": {"path": "_data/conformance.yml", "writer": "tools/dash spec", "slo_days": 14},
    "lake": {"path": ".dash-lake/fleet.sqlite", "writer": "local:harness-review", "slo_days": 2},
}
AG_CFG = {**CFG, "agentic": dict(harness.DEFAULT_AGENTIC), "sources": DECLARED, "hub_repo": HUB}


def coverage_block(**kw) -> dict:
    return {"truncated": False, "runs_missed": 0, "truncated_repos": [],
            "repos": [{"repo": "bamr87", "nwo": HUB, "truncated": False, "runs_missed": 0, "error": None},
                      {"repo": "site", "nwo": "bamr87/site", "truncated": False, "runs_missed": 0,
                       "error": None}],
            **kw}


def ag_usage(**kw) -> dict:
    """actions_usage.yml (v2) with the blocks the agentic layer reads."""
    doc = usage()
    doc.update(by_repo=[{"repo": "bamr87", "runs": 40}, {"repo": "site", "runs": 9}],
               parity={"actions_minutes": {"gap_pct": -2.0, "sampled": False}},
               coverage=coverage_block())
    doc.update(kw)
    return doc


def ai_usage(priced=40, unpriced=5, **kw) -> dict:
    doc = {
        "generated": "2026-08-27 09:30 UTC",   # ai_usage.yml stamps `generated`, not generated_at
        "totals": {"ci_priced_runs": priced, "ci_unpriced_runs": unpriced, "ci_no_spend_runs": 300,
                   "ci_cost_usd": 120.0, "ci_estimated_usd": 3.0},
        "by_repo": [{"repo": "bamr87", "priced_runs": 30, "unpriced_runs": 1},
                    {"repo": "site", "priced_runs": 10, "unpriced_runs": 4}],
        "parity": {"ai_ci_cost": {"gap_pct": 0.0, "runs_off": 0}},
        "coverage": coverage_block(),
    }
    doc.update(kw)
    return doc


def declared_sources(**over) -> dict:
    """What load_declared_sources hands the layer: data per source id, None =
    not readable offline (the lake)."""
    data = {"actions-usage": ag_usage(), "conformance": conformance(), "lake": None}
    data.update(over)
    return data


def agentic(usage_doc=None, ai_doc=None, sources=None, cfg=None, previous=None, now=NOW) -> dict:
    wires = harness.evaluate_agentic_layer(
        cfg or AG_CFG, ag_usage() if usage_doc is None else usage_doc,
        ai_usage() if ai_doc is None else ai_doc,
        declared_sources() if sources is None else sources, now,
        agents={"agents": [{"id": "a", "reads": {"conformance": "x"}}]}, previous=previous)
    return wires_by_id(wires)


def test_agentic_layer_reports_every_wire_quiet_on_healthy_inputs():
    wires = agentic()
    assert set(wires) == AGENTIC_IDS, set(wires)
    for wid, w in wires.items():
        for key in ("id", "group", "tripped", "shadow", "first_seen", "shadow_until", "summary", "detail"):
            assert key in w, (wid, key)
        assert w["tripped"] is False, (wid, w)
        assert w["shadow"] is True and w["first_seen"] == NOW.date().isoformat(), w
    assert {w["group"] for w in wires.values()} == {"source-freshness", "measurement-coverage",
                                                     "unknown-agent-cost"}


# -- source freshness ------------------------------------------------------- #
def test_source_freshness_passes_on_fresh_sources_and_skips_on_change_ones():
    w = agentic()["source-freshness"]
    assert w["tripped"] is False, w
    rows = {r["source"]: r for r in w["detail"]}
    assert "fleet-config" not in rows                    # slo: on-change is not judged by age
    assert rows["actions-usage"]["state"] == "ok"
    assert rows["lake"]["state"] == "unknown"            # never read from the Mac, never decides
    assert "lake" in w["summary"]


def test_source_freshness_trips_on_a_source_past_its_own_slo():
    old = ag_usage(generated_at="2026-08-23 09:00 UTC")  # 4 days old, slo 3
    w = agentic(sources=declared_sources(**{"actions-usage": old}))["source-freshness"]
    assert w["tripped"] is True
    row = next(r for r in w["detail"] if r["source"] == "actions-usage")
    assert row["state"] == "stale" and row["why"] == "older than 3d", row
    # The same 7-day-old conformance file is fresh against its own 14-day SLO.
    assert next(r for r in w["detail"] if r["source"] == "conformance")["state"] == "ok"


def test_source_freshness_trips_on_a_source_with_no_writer():
    cfg = {**AG_CFG, "sources": {**DECLARED, "conformance": {**DECLARED["conformance"], "writer": None}}}
    w = agentic(cfg=cfg)["source-freshness"]
    assert w["tripped"] is True
    row = next(r for r in w["detail"] if r["source"] == "conformance")
    assert row["state"] == "no-writer" and row["why"] == "no writer" and row["readers"] == 1, row


def test_source_freshness_trips_on_a_missing_source():
    w = agentic(sources=declared_sources(conformance={}))["source-freshness"]
    assert w["tripped"] is True
    assert next(r for r in w["detail"] if r["source"] == "conformance")["state"] == "missing"


def test_source_freshness_is_unknown_when_nothing_can_be_read_offline():
    cfg = {**AG_CFG, "sources": {"lake": DECLARED["lake"]}}
    assert agentic(cfg=cfg)["source-freshness"]["tripped"] == "unknown"
    assert agentic(cfg={**AG_CFG, "sources": {}})["source-freshness"]["tripped"] == "unknown"


def test_load_declared_sources_reads_only_committed_data_files():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "_data").mkdir()
        (root / "_data" / "conformance.yml").write_text("generated_at: '2026-08-20T00:00:00Z'\n")
        declared = {**DECLARED,
                    "escape": {"path": "_data/../secrets.yml", "writer": "x", "slo_days": 1},
                    "home": {"path": "~/.claude/projects/", "writer": "x", "slo_days": 1}}
        got = harness.load_declared_sources(declared, root, preloaded={"actions-usage": {"a": 1}})
    assert got["conformance"]["generated_at"] == "2026-08-20T00:00:00Z"
    assert got["actions-usage"] == {"a": 1}                # this run's own input, not re-read
    assert got["lake"] is None and got["escape"] is None and got["home"] is None
    assert "fleet-config" not in got                     # no slo_days: nothing to date


# -- measurement coverage --------------------------------------------------- #
def test_coverage_hub_trips_when_the_hub_is_missing_from_the_analytics():
    # 2026-11-07: actions_usage.yml listed no hub row and had no coverage block.
    gone = ag_usage(by_repo=[{"repo": "site", "runs": 9}])
    gone.pop("coverage")
    w = agentic(usage_doc=gone)["coverage-hub"]
    assert w["tripped"] is True and "actions_usage" in w["summary"], w
    assert {r["analytics"]: r["state"] for r in w["detail"]} == {"actions_usage": "absent",
                                                                 "ai_usage": "present"}


def test_coverage_hub_counts_a_scanned_hub_without_a_by_repo_row():
    w = agentic(usage_doc=ag_usage(by_repo=[{"repo": "site", "runs": 9}]))["coverage-hub"]
    assert w["tripped"] is False, w
    errored = ag_usage(by_repo=[], coverage=coverage_block(
        repos=[{"repo": "bamr87", "nwo": HUB, "error": "404 Not Found"}]))
    assert agentic(usage_doc=errored)["coverage-hub"]["tripped"] is True


def test_coverage_hub_is_unknown_without_an_input_or_a_hub():
    assert agentic(ai_doc={})["coverage-hub"]["tripped"] == "unknown"
    assert agentic(cfg={**AG_CFG, "hub_repo": None})["coverage-hub"]["tripped"] == "unknown"


def test_coverage_complete_trips_on_a_truncated_or_unread_repo():
    cut = ai_usage(coverage=coverage_block(truncated=True, runs_missed=120, truncated_repos=["bamr87"]))
    w = agentic(ai_doc=cut)["coverage-complete"]
    assert w["tripped"] is True
    row = next(r for r in w["detail"] if r["analytics"] == "ai_usage")
    assert row == {"analytics": "ai_usage", "state": "incomplete", "truncated_repos": ["bamr87"],
                   "runs_missed": 120}, row
    unread = ag_usage(coverage=coverage_block(repos=[{"repo": "site", "nwo": "bamr87/site",
                                                     "error": "404 Not Found"}]))
    assert agentic(usage_doc=unread)["coverage-complete"]["tripped"] is True


def test_coverage_complete_is_unknown_without_a_coverage_block():
    old = ag_usage()
    old.pop("coverage")
    w = agentic(usage_doc=old)["coverage-complete"]
    assert w["tripped"] == "unknown" and "no coverage block" in w["summary"], w


def test_coverage_parity_trips_out_of_tolerance():
    w = agentic(usage_doc=ag_usage(parity={"actions_minutes": {"gap_pct": 8.8, "sampled": True}}))
    w = w["coverage-parity"]
    assert w["tripped"] is True and "+8.8%" in w["summary"], w
    row = next(r for r in w["detail"] if r["measure"] == "actions_minutes")
    assert row["state"] == "out" and row["sampled"] is True and row["tolerance_pct"] == 5.0
    # within tolerance either side of zero is quiet
    assert agentic(usage_doc=ag_usage(parity={"actions_minutes": {"gap_pct": -5.0}}))[
        "coverage-parity"]["tripped"] is False


def test_coverage_parity_is_unknown_never_green_when_a_block_is_absent():
    w = agentic(ai_doc={k: v for k, v in ai_usage().items() if k != "parity"})["coverage-parity"]
    assert w["tripped"] == "unknown", w
    assert "no parity.ai_ci_cost block" in w["summary"]
    # a block whose meter was unreachable is unknown too, with its own reason
    meterless = ag_usage(parity={"actions_minutes": {"gap_pct": None, "reason": "billing meter unavailable"}})
    w = agentic(usage_doc=meterless)["coverage-parity"]
    assert w["tripped"] == "unknown" and "billing meter unavailable" in w["summary"], w
    # …but a measure out of tolerance still trips beside an unknown one
    both = agentic(usage_doc=ag_usage(parity={"actions_minutes": {"gap_pct": 30.0}}),
                   ai_doc={k: v for k, v in ai_usage().items() if k != "parity"})
    assert both["coverage-parity"]["tripped"] is True


# -- unknown agent cost ----------------------------------------------------- #
def test_unknown_agent_cost_passes_under_the_ceiling():
    w = agentic()["unknown-agent-cost"]
    assert w["tripped"] is False, w                      # 5 of 45 = 11.1%
    assert w["detail"][0]["unknown_pct"] == 11.1 and w["detail"][0]["agent_runs"] == 45
    assert [r["repo"] for r in w["detail"][1:]] == ["site", "bamr87"]  # most unpriced first


def test_unknown_agent_cost_trips_over_the_ceiling():
    w = agentic(ai_doc=ai_usage(priced=20, unpriced=20))["unknown-agent-cost"]
    assert w["tripped"] is True and "50.0% of 40" in w["summary"], w


def test_unknown_agent_cost_is_unknown_without_counts():
    assert agentic(ai_doc={})["unknown-agent-cost"]["tripped"] == "unknown"
    assert agentic(ai_doc=ai_usage(priced=0, unpriced=0))["unknown-agent-cost"]["tripped"] == "unknown"
    assert agentic(ai_doc=ai_usage(totals={}))["unknown-agent-cost"]["tripped"] == "unknown"


# -- shadow ----------------------------------------------------------------- #
def test_first_seen_is_carried_forward_and_ends_the_shadow():
    prev = {"agentic": [{"id": "coverage-parity", "first_seen": "2026-08-01"},
                        {"id": "coverage-hub", "first_seen": "2026-08-20"},
                        {"id": "unknown-agent-cost", "first_seen": "2026-12-25"}]}  # a future stamp
    wires = agentic(previous=prev)
    assert wires["coverage-parity"]["first_seen"] == "2026-08-01"
    assert wires["coverage-parity"]["shadow"] is False   # 26 days ago, shadow 14
    assert wires["coverage-hub"]["shadow"] is True       # 7 days ago
    assert wires["coverage-hub"]["shadow_until"] == "2026-09-03"
    assert wires["unknown-agent-cost"]["first_seen"] == NOW.date().isoformat()
    assert wires["source-freshness"]["first_seen"] == NOW.date().isoformat()  # new: starts today


def write_run_inputs(d: Path, fleet_doc: dict, previous: dict | None = None):
    import argparse
    import yaml
    (d / "fleet.yml").write_text(yaml.safe_dump(fleet_doc))
    (d / "u.yml").write_text(yaml.safe_dump(ag_usage()))
    (d / "ai.yml").write_text(yaml.safe_dump(ai_usage()))
    (d / "t.yml").write_text(yaml.safe_dump(triage()))
    (d / "p.yml").write_text(yaml.safe_dump(pipeline()))
    (d / "r.yml").write_text(yaml.safe_dump(rotation()))
    if previous is not None:
        (d / "prev.yml").write_text(yaml.safe_dump(previous))
    return argparse.Namespace(
        fleet=str(d / "fleet.yml"), usage=str(d / "u.yml"), triage=str(d / "t.yml"),
        pipeline=str(d / "p.yml"), rotation=str(d / "r.yml"), conformance=str(d / "none.yml"),
        ai_usage=str(d / "ai.yml"), agents=str(d / "none.yml"), previous=str(d / "prev.yml"),
        root=str(d), out=str(d / "out.yml"), quiet=True, now=NOW.isoformat())


def test_a_shadowed_wire_never_adds_to_tripped_count():
    import tempfile
    import yaml
    # One source with no writer trips source-freshness; nothing else trips.
    fleet_doc = {"hub": {"repo": HUB}, "harness": {
        "sources": {"actions-usage": {"path": "_data/actions_usage.yml", "writer": None, "slo_days": 3}}}}
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        ns = write_run_inputs(d, fleet_doc)
        assert harness.run(ns) == 0
        doc = yaml.safe_load((d / "out.yml").read_text())
        six = sum(1 for w in doc["trip_wires"] if w["tripped"])
        fresh = wires_by_id(doc["agentic"])["source-freshness"]
        assert fresh["tripped"] is True and fresh["shadow"] is True, fresh
        assert doc["tripped_count"] == six, (doc["tripped_count"], six)

        # The same inputs fifteen days after first_seen: out of shadow, it counts.
        ns = write_run_inputs(d, fleet_doc, previous={"agentic": [
            {"id": "source-freshness", "first_seen": "2026-08-12"}]})
        assert harness.run(ns) == 0
        doc = yaml.safe_load((d / "out.yml").read_text())
        fresh = wires_by_id(doc["agentic"])["source-freshness"]
        assert fresh["shadow"] is False and fresh["first_seen"] == "2026-08-12", fresh
        assert doc["tripped_count"] == six + 1, (doc["tripped_count"], six)


def test_run_writes_the_agentic_layer():
    import tempfile
    import yaml
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        ns = write_run_inputs(d, {"hub": {"repo": HUB}, "harness": {"sources": DECLARED}})
        assert harness.run(ns) == 0
        doc = yaml.safe_load((d / "out.yml").read_text())
    assert [w["id"] for w in doc["agentic"]] == ["source-freshness", "coverage-hub", "coverage-complete",
                                                 "coverage-parity", "unknown-agent-cost"]
    for w in doc["agentic"]:
        assert w["tripped"] in (True, False, "unknown") and isinstance(w["shadow"], bool), w
    assert doc["sources"]["ai_usage"]["present"] is True
    assert list(doc)[:5] == ["generated_at", "sources", "scorecard", "trip_wires", "agentic"]


def test_agentic_thresholds_live_in_fleet_yml():
    live = harness.load_config(harness.FLEET_DEFAULT)
    import yaml
    declared = (yaml.safe_load(harness.FLEET_DEFAULT.read_text())["harness"]).get("agentic") or {}
    assert set(declared) == set(harness.DEFAULT_AGENTIC), declared   # the contract and the fallbacks agree
    assert live["agentic"]["shadow_days"] == 14
    assert live["hub_repo"] == HUB and live["sources"], live["hub_repo"]


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
