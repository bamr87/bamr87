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

2026-11-07 (epic #773 / E1 #775) added two more:

  * every hub loop call was charged TWICE. claude-code-action prints a
    pretty-printed result block and claude-cost then echoes the same call's
    record on one line; read line by line, the block's `"total_cost_usd"`
    line became a second, session-less record. Issue-pipeline run
    42352285943 ledgered $25.64 against result lines summing to $12.82. The
    block is now decoded whole, given its `Set session_id:`, and folded by the
    lake parser's same-call rules (#771); `parity.ai_ci_cost` holds the
    ledger to the result lines from now on;
  * a 300-run listing budget per repo let the hub's ~200 runs a day crowd
    out its Claude loops: the 2026-11-07 ledger held 5 hub runs for 14 days.
    The window is listed by date range (actions_analytics.list_window_runs).

Deliberately dependency-light — no network, no gh, no pytest. Needs only PyYAML:

    python3 .github/scripts/dash-gen/test_ai_usage_collector.py
"""

from __future__ import annotations

import collections
import datetime as dt
import io
import json
import sys
import tempfile
import zipfile
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
    assert report["parity"]["ai_ci_cost"]["runs_compared"] == 0
    assert report["coverage"]["truncated"] is False


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
# one call printed twice: claude-code-action's block + claude-cost's echo
# --------------------------------------------------------------------------- #
def _echo(session: str, turns: int, cost: float, duration: int) -> str:
    """claude-cost's `claude-run-result` payload, in the CLI's key order."""
    return json.dumps({
        "duration_api_ms": duration - 1000, "session_id": session, "total_cost_usd": cost,
        "usage": {"input_tokens": 192, "cache_creation_input_tokens": 2000,
                  "cache_read_input_tokens": 90000, "output_tokens": 900},
        "modelUsage": {"claude-opus-5-5": {"inputTokens": 192, "outputTokens": 900,
                                           "cacheReadInputTokens": 90000,
                                           "cacheCreationInputTokens": 2000, "costUSD": cost}},
        "is_error": False, "num_turns": turns, "subtype": "success",
        "type": "result", "duration_ms": duration}, separators=(",", ":"))


def _tier_log(hour: int, session: str, turns: int, cost: float, duration: int,
              session_line: bool = True) -> str:
    """One issue-pipeline tier job as run 42352285943's log zip holds it: the
    action's pretty result block, `Set session_id:`, then the cost step's echo."""
    t = f"2026-11-07T{hour:02d}"
    block = (
        f"{t}:44:07.6664407Z {{\n{t}:44:07.6694066Z   \"type\": \"system\",\n"
        f'{t}:44:07.6703993Z   "subtype": "init",\n{t}:44:07.6763883Z   "model": "claude-opus-5-5"\n'
        f"{t}:44:07.6793835Z }}\n"
        f"{t}:58:39.2091451Z {{\n"
        f'{t}:58:39.2091798Z   "type": "result",\n{t}:58:39.2092116Z   "subtype": "success",\n'
        f'{t}:58:39.2092412Z   "is_error": false,\n{t}:58:39.2092678Z   "duration_ms": {duration},\n'
        f'{t}:58:39.2092954Z   "num_turns": {turns},\n{t}:58:39.2093249Z   "total_cost_usd": {cost},\n'
        f'{t}:58:39.2094119Z   "permission_denials_count": 2,\n{t}:58:39.2094452Z   "modelUsage": {{\n'
        f'{t}:58:39.2095979Z     "claude-opus-5-5": {{\n'
        f'{t}:58:39.2096262Z       "contextWindow": 1000000\n{t}:58:39.2096830Z     }}\n'
        f"{t}:58:39.2097041Z   }}\n{t}:58:39.2097505Z }}\n"
        f"{t}:58:39.6102048Z Log saved to /home/runner/work/_temp/claude-execution-output.json\n")
    if session_line:
        block += f"{t}:58:39.6102493Z Set session_id: {session}\n"
    return block + (
        f"{t}:58:39.6586551Z \x1b[36;1mprintf 'claude-run-result %s\\n' \"$result\"\x1b[0m\n"
        f"{t}:58:39.6587000Z \x1b[36;1mcost=$(printf '%s' \"$result\" | jq -r '.total_cost_usd // 0')\x1b[0m\n"
        f"{t}:58:39.6987956Z claude-run-result {_echo(session, turns, cost, duration)}\n")


TIERS = [(7, "1295a0ad-3a48-4f42-89ba-c92c57ef6562", 184, 6.4238041, 871647),
         (8, "51b38cf8-415e-41a4-85ce-8d93a94fe1ff", 165, 4.8263003, 1183822),
         (9, "2ead88a7-cb8d-4cbd-aced-640d11ac24b3", 54, 1.5717504, 260380)]


def test_a_hub_loop_call_is_charged_once_not_twice() -> None:
    """Run 42352285943: three tiers, each printed as the action's block AND the
    echo. FAILS on the pre-fix parser, which priced the run at $25.64."""
    records = []
    for tier in TIERS:
        records += list(col.iter_usage_records(_tier_log(*tier)))
    priced = col.price_records(records)
    want = round(sum(t[3] for t in TIERS), 6)
    assert abs(priced["cost_usd"] - want) < 1e-6, (priced["cost_usd"], want)
    assert priced["result_line_usd"] == priced["cost_usd"], priced
    assert priced["turns"] == 184 + 165 + 54, priced["turns"]
    # the block got its session from the `Set session_id:` line
    block = next(col.iter_usage_records(_tier_log(*TIERS[0])))
    assert block["session"] == TIERS[0][1] and block["echo"] is False, block


def test_a_block_without_its_session_line_still_folds_by_duration_and_turns() -> None:
    records = list(col.iter_usage_records(_tier_log(*TIERS[1], session_line=False)))
    assert len(records) == 2 and records[0]["session"] is None, records
    priced = col.price_records(records)
    assert abs(priced["cost_usd"] - TIERS[1][3]) < 1e-6, priced


def test_two_different_calls_with_equal_cost_are_both_charged() -> None:
    """Folding is by call identity, never by an equal figure."""
    a = list(col.iter_usage_records(_tier_log(7, "s-a", 10, 1.0, 1000)))
    b = list(col.iter_usage_records(_tier_log(8, "s-b", 10, 1.0, 1000)))
    assert col.price_records(a + b)["cost_usd"] == 2.0


def test_parity_holds_the_ledger_to_the_result_lines() -> None:
    rows = [entry(cost_usd=12.821855, result_line_usd=12.821855, url="u1"),
            entry(cost_usd=25.64371, result_line_usd=12.821855, url="u2"),   # the old double count
            entry(cost_usd=0.4, result_line_usd=None, url="u3")]             # no claude-cost: not compared
    p = col.ai_parity(rows)
    assert p["runs_compared"] == 2 and p["runs_off"] == 1 and p["runs_off_sample"] == ["u2"], p
    assert p["result_lines_usd"] == 25.6437 and p["ledger_usd"] == 38.4656, p
    assert p["gap_pct"] == 50.0, p
    clean = col.ai_parity(rows[:1])
    assert clean["gap_pct"] == 0.0 and clean["runs_off"] == 0, clean
    assert col.ai_parity([])["gap_pct"] is None


# --------------------------------------------------------------------------- #
# the window is listed, not capped
# --------------------------------------------------------------------------- #
NOW = dt.datetime(2026, 11, 7, 12, tzinfo=dt.timezone.utc)


class _Api:
    """Runs, workflow files and counted calls, as plain JSON."""

    def __init__(self, runs, files):
        self.runs, self.files = runs, files
        self.calls: collections.Counter = collections.Counter()

    def get(self, path, params=None, kind="other"):
        self.calls[kind] += 1
        if "/contents/" in path:
            import base64
            text = self.files[path.split("/contents/", 1)[1]]
            return {"content": base64.b64encode(text.encode()).decode()}
        a, b = (col.actions_analytics.parse_ts(x) for x in params["created"].split(".."))
        hit = sorted((r for r in self.runs if a <= col.actions_analytics.parse_ts(r["created_at"]) <= b),
                     key=lambda r: r["created_at"], reverse=True)
        per, page = params["per_page"], params["page"]
        return {"total_count": len(hit), "workflow_runs": hit[:1000][(page - 1) * per: page * per]}


class _Session:
    def __init__(self, logs):
        self.logs, self.urls = logs, []

    def get(self, url, timeout=60):
        self.urls.append(url)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("0_tier.txt", self.logs[url])
        return type("R", (), {"status_code": 200, "content": buf.getvalue()})()


def _run(rid, path, minutes_ago, conclusion="success"):
    t = (NOW - dt.timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"id": rid, "name": path.split("/")[-1], "path": path, "event": "schedule",
            "status": "completed", "conclusion": conclusion, "created_at": t, "updated_at": t,
            "html_url": f"https://github.com/bamr87/bamr87/actions/runs/{rid}",
            "logs_url": f"logs/{rid}"}


def test_the_hubs_claude_runs_are_not_crowded_out_by_its_other_runs() -> None:
    """400 newer CI runs, then the issue pipeline's run. FAILS on the old
    listing, which stopped after 300 runs of any workflow."""
    runs = [_run(i, ".github/workflows/ci.yml", i) for i in range(1, 401)]
    runs.append(_run(999, ".github/workflows/issue-pipeline.yml", 600))
    api = _Api(runs, {".github/workflows/ci.yml": "run: pytest",
                      ".github/workflows/issue-pipeline.yml": "uses: anthropics/claude-code-action@v1"})
    session = _Session({"logs/999": _tier_log(*TIERS[0])})
    cov: list = []
    hub = {"name": "bamr87", "repo_url": "https://github.com/bamr87/bamr87"}
    rows = col.collect_ci(api, session, [hub], NOW - dt.timedelta(days=14), 0, now=NOW, coverage=cov)
    assert [r["url"].rsplit("/", 1)[1] for r in rows] == ["999"], rows
    assert abs(rows[0]["cost_usd"] - TIERS[0][3]) < 1e-6 and rows[0]["result_line_usd"] == rows[0]["cost_usd"]
    assert session.urls == ["logs/999"], "only the Claude run's log is downloaded"
    assert api.calls["contents"] == 2, "one contents read per distinct path"
    assert cov == [{"repo": "bamr87", "nwo": "bamr87/bamr87", "runs_in_window": 401,
                    "runs_listed": 401, "claude_runs": 1, "truncated": False,
                    "runs_missed": 0, "error": None}], cov
    capped: list = []
    col.collect_ci(api, session, [hub], NOW - dt.timedelta(days=14), 300, now=NOW, coverage=capped)
    assert capped[0]["truncated"] and capped[0]["runs_missed"] == 101, capped


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
