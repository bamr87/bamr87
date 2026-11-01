#!/usr/bin/env python3
"""
Fixture tests for tools/jev/ledger.py — the conflict-resolution ledger and the
monthly cap. The cap is the only thing standing between a loop that runs every
six hours and the fleet's monthly ceiling (_data/fleet.yml
harnesses.budget.monthly_ai_usd), so the arithmetic is tested rather than
trusted.

Run: python3 tools/test_jev_ledger.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.jev import conflicts as CF  # noqa: E402
from tools.jev import ledger as L  # noqa: E402
from tools.jev.common import JevConfig, JevError, load_config, load_fleet  # noqa: E402

CFG = JevConfig(monthly_usd=10.0, scheduled_stop_pct=80)


def tmp_ledger() -> L.Ledger:
    return L.Ledger(path=Path(tempfile.mkdtemp()) / "jev_resolutions.yml")


def row(**kw) -> L.Resolution:
    base = dict(repo="o/r", pr=1, tier="tier1", outcome="resolved", date="2026-10-15")
    base.update(kw)
    return L.Resolution(**base)


# --------------------------------------------------------------------------- #
# records
# --------------------------------------------------------------------------- #
def test_a_record_defaults_to_today_and_carries_the_call_site():
    r = L.Resolution(repo="o/r", pr=7, tier="tier0", outcome="resolved")
    assert r.date and len(r.date) == 10
    assert r.call_site == "jev-conflicts", "the fleet ledger joins on this"


def test_the_ledger_round_trips_through_yaml():
    led = tmp_ledger()
    led.append(row(cost_usd=0.2))
    led.save()
    again = L.Ledger.load(led.path)
    assert len(again.resolutions) == 1
    assert again.resolutions[0]["repo"] == "o/r" and again.resolutions[0]["cost_usd"] == 0.2
    data = yaml.safe_load(led.path.read_text())
    assert data["schema"] == L.SCHEMA and data["call_site"] == "jev-conflicts"


def test_a_missing_ledger_loads_empty_rather_than_failing():
    led = L.Ledger.load(Path(tempfile.mkdtemp()) / "nothing.yml")
    assert led.resolutions == [] and led.month_total("2026-10") == 0.0


# --------------------------------------------------------------------------- #
# month-to-date
# --------------------------------------------------------------------------- #
def test_month_total_counts_only_that_month():
    led = tmp_ledger()
    led.append(row(cost_usd=1.0, date="2026-10-01"))
    led.append(row(cost_usd=2.0, date="2026-10-31"))
    led.append(row(cost_usd=4.0, date="2026-11-01"))
    assert led.month_total("2026-10") == 3.0
    assert led.month_total("2026-11") == 4.0


def test_the_estimated_share_is_reported_separately():
    # a measured half presented as a whole is exactly how the fleet ledger once
    # read a $75 budget as $1.03 (HUB-032 / NFR10)
    led = tmp_ledger()
    led.append(row(cost_usd=1.0, cost_source="reported"))
    led.append(row(cost_usd=3.0, cost_source="estimated"))
    assert led.month_total("2026-10") == 4.0
    assert led.month_estimated("2026-10") == 3.0


def test_only_real_attempts_count_against_the_retry_budget():
    led = tmp_ledger()
    led.append(row(outcome="triaged"))
    led.append(row(outcome="escalated"))
    assert led.attempts("o/r", 1) == 0, "looking at a PR twice is not two attempts"
    led.append(row(outcome="failed"))
    led.append(row(outcome="resolved"))
    assert led.attempts("o/r", 1) == 2
    assert led.attempts("o/r", 2) == 0 and led.attempts("other/r", 1) == 0


# --------------------------------------------------------------------------- #
# the cap
# --------------------------------------------------------------------------- #
def test_a_scheduled_run_stops_below_the_cap_so_a_human_still_has_budget():
    led = tmp_ledger()
    led.append(row(cost_usd=8.5))
    cron = L.budget_state(CFG, led, scheduled=True, month="2026-10")
    byhand = L.budget_state(CFG, led, scheduled=False, month="2026-10")
    assert cron.ceiling_usd == 8.0 and cron.exhausted
    assert byhand.ceiling_usd == 10.0 and not byhand.exhausted
    assert byhand.remaining_usd == 1.5


def test_affords_looks_at_the_attempt_not_just_the_balance():
    led = tmp_ledger()
    led.append(row(cost_usd=9.0))
    state = L.budget_state(CFG, led, scheduled=False, month="2026-10")
    assert state.affords(0.25) and not state.affords(1.5)


def test_the_summary_says_what_was_estimated_and_where_the_run_stops():
    led = tmp_ledger()
    led.append(row(cost_usd=2.0, cost_source="estimated"))
    text = L.budget_state(CFG, led, scheduled=True, month="2026-10").summary()
    assert "$2.00" in text and "estimated" in text and "stops at $8.00" in text


def test_the_hubs_own_configuration_keeps_jev_inside_the_fleet_budget():
    cfg = load_config()
    fleet_ceiling = float(load_fleet()["harnesses"]["budget"]["monthly_ai_usd"])   # read, never copied
    assert 0 < cfg.monthly_usd <= fleet_ceiling
    assert 0 < cfg.monthly_stop_usd < cfg.monthly_usd
    for tier in ("tier1", "tier2"):
        policy = cfg.tier(tier)
        assert policy.model, f"{tier} has no model"
        assert 0 < policy.max_usd < cfg.monthly_usd, f"{tier} attempt cap is not inside the month"
        assert policy.max_turns > 0, f"{tier} has no turn cap"
    assert cfg.tier("tier1").max_usd < cfg.tier("tier2").max_usd, "the cheap tier must be cheaper"


def _refused(call, what: str, *needles: str) -> None:
    try:
        call()
    except JevError as exc:
        for needle in needles:
            assert needle in str(exc), exc
    else:
        raise AssertionError(f"{what} was accepted")


def test_a_cap_a_ceiling_or_a_stop_that_bounds_nothing_is_refused():
    # YAML reads .inf and .nan: an infinite ceiling affords every attempt, one NaN reads as "fits"
    nan, inf = float("nan"), float("inf")
    for key, bad in (("monthly_usd", inf), ("monthly_usd", nan), ("monthly_usd", 0), ("monthly_usd", None),
                     ("monthly_usd", True), ("scheduled_stop_pct", 1000), ("scheduled_stop_pct", 0),
                     ("scheduled_stop_pct", 80.5), ("tier2_usd", -1), ("tier2_usd", inf), ("tier1_usd", nan),
                     ("tier1_usd", 0)):
        fleet = load_fleet()
        fleet["budget"]["jev"][key] = bad
        _refused(lambda f=fleet: load_config(f), f"budget.jev.{key} {bad!r}", f"budget.jev.{key}")
    fleet = load_fleet()
    del fleet["budget"]["jev"]["tier2_usd"]         # a tier that buys a model, with no cap anywhere
    _refused(lambda: load_config(fleet), "tier2 with a model and no cap", "budget.jev.tier2_usd")
    # the conflicts argv never passes through headless.run_prefix: it refuses on its own
    for cap in (inf, nan, -1, 0, True):
        _refused(lambda c=cap: CF.claude_argv("m", "p", c, 5), f"claude_argv cap {cap!r}", "--max-budget-usd")
    assert CF.claude_argv("m", "p", 1.5, 5)[-3:-1] == ["--max-budget-usd", "1.5"]


def test_a_ledger_figure_that_is_not_finite_or_is_negative_never_reads_as_room():
    # the committed file is YAML, which no gate checks row by row: a negative row gave spend
    # back, and one -.inf row made the month -inf, affordable forever
    def ledger(*rows: str) -> L.Ledger:
        p = Path(tempfile.mkdtemp()) / "jev_resolutions.yml"
        p.write_text("schema: jev-resolutions/v1\nresolutions:\n" + "".join(f"- {r}\n" for r in rows))
        return L.Ledger.load(p)

    spent = "{repo: o/r, pr: 1, tier: tier2, outcome: failed, date: '2026-10-01', cost_usd: 50.0}"
    for bad in ("-.inf", ".inf", ".nan", "-45.0", "true", "lots"):
        led = ledger(spent, f"{{repo: o/r, pr: 2, tier: tier2, outcome: failed, date: '2026-10-02', "
                            f"cost_usd: {bad}, cost_source: estimated}}")
        for call in (lambda d=led: L.budget_state(CFG, d, scheduled=True, month="2026-10"),
                     lambda d=led: d.month_estimated("2026-10")):
            _refused(call, f"a ledger row of cost_usd {bad}", "cannot be judged", "o/r#2")
        assert led.month_total("2026-11") == 0.0, "another month's row is not this month's spend"
    led = ledger(spent, "{repo: o/r, pr: 3, tier: tier0, outcome: resolved, date: '2026-10-03'}")
    state = L.budget_state(CFG, led, scheduled=True, month="2026-10")
    assert state.spent_usd == 50.0 and state.exhausted and not state.affords(1.5), "a row with no cost spent nothing"
    for body in ("- {cost_usd: 50.0, date: '2026-10-01'}\n", "schema: x\nresolutions: {a: {cost_usd: 50.0}}\n"):
        p = Path(tempfile.mkdtemp()) / "jev_resolutions.yml"
        p.write_text(body)
        _refused(lambda q=p: L.Ledger.load(q), f"a ledger shaped {body!r}", "cannot be judged")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"ok   {t.__name__}")
        except AssertionError as e:  # noqa: PERF203
            failed += 1
            print(f"FAIL {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"ERR  {t.__name__}: {type(e).__name__}: {e}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    raise SystemExit(1 if failed else 0)
