#!/usr/bin/env python3
"""Tests for tools/fleetcore/prqueue.py — the PR queue's model: collapsing superseded check runs,
the review gate as tools/weekly/closeout.py encodes it, who moves each pull request next, the
fan-out batches, the triage comment read as a hint, and plan identity.
Offline, no pytest:  python3 tools/test_fleetcore_prqueue.py"""
from __future__ import annotations

import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fleetcore import prqueue as pq  # noqa: E402

NOW = dt.datetime(2026, 11, 15, 12, 0, tzinfo=dt.timezone.utc)
FLEET = {
    "jev": {"allowed_authors": ["bamr87", "github-actions[bot]", "app/github-actions", "claude[bot]"]},
    "weekly": {"closeout": {"never_merge": ["o/noagents"]}},
    "pr_queue": {"merge": {"enabled": False}, "repo_rules": {"o/gitorio": {"dependabot_merge_label": "dep:merge-approved"}}},
}
CFG = pq.config(FLEET)


def run(name, conclusion, at, workflow="Verify", status="COMPLETED", run_id=1):
    return {"__typename": "CheckRun", "name": name, "status": status, "conclusion": conclusion, "completedAt": at,
            "startedAt": at, "checkSuite": {"workflowRun": {"databaseId": run_id, "event": "pull_request",
                                                             "workflow": {"name": workflow}}}}


def rec(**kw):
    base = {"id": "PR_1", "repo": "o/app", "number": 7, "title": "docs: fix a typo", "author": "bamr87", "bot": False,
            "labels": [], "created_at": "2026-11-10T00:00:00Z", "updated_at": "2026-11-14T00:00:00Z", "draft": False,
            "head": "docs/typo", "base": "main", "enrich": {"checks": "SUCCESS", "mergeable": "MERGEABLE", "merge_state": "CLEAN"}}
    base.update(kw)
    return base


def detail(**kw):
    base = {"read": True, "head_sha": "a" * 40, "mergeable": "MERGEABLE", "merge_state": "CLEAN", "review": None,
            "repo": {"merge_commit": True, "squash": True, "rebase": False, "private": False, "default_branch": "main"},
            "files": [{"path": "docs/guide.md", "change": "MODIFIED"}], "files_total": 1,
            "contexts": [run("verify", "SUCCESS", "2026-11-14T01:00:00Z")]}
    base.update(kw)
    return base


class CheckTests(unittest.TestCase):
    def test_cancelled_then_success_is_green(self):
        rows = pq.collapse_checks([run("verify", "CANCELLED", "2026-11-14T01:00:00Z", run_id=1),
                                   run("verify", "CANCELLED", "2026-11-14T01:01:00Z", run_id=2),
                                   run("verify", "SUCCESS", "2026-11-14T01:05:00Z", run_id=3)])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["state"], "green")
        self.assertEqual(rows[0]["superseded"], 2)
        self.assertEqual(rows[0]["run_id"], 3)
        s = pq.checks_summary(rows, "FAILURE")
        self.assertEqual(s["state"], "green")
        self.assertTrue(s["false_red"])

    def test_an_earlier_failure_still_counts(self):
        rows = pq.collapse_checks([run("verify", "FAILURE", "2026-11-14T01:00:00Z", run_id=1),
                                   run("verify", "SUCCESS", "2026-11-14T02:00:00Z", run_id=2)])
        s = pq.checks_summary(rows, "FAILURE")
        self.assertEqual(s["state"], "failing")
        self.assertFalse(s["false_red"])
        self.assertEqual(s["failing"], ["verify (an earlier run)"])
        ok, _ = pq.closeout.checks_green(pq.rollup_for_gate(rows))
        self.assertFalse(ok, "the gate never reads a failed-then-passed check as green")

    def test_success_then_cancelled_stays_cancelled(self):
        rows = pq.collapse_checks([run("verify", "SUCCESS", "2026-11-14T01:00:00Z"),
                                   run("verify", "CANCELLED", "2026-11-14T02:00:00Z")])
        self.assertEqual(pq.checks_summary(rows)["state"], "cancelled")

    def test_same_job_name_in_two_workflows_is_two_checks(self):
        rows = pq.collapse_checks([run("build", "FAILURE", "2026-11-14T01:00:00Z", workflow="CI"),
                                   run("build", "SUCCESS", "2026-11-14T02:00:00Z", workflow="Docs")])
        self.assertEqual(len(rows), 2)
        self.assertEqual(pq.checks_summary(rows)["state"], "failing")

    def test_status_contexts_and_gh_shape(self):
        rows = pq.collapse_checks([{"__typename": "StatusContext", "context": "ci/legacy", "state": "PENDING",
                                    "createdAt": "2026-11-14T01:00:00Z"},
                                   {"name": "lint", "workflowName": "CI", "status": "IN_PROGRESS", "conclusion": "",
                                    "startedAt": "2026-11-14T01:00:00Z", "completedAt": "0001-01-01T00:00:00Z",
                                    "detailsUrl": "https://github.com/o/app/actions/runs/42/job/9"}])
        self.assertEqual({r["state"] for r in rows}, {"pending"})
        lint = next(r for r in rows if r["name"] == "lint")
        self.assertEqual((lint["workflow"], lint["run_id"]), ("CI", 42))

    def test_no_checks_and_all_skipped(self):
        self.assertEqual(pq.checks_summary([])["state"], "none")
        self.assertEqual(pq.checks_summary(pq.collapse_checks([run("x", "SKIPPED", "2026-11-14T01:00:00Z")]))["state"], "skipped")


