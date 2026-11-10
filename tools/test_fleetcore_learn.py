#!/usr/bin/env python3
"""Tests for tools/fleetcore/learn.py — outcome learning in shadow: how an output
is sorted into an outcome, the estimate and its decay, the Thompson plan, the
replay skill test, the lake reader (read-only, and honest about a lake that
predates the outcome columns) and the hub's own `learning:` block.
Offline, no pytest:  python3 tools/test_fleetcore_learn.py"""
from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import io
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fleetcore import learn  # noqa: E402

HUB = Path(__file__).resolve().parent.parent
NOW = dt.datetime(2026, 11, 10, 12, 0, tzinfo=dt.timezone.utc)

FLEET = {"hub": {"repo": "o/hub", "owners": ["o"]}, "learning": {
    "mode": "shadow", "window_days": 90, "horizon_days": 14, "half_life_days": 30, "prior_strength": 4,
    "min_resolved": 4, "backlog_weeks": {"slow": 4, "hold": 12}, "working_labels": ["agent:ready"],
    "loops": {
        "scout": {"kind": "issue", "labels": ["ai-scout"], "workflow": "repo-scout.yml", "arms": "registry"},
        "evolve": {"kind": "pr", "labels": ["ai-evolution"]},
        "pipeline": {"kind": "issue", "any_labels": ["agent:in-pr", "agent:done"]},
    }}}
CFG = learn.load_config(FLEET)


def days_ago(n: float) -> str:
    return (NOW - dt.timedelta(days=n)).strftime("%Y-%m-%dT%H:%M:%SZ")


def item(number, *, nwo="o/a", pr=False, state="open", reason=None, merged=None, created=30, closed=None, labels=()):
    return learn.normalise({"nwo": nwo, "number": number, "is_pr": pr, "state": state, "state_reason": reason,
                            "merged_at": days_ago(merged) if merged is not None else None,
                            "created_at": days_ago(created), "closed_at": days_ago(closed) if closed is not None else None,
                            "labels": list(labels), "title": f"item {number}"})


class ConfigTests(unittest.TestCase):
    def cfg(self, **over):
        return learn.load_config({"learning": {**FLEET["learning"], **over}})

    def test_shadow_is_the_only_mode(self):
        for mode in ("advise", "steer", "on", ""):
            with self.assertRaises(learn.ConfigError) as err:
                self.cfg(mode=mode)
            self.assertIn("only shadow exists", str(err.exception))

    def test_a_missing_block_a_bad_number_and_a_rule_with_no_labels_are_refused(self):
        with self.assertRaises(learn.ConfigError):
            learn.load_config({})
        for key in ("window_days", "horizon_days", "half_life_days", "prior_strength", "min_resolved"):
            for bad in (0, -1, "14", True):
                with self.assertRaises(learn.ConfigError, msg=f"{key}={bad!r}"):
                    self.cfg(**{key: bad})
        with self.assertRaises(learn.ConfigError):
            self.cfg(backlog_weeks={"slow": 12, "hold": 4})
        with self.assertRaises(learn.ConfigError):
            self.cfg(loops={})
        with self.assertRaises(learn.ConfigError):
            self.cfg(loops={"x": {"kind": "issue"}})
        with self.assertRaises(learn.ConfigError):
            self.cfg(loops={"x": {"kind": "commit", "labels": ["a"]}})

    def test_the_hubs_own_block_loads_and_every_workflow_it_names_exists(self):
        cfg = learn.load_config(learn.load_fleet(HUB))
        self.assertEqual(cfg["mode"], "shadow")
        self.assertGreaterEqual(len(cfg["loops"]), 4)
        for name, rule in cfg["loops"].items():
            if rule.get("workflow"):
                self.assertTrue((HUB / ".github" / "workflows" / rule["workflow"]).is_file(), f"{name}: {rule['workflow']}")


