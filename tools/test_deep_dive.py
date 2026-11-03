#!/usr/bin/env python3
"""
Fixture tests for tools/deep_dive.py — the daily repo deep-dive tracker.

Guards what the routine and the /deep-dive page rely on: the rotation's day
math (scheduled, catch-up, before/after the cycle), recording a run (links
deduplicated, status validated), the GitHub refresh (counts grouped per repo
from one search per kind, no network), rollover, the optional Quest Log
showcase (recorded without touching the run, validated, counted per cycle,
absent from an older ledger's projection), the committed tracker being valid
with every repo once, and the JSON projection being fresh.

Stdlib + PyYAML:

    python3 tools/test_deep_dive.py
"""
import datetime as dt
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("deep_dive", HERE / "deep_dive.py")
dd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dd)

D = dt.date.fromisoformat
START = D("2026-10-30")


def doc(n=3, days=5):
    return dd.build([f"r{i}" for i in range(1, n + 1)], START, cycle_days=days)


class Schedule(unittest.TestCase):
    def test_days_and_dates(self):
        d = doc()
        self.assertEqual([r["scheduled"] for r in d["repos"]], ["2026-10-30", "2026-10-31", "2026-11-01"])
        self.assertEqual(dd.today(d, START)["repo"], "r1")
        self.assertEqual(dd.today(d, D("2026-11-01"))["repo"], "r3")

    def test_before_and_after(self):
        d = doc()
        self.assertEqual(dd.today(d, D("2026-10-29"))["kind"], "not_started")
        self.assertEqual(dd.today(d, D("2026-11-04"))["kind"], "cycle_over")

    def test_catch_up_picks_earliest_unfinished(self):
        d = doc()
        dd.record(d, "r1", START)
        dd.record(d, "r2", START, status="skipped")
        t = dd.today(d, D("2026-11-02"))
        self.assertEqual((t["kind"], t["repo"]), ("catch_up", "r2"))

    def test_cycle_days_never_shorter_than_rotation(self):
        self.assertEqual(dd.build(["a", "b", "c"], START, cycle_days=2)["cycle_days"], 3)


class Record(unittest.TestCase):
    def test_record_dedupes_and_sets_fields(self):
        d = doc()
        dd.record(d, "r2", D("2026-10-31"), issues=["u1", "u1"], prs=["p1"], findings="f", score=81.26, next_focus="ux")
        dd.record(d, "r2", D("2026-10-31"), issues=["u1", "u2"])
        r = d["repos"][1]
        self.assertEqual((r["status"], r["last_processed"], r["issues"], r["prs"], r["score"]),
                         ("done", "2026-10-31", ["u1", "u2"], ["p1"], 81.3))
        self.assertEqual(r["next_focus"], "ux")

    def test_bad_input(self):
        d = doc()
        with self.assertRaises(KeyError):
            dd.record(d, "nope", START)
        with self.assertRaises(ValueError):
            dd.record(d, "r1", START, status="finished")
        d["repos"][0]["score"] = 101
        with self.assertRaises(ValueError):
            dd.validate(d)

    def test_summary(self):
        d = doc()
        dd.record(d, "r1", START, score=60)
        dd.record(d, "r2", D("2026-10-31"), score=80)
        s = dd.summary(d, D("2026-11-01"))
        self.assertEqual((s["processed"], s["total"], s["last"], s["avg_score"], s["day"]), (2, 3, "r2", 70.0, 3))
        self.assertEqual(s["today"]["repo"], "r3")
        self.assertEqual(s["cycle_end"], "2026-11-03")


class Refresh(unittest.TestCase):
    def test_groups_search_results_per_repo(self):
        calls = []

        def fake(url, token):
            calls.append(url)
            pr = "is%3Apr" in url
            items = [{"repository_url": "https://api.github.com/repos/bamr87/r1", "html_url": f"h/{'p' if pr else 'i'}1"},
                     {"repository_url": "https://api.github.com/repos/bamr87/other", "html_url": "x"}]
            return {"total_count": len(items), "items": items}

        d = doc()
        counts = dd.refresh(d, None, dt.datetime(2026, 10, 30, 12, tzinfo=dt.timezone.utc), get=fake)
        self.assertEqual(len(calls), 2)
        self.assertEqual(counts["r1"], (1, 1))
        self.assertEqual(counts["r2"], (0, 0))
        self.assertEqual(d["repos"][0]["issues"], ["h/i1"])
        self.assertEqual(d["refreshed_at"], "2026-10-30T12:00:00Z")


class Rollover(unittest.TestCase):
    def test_refuses_unfinished_then_resets(self):
        d = doc()
        with self.assertRaises(ValueError):
            dd.rollover(d)
        for r in ("r1", "r2", "r3"):
            dd.record(d, r, START, score=50)
        dd.rollover(d)
        self.assertEqual((d["cycle"], d["cycle_start"], d["repos"][0]["scheduled"]), (2, "2026-11-04", "2026-11-04"))
        self.assertEqual({r["status"] for r in d["repos"]}, {"pending"})
        self.assertEqual(d["repos"][0]["score"], 50)