class GateTests(unittest.TestCase):
    def test_docs_change_by_trusted_author_is_ungated(self):
        g = pq.gate_of(rec(), detail(), CFG)
        self.assertFalse(g["gated"], g)

    def test_gated_path(self):
        g = pq.gate_of(rec(), detail(files=[{"path": ".github/workflows/ci.yml", "change": "MODIFIED"}]), CFG)
        self.assertTrue(g["gated"])
        self.assertIn(".github/workflows/ci.yml", g["reason"])

    def test_gate_label_never_merge_and_unread(self):
        self.assertTrue(pq.gate_of(rec(labels=["needs-amr"]), detail(), CFG)["gated"])
        self.assertTrue(pq.gate_of(rec(repo="o/noagents"), detail(), CFG)["gated"])
        self.assertTrue(pq.gate_of(rec(), {}, CFG)["gated"])

    def test_incomplete_file_list_is_gated(self):
        self.assertTrue(pq.gate_of(rec(), detail(files_total=140), CFG)["gated"])

    def test_gate_ignores_draft_and_red_checks(self):
        g = pq.gate_of(rec(draft=True), detail(contexts=[run("verify", "FAILURE", "2026-11-14T01:00:00Z")]), CFG)
        self.assertFalse(g["gated"], g)

    def test_untrusted_author_and_major_dependabot(self):
        self.assertTrue(pq.gate_of(rec(author="stranger"), detail(), CFG)["gated"])
        bump = rec(author="dependabot[bot]", bot=True, title="Bump rails from 7.1.0 to 8.0.1")
        self.assertIn("major", pq.gate_of(bump, detail(), CFG)["reason"])

    def test_agent_merge_needs_merge_commits(self):
        self.assertTrue(pq.agent_merge_of(rec(), detail(), CFG, pq.collapse_checks(detail()["contexts"]))["ok"])
        squash = detail(repo={"merge_commit": False, "squash": True, "private": False, "default_branch": "main"})
        self.assertFalse(pq.agent_merge_of(rec(), squash, CFG, pq.collapse_checks(squash["contexts"]))["ok"])
        self.assertEqual(pq.merge_method(squash["repo"]), "squash")
        self.assertEqual(pq.merge_method(detail()["repo"]), "merge")
        self.assertIsNone(pq.merge_method({}))


class NextTests(unittest.TestCase):
    def nxt(self, r, d):
        return pq.row(r, d, CFG, NOW, set())["next"]

    def test_rules_in_order(self):
        self.assertEqual(self.nxt(rec(), {})["who"], "loop")
        self.assertEqual(self.nxt(rec(draft=True), detail())["act"], "ready")
        self.assertEqual(self.nxt(rec(draft=True, updated_at="2026-10-01T00:00:00Z"), detail())["act"], "close")
        self.assertEqual(self.nxt(rec(), detail(mergeable="CONFLICTING"))["who"], "loop")
        self.assertEqual(self.nxt(rec(), detail(contexts=[run("v", "FAILURE", "2026-11-14T01:00:00Z")]))["act"], "agent")
        self.assertEqual(self.nxt(rec(), detail(contexts=[run("v", "CANCELLED", "2026-11-14T01:00:00Z")]))["act"], "rerun")
        self.assertEqual(self.nxt(rec(), detail(merge_state="BEHIND"))["act"], "update-branch")
        self.assertEqual(self.nxt(rec(), detail(review="CHANGES_REQUESTED"))["act"], "agent")
        gated = self.nxt(rec(labels=["needs-amr"]), detail())
        self.assertEqual((gated["who"], gated["act"]), ("amr", "merge"))
        self.assertEqual(self.nxt(rec(), detail())["who"], "agent")  # ungated, green, merge commits allowed

    def test_github_actions_pr_without_ci(self):
        n = self.nxt(rec(author="app/github-actions", bot=True), detail(contexts=[]))
        self.assertEqual(n["who"], "amr")
        self.assertIn("FLEET_TOKEN", n["action"])