class OutcomeTests(unittest.TestCase):
    def state(self, it, **flags):
        return learn.classify(dict(it, **flags), CFG, NOW)

    def test_each_outcome(self):
        self.assertEqual(self.state(item(1, pr=True, state="closed", merged=3, closed=3)), "landed")
        self.assertEqual(self.state(item(2, pr=True, state="closed", closed=3)), "rejected")
        self.assertEqual(self.state(item(3, state="closed", reason="completed", closed=3)), "landed")
        self.assertEqual(self.state(item(4, state="closed", reason="not_planned", closed=3)), "rejected")
        self.assertEqual(self.state(item(5, state="closed", reason="duplicate", closed=3)), "rejected")
        self.assertEqual(self.state(item(6, created=20)), "stale")
        self.assertEqual(self.state(item(7, created=13.9)), "young")
        self.assertEqual(self.state(item(8, created=14)), "stale")          # the horizon itself is stale
        self.assertEqual(self.state(item(9, created=60, labels=["agent:ready"])), "working")

    def test_a_close_with_no_stored_reason_is_unread_never_a_guess(self):
        self.assertEqual(self.state(item(1, state="closed", closed=3)), "unread")
        # a closed pull request with no merge time is a rejection only in a lake that stores merge times
        closed_pr = item(2, pr=True, state="closed", closed=3)
        self.assertEqual(self.state(closed_pr, _outcomes_known=True), "rejected")
        self.assertEqual(self.state(closed_pr, _outcomes_known=False), "unread")

    def test_attribution_is_by_label_and_kind_and_can_name_two_loops(self):
        self.assertEqual(learn.attribute(item(1, labels=["ai-scout"]), CFG), ["scout"])
        self.assertEqual(learn.attribute(item(2, labels=["ai-scout"], pr=True), CFG), [])           # wrong kind
        self.assertEqual(learn.attribute(item(3, labels=["ai-evolution", "automation"], pr=True), CFG), ["evolve"])
        self.assertEqual(learn.attribute(item(4, labels=["agent:done"]), CFG), ["pipeline"])         # any of them
        self.assertEqual(learn.attribute(item(5, labels=["ai-scout", "agent:in-pr"]), CFG), ["scout", "pipeline"])
        self.assertEqual(learn.attribute(item(6, labels=["bug"]), CFG), [])

    def test_an_outcome_is_dated_when_it_became_known(self):
        rows = learn.outcomes([item(1, labels=["ai-scout"], state="closed", reason="completed", created=20, closed=5),
                               item(2, labels=["ai-scout"], created=20),
                               item(3, labels=["ai-scout"], created=2),
                               item(4, labels=["other"], created=2)], CFG, NOW)
        got = {r["key"]: (r["state"], r["decided_at"]) for r in rows}
        self.assertEqual(got["o/a#1"], ("landed", learn.parse_ts(days_ago(5))))
        self.assertEqual(got["o/a#2"], ("stale", learn.parse_ts(days_ago(6))))     # filed 20 days ago + the 14-day horizon
        self.assertEqual(got["o/a#3"], ("young", None))
        self.assertNotIn("o/a#4", got)


