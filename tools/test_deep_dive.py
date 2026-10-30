#!/usr/bin/env python3
"""
Fixture tests for tools/deep_dive.py — the daily repo deep-dive tracker.

Guards what the routine and the /deep-dive page rely on: the rotation's day
math (scheduled, catch-up, before/after the cycle), recording a run (links
deduplicated, status validated), the GitHub refresh (counts grouped per repo
from one search per kind, no network), rollover, the committed tracker being
valid with every repo once, and the JSON projection being fresh.

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


class Cli(unittest.TestCase):
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
