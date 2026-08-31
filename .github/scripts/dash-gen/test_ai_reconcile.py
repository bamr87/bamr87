#!/usr/bin/env python3
"""
Fixture tests for ai_reconcile.py — the `dash ai check` ledger/ccusage audit.

Guards the invariants that make this audit worth trusting:

  * TOKENS are compared, not only cost — a dedupe regression changes token
    counts while leaving the model set and the price identical, so a cost-only
    reconciliation cannot see it. This is the whole reason the check exists;
  * an EXPLAINABLE delta (unpriced model, intro-vs-list pricing, a day-boundary
    shift) is itemized separately and does NOT fail the command;
  * an UNEXPLAINED delta past tolerance DOES fail it;
  * ccusage absent, offline, or emitting a changed schema is a SKIP with a
    reason and exit ZERO — never a false "reconciled";
  * the PRICING table actually covers the model this fleet runs on. That row
    was missing for two months and priced every Opus 5 session at $0.

No network, no npx, no gh, no pytest — the ccusage side is a recorded payload.
Needs only PyYAML:

    python3 .github/scripts/dash-gen/test_ai_reconcile.py
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ai_activity  # noqa: E402
import ai_reconcile  # noqa: E402

CFG = dict(ai_reconcile.DEFAULTS)
MACHINE = "fixture-host"

# A day inside claude-sonnet-5's intro-pricing window, and one after it.
INTRO_DAY = "2026-08-30"
DAY = "2026-09-02"
NEXT_DAY = "2026-09-03"

TOKEN_SET = {"input", "output", "cache_write", "cache_read"}


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #
def usage(inp=1_000, out=2_000, c5m=0, c1h=0, cread=0, turns=1) -> dict:
    return {
        "input": inp, "output": out, "cache_5m": c5m,
        "cache_1h": c1h, "cache_read": cread, "turns": turns,
    }


def ledger(rows: dict) -> dict:
    """{(day, repo, model): usage} -> a ledger file's in-memory shape."""
    return {
        "version": ai_activity.LEDGER_VERSION,
        "usage": {f"{MACHINE}|{d}|{r}|{m}": u for (d, r, m), u in rows.items()},
        "sessions": {},
    }


def cc_payload(rows: dict) -> dict:
    """{day: [(model, inp, out, cwrite, cread, cost)]} -> a ccusage payload."""
    return {
        "daily": [
            {
                "date": day,
                "modelBreakdowns": [
                    {
                        "modelName": m, "inputTokens": i, "outputTokens": o,
                        "cacheCreationTokens": cw, "cacheReadTokens": cr, "cost": cost,
                    }
                    for (m, i, o, cw, cr, cost) in models
                ],
            }
            for day, models in sorted(rows.items())
        ]
    }


def reconcile(led: dict, cc: dict, cfg: dict | None = None) -> dict:
    cfg = cfg or CFG
    since = min(d for d, _m in ai_reconcile.ccusage_rows(cc)) if cc.get("daily") else DAY
    until = max(d for d, _m in ai_reconcile.ccusage_rows(cc)) if cc.get("daily") else DAY
    return ai_reconcile.build_report(
        ai_reconcile.ledger_rows(led, MACHINE, since, until),
        ai_reconcile.ccusage_rows(cc),
        cfg,
        {"machine": MACHINE, "since": since, "until": until, "days": 7},
    )


def reasons(report: dict) -> set[str]:
    return {f["reason"] for f in report["explainable"]}


def metrics(rows: list[dict]) -> set[str]:
    return {f["metric"] for f in rows}