class EstimateTests(unittest.TestCase):
    def test_the_beta_functions_agree_with_what_is_known_in_closed_form(self):
        for x in (0.1, 0.37, 0.9):
            self.assertAlmostEqual(learn.beta_cdf(x, 1, 1), x, places=9)                 # uniform
            self.assertAlmostEqual(learn.beta_cdf(x, 2, 1), x * x, places=9)             # Beta(2,1): x²
            self.assertAlmostEqual(learn.beta_cdf(x, 1, 3), 1 - (1 - x) ** 3, places=9)  # Beta(1,3)
        self.assertAlmostEqual(learn.beta_cdf(0.5, 7.5, 7.5), 0.5, places=9)             # symmetric
        self.assertEqual((learn.beta_cdf(0, 2, 3), learn.beta_cdf(1, 2, 3)), (0.0, 1.0))
        for a, b in ((0.7, 3.2), (12.0, 2.5), (40.0, 60.0)):
            for q in (0.05, 0.5, 0.95):
                self.assertAlmostEqual(learn.beta_cdf(learn.beta_quantile(q, a, b), a, b), q, places=6)

    def test_an_outcome_loses_half_its_weight_every_half_life_and_the_future_is_not_read(self):
        self.assertAlmostEqual(learn.decay(30, 30), 0.5)
        self.assertAlmostEqual(learn.decay(60, 30), 0.25)
        self.assertEqual(learn.decay(-5, 30), 1.0)
        rows = learn.outcomes([item(1, labels=["ai-scout"], state="closed", reason="completed", created=40, closed=30),
                               item(2, labels=["ai-scout"], state="closed", reason="not_planned", created=10, closed=0)],
                              CFG, NOW)
        won, lost = learn.weigh(rows, NOW, CFG)
        self.assertAlmostEqual(won, 0.5, places=3)
        self.assertAlmostEqual(lost, 1.0, places=3)
        # ten days ago the rejection had not happened yet
        self.assertEqual(learn.weigh(rows, NOW - dt.timedelta(days=10), CFG)[1], 0.0)

    def test_an_arm_with_no_history_starts_at_the_loops_rate_and_evidence_moves_it(self):
        good = [item(i, nwo="o/good", labels=["ai-scout"], state="closed", reason="completed", created=9, closed=1)
                for i in range(1, 7)]
        bad = [item(i, nwo="o/bad", labels=["ai-scout"], state="closed", reason="not_planned", created=9, closed=1)
               for i in range(11, 17)]
        rows = learn.outcomes(good + bad, CFG, NOW)
        loop = learn.estimate(rows, rows, NOW, CFG)
        unseen = learn.estimate([], rows, NOW, CFG)
        self.assertAlmostEqual(loop["mean"], 0.5, places=2)
        self.assertAlmostEqual(unseen["mean"], 0.5, places=2)
        self.assertEqual(unseen["evidence"], 0.0)
        g = learn.estimate([r for r in rows if r["arm"] == "o/good"], rows, NOW, CFG)
        b = learn.estimate([r for r in rows if r["arm"] == "o/bad"], rows, NOW, CFG)
        self.assertGreater(g["mean"], 0.75)
        self.assertLess(b["mean"], 0.25)
        self.assertLess(g["low"], g["mean"])
        self.assertLess(g["mean"], g["high"])
        self.assertLess(unseen["high"] - unseen["low"], 1.0)
        self.assertGreater(unseen["high"] - unseen["low"], g["high"] - g["low"])   # less evidence, wider range

    def test_pressure_turns_backlog_and_landing_rate_into_one_word(self):
        def rows(landed_recent, open_young, unread=0):
            its = [item(i, labels=["ai-scout"], state="closed", reason="completed", created=10, closed=2)
                   for i in range(landed_recent)]
            its += [item(100 + i, labels=["ai-scout"], created=3) for i in range(open_young)]
            its += [item(200 + i, labels=["ai-scout"], state="closed", closed=2) for i in range(unread)]
            return learn.outcomes(its, CFG, NOW)
        self.assertEqual(learn.pressure(rows(4, 0), NOW, CFG)["advice"], "file")       # nothing open
        self.assertEqual(learn.pressure(rows(4, 3), NOW, CFG), {"open": 3, "landed_per_week": 1.0, "weeks": 3.0, "advice": "file"})
        self.assertEqual(learn.pressure(rows(4, 4), NOW, CFG)["advice"], "slow")       # 4 weeks
        self.assertEqual(learn.pressure(rows(4, 12), NOW, CFG)["advice"], "hold")      # 12 weeks
        self.assertEqual(learn.pressure(rows(0, 2), NOW, CFG)["advice"], "hold")       # open and nothing landing
        self.assertEqual(learn.pressure(rows(4, 1, unread=1), NOW, CFG)["advice"], "unread")