class Showcase(unittest.TestCase):
    """The optional per-repo Quest Log showcase (docs/SHOWCASE.md)."""

    ART = "https://bamr87.github.io/posts/2026/11/02/quest-log-r1/"

    def test_ledger_without_showcases_projects_as_before(self):
        d = doc()
        out = json.loads(dd.render_json(d))
        self.assertNotIn("showcased", out["summary"])
        self.assertTrue(all("showcase" not in r for r in out["repos"]))
        dd.validate(d)

    def test_showcase_alone_leaves_the_run_alone(self):
        d = doc()
        dd.record(d, "r1", START, score=70)
        sc = dd.record(d, "r1", D("2026-11-02"), status=None, article=self.ART)["showcase"]
        r = d["repos"][0]
        self.assertEqual((r["status"], r["last_processed"], r["score"]), ("done", "2026-10-30", 70.0))
        self.assertEqual((sc["cycle"], sc["date"], sc["article"]), (1, "2026-11-02", self.ART))
        self.assertEqual(list(sc), list(dd.SHOWCASE_KEYS))
        dd.record(d, "r2", START, status=None, article="x")
        self.assertEqual(d["repos"][1]["status"], "pending")

    def test_links_replace_and_presentation_prs_accumulate(self):
        d = doc()
        dd.record(d, "r1", START, status=None, linkedin_personal="pr/1", presentation_prs=["p1", "p1"])
        dd.record(d, "r1", START, status=None, linkedin_personal="post/1", presentation_prs=["p2", "p1"],
                  showcase_note="screenshots pending")
        sc = d["repos"][0]["showcase"]
        self.assertEqual((sc["linkedin_personal"], sc["presentation_prs"], sc["note"]),
                         ("post/1", ["p1", "p2"], "screenshots pending"))
        self.assertIsNone(sc["article"])

    def test_a_hand_written_partial_showcase_is_completed(self):
        d = doc()
        d["repos"][0]["showcase"] = {"cycle": 1, "date": "2026-11-02", "article": "a"}
        dd.validate(d)
        sc = dd.record(d, "r1", D("2026-11-03"), status=None, presentation_prs=["p1"])["showcase"]
        self.assertEqual((sc["article"], sc["note"], sc["presentation_prs"]), ("a", "", ["p1"]))
        dd.validate(d)

    def test_a_new_cycle_replaces_the_old_showcase(self):
        d = doc()
        dd.record(d, "r1", START, status=None, article=self.ART, presentation_prs=["p1"])
        d["cycle"] = 2
        sc = dd.record(d, "r1", D("2026-12-11"), status=None, presentation_prs=["p9"])["showcase"]
        self.assertEqual((sc["cycle"], sc["article"], sc["presentation_prs"]), (2, None, ["p9"]))

    def test_validate_rejects_a_malformed_showcase(self):
        good = {"cycle": 1, "date": "2026-11-02", "article": None, "linkedin_personal": None,
                "linkedin_company": None, "presentation_prs": [], "note": ""}
        bad = [{**good, "linkedin_compnay": "x"}, {**good, "cycle": 0}, {**good, "cycle": True},
               {**good, "date": None}, {**good, "presentation_prs": "p1"}, {**good, "article": 5}, "nope"]
        for sc in bad:
            d = doc()
            d["repos"][0]["showcase"] = sc
            with self.assertRaises(ValueError, msg=sc):
                dd.validate(d)
        d = doc()
        d["repos"][0]["showcase"] = good
        dd.validate(d)

    def test_summary_counts_this_cycle_with_an_article(self):
        d = doc()
        for r in ("r1", "r2", "r3"):
            dd.record(d, r, START)
        dd.record(d, "r1", START, status=None, article=self.ART)
        dd.record(d, "r2", START, status=None, article="a2")
        dd.record(d, "r3", START, status=None, presentation_prs=["p3"])  # no article yet
        self.assertEqual(dd.summary(d, START)["showcased"], 2)
        dd.rollover(d)
        self.assertEqual(dd.summary(d, D("2026-11-04"))["showcased"], 0)
        self.assertEqual(d["repos"][0]["showcase"]["article"], self.ART)  # history carries over

    def test_slug(self):
        self.assertEqual(dd.showcase_slug("bamr87.github.io"), "quest-log-bamr87-github-io")
        self.assertEqual(dd.showcase_slug("zer0-CMS"), "quest-log-zer0-cms")
        self.assertEqual(dd.showcase_slug(".github"), "quest-log-github")
        self.assertEqual(dd.showcase_slug("it-journey"), "quest-log-it-journey")

    def test_missed_is_done_before_today_without_a_showcase(self):
        d = doc(n=4, days=6)
        dd.record(d, "r1", START)
        dd.record(d, "r2", START)
        dd.record(d, "r3", START)
        dd.record(d, "r2", START, status=None, article="a2")
        self.assertEqual(dd.showcase_missed(d, D("2026-11-01")), ["r1"])  # day 3: r3 is today's
        self.assertEqual(dd.showcase_missed(d, D("2026-11-04")), ["r1", "r3"])  # a catch-up day
        self.assertEqual(dd.showcase_missed(d, D("2026-10-29")), [])  # before the cycle

    def test_yaml_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            y, j = Path(tmp) / "t.yml", Path(tmp) / "t.json"
            d = doc()
            dd.record(d, "r1", START, status=None, article=self.ART, presentation_prs=["p1"])
            dd.save(d, y, j)
            back = dd.load(y)
            self.assertEqual(back["repos"][0]["showcase"], d["repos"][0]["showcase"])
            self.assertEqual(json.loads(j.read_text())["summary"]["showcased"], 1)


