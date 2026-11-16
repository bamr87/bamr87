#!/usr/bin/env python3
"""
Fixture tests for tools/jev/sprints.py — an expedite sprint's ceiling and
circuit breaker (constitution § 27.3, § 27.4, § 27.6; #689).

What is held here: a declaration that bounds nothing (`.inf`, `.nan`, 0, a
negative cap or appetite, a ceiling above the fleet's monthly one) and a
second sprint whose time box overlaps another (WIP 1) are refused at load; a
sprint at its cap answers `budget-skip` to the next attempt; its switch set
to 'false' answers `sprint-off` on a scheduled run and a manual run bypasses
it; a closed sprint keeps its declared item stopped; spend is read from the
AI ledger's loop rows, JEV's ledger, the sprint repositories' own CI runs
(never the hub's) and the tier caps the issue pipeline's runs reserved for
sprint items (its snapshot's `sprint.reservations`, an estimate). The loop
runner, the conflict engine and the issue
pipeline each prove the same breaker in their own suites
(tools/test_jev_loop.py, tools/test_jev_conflicts.py,
.github/scripts/dash-gen/test_issue_pipeline.py).

Run: python3 tools/test_jev_sprints.py
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import math
import os
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(1, str(ROOT / ".github" / "scripts" / "dash-gen"))

from tools.jev import loop as L  # noqa: E402
from tools.jev import sprints as sp  # noqa: E402
from tools.jev.common import JevError, load_config, load_fleet  # noqa: E402
from tools.jev.ledger import Ledger, Resolution  # noqa: E402

NOW = dt.datetime(2026, 11, 20, 18, 0, tzinfo=dt.UTC)
REPO = "bash-365/bash-365.com"


def fleet(**sprints) -> dict:
    return {"budget": {"sprints": sprints}, "harnesses": {"budget": {"monthly_ai_usd": 200}}}


def entry(**kw) -> dict:
    base = {"item": f"issue:{REPO}#26", "usd": 30, "hours": 72, "declared": "2026-11-20T15:00:00Z"}
    base.update(kw)
    return base


def one(**kw) -> sp.Sprint:
    [s] = sp.load_sprints(fleet(pilot=entry(**kw)))
    return s


def refused(what: str, doc: dict, *needles: str) -> None:
    try:
        sp.load_sprints(doc)
    except JevError as exc:
        for needle in needles:
            assert needle in str(exc), (what, str(exc))
    else:
        raise AssertionError(f"{what} was accepted")


def armed() -> tuple[bool, str]:
    return True, "armed"


def spent(usd: float):
    return lambda s: sp.Spend(spent_usd=usd)


# --------------------------------------------------------------------------- #
# the declaration
# --------------------------------------------------------------------------- #
def test_no_block_or_an_empty_one_declares_nothing():
    assert sp.load_sprints({}) == [] and sp.load_sprints(fleet()) == []
    assert sp.load_sprints({"budget": {"sprints": None}}) == []


def test_a_declaration_loads_its_repo_from_the_item_and_its_box_from_the_appetite():
    s = one()
    assert s.repos == (REPO,) and s.usd == 30.0 and s.hours == 72.0
    assert s.declared == dt.datetime(2026, 11, 20, 15, 0, tzinfo=dt.UTC)
    assert s.ends == s.declared + dt.timedelta(hours=72)
    assert s.active(NOW) and not s.closed(NOW) and s.covers(REPO.upper())
    # YAML's own date and datetime types, and a zone-less time (read as UTC)
    assert one(declared=dt.date(2026, 11, 20)).declared == dt.datetime(2026, 11, 20, tzinfo=dt.UTC)
    assert one(declared=dt.datetime(2026, 11, 20, 15, 0)).declared == s.declared
    loaded = sp.load_sprints(yaml.safe_load(
        "budget:\n  sprints:\n    pilot:\n      item: issue:bash-365/bash-365.com#26\n      usd: 30\n"
        "      hours: 72\n      declared: 2026-11-20T15:00:00Z\n"))
    assert loaded[0].declared == s.declared


def test_neither_end_extends_the_other():
    assert one(ends="2026-11-21T15:00:00Z").ends == dt.datetime(2026, 11, 21, 15, 0, tzinfo=dt.UTC)
    assert one(ends="2026-12-31T00:00:00Z").ends == one().ends, "a later `ends` never outlasts the appetite"


def test_listed_repos_win_and_an_item_with_no_repo_needs_them():
    s = one(item="roadmap:FF-0042", repos=[REPO, "bamr87/bamr87", REPO])
    assert s.repos == (REPO, "bamr87/bamr87")
    refused("a roadmap item with no repos", fleet(pilot=entry(item="roadmap:FF-0042")), "names no repository")
    refused("an empty repos list", fleet(pilot=entry(repos=[])), "repos must be")
    refused("a repo that is not owner/repo", fleet(pilot=entry(repos=["bash-365.com"])), "repos must be")


def test_a_cap_or_appetite_that_bounds_nothing_is_refused_at_load():
    for bad in (math.inf, math.nan, 0, -5, "lots", True, None):
        refused(f"usd {bad!r}", fleet(pilot=entry(usd=bad)), "budget.sprints.pilot.usd", "finite number above 0")
        refused(f"hours {bad!r}", fleet(pilot=entry(hours=bad)), "budget.sprints.pilot.hours", "finite number above 0")
    # the YAML spellings themselves, as a hand edit would write them
    for raw in (".inf", ".nan", "0", "-1"):
        doc = yaml.safe_load(f"budget:\n  sprints:\n    pilot:\n      item: issue:{REPO}#26\n      usd: {raw}\n"
                             "      hours: 72\n      declared: 2026-11-20\n")
        refused(f"usd: {raw}", doc, "finite number above 0")
    refused("hours past any calendar", fleet(pilot=entry(hours=1e300)), "runs past any calendar")


def test_a_ceiling_above_the_fleet_monthly_ceiling_is_refused():
    refused("usd above monthly_ai_usd", fleet(pilot=entry(usd=250)), "above harnesses.budget.monthly_ai_usd", "§ 27.4")
    assert one(usd=200).usd == 200.0, "the ceiling itself fits"


def test_a_malformed_declaration_is_refused():
    refused("a list", {"budget": {"sprints": ["pilot"]}}, "must be a mapping")
    refused("a bad slug", fleet(**{"Pilot One": entry()}), "not a sprint slug")
    refused("an entry that is not a mapping", fleet(pilot="soon"), "must be a mapping")
    refused("an unknown key", fleet(pilot=entry(cap_usd=30)), "unknown key(s) cap_usd")
    refused("an item that is no work-queue key", fleet(pilot=entry(item="bash-365.com#26")), "work_queue.yml key")
    refused("no declared time", fleet(pilot=entry(declared=None)), "declared must be a date or an ISO time")
    refused("a declared time that does not parse", fleet(pilot=entry(declared="soon")), "ISO time")
    refused("an end before the declaration", fleet(pilot=entry(ends="2026-11-19T00:00:00Z")), "is not after")


def test_a_second_sprint_whose_box_overlaps_is_refused_wip_1():
    first = entry()
    second = entry(item="issue:bamr87/bamr87#691", declared="2026-11-22T00:00:00Z")
    refused("two overlapping sprints", fleet(pilot=first, record=second), "overlap", "WIP 1")
    after = entry(item="issue:bamr87/bamr87#691", declared="2026-11-23T15:00:00Z")   # exactly at the first's end
    loaded = sp.load_sprints(fleet(record=after, pilot=first))
    assert [s.slug for s in loaded] == ["pilot", "record"], "oldest first"
    assert sp.active(loaded, NOW).slug == "pilot"
    assert sp.active(loaded, dt.datetime(2026, 11, 24, tzinfo=dt.UTC)).slug == "record"


def test_the_committed_fleet_declares_a_sprint_block_that_loads_and_raises_no_cap():
    doc = load_fleet()
    assert isinstance(doc["budget"].get("sprints"), dict), "budget.sprints is declared (empty until Amr's Gate A)"
    for s in sp.load_sprints(doc):
        assert s.usd <= doc["harnesses"]["budget"]["monthly_ai_usd"]
    assert load_config(doc).sprints == sp.load_sprints(doc), "the conflict engine loads the same declaration"


def test_a_declaration_that_bounds_nothing_stops_the_conflict_engine_at_load():
    doc = copy.deepcopy(load_fleet())
    doc["budget"]["sprints"] = {"pilot": entry(usd=math.inf)}
    try:
        load_config(doc)
    except JevError as exc:
        assert "budget.sprints.pilot.usd" in str(exc), exc
    else:
        raise AssertionError("load_config accepted an infinite sprint ceiling")


def test_the_work_queue_key_pattern_is_dash_gens():
    import work_queue
    assert sp.WORK_KEY_RX.pattern == work_queue.KEY_RX.pattern


# --------------------------------------------------------------------------- #
# the gate
# --------------------------------------------------------------------------- #
def test_a_sprint_at_its_cap_skips_the_next_attempt():
    sprints = [one(usd=30)]
    assert sp.gate(sprints, repo=REPO, now=NOW, cost_usd=8, spend_of=spent(22)) is None, "$22 + $8 fits $30"
    v = sp.gate(sprints, repo=REPO, now=NOW, cost_usd=8, spend_of=spent(22.5))
    assert v and v.decision == sp.BUDGET_SKIP == "budget-skip", v
    assert "sprint pilot ceiling" in v.reason and sp.COST_LABEL in v.reason and "§ 27.3" in v.reason, v.reason
    ev = v.event(NOW)
    assert ev["event"] == "sprint-stop" and ev["cap_usd"] == 30.0 and ev["spent_usd"] == 22.5 and ev["at"] == sp.iso(NOW)
    at_cap = sp.gate(sprints, repo=REPO, now=NOW, cost_usd=0.25, spend_of=spent(30))
    assert at_cap and at_cap.decision == sp.BUDGET_SKIP, "at the cap even the cheapest attempt is skipped"


def test_outside_the_sprint_nothing_changes():
    sprints = [one(usd=30)]
    never = lambda s: (_ for _ in ()).throw(AssertionError("spend read for an item no sprint holds"))  # noqa: E731
    assert sp.gate(sprints, repo="bamr87/bamr87", now=NOW, cost_usd=60, spend_of=never) is None
    before = dt.datetime(2026, 11, 20, 14, 59, tzinfo=dt.UTC)
    assert sp.gate(sprints, repo=REPO, now=before, cost_usd=60, spend_of=never) is None, "not declared yet"
    assert sp.gate(sprints, repo=REPO, now=NOW, cost_usd=None, spend_of=never, switch=armed) is None


def test_a_closed_sprint_keeps_its_item_stopped_until_a_new_declaration():
    sprints = [one(usd=30)]
    later = sprints[0].ends + dt.timedelta(minutes=1)
    v = sp.gate(sprints, repo=REPO, now=later, cost_usd=8, spend_of=spent(0), key=f"issue:{REPO}#26")
    assert v and v.decision == sp.BUDGET_SKIP and "time box closed" in v.reason and "new declaration" in v.reason, v
    assert sp.gate(sprints, repo=REPO, now=later, cost_usd=8, spend_of=spent(0), key=f"issue:{REPO}#27") is None, \
        "the repo's other work is back in its lanes"
    again = sp.load_sprints(fleet(pilot=entry(usd=30), again=entry(usd=10, declared=sp.iso(later))))
    assert sp.gate(again, repo=REPO, now=later, cost_usd=8, spend_of=spent(0), key=f"issue:{REPO}#26") is None, \
        "a new declaration of the same item runs under its own ceiling"


def test_the_switch_stops_every_sprint_loop_and_a_manual_run_bypasses_it():
    sprints = [one()]
    off = lambda: sp.read_switch(scheduled=True, env={sp.SWITCH: "false"})  # noqa: E731
    v = sp.gate(sprints, repo=REPO, now=NOW, cost_usd=1, spend_of=spent(0), switch=off)
    assert v and v.decision == sp.SPRINT_OFF == "sprint-off" and "switched off" in v.reason, v
    assert v.event(NOW)["event"] == "sprint-off"
    assert sp.switched_off(sprints, repo=REPO, now=NOW, switch=off).decision == sp.SPRINT_OFF
    assert sp.switched_off(sprints, repo="bamr87/bamr87", now=NOW, switch=off) is None, "only the sprint's items"
    manual = lambda: sp.read_switch(scheduled=False, env={sp.SWITCH: "false"})  # noqa: E731
    assert sp.gate(sprints, repo=REPO, now=NOW, cost_usd=1, spend_of=spent(0), switch=manual) is None


def test_the_switch_reads_like_a_section_17_opt_out_switch():
    assert sp.read_switch(scheduled=True, env={sp.SWITCH: "FALSE"})[0] is False, "case-blind, as GitHub compares"
    assert sp.read_switch(scheduled=True, env={sp.SWITCH: ""})[0] is True, "an unset variable arms an opt-out switch"
    assert sp.read_switch(scheduled=True, env={sp.SWITCH: "true"})[0] is True
    assert sp.read_switch(scheduled=True, env={}, reader=lambda: "false")[0] is False
    assert sp.read_switch(scheduled=True, env={}, reader=lambda: None)[0] is True
    assert sp.read_switch(scheduled=True, env={})[0] is True, "no workflow value and no reader: unset"

    def broken() -> str:
        raise JevError("HTTP 403")
    ok, why = sp.read_switch(scheduled=True, env={}, reader=broken)
    assert ok is False and "refuses rather than guess" in why, why
    calls = []
    memo = sp.once(lambda: calls.append(1) or (True, "x"))
    memo(), memo()
    assert calls == [1], "read once a run"


# --------------------------------------------------------------------------- #
# spend
# --------------------------------------------------------------------------- #
def _ai_ledger(tmp: Path, rows: list[dict], unledgered: list[dict] = ()) -> Path:
    p = tmp / "ledger.json"
    p.write_text(json.dumps({"version": 1, "usage": {}, "sessions": {}, "runs": {f"s{i}": r for i, r in enumerate(rows)}}))
    if unledgered:
        L.unledgered_path(p).write_text("".join(json.dumps(r) + "\n" for r in unledgered))
    return p


def test_spend_reads_the_loop_rows_jev_and_the_sprint_repos_own_ci_inside_the_box():
    s = one(usd=50)
    tmp = Path(tempfile.mkdtemp(prefix="jev-sprint-test-"))
    row = {"timestamp": "2026-11-20T16:00:00+00:00", "origin": "local", "loop": "repo-scout", "repo": REPO,
           "total_cost_usd": 2.5, "cost_source": "reported"}
    ai = _ai_ledger(tmp, [
        row,
        {**row, "total_cost_usd": "NaN", "cap_usd": 8.0, "cost_source": "estimated", "attempt_id": "a1"},
        {**row, "repo": "bamr87/SCHEMA"},                                  # another repo
        {**row, "timestamp": "2026-11-20T14:00:00+00:00"},                # before the declaration
        {**row, "loop": None},                                             # a plain dash ai run
        {**row, "origin": "ci"},
    ], unledgered=[
        {"timestamp": "2026-11-20T17:00:00+00:00", "attempt_id": "a2", "repo": REPO, "cost_usd": 1.0,
         "cost_source": "estimated"},
        {"timestamp": "2026-11-20T17:00:00+00:00", "attempt_id": "a1", "repo": REPO, "cost_usd": 8.0,
         "cost_source": "estimated"},                                      # the ledger has this attempt already
        {"timestamp": "2026-11-20T17:00:00+00:00", "attempt_id": "a3", "cost_usd": 4.0,
         "cost_source": "estimated"},                                      # no repo: not attributable
    ])
    jev = Ledger(path=tmp / "jev.yml")
    for r in (Resolution(repo=REPO, pr=3, tier="tier1", outcome="resolved", date="2026-11-20", cost_usd=0.2),
              Resolution(repo=REPO, pr=3, tier="tier2", outcome="failed", date="2026-11-19", cost_usd=9.0),
              Resolution(repo="bamr87/bamr87", pr=9, tier="tier2", outcome="resolved", date="2026-11-20",
                         cost_usd=9.0)):
        jev.append(r)
    ci = [{"repo": "bash-365.com", "day": "2026-11-21", "cost_usd": 3.0, "cost_source": "reported"},
          {"repo": "bash-365.com", "day": "2026-11-30", "cost_usd": 3.0, "cost_source": "reported"},
          {"repo": "bamr87", "day": "2026-11-21", "cost_usd": 40.0, "cost_source": "reported"},
          {"repo": "bash-365.com", "day": dt.date(2026, 11, 22), "cost_usd": 0.5, "cost_source": "estimated"}]
    got = sp.spend(s, ai_ledger=ai, jev=jev, ci=ci, hub="bamr87/bamr87", extra=[(0.3, "estimated")])
    assert got.by_source == {"loops": 11.5, "jev": 0.2, "ci": 3.5, "unledgered": 0.3}, got.by_source
    assert got.spent_usd == 15.5 and got.estimated_usd == 9.8, got
    hub_sprint = one(item="issue:bamr87/bamr87#691")
    assert sp.spend(hub_sprint, ci=ci, hub="bamr87/bamr87").spent_usd == 0, \
        "the hub's CI runs fleet-wide loops: never attributed to a sprint"


def test_an_unreadable_figure_refuses_rather_than_reads_as_free():
    s = one()
    for bad in ("NaN", float("inf"), -1, "lots"):
        try:
            sp.spend(s, ci=[{"repo": "bash-365.com", "day": "2026-11-20", "cost_usd": bad}])
        except JevError as exc:
            assert "cannot be judged" in str(exc), exc
        else:
            raise AssertionError(f"a CI cost of {bad!r} was read")
    tmp = Path(tempfile.mkdtemp(prefix="jev-sprint-test-"))
    (tmp / "ledger.json").write_text("{not json")
    try:
        sp.spend(s, ai_ledger=tmp / "ledger.json")
    except JevError as exc:
        assert "cannot be read" in str(exc), exc
    else:
        raise AssertionError("an unreadable AI ledger read as $0")
    (tmp / "usage.yml").write_text("ci_ledger: {not: a list}\n")
    try:
        sp.ci_rows(tmp / "usage.yml")
    except JevError as exc:
        assert "not a list" in str(exc), exc
    else:
        raise AssertionError("a ci_ledger that is not a list was read")
    assert sp.ci_rows(tmp / "missing.yml") == []


def test_the_issue_pipelines_reservations_are_estimated_sprint_spend():
    s = one(usd=200)
    row = sp.reservation(s, run="77.1", at=NOW, tiers={"intake": 40, "implement": 60})
    assert row == {"run": "77.1", "at": "2026-11-20T18:00:00Z", "sprint": "pilot", "declared": "2026-11-20T15:00:00Z",
                   "usd": 100.0, "tiers": {"intake": 40.0, "implement": 60.0},
                   "label": "API-equivalent (estimate)"}, row
    rows = [row, dict(row),                                              # one row per run
            dict(row, run="78.1", at="2026-11-24T00:00:00Z"),            # after the time box
            dict(row, run="79.1", sprint="other"),                       # another sprint
            dict(row, run="80.1", declared="2026-11-01T00:00:00Z"),      # an earlier declaration of the slug
            dict(row, run="81.1", usd=60.0, tiers={"complete": 60.0})]
    assert sp.pipeline_spend(s, rows) == 160.0
    got = sp.spend(s, pipeline=rows)
    assert got.by_source == {"issue-pipeline": 160.0} and got.estimated_usd == 160.0, got
    hub_sprint = one(item="issue:bamr87/bamr87#691")
    hub_row = sp.reservation(hub_sprint, run="82.1", at=NOW, tiers={"intake": 40})
    assert sp.spend(hub_sprint, pipeline=[hub_row]).spent_usd == 40.0, \
        "the hub's CI rows are never counted, but what the issue pipeline reserved for a hub sprint is"
    for bad in ({**row, "usd": "NaN"}, {**row, "usd": -1}, {**row, "usd": True}, {**row, "usd": None},
                {**row, "at": "soon"}, {**row, "run": ""}):
        try:
            sp.pipeline_spend(s, [bad])
        except JevError as exc:
            assert "cannot be judged" in str(exc), exc
        else:
            raise AssertionError(f"a reservation row {bad!r} was read")
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "issue_pipeline.yml"
        assert sp.pipeline_rows(p) == [], "no snapshot yet: no rows"
        p.write_text("# GENERATED\ntotals: {open_issues: 3}\n")
        assert sp.pipeline_rows(p) == [], "no sprint declared: no rows"
        p.write_text(yaml.safe_dump({"sprint": {"active": None, "reservations": [row]}}))
        assert sp.pipeline_rows(p) == [row], "the committed snapshot reads back as written"
        saved = os.environ.get("JEV_ISSUE_PIPELINE")
        os.environ["JEV_ISSUE_PIPELINE"] = str(p)
        try:
            assert sp.pipeline_rows() == [row], "JEV_ISSUE_PIPELINE points the default reader elsewhere"
        finally:
            os.environ.pop("JEV_ISSUE_PIPELINE")
            if saved is not None:
                os.environ["JEV_ISSUE_PIPELINE"] = saved
        for text in ("sprint: [1, 2]\n", "sprint: {reservations: {a: 1}}\n", "sprint: {reservations: [1]}\n",
                     "sprint: {reservations: [\n"):
            p.write_text(text)
            try:
                sp.pipeline_rows(p)
            except JevError as exc:
                assert "cannot be" in str(exc), exc
            else:
                raise AssertionError(f"a snapshot of {text!r} was read")
    assert sp.pipeline_rows(text="sprint:\n  reservations: []\n") == []


def test_the_ai_ledger_path_is_the_loop_runners():
    saved = os.environ.get("DASH_AI_LEDGER")
    try:
        os.environ["DASH_AI_LEDGER"] = "/tmp/x/ledger.json"
        assert sp.ai_ledger_path() == L.ledger_path()
        os.environ.pop("DASH_AI_LEDGER")
        assert sp.ai_ledger_path() == L.ledger_path()
    finally:
        if saved is not None:
            os.environ["DASH_AI_LEDGER"] = saved


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