def history(good=8, bad=8, stamp=0):
    """Two arms with opposite records, filed one a day so a replay has an order."""
    its = []
    for i in range(good):
        its.append(item(i + 1, nwo="o/good", pr=True, labels=["ai-evolution"], state="closed",
                        merged=i + 0.5 + stamp, closed=i + 0.5 + stamp, created=i + 2 + stamp))
    for i in range(bad):
        its.append(item(i + 101, nwo="o/bad", pr=True, labels=["ai-evolution"], state="closed",
                        closed=i + 0.5 + stamp, created=i + 2 + stamp))
    return its


class PlanAndReplayTests(unittest.TestCase):
    def setUp(self):
        self.rows = [r for r in learn.outcomes(history(), CFG, NOW) if r["loop"] == "evolve"]

    def test_one_day_gives_one_plan_and_the_shares_add_up(self):
        a = learn.plan("evolve", self.rows, NOW, CFG, slots=6, candidates=["o/new"])
        b = learn.plan("evolve", self.rows, NOW, CFG, slots=6, candidates=["o/new"])
        self.assertEqual(a, b)
        self.assertEqual(a["seed"], "2026-11-10:evolve")
        self.assertAlmostEqual(sum(x["share"] for x in a["arms"]), 1.0, places=6)
        self.assertAlmostEqual(sum(x["slots"] for x in a["arms"]), 6.0, places=1)
        other = learn.plan("evolve", self.rows, NOW + dt.timedelta(days=1), CFG, slots=6, candidates=["o/new"])
        self.assertEqual(other["seed"], "2026-11-11:evolve")
        self.assertEqual(a["mode"], "shadow")
        self.assertIn("steers nothing", a["note"])

    def test_the_arm_that_lands_gets_the_slots_and_an_unseen_arm_keeps_a_share(self):
        plan = learn.plan("evolve", self.rows, NOW, CFG, slots=10, candidates=["o/new"])
        share = {x["arm"]: x["share"] for x in plan["arms"]}
        self.assertEqual([x["arm"] for x in plan["arms"]][0], "o/good")
        self.assertGreater(share["o/good"], 0.6)
        self.assertLess(share["o/bad"], 0.02)
        self.assertGreater(share["o/new"], share["o/bad"])     # exploration: no history beats a bad one
        self.assertGreater(share["o/new"], 0.02)
        new = next(x for x in plan["arms"] if x["arm"] == "o/new")
        self.assertEqual((new["evidence"], new["filed_recently"]), (0.0, 0))

    def test_what_the_loop_filed_lately_sits_beside_what_the_plan_would_file(self):
        plan = learn.plan("evolve", self.rows, NOW, CFG, slots=4)
        actual = {x["arm"]: x["actual_share"] for x in plan["arms"]}
        self.assertAlmostEqual(actual["o/good"], 0.5)          # the loop's own rule split it evenly
        self.assertAlmostEqual(actual["o/bad"], 0.5)

    def test_no_arm_is_a_plan_that_says_so(self):
        self.assertEqual(learn.plan("evolve", [], NOW, CFG)["arms"], [])

    def test_replay_finds_skill_when_arms_differ_and_none_when_they_do_not(self):
        r = learn.replay("evolve", self.rows, CFG)
        self.assertEqual((r["scored"], r["arms"], r["enough"]), (16, 2, True))
        self.assertGreater(r["skill"], 0.3)
        self.assertLess(r["brier_arm"], r["brier_loop"])
        self.assertIn("predicts better", r["verdict"])
        # the same history with the arm names shuffled away: one arm, nothing to learn
        flat = [dict(x, arm="o/only") for x in self.rows]
        one = learn.replay("evolve", flat, CFG)
        self.assertEqual((one["skill"], one["verdict"]), (None, "one arm: nothing to choose between"))

    def test_replay_refuses_to_judge_on_too_little(self):
        few = [r for r in learn.outcomes(history(good=1, bad=1), CFG, NOW) if r["loop"] == "evolve"]
        r = learn.replay("evolve", few, CFG)
        self.assertEqual((r["scored"], r["enough"], r["verdict"]), (2, False, "not enough evidence"))

    def test_an_estimate_that_is_no_better_than_the_average_says_so(self):
        # both arms land half the time, alternating: knowing the arm tells nothing
        its = []
        for i in range(12):
            landed = i % 2 == 0
            for arm in ("o/a", "o/b"):
                its.append(item(i * 2 + (arm == "o/b") + 1, nwo=arm, pr=True, labels=["ai-evolution"], state="closed",
                                merged=i + 0.5 if landed else None, closed=i + 0.5, created=i + 2))
        rows = [r for r in learn.outcomes(its, CFG, NOW) if r["loop"] == "evolve"]
        r = learn.replay("evolve", rows, CFG)
        self.assertLessEqual(r["skill"], 0.05)
        self.assertNotIn("not enough", r["verdict"])