# --------------------------------------------------------------------------- #
# the companion fix: the table must cover the model we actually run
# --------------------------------------------------------------------------- #
def test_current_opus_is_priced_and_aliased():
    """Fails on main: `claude-opus-5` had no PRICING row and `opus` pointed at 4-8."""
    assert "claude-opus-5" in ai_activity.PRICING, "claude-opus-5 is priced at $0"
    assert ai_activity.MODEL_ALIASES["opus"] == "claude-opus-5", (
        f"stale alias: opus -> {ai_activity.MODEL_ALIASES['opus']}"
    )
    # $5/$25 per MTok, derived from ccusage's own costing of a real Opus 5 day
    # (48 in / 12,772 out / 76,954 cache-write@2x / 1,355,482 cache-read@0.1x
    # = $1.766821, an exact fit) and matching the rest of the Opus family.
    assert ai_activity.PRICING["claude-opus-5"] == {"in": 5.0, "out": 25.0}


# --------------------------------------------------------------------------- #
# clean reconciliation
# --------------------------------------------------------------------------- #
def test_matching_sides_reconcile():
    u = usage(inp=1_000, out=2_000, c5m=4_000, cread=10_000)
    cost = ai_activity.cost_usd("claude-opus-5", u)
    report = reconcile(
        ledger({(DAY, "bamr87", "claude-opus-5"): u}),
        cc_payload({DAY: [("claude-opus-5", 1_000, 2_000, 4_000, 10_000, cost)]}),
    )
    assert report["ok"], report["unexplained"]
    assert not report["explainable"]


def test_multiple_repos_aggregate_onto_one_day_model_pair():
    """ccusage has no repo dimension; the ledger's per-repo rows must sum."""
    u = usage(inp=500, out=1_000)
    cost = 2 * ai_activity.cost_usd("claude-opus-5", u)
    report = reconcile(
        ledger({
            (DAY, "bamr87", "claude-opus-5"): u,
            (DAY, "it-journey", "claude-opus-5"): u,
        }),
        cc_payload({DAY: [("claude-opus-5", 1_000, 2_000, 0, 0, cost)]}),
    )
    assert report["ok"], report["unexplained"]
    assert report["compared_keys"] == 1


def test_other_machines_are_excluded():
    """ccusage reads THIS machine; another host's ledger rows are not drift."""
    u = usage(inp=1_000, out=2_000)
    led = ledger({(DAY, "bamr87", "claude-opus-5"): u})
    led["usage"][f"laptop|{DAY}|bamr87|claude-opus-5"] = usage(inp=99_999, out=99_999)
    report = reconcile(
        led, cc_payload({DAY: [
            ("claude-opus-5", 1_000, 2_000, 0, 0,
             ai_activity.cost_usd("claude-opus-5", u)),
        ]}),
    )
    assert report["ok"], report["unexplained"]


def test_tolerance_absorbs_a_rounding_gap():
    u = usage(inp=1_000, out=2_000)
    cost = ai_activity.cost_usd("claude-opus-5", u)
    report = reconcile(
        ledger({(DAY, "bamr87", "claude-opus-5"): u}),
        cc_payload({DAY: [("claude-opus-5", 1_000, 2_000, 0, 0, cost + 0.004)]}),
    )
    assert report["ok"], report["unexplained"]


# --------------------------------------------------------------------------- #
# the dedupe half — cost-only comparison cannot see this
# --------------------------------------------------------------------------- #
def test_dedupe_regression_surfaces_as_unexplained_token_drift():
    """A dedupe regression double-counts tokens on a correctly-priced model.

    Cost moves in lockstep with tokens, so both sides stay internally
    consistent — the ONLY way to catch it is comparing token counts.
    """
    doubled = usage(inp=2_000, out=4_000, c5m=8_000, cread=20_000)
    truth = usage(inp=1_000, out=2_000, c5m=4_000, cread=10_000)
    report = reconcile(
        ledger({(DAY, "bamr87", "claude-opus-5"): doubled}),
        cc_payload({DAY: [(
            "claude-opus-5", 1_000, 2_000, 4_000, 10_000,
            ai_activity.cost_usd("claude-opus-5", truth),
        )]}),
    )
    assert not report["ok"]
    assert TOKEN_SET <= metrics(report["unexplained"]), metrics(report["unexplained"])
    assert all(f["delta"] < 0 for f in report["unexplained"]), "ledger over-counted"


