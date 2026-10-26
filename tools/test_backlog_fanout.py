#!/usr/bin/env python3
"""Fixture tests for tools/backlog_fanout.py + tools/fleet_activity.py.
Offline: GitHub is a stub, fanout.sh a fake runner. Run:
    python3 tools/test_backlog_fanout.py
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
import backlog_fanout as bf  # noqa: E402
import fleet_activity as fa  # noqa: E402

PRD = """# PRD
## 5. Requirements
- FR1: Registry agrees
- FR2: Served by a planned feature only
- FR7–FR9 (proposed): range
- NFR1: CI on 3.12
"""
FEATURES = """schema: features/v1
features:
  - id: HUB-001
    title: Shipped
    status: shipped
    prd: [FR1, FR7, FR8, FR9]
  - id: HUB-002
    title: Planned thing
    status: planned
    prd: [FR2]
    applies_to: [alpha]
"""
PROJECTS = """projects:
  - name: alpha
    submodule_path: projects/alpha
    repo_url: https://github.com/bamr87/alpha
    status: active
  - name: beta
    submodule_path: projects/beta
    repo_url: https://github.com/bamr87/beta
    status: active
  - name: skills
    submodule_path: projects/skills
    repo_url: https://github.com/microsoft/skills
    status: active
"""
CFG = """cadence: {cadence}
weekly_day: monday
apply: false
max_prs_per_run: 10
skip_labels: [agent:blocked]
requirements:
  NFR1: [beta]