class BuildTests(unittest.TestCase):
    def test_batches_kinds_and_counts(self):
        recs = [rec(id=f"PR_{i}", repo=f"o/r{i}", number=i + 1, head="chore/agent-context-kit") for i in range(3)]
        recs.append(rec(id="PR_d", repo="o/r9", number=9, author="dependabot[bot]", bot=True, head="dependabot/npm/x",
                        title="Bump x from 1.2.0 to 1.2.1", labels=["security"]))
        recs.append(rec(id="PR_e", repo="o/r8", number=9, head="dependabot/npm/x"))
        dets = {r["id"]: detail(files=[{"path": "CLAUDE.md", "change": "MODIFIED"}]) for r in recs[:3]}
        doc = pq.build(recs, dets, CFG, NOW)
        self.assertEqual([b["head"] for b in doc["batches"]], ["chore/agent-context-kit"])
        self.assertEqual(doc["batches"][0]["count"], 3)
        row0 = next(r for r in doc["rows"] if r["key"] == "o/r0#1")
        self.assertIn("batch", row0["kinds"])
        self.assertIn("harness", row0["kinds"])
        dep = next(r for r in doc["rows"] if r["key"] == "o/r9#9")
        self.assertEqual(set(dep["kinds"]) & {"dependabot", "security", "batch"}, {"dependabot", "security"})
        self.assertEqual(doc["counts"]["total"], 5)
        self.assertEqual(doc["counts"]["unread"], 2)
        self.assertEqual(sum(doc["counts"]["who"].values()), 5)

    def test_triage_comment_is_a_hint(self):
        body = ("**Next action:** Amr decides the guard policy, then merges.\nGated: it changes `.github/x`.\n"
                "Question: should it drop out? If yes: `gh pr merge 830 --repo bamr87/bamr87 --merge`.\n\n"
                "<sub>Triage by a Claude Code session.</sub>\n" + pq.TRIAGE_MARKER)
        t = pq.parse_triage(body)
        self.assertEqual(t["who_hint"], "amr")
        self.assertTrue(t["next_action"].startswith("Amr decides"))
        self.assertEqual(t["commands"], ["gh pr merge 830 --repo bamr87/bamr87 --merge"])
        self.assertIn("drop out", t["question"])
        self.assertIsNone(pq.parse_triage("no marker here"))
        r = pq.row(rec(), detail(triage={"body": body, "url": "u"}), CFG, NOW, set())
        self.assertEqual(r["triage"]["url"], "u")
        self.assertEqual(r["next"]["who"], "agent")  # the hint never changes the verdict


class ActionTests(unittest.TestCase):
    def test_switches_default_off(self):
        self.assertFalse(pq.action_enabled("merge", pq.config({}))[0])
        self.assertFalse(pq.action_enabled("close", pq.config({}))[0])
        self.assertTrue(pq.action_enabled("ready", pq.config({}))[0])
        on = pq.config({"pr_queue": {"merge": {"enabled": "yes"}}})
        self.assertFalse(on["merge"]["enabled"], "only a literal true turns merge on")

    def test_applies(self):
        r = pq.row(rec(repo="o/noagents"), detail(), CFG, NOW, set())
        self.assertFalse(pq.applies("merge", r, CFG)[0])
        self.assertTrue(pq.applies("comment", r, CFG)[0])
        self.assertFalse(pq.applies("ready", r, CFG)[0])

    def test_plan_id_is_stable_and_sensitive(self):
        items = [{"key": "o/a#1", "do": True, "op": {"argv": ["gh"]}, "head_sha": "a"}]
        self.assertEqual(pq.plan_id("ready", {}, items), pq.plan_id("ready", {}, [dict(items[0])]))
        self.assertNotEqual(pq.plan_id("ready", {}, items), pq.plan_id("ready", {}, [{**items[0], "head_sha": "b"}]))
        self.assertNotEqual(pq.plan_id("ready", {}, items), pq.plan_id("merge", {}, items))

    def test_comment_body(self):
        body = pq.comment_body(pq.row(rec(), detail(), CFG, NOW, set()), "see #12", "2026-11-15")
        self.assertTrue(body.startswith("**Next action:**"))
        self.assertIn(pq.TRIAGE_MARKER, body)
        self.assertTrue(body.rstrip().endswith(pq.SOURCE_SIGNATURE))
        self.assertIn("see #12", body)


class HubConfigTests(unittest.TestCase):
    def test_hub_block_validates(self):
        import yaml
        fleet = yaml.safe_load((Path(__file__).resolve().parent.parent / "_data" / "fleet.yml").read_text())
        cfg = pq.config(fleet)
        self.assertIn("pr_queue", fleet, "_data/fleet.yml has no pr_queue: block")
        self.assertFalse(cfg["merge"]["enabled"], "merge stays off until the amendment is ratified")
        self.assertFalse(cfg["close"]["enabled"], "close stays off until the amendment is ratified")
        allowed = {m for ids in (fleet.get("ai_models") or {}).get("allowed", {}).values() for m in ids or []}
        self.assertIn(cfg["agent"]["model"], allowed, "pr_queue.agent.model must be an exact id (§ 13.3)")
        self.assertIn("bamr87/lifehacker.dev", [str(x).lower() for x in cfg["closeout"]["never_merge"]])


if __name__ == "__main__":
    unittest.main()
