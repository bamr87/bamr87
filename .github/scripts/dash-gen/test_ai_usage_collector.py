#!/usr/bin/env python3
"""
Fixture tests for ai_usage_collector.py — the fleet's COMMITTED Claude CI
spend ledger, and therefore the input to the $75/month budget check.

WHY THIS EXISTS
---------------
On 2026-10-29 the ledger reported 277 CI runs, $1.03 of spend and 242 runs
"unpriced" — 87% of the fleet's AI runs accounted at exactly nothing, against
a ceiling the same data is judged by. Four separate faults produced that
number, and each has a test here:

  * the HUB ITSELF was never collected. `_data/projects.yml` lists the
    submodules; the control plane is declared in `_data/fleet.yml` `hub.repo`,
    and its loops (fleet-pulse's doctor at a $40 cap, the issue pipeline's
    three tiers, the fan-outs) are the fleet's largest AI spend. One doctor
    run on 2026-10-29 reported $0.67 — two thirds of the whole fleet total as
    then computed;
  * a run with MORE THAN ONE Claude session was charged for one of them: the
    scraper took the last regex match in the log. Summing naively is just as
    wrong — GitHub's log zip carries each job's text twice, and the CLI's
    `total_cost_usd` is cumulative within a session — so records are
    de-duplicated per `session_id` and then summed;
  * 146 of the 242 "unpriced" runs were `skipped`, and most of the rest ran
    only the "is the loop on?" gate job. Those cost nothing: they are
    `no-spend`, and calling them unknown hid the runs that really were;
  * a run that genuinely left no usage behind contributed $0 to the totals.
    It now carries an explicit `est_cost_usd` with a named basis, and the
    budget check reads the accounted figure (measured + estimated).

Deliberately dependency-light — no network, no gh, no pytest. Needs only PyYAML:

    python3 .github/scripts/dash-gen/test_ai_usage_collector.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ai_activity  # noqa: E402
import ai_usage_collector as col  # noqa: E402
import harness_registry as hr  # noqa: E402

# The shape the CLI actually emits, as the hub's workflows echo it into the run
# log behind `claude-run-result` (fleet-pulse.yml "Report Claude run cost").
RESULT = (
    '{"type":"result","subtype":"success","is_error":false,"num_turns":7,'
    '"session_id":"sess-1","total_cost_usd":0.6683591,'
    '"usage":{"input_tokens":120,"output_tokens":4000,'
    '"cache_creation_input_tokens":5000,"cache_read_input_tokens":900000},'
    '"modelUsage":{"claude-opus-5":{"inputTokens":120,"outputTokens":4000,'
    '"cacheReadInputTokens":900000,"cacheCreationInputTokens":5000}}}'
)


def log_line(payload: str, step: str = "Fix failing & long-running workflows") -> str:
    return f"{step}\tUNKNOWN STEP\t2026-10-29T06:02:51.3920810Z claude-run-result {payload}"


def entry(**kw) -> dict:
    row = {"repo": "r", "workflow": "W", "day": "2026-10-20", "duration_min": 1.0,
           "cost_usd": None, "est_cost_usd": None, "cost_source": None,
           "cost_basis": None, "turns": None}
    row.update({k: 0 for k in col.TOKEN_KEYS})
    row.update(kw)
    return row


# --------------------------------------------------------------------------- #
# log scraping
# --------------------------------------------------------------------------- #
def test_reads_the_result_payload_out_of_an_actions_log_line() -> None:
    recs = list(col.iter_usage_records(log_line(RESULT)))
    assert len(recs) == 1, recs
    rec = recs[0]
    assert rec["session"] == "sess-1"
    assert rec["cost_usd"] == 0.6683591
    assert rec["turns"] == 7
    assert rec["tokens"]["cache_read_tokens"] == 900000
    assert rec["models"] == {"claude-opus-5": {
        "tokens": {"input_tokens": 120, "output_tokens": 4000,
                   "cache_read_tokens": 900000, "cache_write_tokens": 5000},
        "cache_1h": 0}}


def test_duplicated_log_text_is_one_charge() -> None:
    """A run's log zip carries each job twice; the old scraper's `max`/last-wins
    hid that, summing would double it, dedupe by session is the answer."""
    text = "\n".join([log_line(RESULT), log_line(RESULT)])
    priced = col.price_records(list(col.iter_usage_records(text)))
    assert priced["cost_usd"] == 0.668359, priced
    assert priced["turns"] == 7, priced


def test_two_sessions_in_one_run_are_summed() -> None:
    other = RESULT.replace("sess-1", "sess-2").replace("0.6683591", "0.25")
    priced = col.price_records(list(col.iter_usage_records(
        "\n".join([log_line(RESULT), log_line(other)]))))
    assert priced["cost_usd"] == round(0.6683591 + 0.25, 6), priced
    assert priced["turns"] == 14, priced
    assert priced["cost_source"] == "reported"


def test_a_resumed_session_is_charged_once_at_its_cumulative_figure() -> None:
    mid = RESULT.replace("0.6683591", "0.40")
    priced = col.price_records(list(col.iter_usage_records(
        "\n".join([log_line(mid), log_line(RESULT)]))))
    assert priced["cost_usd"] == 0.668359, priced


def test_an_unparseable_result_line_still_yields_its_cost() -> None:
    """ANSI escapes and truncation are routine in Actions logs; a reported cost
    must not decay into an estimate because the decoder choked."""
    mangled = ('\x1b[36;1m{"type":"result" ,, "session_id":"sess-9",'
               '"num_turns":3,"total_cost_usd":1.25')
    recs = list(col.iter_usage_records(log_line(mangled)))
    assert len(recs) == 1, recs
    assert recs[0]["cost_usd"] == 1.25 and recs[0]["session"] == "sess-9"
    assert col.price_records(recs)["cost_source"] == "reported"


# --------------------------------------------------------------------------- #
# token-rate pricing
# --------------------------------------------------------------------------- #
def test_prices_tokens_when_the_payload_carries_no_cost() -> None:
    payload = ('{"type":"result","num_turns":3,"session_id":"t",'
               '"modelUsage":{"claude-sonnet-5-5":{"inputTokens":1000000,'
               '"outputTokens":1000000,"cacheReadInputTokens":1000000,'
               '"cacheCreationInputTokens":1000000}}}')
    priced = col.price_records(list(col.iter_usage_records(log_line(payload))))
    # 1 MTok each at $2 in / $10 out, cache write 1.25x in, cache read 0.1x in
    assert priced["cost_usd"] == 14.7, priced
    assert priced["cost_source"] == "tokens"
    assert priced["cost_basis"] == "token-rates"
    assert priced["cache_write_tokens"] == 1000000


def test_cache_writes_are_priced_by_ttl_when_the_payload_splits_them() -> None:
    tokens = {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0,
              "cache_write_tokens": 2000000}
    five_only = col.price_tokens("claude-sonnet-5-5", tokens, cache_1h=0)
    half_1h = col.price_tokens("claude-sonnet-5-5", tokens, cache_1h=1000000)
    assert five_only == 2 * 2.0 * 1.25, five_only
    assert half_1h == 2.0 * 1.25 + 2.0 * 2.0, half_1h
    payload = ('{"session_id":"c","usage":{"output_tokens":0,'
               '"cache_creation":{"ephemeral_5m_input_tokens":1000000,'
               '"ephemeral_1h_input_tokens":1000000}},"model":"claude-sonnet-5-5"}')
    recs = list(col.iter_usage_records(log_line(payload)))
    assert recs[0]["cache_1h"] == 1000000, recs
    assert col.price_records(recs)["cost_usd"] == round(half_1h, 6)


def test_every_model_the_fleet_runs_has_a_rate_row() -> None:
    """A missing row prices a model's whole window at nothing — the failure that
    lost two months of Opus 5 (bamr87#130). Aliases resolve, dated ids strip."""
    for model in ("opus", "sonnet", "haiku", "claude-opus-5-20260514",
                  "claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-4-5"):
        resolved = ai_activity.normalize_model(model)
        assert resolved in ai_activity.PRICING, f"{model} -> {resolved} has no rate row"


def test_an_unknown_model_is_surfaced_not_silently_zeroed() -> None:
    payload = ('{"num_turns":1,"session_id":"q","modelUsage":'
               '{"claude-zeta-9":{"outputTokens":10,"inputTokens":10}}}')
    priced = col.price_records(list(col.iter_usage_records(log_line(payload))))
    assert priced["cost_usd"] is None, priced
    assert priced["unpriced_models"] == ["claude-zeta-9"], priced


# --------------------------------------------------------------------------- #
# classification
# --------------------------------------------------------------------------- #
def test_a_skipped_run_is_no_spend_not_unpriced() -> None:
    row = col.classify_run("skipped", None)
    assert (row["cost_usd"], row["cost_source"], row["cost_basis"]) == (
        0.0, "no-spend", "run-skipped"), row


def test_a_gate_only_run_is_no_spend() -> None:
    """The fleet's loops open with an "is the loop on?" job. It succeeds, runs
    no Claude step, and used to land in the ledger as unknown spend."""
    scan = {"log": "ok", "claude_step": False, "records": []}
    row = col.classify_run("success", scan)
    assert (row["cost_usd"], row["cost_source"], row["cost_basis"]) == (
        0.0, "no-spend", "no-ai-step"), row


def test_a_claude_step_with_no_usage_is_left_for_the_estimator() -> None:
    scan = {"log": "ok", "claude_step": True, "records": []}
    row = col.classify_run("failure", scan)
    assert row["cost_usd"] is None and row["cost_source"] is None, row


def test_a_missing_log_is_never_read_as_free() -> None:
    row = col.classify_run("success", {"log": "unavailable", "claude_step": False,
                                       "records": []})
    assert row["cost_source"] is None and row["cost_basis"] == "log-unavailable", row


def test_a_priced_run_keeps_its_reported_cost() -> None:
    scan = {"log": "ok", "claude_step": True,
            "records": list(col.iter_usage_records(log_line(RESULT)))}
    row = col.classify_run("success", scan)
    assert row["cost_source"] == "reported" and row["cost_usd"] == 0.668359, row


# --------------------------------------------------------------------------- #
# estimation
# --------------------------------------------------------------------------- #
def test_estimates_from_the_workflows_own_priced_median_first() -> None:
    rows = [
        entry(cost_usd=0.40, cost_source="reported"),
        entry(cost_usd=0.60, cost_source="reported"),
        entry(),  # the unknown one
    ]
    bases = col.estimate_unpriced(rows, usd_per_turn=0.15)
    assert bases == {"workflow-median": 1}, bases
    assert rows[-1]["est_cost_usd"] == 0.5, rows[-1]
    assert rows[-1]["cost_source"] == "estimated"
    assert rows[-1]["cost_basis"] == "workflow-median"
    # the measured rows are untouched
    assert rows[0]["est_cost_usd"] is None and rows[0]["cost_source"] == "reported"


def test_falls_back_to_turns_then_the_fleet_median_then_the_rate_floor() -> None:
    rows = [
        entry(repo="a", workflow="A", cost_usd=1.0, cost_source="reported"),
        entry(repo="b", workflow="B", turns=4),        # turns at the declared rate
        entry(repo="c", workflow="C"),                 # fleet median
    ]
    bases = col.estimate_unpriced(rows, usd_per_turn=0.15)
    assert bases == {"turns-rate": 1, "fleet-median": 1}, bases
    assert rows[1]["est_cost_usd"] == 0.6, rows[1]
    assert rows[2]["est_cost_usd"] == 1.0, rows[2]
    lonely = [entry()]
    assert col.estimate_unpriced(lonely, 0.15) == {"rate-floor": 1}
    assert lonely[0]["est_cost_usd"] == 0.15


def test_a_no_spend_run_is_never_given_an_estimate() -> None:
    rows = [entry(cost_usd=0.0, cost_source="no-spend", cost_basis="run-skipped")]
    assert col.estimate_unpriced(rows, 0.15) == {}
    assert rows[0]["est_cost_usd"] is None and rows[0]["cost_usd"] == 0.0


def test_a_lost_log_keeps_that_fact_in_its_basis() -> None:
    rows = [entry(cost_usd=0.2, cost_source="reported"), entry(cost_basis="log-unavailable")]
    col.estimate_unpriced(rows, 0.15)
    assert rows[1]["cost_basis"] == "log-unavailable/workflow-median", rows[1]


# --------------------------------------------------------------------------- #
# aggregation + the hub
# --------------------------------------------------------------------------- #
def test_rollup_separates_measured_estimated_and_free_runs() -> None:
    rows = [
        entry(cost_usd=0.50, cost_source="reported", turns=5, input_tokens=10,
              cache_read_tokens=1000),
        entry(cost_usd=0.25, cost_source="tokens", output_tokens=7),
        entry(est_cost_usd=0.30, cost_source="estimated"),
        entry(cost_usd=0.0, cost_source="no-spend"),
    ]
    agg = col._rollup(rows, lambda r: r["repo"])["r"]
    assert agg["runs"] == 4
    assert agg["cost_usd"] == 0.75 and agg["est_cost_usd"] == 0.30
    assert agg["accounted_usd"] == 1.05
    assert (agg["priced_runs"], agg["unpriced_runs"], agg["no_spend_runs"]) == (2, 1, 1)
    assert agg["cache_read_tokens"] == 1000 and agg["output_tokens"] == 7
    assert agg["turns"] == 5


def test_build_totals_report_measured_estimated_and_accounted(tmp: Path | None = None) -> None:
    rows = [
        entry(day="2026-10-20", cost_usd=0.50, cost_source="reported", turns=5),
        entry(day="2026-10-21", cost_source=None),       # estimator fills this
        entry(day="2026-10-21", cost_usd=0.0, cost_source="no-spend"),
    ]
    saved = (col.collect_ci, col.collect_vcs, col.local_section)
    col.collect_ci = lambda *a, **k: rows
    col.collect_vcs = lambda *a, **k: ([], [])
    col.local_section = lambda *a, **k: None
    try:
        report = col.build(None, None, [{"name": "r", "category": "harness"}],
                           14, 1, 1, Path("/nonexistent/ai_usage.yml"))
    finally:
        col.collect_ci, col.collect_vcs, col.local_section = saved
    t = report["totals"]
    assert t["ci_runs"] == 3
    assert t["ci_cost_usd"] == 0.5
    assert t["ci_estimated_usd"] == 0.5          # workflow median of the one priced run
    assert t["ci_accounted_usd"] == 1.0
    assert (t["ci_priced_runs"], t["ci_unpriced_runs"], t["ci_no_spend_runs"]) == (1, 1, 1)
    assert report["pricing"]["estimated_share_pct"] == 50.0
    assert report["pricing"]["estimate_bases"] == {"workflow-median": 1}
    day = {r["day"]: r for r in report["by_day"]}
    assert day["2026-10-21"]["accounted_usd"] == 0.5, day


def test_the_hub_is_collected_even_though_it_is_not_in_the_registry() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        fleet = Path(tmpdir) / "fleet.yml"
        fleet.write_text(yaml.safe_dump({"hub": {"repo": "bamr87/bamr87"},
                                         "budget": {"usd_per_turn": 0.2}}))
        hub = col.hub_entry(fleet)
        assert hub["repo_url"] == "https://github.com/bamr87/bamr87", hub
        assert col.load_usd_per_turn(fleet) == 0.2
        registry = [{"name": "godotgo", "repo_url": "https://github.com/bamr87/godotgo"}]
        assert [p["name"] for p in col.with_hub(registry, fleet)] == ["bamr87", "godotgo"]
        # idempotent: a registry that already lists the hub gains nothing
        assert len(col.with_hub([hub, *registry], fleet)) == 2


def test_the_live_fleet_config_still_declares_the_hub_and_the_turn_rate() -> None:
    assert col.hub_entry()["repo_url"].endswith("/bamr87/bamr87")
    assert col.load_usd_per_turn() > 0


def test_claude_is_detected_by_every_route_the_fleet_uses() -> None:
    for marker in ("uses: anthropics/claude-code-action@v1",
                   "uses: bamr87/bamr87/.github/actions/claude-run@main",
                   "run: scripts/ai/run.sh --prompt x"):
        assert any(m in marker for m in col.CLAUDE_WORKFLOW_MARKERS), marker
    # a credential check alone is not a Claude step: the gate job prints it
    gate = 'if [ -n "$CLAUDE_CODE_OAUTH_TOKEN" ] || [ -n "$ANTHROPIC_API_KEY" ]; then'
    assert not any(m in gate for m in col.CLAUDE_LOG_MARKERS), gate


# --------------------------------------------------------------------------- #
# the budget check reads the accounted figure
# --------------------------------------------------------------------------- #
def test_the_budget_check_counts_estimates_too() -> None:
    """The reported incident: a $75/month ceiling judged on the measured half of
    a ledger whose runs were 87% unpriced. Same days, same ceiling — measured
    alone reads "ok", accounted reads "breach"."""
    days = [{"day": f"2026-10-{d:02d}", "cost_usd": 0.05, "est_cost_usd": 3.0,
             "accounted_usd": 3.05} for d in range(16, 30)]
    cfg = {"budget": {"monthly_ai_usd": 75, "trend_warn_pct": 50}}
    trend = hr.build_trends({"by_day": days}, {}, cfg)["ai_cost_usd"]
    assert trend["window_total"] == 42.7, trend
    assert trend["status"] == "breach", trend
    assert trend["measured_total"] == 0.7 and trend["estimated_total"] == 42.0
    assert trend["estimated_share_pct"] == 98.4, trend
    assert trend["cost_basis"] == "measured+estimated"

    measured_only = [{"day": d["day"], "cost_usd": d["cost_usd"]} for d in days]
    old = hr.build_trends({"by_day": measured_only}, {}, cfg)["ai_cost_usd"]
    assert old["status"] == "ok" and old["cost_basis"] == "measured", old


def test_a_pre_estimator_ledger_still_reads_as_its_measured_total() -> None:
    assert hr.ai_day_cost({"day": "2026-10-20", "cost_usd": 1.5}) == 1.5
    assert hr.ai_day_cost({"cost_usd": 1.0, "est_cost_usd": 2.0}) == 3.0
    assert hr.ai_day_cost({"cost_usd": 1.0, "est_cost_usd": 2.0,
                           "accounted_usd": 3.0}) == 3.0
    assert hr.ai_day_cost({}) == 0.0


def test_the_estimator_calibration_divides_by_the_measured_runs_only() -> None:
    """engagements.py prices an issue from "average priced cost per CI run". It
    derived the denominator as runs minus unpriced, which now also counts the
    no-spend runs — 146 of 277 in the snapshot that exposed this — and would
    divide real spend by runs that never called a model."""
    import engagements

    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "ai_usage.yml"
        path.write_text(yaml.safe_dump({"by_repo": [
            {"repo": "new", "runs": 20, "priced_runs": 2, "unpriced_runs": 3,
             "no_spend_runs": 15, "cost_usd": 1.0},
            {"repo": "old", "runs": 20, "unpriced_runs": 18, "cost_usd": 1.0},
        ]}))
        calib = engagements.load_calibration(path)
    assert calib["new"] == 0.5, calib          # 2 measured runs, not 17
    assert calib["old"] == 0.5, calib          # pre-estimator ledger: unchanged


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
    print(f"{'FAIL' if failures else 'OK'} — ai_usage_collector fixture tests")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