"""


class StubGh:
    def __init__(self, issues, prs=None):
        self.issues, self.prs = issues, prs or {}

    def open_issues(self, repo):
        return self.issues

    def open_pr(self, slug, branch):
        return self.prs.get((slug, branch))

    def agents_md(self, slug):
        return "<!-- kit: sdlc v0.1.0 · x -->" if slug.endswith("alpha") else None


ISSUES = [
    {"number": 1, "title": "alpha CI: broken", "labels": [], "body": "see HUB-001", "url": "u1"},
    {"number": 2, "title": "Hub-only thing", "labels": [], "body": "", "url": "u2"},
    {"number": 3, "title": "beta blocked", "labels": [{"name": "agent:blocked"}], "body": "", "url": "u3"},
    {"number": 4, "title": "Fleet-wide", "labels": [], "body": "applies_to: all", "url": "u4"},
    {"number": 5, "title": "x", "labels": [{"name": "repo:beta"}], "body": "", "url": "u5"},
]


def make_hub(cadence="daily") -> Path:
    d = Path(tempfile.mkdtemp())
    (d / "_data").mkdir()
    (d / "features").mkdir()
    (d / "PRD.md").write_text(PRD)
    (d / "features" / "features.yml").write_text(FEATURES)
    (d / "_data" / "projects.yml").write_text(PROJECTS)
    (d / "_data" / "fleet.yml").write_text("hub: {owners: [bamr87]}\n")
    (d / "_data" / "backlog_fanout.yml").write_text(CFG.format(cadence=cadence))
    (d / "AGENTS.md").write_text("<!-- kit: sdlc v0.1.0 -->\n")
    return d


def args(hub, queue, **kw):
    base = dict(hub=str(hub), apply=False, cadence="config", force=False, max_prs=None,
                no_stamp=False, queue=str(queue))
    base.update(kw)
    return SimpleNamespace(**base)


def events(queue: Path) -> list[dict]:
    return [json.loads(l) for l in queue.read_text().splitlines() if l.strip()]


MONDAY = datetime(2026, 10, 26, tzinfo=timezone.utc)
SUNDAY = datetime(2026, 10, 25, tzinfo=timezone.utc)


class Parsing(unittest.TestCase):
    def test_prd_ranges_expand(self):
        r = bf.parse_prd(PRD)
        self.assertEqual(sorted(r), ["FR1", "FR2", "FR7", "FR8", "FR9", "NFR1"])

    def test_branch_is_stable(self):
        self.assertEqual(bf.branch_for({"id": "feat-HUB-002"}), "backlog/feat-hub-002")

    def test_standard_version(self):
        self.assertEqual(fa.standard_version("<!-- kit: sdlc v0.1.0 · A -->"), "sdlc v0.1.0")
        self.assertEqual(fa.standard_version(None), "unknown")


class DryRun(unittest.TestCase):
    def setUp(self):
        self.hub = make_hub()
        self.q = self.hub / "q.jsonl"

    def test_plan_and_mapping(self):
        gh = StubGh(ISSUES, prs={("bamr87/alpha", "backlog/issue-1"): {"number": 9, "url": "x"}})
        r = bf.run(args(self.hub, self.q), gh=gh, now=MONDAY)
        self.assertTrue(r["dry_run"])
        got = {(p["item"], p["repo"], p["action"]) for p in r["planned"]}
        self.assertIn(("issue-1", "bamr87/alpha", "update PR #9"), got)    # title + idempotent update
        self.assertIn(("issue-4", "bamr87/beta", "open PR"), got)          # applies_to: all
        self.assertNotIn("bamr87/skills", {p["repo"] for p in r["planned"]})  # external upstream
        self.assertIn(("issue-5", "bamr87/beta", "open PR"), got)          # repo: label
        self.assertIn(("feat-HUB-002", "bamr87/alpha", "open PR"), got)    # feature applies_to
        self.assertIn(("req-NFR1", "bamr87/beta", "open PR"), got)         # config mapping
        self.assertNotIn("req-FR1", {p["item"] for p in r["planned"]})     # served by shipped feature
        issue1 = next(p for p in r["planned"] if p["item"] == "issue-1")
        self.assertEqual(issue1["features"], ["HUB-001"])
        self.assertEqual(issue1["requirements"], ["FR1", "FR7", "FR8", "FR9"])
        reasons = {s["reason"] for s in r["skipped"]}
        self.assertIn("skip label agent:blocked", reasons)
        self.assertIn("unmapped: no applies_to target", reasons)
        evs = events(self.q)
        self.assertTrue(all(e["detail"]["dry_run"] for e in evs))
        self.assertIn("declined", {e["event_type"] for e in evs})
        self.assertEqual(r["activity"]["flush"], "kept-dry-run")
        alpha = next(e for e in evs if e["repo"] == "bamr87/alpha")
        self.assertEqual(alpha["standard_version"], "sdlc v0.1.0")
        for k in ("event_id", "ts", "bot_id", "task_ref", "run_id", "standard_source", "decision", "outcome"):
            self.assertIn(k, alpha)

    def test_cap(self):
        r = bf.run(args(self.hub, self.q, max_prs=1), gh=StubGh(ISSUES), now=MONDAY)
        self.assertEqual(len(r["planned"]), 1)
        self.assertTrue(any("cap" in s["reason"] for s in r["skipped"]))

    def test_weekly_cadence_skips_off_days(self):
        hub = make_hub("weekly")
        r = bf.run(args(hub, self.q), gh=StubGh(ISSUES), now=SUNDAY)
        self.assertTrue(r["cadence_skip"])
        self.assertEqual(r["planned"], [])
        r = bf.run(args(hub, self.q, force=True), gh=StubGh(ISSUES), now=SUNDAY)
        self.assertFalse(r["cadence_skip"])
        self.assertTrue(bf.run(args(hub, self.q), gh=StubGh(ISSUES), now=MONDAY)["planned"])


class Apply(unittest.TestCase):
    def test_failure_retries_and_reports(self):
        hub = make_hub()
        q = hub / "q.jsonl"
        calls = []

        def runner(argv, **kw):
            calls.append(kw["env"]["FANOUT_BRANCH"])
            ok = kw["env"]["FANOUT_BRANCH"] != "backlog/issue-1"
            return SimpleNamespace(returncode=0 if ok else 1, stdout="ok\n" if ok else "boom\n", stderr="")

        r = bf.run(args(hub, q, apply=True, max_prs=2), gh=StubGh(ISSUES[:1] + ISSUES[3:4]), now=MONDAY, runner=runner)
        self.assertEqual([f["item"] for f in r["failed"]], ["issue-1"])
        self.assertEqual(len(r["succeeded"]), 1)
        self.assertEqual(calls.count("backlog/issue-1"), 2)
        retries = [e for e in events(q) if e["event_type"] == "retry"]
        self.assertEqual(retries[0]["detail"]["attempt"], 1)
        self.assertEqual(retries[0]["detail"]["final_outcome"], "gave_up")


class GracefulDegradation(unittest.TestCase):
    def test_unwritable_queue_never_fails_the_routine(self):
        hub = make_hub()
        blocker = hub / "not-a-dir"
        blocker.write_text("file, so the queue's parent cannot be created")
        r = bf.run(args(hub, blocker / "sub" / "q.jsonl"), gh=StubGh(ISSUES), now=MONDAY)
        self.assertTrue(r["planned"])                  # the work still happened
        self.assertGreater(r["activity"]["errors"], 0)  # the loss is counted
        self.assertEqual(r["activity"]["emitted"], 0)

    def test_unreachable_endpoint_keeps_spool(self):
        q = Path(tempfile.mkdtemp()) / "q.jsonl"
        a = fa.Activity("t", queue=q, dry_run=False, endpoint="http://127.0.0.1:9/ingest")
        a.emit("finish", repo="r", task_ref="t", decision="d", outcome="success")
        self.assertEqual(a.flush(timeout=0.5), "kept-unavailable")
        self.assertEqual(len(events(q)), 1)
        self.assertEqual(fa.Activity("t", queue=q, dry_run=False, endpoint="").flush(), "kept-no-endpoint")

    def test_redaction_and_bound(self):
        q = Path(tempfile.mkdtemp()) / "q.jsonl"
        a = fa.Activity("t", queue=q, max_events=3)
        a.emit("finish", repo="r", task_ref="t", decision="token ghp_" + "a" * 30)
        self.assertNotIn("ghp_", q.read_text())
        for _ in range(5):
            a.emit("finish", repo="r", task_ref="t", decision="d")
        evs = events(q)
        self.assertEqual(len(evs), 3)
        self.assertIn("dropped", evs[-1]["detail"])


class SchemaConformance(unittest.TestCase):
    """Events match docs/prd/FLEET-ACTIVITY-LOG.md §3/§4 (HUB-024)."""
    COLUMNS = {"event_id", "ts", "bot_id", "repo", "task_ref", "run_id", "event_type", "standard_version",
               "standard_source", "decision", "outcome", "detail", "amendments"}

    def test_typed_events_and_columns(self):
        q = Path(tempfile.mkdtemp()) / "q.jsonl"
        a = fa.Activity("backlog-fanout", queue=q)
        a.declined(repo="r", task_ref="t", decision="skip", reason="bogus", reason_text="x")
        a.blocked_handoff(repo="r", task_ref="t", decision="wait", blocked_by="human", handoff_to="ops", why="approval")
        a.retry(repo="r", task_ref="t", decision="retry", attempt=1, max_attempts=2, cause="boom")
        a.emit("finish", repo="r", task_ref="t", decision="d",
               amendments=[{"amendment": "0001", "relation": "followed"}])
        evs = events(q)
        for e in evs:
            self.assertEqual(set(e), self.COLUMNS)
        d, b, r, f = (e["detail"] for e in evs)
        self.assertEqual(d["reason"], "other")
        self.assertIn("rule_ref", d)
        self.assertEqual(set(fa.TYPED_DETAIL["blocked_handoff"]) - set(b), set())
        self.assertEqual(b["resolution"], "open")
        self.assertEqual(r["final_outcome"], "pending")
        self.assertEqual(evs[3]["amendments"], [{"amendment": "0001", "repo": "bamr87/bamr87", "relation": "followed"}])


if __name__ == "__main__":
    unittest.main(verbosity=1)