def test_a_model_missing_from_the_ledger_is_unexplained():
    report = reconcile(
        ledger({(DAY, "bamr87", "claude-opus-5"): usage()}),
        cc_payload({DAY: [
            ("claude-opus-5", 1_000, 2_000, 0, 0,
             ai_activity.cost_usd("claude-opus-5", usage())),
            ("claude-haiku-4-5", 5_000, 6_000, 0, 0, 0.035),
        ]}),
    )
    assert not report["ok"]
    haiku = [f for f in report["unexplained"] if f["model"] == "claude-haiku-4-5"]
    assert haiku and all(f["presence"] == "ccusage-only" for f in haiku)


# --------------------------------------------------------------------------- #
# the pricing half
# --------------------------------------------------------------------------- #
def test_unpriced_model_is_explainable_on_cost_only():
    """Criterion (a): priced at $0 here, real cost in ccusage."""
    report = reconcile(
        ledger({(DAY, "bamr87", "claude-unreleased-9"): usage()}),
        cc_payload({DAY: [("claude-unreleased-9", 1_000, 2_000, 0, 0, 4.20)]}),
    )
    assert report["ok"], report["unexplained"]
    assert reasons(report) == {"unpriced-model"}
    assert metrics(report["explainable"]) == {"cost"}


def test_unpriced_model_still_fails_on_a_token_delta():
    """The $0 excuse covers cost. It must not launder a token discrepancy."""
    report = reconcile(
        ledger({(DAY, "bamr87", "claude-unreleased-9"): usage(inp=9_999)}),
        cc_payload({DAY: [("claude-unreleased-9", 1_000, 2_000, 0, 0, 4.20)]}),
    )
    assert not report["ok"]
    assert metrics(report["unexplained"]) == {"input"}


def test_intro_pricing_divergence_is_explainable():
    """Criterion (b): we bill list ($3/$15), ccusage billed intro ($2/$10)."""
    u = usage(inp=1_000_000, out=1_000_000)
    intro = (1_000_000 * 2.0 + 1_000_000 * 10.0) / 1_000_000
    report = reconcile(
        ledger({(INTRO_DAY, "bamr87", "claude-sonnet-5"): u}),
        cc_payload({INTRO_DAY: [("claude-sonnet-5", 1_000_000, 1_000_000, 0, 0, intro)]}),
    )
    assert report["ok"], report["unexplained"]
    assert reasons(report) == {"intro-pricing"}


def test_the_same_divergence_after_the_intro_window_is_drift():
    """The excuse has a hard expiry — after it, the two must agree."""
    u = usage(inp=1_000_000, out=1_000_000)
    intro = (1_000_000 * 2.0 + 1_000_000 * 10.0) / 1_000_000
    report = reconcile(
        ledger({(DAY, "bamr87", "claude-sonnet-5"): u}),
        cc_payload({DAY: [("claude-sonnet-5", 1_000_000, 1_000_000, 0, 0, intro)]}),
    )
    assert not report["ok"]
    assert metrics(report["unexplained"]) == {"cost"}


def test_unexplained_cost_delta_on_a_priced_model_fails():
    """A wrong PRICING row: tokens agree, cost does not, no excuse applies."""
    u = usage(inp=1_000_000, out=1_000_000)
    report = reconcile(
        ledger({(DAY, "bamr87", "claude-opus-5"): u}),
        cc_payload({DAY: [("claude-opus-5", 1_000_000, 1_000_000, 0, 0, 99.0)]}),
    )
    assert not report["ok"]
    assert metrics(report["unexplained"]) == {"cost"}