class Cli(unittest.TestCase):
    def test_showcase_flags(self):
        with tempfile.TemporaryDirectory() as tmp:
            y, j = Path(tmp) / "t.yml", Path(tmp) / "t.json"
            run = lambda *a: dd.main(list(a), data=y, json_path=j)  # noqa: E731
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(run("init", "--repo", "a.b", "--repo", "c", "--cycle-days", "3"), 0)
                self.assertEqual(run("record", "a.b", "--date", "2026-10-30"), 0)
                self.assertEqual(run("record", "a.b", "--date", "2026-11-02",
                                     "--article", "https://bamr87.github.io/posts/2026/11/02/quest-log-a-b/",
                                     "--linkedin-personal", "s/pr/1", "--linkedin-company", "b/pr/2",
                                     "--presentation-pr", "r/pr/3", "--showcase-note", "screenshots pending"), 0)
                # A showcase flag with a run flag is a run again: status defaults to done.
                self.assertEqual(run("record", "c", "--score", "60", "--presentation-pr", "r/pr/4"), 0)
                self.assertEqual(run("json", "--check"), 0)
            out = json.loads(j.read_text())
            a, c = out["repos"]
            self.assertEqual((a["status"], a["last_processed"]), ("done", "2026-10-30"))
            self.assertEqual((a["showcase"]["linkedin_company"], a["showcase"]["presentation_prs"],
                              a["showcase"]["note"]), ("b/pr/2", ["r/pr/3"], "screenshots pending"))
            self.assertEqual((c["status"], c["showcase"]["presentation_prs"]), ("done", ["r/pr/4"]))
            self.assertEqual(out["summary"]["showcased"], 1)
            buf = io.StringIO()
            with redirect_stdout(buf):
                run("today", "--date", "2026-10-31", "--json")
            t = json.loads(buf.getvalue())
            self.assertEqual((t["repo"], t["showcase_slug"], t["showcase_missed"]), ("c", "quest-log-c", []))
            buf = io.StringIO()
            with redirect_stdout(buf):
                run("today", "--date", "2026-11-05", "--json")  # cycle over
            t = json.loads(buf.getvalue())
            self.assertEqual((t["kind"], t["showcase_slug"]), ("cycle_over", None))


    def test_roundtrip_through_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            y, j = Path(tmp) / "t.yml", Path(tmp) / "t.json"
            run = lambda *a: dd.main(list(a), data=y, json_path=j)  # noqa: E731
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(run("init", "--repo", "a", "--repo", "b", "--cycle-days", "3"), 0)
                self.assertEqual(run("init", "--repo", "a"), 1)
                self.assertEqual(run("record", "b", "--pr", "u", "--date", "2026-10-31"), 0)
                self.assertEqual(run("record", "zzz"), 2)
                self.assertEqual(run("json", "--check"), 0)
            out = json.loads(j.read_text())
            self.assertEqual(out["summary"]["processed"], 1)
            self.assertEqual(out["repos"][1]["prs"], ["u"])
            buf = io.StringIO()
            with redirect_stdout(buf):
                run("today", "--date", "2026-10-31", "--json")
            self.assertEqual(json.loads(buf.getvalue())["repo"], "b")


class Committed(unittest.TestCase):
    def test_tracker_is_valid_and_projection_fresh(self):
        d = dd.load()
        self.assertEqual(d["cycle_start"], "2026-10-30")
        self.assertGreaterEqual(int(d["cycle_days"]), len(d["repos"]))
        self.assertIn("bamr87", [r["repo"] for r in d["repos"]])
        self.assertEqual(dd.JSON_OUT.read_text(encoding="utf-8"), dd.render_json(d) + "\n")


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False, verbosity=1).result.wasSuccessful() else 1)