def make_lake(path: Path, items, *, outcome_columns=True, runs=()):
    conn = sqlite3.connect(str(path))
    extra = ", state_reason TEXT, merged_at TEXT" if outcome_columns else ""
    conn.execute("CREATE TABLE issues (nwo TEXT, number INTEGER, title TEXT, state TEXT, is_pr INTEGER, labels TEXT, "
                 f"author TEXT, created_at TEXT, updated_at TEXT, closed_at TEXT, html_url TEXT, body TEXT{extra}, "
                 "PRIMARY KEY (nwo, number))")
    conn.execute("CREATE TABLE runs (id INTEGER PRIMARY KEY, nwo TEXT, workflow_path TEXT, created_at TEXT)")
    conn.execute("CREATE TABLE agent_runs (run_id INTEGER PRIMARY KEY, nwo TEXT, cost_usd REAL)")
    for it in items:
        row = {"nwo": it["nwo"], "number": it["number"], "title": it["title"], "state": it["state"],
               "is_pr": int(it["is_pr"]), "labels": json.dumps(it["labels"]),
               "created_at": it["created_at"].strftime("%Y-%m-%dT%H:%M:%SZ"),
               "closed_at": it["closed_at"].strftime("%Y-%m-%dT%H:%M:%SZ") if it["closed_at"] else None}
        if outcome_columns:
            row["state_reason"] = it["state_reason"]
            row["merged_at"] = it["merged_at"].strftime("%Y-%m-%dT%H:%M:%SZ") if it["merged_at"] else None
        conn.execute(f"INSERT INTO issues ({', '.join(row)}) VALUES ({', '.join('?' for _ in row)})", list(row.values()))
    for rid, path_, cost in runs:
        conn.execute("INSERT INTO runs VALUES (?, 'o/hub', ?, ?)", (rid, path_, days_ago(5)))
        if cost is not ...:
            conn.execute("INSERT INTO agent_runs VALUES (?, 'o/hub', ?)", (rid, cost))
    conn.commit()
    conn.close()


class LakeAndDocumentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "_data").mkdir()
        (self.root / "_data" / "fleet.yml").write_text(json.dumps(FLEET), encoding="utf-8")   # JSON is YAML
        (self.root / "_data" / "projects.yml").write_text(json.dumps([
            {"name": "a", "repo_url": "https://github.com/o/a", "status": "active"},
            {"name": "fresh", "repo_url": "https://github.com/o/fresh.git", "status": "active"},
            {"name": "old", "repo_url": "https://github.com/o/old", "status": "archived"},
            {"name": "theirs", "repo_url": "https://github.com/else/theirs", "status": "active"}]), encoding="utf-8")
        self.items = [
            item(1, labels=["ai-scout"], state="closed", reason="completed", created=20, closed=10),
            item(2, labels=["ai-scout"], state="closed", reason="not_planned", created=20, closed=10),
            item(3, labels=["ai-scout"], created=30),
            item(4, labels=["ai-scout"], created=3),
            item(5, pr=True, labels=["ai-evolution"], state="closed", merged=4, closed=4, created=8),
            item(6, labels=["ai-scout"], state="closed", reason="completed", created=200, closed=190),   # outside the window
        ]
        self.lake = self.root / "lake.sqlite"

    def tearDown(self):
        self.tmp.cleanup()

    def loops(self, doc):
        return {lp["loop"]: lp for lp in doc["loops"]}

    def test_the_document_counts_each_loop_and_ignores_what_is_older_than_the_window(self):
        doc = learn.build(self.root, items=self.items, now=NOW)
        self.assertEqual((doc["schema"], doc["mode"], doc["cost_label"]), ("learning/v1", "shadow", "API-equivalent (estimate)"))
        scout = self.loops(doc)["scout"]
        self.assertEqual(scout["counts"], {"landed": 1, "rejected": 1, "stale": 1, "working": 0, "young": 1, "unread": 0})
        self.assertEqual((scout["outputs"], scout["resolved"], scout["enough"]), (4, 3, False))
        self.assertAlmostEqual(scout["landed_pct"], 33.3, places=1)
        self.assertEqual(scout["median_days_to_land"], 10.0)
        self.assertEqual(self.loops(doc)["evolve"]["counts"]["landed"], 1)
        self.assertEqual(doc["notes"], [])
        # `arms: registry` adds the hub's own active repos as arms: not the archived one, not another owner's
        arms = {a["arm"] for a in scout["plan"]["arms"]}
        self.assertEqual(arms, {"o/a", "o/fresh"})
        self.assertEqual({a["arm"] for a in self.loops(doc)["evolve"]["plan"]["arms"]}, {"o/a"})

    def test_one_loop_can_be_asked_for_and_an_unknown_one_is_refused(self):
        doc = learn.build(self.root, items=self.items, now=NOW, loop="evolve")
        self.assertEqual([lp["loop"] for lp in doc["loops"]], ["evolve"])
        with self.assertRaises(learn.ConfigError) as err:
            learn.build(self.root, items=self.items, now=NOW, loop="nope")
        self.assertIn("scout", str(err.exception))

    def test_the_lake_is_read_and_never_written(self):
        make_lake(self.lake, self.items, runs=[(1, ".github/workflows/repo-scout.yml", 1.5),
                                               (2, ".github/workflows/repo-scout.yml", 0.5),
                                               (3, ".github/workflows/repo-scout.yml", ...),      # a run with no cost read
                                               (4, ".github/workflows/other.yml", 9.0)])
        before = hashlib.sha256(self.lake.read_bytes()).hexdigest()
        doc = learn.build(self.root, lake=self.lake, now=NOW)
        self.assertEqual(hashlib.sha256(self.lake.read_bytes()).hexdigest(), before)
        self.assertEqual(doc["source"]["kind"], "lake")
        self.assertTrue(doc["source"]["outcome_columns"])
        scout = self.loops(doc)["scout"]
        self.assertEqual(scout["counts"]["landed"], 1)
        # cost is what the lake has read, per landed output, and says how many runs it covers
        self.assertEqual(scout["cost"], {"usd": 2.0, "runs_read": 2, "runs": 3, "usd_per_landed": 2.0,
                                         "label": "API-equivalent (estimate)"})
        self.assertNotIn("cost", self.loops(doc)["evolve"])       # its rule names no workflow

    def test_a_lake_from_before_the_outcome_columns_reads_closed_work_as_unread(self):
        make_lake(self.lake, self.items, outcome_columns=False)
        doc = learn.build(self.root, lake=self.lake, now=NOW)
        self.assertFalse(doc["source"]["outcome_columns"])
        scout, evolve = self.loops(doc)["scout"], self.loops(doc)["evolve"]
        self.assertEqual((scout["counts"]["landed"], scout["counts"]["rejected"], scout["counts"]["unread"]), (0, 0, 2))
        self.assertEqual(evolve["counts"]["unread"], 1)           # a closed pull request is not called rejected
        self.assertEqual(scout["pressure"]["advice"], "unread")
        self.assertIn("lake sync --days 90", doc["notes"][0])

    def test_no_lake_says_what_builds_one(self):
        with self.assertRaises(learn.LakeError) as err:
            learn.build(self.root, lake=self.root / "missing.sqlite", now=NOW)
        self.assertIn("lake sync", str(err.exception))
        (self.root / "empty.sqlite").write_bytes(b"")
        sqlite3.connect(str(self.root / "empty.sqlite")).close()
        with self.assertRaises(learn.LakeError):
            learn.build(self.root, lake=self.root / "empty.sqlite", now=NOW)


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.export = Path(self.tmp.name) / "items.jsonl"
        rows = []
        for it in history(good=6, bad=6):
            rows.append({"nwo": it["nwo"], "number": it["number"], "is_pr": True, "state": it["state"],
                         "state_reason": None, "merged_at": it["merged_at"].isoformat() if it["merged_at"] else None,
                         "created_at": it["created_at"].isoformat(), "closed_at": it["closed_at"].isoformat(),
                         "labels": ["ai-evolution"], "title": it["title"]})
        self.export.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = learn.main(list(argv) + ["--now", "2026-11-10T12:00:00Z"])
        return code, out.getvalue(), err.getvalue()

    def test_status_plan_and_replay_read_an_export(self):
        code, out, _ = self.run_cli("status", "--items", str(self.export))
        self.assertEqual(code, 0)
        self.assertIn("outcome learning · shadow", out.splitlines()[0])
        self.assertIn("repo-evolution", out)
        code, out, _ = self.run_cli("plan", "--items", str(self.export), "--loop", "repo-evolution", "--top", "3")
        self.assertEqual(code, 0)
        self.assertIn("o/good", out)
        self.assertIn("replay:", out)
        code, out, _ = self.run_cli("replay", "--items", str(self.export), "--json")
        doc = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual({r["loop"] for r in doc["loops"]}, set(learn.load_config(learn.load_fleet(HUB))["loops"]))
        self.assertGreater(next(r for r in doc["loops"] if r["loop"] == "repo-evolution")["skill"], 0)

    def test_json_status_is_the_document_every_surface_reads(self):
        code, out, _ = self.run_cli("--json", "--items", str(self.export))
        doc = json.loads(out)
        self.assertEqual((code, doc["schema"], doc["mode"]), (0, "learning/v1", "shadow"))
        evo = next(lp for lp in doc["loops"] if lp["loop"] == "repo-evolution")
        self.assertEqual(set(evo) >= {"counts", "estimate", "pressure", "plan", "replay", "arms", "rule"}, True)

    def test_a_missing_lake_an_unknown_loop_and_a_bad_export_exit_2_on_stderr(self):
        code, out, err = self.run_cli("status", "--lake", str(Path(self.tmp.name) / "none.sqlite"))
        self.assertEqual((code, out), (2, ""))
        self.assertIn("no lake at", err)
        code, _, err = self.run_cli("plan", "--items", str(self.export), "--loop", "nope")
        self.assertEqual(code, 2)
        self.assertIn("no loop called", err)
        bad = Path(self.tmp.name) / "bad.jsonl"
        bad.write_text("{not json\n", encoding="utf-8")
        code, _, err = self.run_cli("status", "--items", str(bad))
        self.assertEqual(code, 2)
        self.assertIn("cannot read", err)


if __name__ == "__main__":
    unittest.main()