# --------------------------------------------------------------------------- #
# the bucketing half
# --------------------------------------------------------------------------- #
def test_day_boundary_shift_is_explainable():
    """Criterion (c): the records were counted, just filed under the next day."""
    led = ledger({
        (DAY, "bamr87", "claude-opus-5"): usage(inp=1_000, out=2_000),
        (NEXT_DAY, "bamr87", "claude-opus-5"): usage(inp=5_000, out=6_000),
    })
    report = reconcile(led, cc_payload({
        # 500 input tokens moved from DAY to NEXT_DAY.
        DAY: [("claude-opus-5", 500, 2_000, 0, 0,
               ai_activity.cost_usd("claude-opus-5", usage(inp=500, out=2_000)))],
        NEXT_DAY: [("claude-opus-5", 5_500, 6_000, 0, 0,
                    ai_activity.cost_usd("claude-opus-5", usage(inp=5_500, out=6_000)))],
    }))
    assert report["ok"], report["unexplained"]
    assert reasons(report) == {"day-boundary"}


def test_a_one_sided_token_loss_is_not_a_boundary_shift():
    """Same shape, but nothing on the neighbouring day absorbs it."""
    led = ledger({
        (DAY, "bamr87", "claude-opus-5"): usage(inp=1_000, out=2_000),
        (NEXT_DAY, "bamr87", "claude-opus-5"): usage(inp=5_000, out=6_000),
    })
    report = reconcile(led, cc_payload({
        DAY: [("claude-opus-5", 500, 2_000, 0, 0,
               ai_activity.cost_usd("claude-opus-5", usage(inp=500, out=2_000)))],
        NEXT_DAY: [("claude-opus-5", 5_000, 6_000, 0, 0,
                    ai_activity.cost_usd("claude-opus-5", usage(inp=5_000, out=6_000)))],
    }))
    assert not report["ok"]
    assert metrics(report["unexplained"]) == {"input"}


# --------------------------------------------------------------------------- #
# model-id folding
# --------------------------------------------------------------------------- #
def test_dated_snapshot_ids_fold_onto_the_ledger_key():
    """ccusage reports raw ids; both sides go through the same normalizer."""
    u = usage(inp=1_000, out=2_000)
    report = reconcile(
        ledger({(DAY, "bamr87", "claude-haiku-4-5"): u}),
        cc_payload({DAY: [("claude-haiku-4-5-20251001", 1_000, 2_000, 0, 0,
                           ai_activity.cost_usd("claude-haiku-4-5", u))]}),
    )
    assert report["ok"], report["unexplained"]
    assert report["compared_keys"] == 1


# --------------------------------------------------------------------------- #
# offline safety — a skip is never a pass
# --------------------------------------------------------------------------- #
def test_missing_npx_is_a_skip_not_a_failure():
    saved = ai_reconcile.subprocess.run

    def boom(*_a, **_k):
        raise FileNotFoundError("npx")

    ai_reconcile.subprocess.run = boom
    try:
        payload, reason = ai_reconcile.run_ccusage("20.0.20", "2026-09-01", 5)
    finally:
        ai_reconcile.subprocess.run = saved
    assert payload is None
    assert reason and "npx" in reason


def test_schema_change_is_a_skip_that_names_the_pin():
    class Done:
        returncode = 0
        stdout = '{"totals": {}}'
        stderr = ""

    saved = ai_reconcile.subprocess.run
    ai_reconcile.subprocess.run = lambda *_a, **_k: Done()
    try:
        payload, reason = ai_reconcile.run_ccusage("20.0.20", "2026-09-01", 5)
    finally:
        ai_reconcile.subprocess.run = saved
    assert payload is None
    assert reason and "ccusage_version" in reason


def test_run_exits_zero_when_the_ledger_is_absent():
    with tempfile.TemporaryDirectory() as tmp:
        args = _args(ledger=str(Path(tmp) / "nope.json"))
        assert ai_reconcile.run(args) == 0


def test_today_is_excluded_unless_asked_for():
    """A day still being written is a partial period, not drift."""
    with tempfile.TemporaryDirectory() as tmp:
        today = dt.date.today().isoformat()
        led = Path(tmp) / "ledger.json"
        led.write_text(json.dumps(
            ledger({(today, "bamr87", "claude-opus-5"): usage(inp=1_000_000, out=1_000_000)})
        ))
        cc = Path(tmp) / "cc.json"
        cc.write_text(json.dumps(
            cc_payload({today: [("claude-opus-5", 1_000_000, 1_000_000, 0, 0, 99.0)]})
        ))
        common = dict(ledger=str(led), ccusage_json=str(cc))
        # Same drift, both ways: skipped by default, caught on request.
        assert ai_reconcile.run(_args(include_today=False, **common)) == 0
        assert ai_reconcile.run(_args(include_today=True, **common)) == 1


def test_run_exits_zero_when_ccusage_saw_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        led = Path(tmp) / "ledger.json"
        led.write_text(json.dumps(ledger({(DAY, "bamr87", "claude-opus-5"): usage()})))
        empty = Path(tmp) / "cc.json"
        empty.write_text(json.dumps({"daily": []}))
        assert ai_reconcile.run(_args(ledger=str(led), ccusage_json=str(empty))) == 0


def test_run_exits_nonzero_on_unexplained_drift():
    """End-to-end through run(), the exit code CI/a human would see."""
    with tempfile.TemporaryDirectory() as tmp:
        led = Path(tmp) / "ledger.json"
        today = dt.date.today().isoformat()
        led.write_text(json.dumps(
            ledger({(today, "bamr87", "claude-opus-5"): usage(inp=1_000_000, out=1_000_000)})
        ))
        cc = Path(tmp) / "cc.json"
        cc.write_text(json.dumps(
            cc_payload({today: [("claude-opus-5", 1_000_000, 1_000_000, 0, 0, 99.0)]})
        ))
        assert ai_reconcile.run(_args(ledger=str(led), ccusage_json=str(cc))) == 1


def _args(**over):
    base = dict(
        window=None, ledger=None, claude_dir=None, ccusage_version=None,
        ccusage_json=None, machine=MACHINE, include_today=True,
        fleet=str(ai_reconcile.FLEET),
    )
    base.update(over)
    return argparse.Namespace(**base)


# --------------------------------------------------------------------------- #
# the `tools/dash ai` dispatcher
# --------------------------------------------------------------------------- #
def _dash_routes(argv: list[str]) -> str:
    """Run the REAL tools/dash against a dash-gen stub; return the args it passed.

    tools/dash derives TOOLS from its own location, so copying it beside a stub
    is enough to exercise the dispatch without running a generator.
    """
    import shutil
    import subprocess

    real = Path(__file__).resolve().parents[3] / "tools" / "dash"
    with tempfile.TemporaryDirectory() as tmp:
        tools = Path(tmp) / "tools"
        tools.mkdir()
        shutil.copy(real, tools / "dash")
        stub = tools / "dash-gen"
        stub.write_text('#!/usr/bin/env bash\necho "$@"\n')
        stub.chmod(0o755)
        out = subprocess.run(
            ["bash", str(tools / "dash"), *argv],
            capture_output=True, text=True, timeout=60,
        )
        assert out.returncode == 0, out.stderr
        return out.stdout.strip()


def test_dash_ai_check_routes_to_the_new_subcommand():
    assert _dash_routes(["ai", "check", "--window", "3"]) == "ai-check --window 3"


def test_bare_dash_ai_is_unchanged():
    """The whole point of a dispatcher: the old invocation must not move."""
    assert _dash_routes(["ai"]) == "ai"
    assert _dash_routes(["ai", "--window", "30"]) == "ai --window 30"


# --------------------------------------------------------------------------- #
# config
# --------------------------------------------------------------------------- #
def test_config_reads_the_shipped_fleet_block():
    cfg = ai_reconcile.load_config(ai_reconcile.FLEET)
    assert cfg["ccusage_version"], "ai_reconcile.ccusage_version must be pinned"
    assert cfg["window_days"] >= 1


def test_config_falls_back_when_the_block_is_absent():
    cfg = ai_reconcile.load_config(Path("/nonexistent/fleet.yml"))
    assert cfg == ai_reconcile.DEFAULTS


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
    print(f"{'FAIL' if failures else 'OK'} — ai_reconcile fixture tests")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
