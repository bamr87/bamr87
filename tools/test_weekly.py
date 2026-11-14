#!/usr/bin/env python3
"""Offline tests for tools/weekly/core.py, on real throwaway git repositories (a bare origin and a clone),
because what this tool must never get wrong is git's behaviour. Run: python3 tools/test_weekly.py
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.weekly import cli, core as weekly  # noqa: E402

NOW = datetime(2026, 11, 13, 5, 37, tzinfo=timezone.utc)
LATER = datetime.now(timezone.utc) + timedelta(days=2)
NOBODY = {"sessions": [], "paths": [], "session_ids": [], "fixed": True}
ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "t",
       "GIT_COMMITTER_EMAIL": "t@example.com", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}
FAKE_TOKEN = "ghp_" + "a1B2" * 9  # built here so no scanner mistakes this file for a leak
CFG = weekly.load_config({})


def g(repo, *args):
    r = subprocess.run(["git", "-C", str(repo), "-c", "protocol.file.allow=always", *args], capture_output=True,
                       text=True, env=ENV)
    if r.returncode != 0:
        raise AssertionError(f"git {args}: {r.stderr}")
    return r.stdout.strip()


def commit(repo, name="f.txt", text="x\n", message="c"):
    path = Path(repo) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    g(repo, "add", "-A")
    g(repo, "commit", "-q", "-m", message)
    return g(repo, "rev-parse", "HEAD")


class Repo(unittest.TestCase):
    """A clone of a bare origin, on main, with one pushed commit."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="weekly-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.origin = self.tmp / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.origin)], check=True, env=ENV)
        self.repo = self.tmp / "repo"
        subprocess.run(["git", "clone", "-q", str(self.origin), str(self.repo)], check=True, env=ENV, capture_output=True)
        g(self.repo, "checkout", "-q", "-b", "main")
        commit(self.repo, "README.md", "hello\n", "init")
        g(self.repo, "push", "-q", "-u", "origin", "main")

    def branch(self, name, *, file="work.txt", text="work\n"):
        g(self.repo, "checkout", "-q", "-b", name)
        tip = commit(self.repo, file, text, f"work on {name}")
        g(self.repo, "checkout", "-q", "main")
        return tip

    def classify(self, name, prs=()):
        tip = g(self.repo, "rev-parse", name)
        return weekly.classify_branch(self.repo, name, tip, "origin/main", list(prs), offline=True)


class MergeProof(Repo):
    def test_an_ancestor_of_main_is_merged(self):
        self.branch("feature/a")
        g(self.repo, "merge", "-q", "--ff-only", "feature/a")
        g(self.repo, "push", "-q", "origin", "main")
        self.assertEqual(self.classify("feature/a")["state"], "merged")

    def test_a_squash_with_the_same_patch_is_merged(self):
        self.branch("feature/a")
        commit(self.repo, "work.txt", "work\n", "squashed")
        g(self.repo, "push", "-q", "origin", "main")
        row = self.classify("feature/a")
        self.assertEqual((row["state"], row["proof"]), ("merged", "main already holds all of it"))

    def test_the_head_of_a_merged_pr_is_merged(self):
        tip = self.branch("feature/a")
        commit(self.repo, "work.txt", "conflicting\n", "main moved on")
        g(self.repo, "push", "-q", "origin", "main")
        pr = {"headRefName": "feature/a", "state": "MERGED", "headRefOid": tip, "number": 7, "baseRefName": "main"}
        self.assertEqual(self.classify("feature/a", [pr])["proof"], "tip is the head of merged PR #7")

    def test_a_reused_branch_name_with_new_commits_is_not_merged(self):
        old = self.branch("feature/a")
        g(self.repo, "checkout", "-q", "feature/a")
        commit(self.repo, "new.txt", "new work\n", "new work after the PR merged")
        g(self.repo, "checkout", "-q", "main")
        pr = {"headRefName": "feature/a", "state": "MERGED", "headRefOid": old, "number": 7, "baseRefName": "main"}
        self.assertEqual(self.classify("feature/a", [pr])["state"], "local-only")

    def test_a_gone_upstream_proves_nothing(self):
        self.branch("feature/a")
        g(self.repo, "push", "-q", "-u", "origin", "feature/a")
        g(self.repo, "push", "-q", "origin", "--delete", "feature/a")
        g(self.repo, "fetch", "-q", "--prune")
        self.assertEqual(self.classify("feature/a")["state"], "local-only")

    def test_an_open_pr_is_kept_whatever_else_is_true(self):
        tip = self.branch("feature/a")
        pr = {"headRefName": "feature/a", "state": "OPEN", "headRefOid": tip, "number": 9}
        self.assertEqual(self.classify("feature/a", [pr])["state"], "open-pr")

    def test_unmerged_work_on_a_remote_is_remote_held(self):
        self.branch("feature/a")
        g(self.repo, "push", "-q", "origin", "feature/a")
        self.assertEqual(self.classify("feature/a")["state"], "remote-held")


class Worktrees(Repo):
    def add(self, name="wt", *args):
        path = self.tmp / name
        g(self.repo, "worktree", "add", "-q", *args, str(path))
        return path

    def state(self, path, live=NOBODY, cfg=CFG, now=LATER):
        row = next(w for w in weekly.worktrees(self.repo) if w["worktree"] == weekly.real(path))
        return weekly.classify_worktree(row, cfg, live, now)

    def test_clean_idle_and_unused_is_dead(self):
        self.assertEqual(self.state(self.add("wt", "-b", "x"))["state"], "dead")

    def test_a_recent_worktree_is_left_alone(self):
        self.assertEqual(self.state(self.add("wt", "-b", "x"), now=datetime.now(timezone.utc))["state"], "recent")

    def test_uncommitted_work_blocks_removal(self):
        path = self.add("wt", "-b", "x")
        (path / "new.txt").write_text("unsaved\n")
        self.assertEqual(self.state(path)["state"], "dirty")

    def test_a_process_inside_makes_it_live_but_one_at_a_parent_does_not(self):
        path = self.add("wt", "-b", "x")
        inside = {**NOBODY, "paths": [weekly.real(path / "sub")]}
        parent = {**NOBODY, "paths": [weekly.real(self.tmp)]}
        self.assertEqual(self.state(path, inside)["state"], "live")
        self.assertEqual(self.state(path, parent)["state"], "dead")

    def test_a_live_sessions_scratchpad_is_live(self):
        path = self.add("abc-123/scratchpad/wt", "-b", "x")
        self.assertEqual(self.state(path, {**NOBODY, "session_ids": ["abc-123"]})["state"], "live")

    def test_a_live_worktree_still_reports_its_uncommitted_work(self):
        path = self.add("wt", "-b", "x")
        (path / "new.txt").write_text("in progress\n")
        row = self.state(path, {**NOBODY, "paths": [weekly.real(path)]})
        self.assertEqual((row["state"], row["files"]), ("live", 1))

    def test_another_tools_pool_is_foreign(self):
        path = self.add("pool/wt", "-b", "x")
        cfg = {**CFG, "foreign_roots": [str(self.tmp / "pool")]}
        self.assertEqual(self.state(path, cfg=cfg)["state"], "foreign")

    def test_an_ignored_env_blocks_removal_and_node_modules_does_not(self):
        commit(self.repo, ".gitignore", ".env\nnode_modules/\n", "ignore")
        path = self.add("wt", "-b", "x")
        (path / "node_modules").mkdir()
        (path / "node_modules" / "a.js").write_text("x\n")
        self.assertEqual(self.state(path)["state"], "dead")
        (path / ".env").write_text("A=1\n")
        self.assertEqual(self.state(path)["state"], "holds-ignored")

    def test_detached_commits_no_ref_holds_are_kept(self):
        path = self.add("wt", "--detach")
        commit(path, "lost.txt", "only here\n", "orphan")
        self.assertEqual(self.state(path)["state"], "unique-commits")

    def test_a_nested_submodules_work_blocks_removal(self):
        lib = self.tmp / "lib"
        subprocess.run(["git", "init", "-q", "-b", "main", str(lib)], check=True, env=ENV)
        commit(lib, "lib.txt", "lib\n", "lib")
        g(self.repo, "submodule", "add", "-q", str(lib), "projects/lib")
        g(self.repo, "commit", "-q", "-m", "add lib")
        path = self.add("wt", "-b", "x")
        g(path, "submodule", "update", "--init", "-q")
        row = self.state(path)  # clean, and still kept: a stash or ignored file in it would be lost
        self.assertEqual(row["state"], "has-submodules")

    def test_a_missing_directory_is_missing(self):
        path = self.add("wt", "-b", "x")
        shutil.rmtree(path)
        self.assertEqual(self.state(path)["state"], "missing")


class Tidy(Worktrees):
    def inv(self, live=NOBODY):
        row = {"name": "repo", "path": self.repo, "branch": "main"}
        return [weekly.inventory_repo(row, CFG, live, lambda _: [], True, LATER)]

    def go(self, inv, saved=None, live=NOBODY):
        plan = weekly.removals(inv)
        return plan, weekly.tidy(plan, saved if saved is not None else [{"repo": "repo", "ok": True}], CFG, live, LATER)

    def test_removes_merged_and_dead_and_keeps_everything_else(self):
        self.add("wt-merged", "-b", "merged-here")
        keep = self.branch("unmerged")
        self.branch("squashed", file="s.txt", text="s\n")
        commit(self.repo, "s.txt", "s\n", "squash")
        g(self.repo, "push", "-q", "origin", "main")
        _, done = self.go(self.inv())
        self.assertIn("repo:squashed", done["branches"])
        self.assertIn("repo:merged-here", done["branches"])
        self.assertEqual(g(self.repo, "rev-parse", "unmerged"), keep)
        self.assertFalse((self.tmp / "wt-merged").exists())

    def test_a_merged_branch_in_a_live_worktree_is_not_touched(self):
        path = self.add("wt", "-b", "merged-here")
        live = {**NOBODY, "paths": [weekly.real(path)]}
        plan = weekly.removals(self.inv(live))
        self.assertEqual((plan["branches"], plan["worktrees"]), ([], []))

    def test_a_worktree_that_became_dirty_after_the_inventory_survives(self):
        path = self.add("wt", "-b", "merged-here")
        inv = self.inv()
        (path / "new.txt").write_text("started working\n")
        _, done = self.go(inv)
        self.assertTrue(path.exists())
        self.assertIn("now dirty", done["skipped"][0])

    def test_a_branch_that_moved_after_the_inventory_survives(self):
        g(self.repo, "branch", "merged-here")
        inv = self.inv()
        g(self.repo, "checkout", "-q", "merged-here")
        commit(self.repo, "new.txt", "new\n", "new")
        g(self.repo, "checkout", "-q", "main")
        _, done = self.go(inv)
        self.assertIn("moved since the inventory", done["skipped"][0])

    def test_a_failed_save_stops_removal_in_that_repo(self):
        self.add("wt", "-b", "merged-here")
        _, done = self.go(self.inv(), saved=[{"repo": "repo", "ok": False}])
        self.assertEqual((done["branches"], done["worktrees"]), ([], []))
        self.assertTrue((self.tmp / "wt").exists())


class Save(Repo):
    def inv(self):
        row = {"name": "repo", "path": self.repo, "branch": "main"}
        return weekly.inventory_repo(row, CFG, NOBODY, lambda _: [], True, NOW)

    def test_the_bundle_restores_an_unmerged_branch_and_a_stash(self):
        tip = self.branch("feature/a")
        (self.repo / "README.md").write_text("stashed\n")
        g(self.repo, "stash", "push", "-q")
        stash = g(self.repo, "rev-parse", "stash@{0}")
        dest = self.tmp / "archive"
        [saved] = weekly.save([self.inv()], dest, CFG)
        self.assertTrue(saved["ok"], saved)
        fresh = self.tmp / "fresh"
        subprocess.run(["git", "clone", "-q", str(self.origin), str(fresh)], check=True, env=ENV, capture_output=True)
        g(fresh, "fetch", "-q", str(dest / "repo.bundle"), "refs/heads/feature/a:refs/heads/restored", "refs/weekly/keep-0:refs/heads/stash")
        self.assertEqual(g(fresh, "rev-parse", "restored"), tip)
        self.assertEqual(g(fresh, "rev-parse", "stash"), stash)
        self.assertEqual(g(self.repo, "for-each-ref", "refs/weekly"), "")

    def test_a_snapshot_leaves_the_working_tree_exactly_as_it_was(self):
        (self.repo / "README.md").write_text("edited\n")
        (self.repo / "note.txt").write_text("new file\n")
        before = g(self.repo, "status", "--porcelain")
        dest = self.tmp / "archive"
        [saved] = weekly.save([self.inv()], dest, CFG)
        self.assertEqual(g(self.repo, "status", "--porcelain"), before)
        snap = saved["snapshots"][0]
        self.assertEqual(snap["untracked"], 1)
        self.assertIn("edited", Path(snap["patch"]).read_text())

    def test_the_archive_is_private(self):
        dest = self.tmp / "archive"
        weekly.save([self.inv()], dest, CFG)
        self.assertEqual(dest.stat().st_mode & 0o777, 0o700)


class Wip(Repo):
    def row(self, branch="feature/a"):
        return {"path": str(self.repo), "branch": branch, "tip": g(self.repo, "rev-parse", branch), "blocked": []}

    def ref(self, branch="feature/a"):
        return f"refs/heads/wip/mac/{branch}"

    def test_a_push_mirrors_the_branch_under_wip_and_skips_ci(self):
        tip = self.branch("feature/a")
        self.assertEqual(weekly.push_wip(self.row(), CFG), "pushed")
        sent = g(self.origin, "rev-parse", self.ref())
        self.assertIn("[skip ci]", g(self.origin, "log", "-1", "--format=%s", sent))
        self.assertEqual(g(self.origin, "rev-parse", f"{sent}^"), tip)
        self.assertEqual(g(self.origin, "rev-parse", f"{sent}^{{tree}}"), g(self.repo, "rev-parse", f"{tip}^{{tree}}"))
        self.assertEqual(g(self.repo, "rev-parse", "feature/a"), tip)

    def test_it_uses_the_noreply_identity(self):
        self.branch("feature/a")
        weekly.push_wip(self.row(), CFG)
        self.assertEqual(g(self.origin, "log", "-1", "--format=%ae", self.ref()), CFG["commit"]["email"])

    def test_the_second_push_of_the_same_tip_is_a_no_op(self):
        self.branch("feature/a")
        weekly.push_wip(self.row(), CFG)
        sent = g(self.origin, "rev-parse", self.ref())
        self.assertEqual(weekly.push_wip(self.row(), CFG), "already saved")
        self.assertEqual(g(self.origin, "rev-parse", self.ref()), sent)

    def test_a_branch_that_advanced_updates_its_mirror(self):
        self.branch("feature/a")
        weekly.push_wip(self.row(), CFG)
        g(self.repo, "checkout", "-q", "feature/a")
        tip = commit(self.repo, "more.txt", "more\n", "more")
        g(self.repo, "checkout", "-q", "main")
        self.assertEqual(weekly.push_wip(self.row(), CFG), "pushed")
        self.assertEqual(g(self.origin, "rev-parse", self.ref() + "^"), tip)

    def test_a_branch_that_moved_since_the_review_is_not_pushed(self):
        self.branch("feature/a")
        row = self.row()
        g(self.repo, "checkout", "-q", "feature/a")
        commit(self.repo, "more.txt", "more\n", "unreviewed")
        g(self.repo, "checkout", "-q", "main")
        self.assertIn("moved since the review", weekly.push_wip(row, CFG))

    def test_nothing_outside_wip_is_ever_pushed(self):
        self.branch("feature/a")
        self.assertIn("outside wip/", weekly.push_wip(self.row(), {**CFG, "wip_prefix": "main"}))
        self.assertEqual(g(self.origin, "rev-parse", "main"), g(self.repo, "rev-parse", "origin/main"))

    def test_a_blocked_branch_is_held(self):
        self.branch("feature/a")
        self.assertIn("held", weekly.push_wip({**self.row(), "blocked": ["x"]}, CFG))

    def test_a_token_in_a_commit_is_found_and_the_value_never_reported(self):
        tip = self.branch("feature/a", file="config.txt", text=f"key={FAKE_TOKEN}\n")
        hits = weekly.scan_commits(self.repo, tip)
        self.assertEqual(hits, ["config.txt"])
        self.assertNotIn(FAKE_TOKEN, json.dumps(hits))

    def test_secret_shaped_file_names_are_found_and_examples_are_not(self):
        tip = self.branch("feature/a", file=".env", text="A=1\n")
        self.assertEqual(len(weekly.scan_commits(self.repo, tip)), 1)
        tip = self.branch("feature/b", file=".env.example", text="A=\n")
        self.assertEqual(weekly.scan_commits(self.repo, tip), [])

    def test_a_clean_branch_is_not_flagged(self):
        self.assertEqual(weekly.scan_commits(self.repo, self.branch("feature/a")), [])


class Modes(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="weekly-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def past_run(self, name, **fields):
        folder = self.tmp / name
        folder.mkdir()
        (folder / "run.json").write_text(json.dumps({"scheduled": True, "finished": "x", "errors": [], **fields}))

    def mode(self, **flags):
        return weekly.decide_mode(argparse.Namespace(**flags), self.tmp, CFG)

    def test_a_manual_run_is_a_preview_and_apply_is_active(self):
        self.assertEqual(self.mode(scheduled=False, apply=False), "preview")
        self.assertEqual(self.mode(scheduled=False, apply=True), "active")

    def test_the_first_two_scheduled_runs_are_report_only(self):
        self.assertEqual(self.mode(scheduled=True, apply=False), "report-only")
        self.past_run("20261107T0-2026-W46")
        self.assertEqual(self.mode(scheduled=True, apply=False), "report-only")
        self.past_run("20261114T0-2026-W47")
        self.assertEqual(self.mode(scheduled=True, apply=False), "active")

    def test_a_run_with_errors_does_not_count_towards_going_active(self):
        self.past_run("20261107T0-2026-W46", errors=["boom"])
        self.past_run("20261114T0-2026-W47", errors=["boom"])
        self.assertEqual(self.mode(scheduled=True, apply=False), "report-only")

    def test_a_preview_does_not_count_either(self):
        self.past_run("20261107T0-2026-W46", scheduled=False)
        self.past_run("20261114T0-2026-W47", scheduled=False)
        self.assertEqual(self.mode(scheduled=True, apply=False), "report-only")

    def test_the_switch_most_restrictive_level_wins(self):
        on = {"global": {"state": "on"}, "groups": {"g": {"state": "on"}}, "loops": {weekly.SWITCH_KEY: {"group": "g", "state": "on"}}}
        self.assertIsNone(weekly.switched_off({"switches": on}))
        for off in ({**on, "global": {"state": "off"}}, {**on, "groups": {"g": {"state": "off"}}},
                    {**on, "loops": {weekly.SWITCH_KEY: {"group": "g", "state": "off", "reason": "away"}}}):
            self.assertIn("off", weekly.switched_off({"switches": off}))

    def test_the_config_gate_stops_it_too(self):
        self.assertIn("weekly.enabled", weekly.switched_off({"weekly": {"enabled": False}}))

    def test_a_friday_night_plans_the_coming_week(self):
        self.assertEqual(weekly.plan_week(datetime(2026, 11, 14, 5, 37, tzinfo=timezone.utc)), "2026-W47")

    def test_a_second_run_cannot_start_while_one_holds_the_lock(self):
        with weekly.lock(self.tmp):
            with self.assertRaises(SystemExit):
                with weekly.lock(self.tmp):
                    self.fail("the lock did not hold")
        self.assertFalse((self.tmp / ".lock").exists())

    def test_a_stale_lock_is_taken_over(self):
        (self.tmp / ".lock").write_text("999999")
        with weekly.lock(self.tmp):
            pass


def item(number, labels=(), kind="issue", created="2026-10-01T00:00:00Z", repo="o/r"):
    return {"repo": repo, "number": number, "title": f"item {number}", "labels": list(labels), "kind": kind,
            "created_at": created, "url": f"https://x/{number}"}


class Ranking(unittest.TestCase):
    def rank(self, items, prs=None, queue=None, board=(), cfg=CFG, repo=None):
        model = {"repos": [{"items": items, "prs": prs or {}, **(repo or {})}], "board": {"items": list(board)}}
        return weekly.rank(model, queue or {}, cfg, ["Hold", "Blocked", "Needs Amr", "Won't do"], NOW)

    def refs(self, plan, lane):
        return [r["ref"] for r in plan["lanes"][lane]]

    def test_priority_then_age_then_ref_and_the_same_every_time(self):
        items = [item(1, ["P2"]), item(2, ["P0"]), item(3, ["P2"], created="2026-11-01T00:00:00Z"), item(4)]
        plan = self.rank(items)
        self.assertEqual(self.refs(plan, "do"), ["o/r#2", "o/r#1", "o/r#3", "o/r#4"])
        self.assertEqual(plan, self.rank(list(reversed(items))))

    def test_a_pin_beats_everything_and_the_humans_order_holds(self):
        q = {"order": ["issue:o/r#3", "issue:o/r#1"]}
        plan = self.rank([item(1), item(2, ["P0"]), item(3)], queue=q)
        self.assertEqual(self.refs(plan, "do")[:3], ["o/r#3", "o/r#1", "o/r#2"])

    def test_the_lanes(self):
        prs = {"5": {"mergeable": "MERGEABLE", "ci": "SUCCESS"}, "6": {"mergeable": "CONFLICTING"},
               "7": {"mergeable": "MERGEABLE", "ci": "FAILURE"}, "8": {"draft": True}}
        items = [item(5, kind="pr"), item(6, kind="pr"), item(7, kind="pr"), item(8, kind="pr"), item(9, ["needs-amr"]), item(10)]
        plan = self.rank(items, prs=prs)
        self.assertEqual(self.refs(plan, "finish"), ["o/r#5"])
        self.assertCountEqual(self.refs(plan, "unblock"), ["o/r#6", "o/r#7"])
        self.assertEqual(self.refs(plan, "decide"), ["o/r#9"])
        self.assertCountEqual(self.refs(plan, "do"), ["o/r#8", "o/r#10"])

    def test_held_items_and_epics_are_left_out_and_counted(self):
        board = [{"repo": "o/r", "number": 1, "fields": {"Status": "Hold"}}]
        plan = self.rank([item(1), item(2, ["epic"]), item(3)], board=board)
        self.assertEqual((self.refs(plan, "do"), plan["held"], plan["ranked"]), (["o/r#3"], 1, 1))

    def test_a_private_or_archived_repo_never_reaches_the_plan(self):
        self.assertEqual(self.rank([item(1)], repo={"private": True})["ranked"], 0)
        self.assertEqual(self.rank([item(1)], repo={"archived": True})["ranked"], 0)

    def test_capacity_caps_a_lane_but_everything_is_still_ranked(self):
        plan = self.rank([item(n) for n in range(1, 21)])
        self.assertEqual(len(plan["lanes"]["do"]), CFG["plan"]["capacity"]["do"])
        self.assertEqual(plan["by_lane"]["do"], 20)

    def test_the_project_field_wins_over_a_label(self):
        board = [{"repo": "o/r", "number": 1, "fields": {"Priority": "P0"}}]
        self.assertEqual(self.rank([item(1, ["P3"]), item(2, ["P1"])], board=board)["lanes"]["do"][0]["ref"], "o/r#1")

    def test_the_proposal_keeps_human_pins_first_and_drops_closed_items(self):
        doc = {"order": ["issue:o/r#1", "issue:o/r#99", "roadmap:FF-0001"], "priority": {}, "notes": {}}
        plan = self.rank([item(1), item(2, ["P0"])])
        result = weekly.proposed_queue(doc, plan, {"issue:o/r#1", "issue:o/r#2"}, set(doc["order"]), "2026-W47", "2026-11-14")
        self.assertEqual(result["order"], ["issue:o/r#1", "roadmap:FF-0001", "issue:o/r#2"])
        self.assertEqual(result["notes"], {"issue:o/r#2": "Weekly plan 2026-W47"})


class Recap(unittest.TestCase):
    def test_a_chronicle_is_a_draft_and_secrets_never_reach_it(self):
        text = weekly.render_chronicle("2026-11-06", {"o/r": [f"fix: rotate {FAKE_TOKEN}", "feat: a thing (#12)"]}, 8)
        self.assertRegex(text, r"(?m)^draft: true$")
        self.assertNotIn(FAKE_TOKEN, text)
        self.assertIn("[REDACTED]", text)

    def test_a_long_day_is_summarized_not_dumped(self):
        text = weekly.render_chronicle("2026-11-06", {"o/r": [f"fix: {n}" for n in range(20)]}, 8)
        self.assertIn("and 12 more", text)
        self.assertNotIn("fix: 19", text)

    def test_what_shipped_leads_with_features_then_fixes(self):
        rows = ["docs: a", "chore: b", "fix(x): c", "feat(y): d", "feat!: e"]
        self.assertEqual(weekly.repo_lines(rows, 3), ["- feat(y): d", "- feat!: e", "- fix(x): c", "- and 2 more"])

    def test_totals_count_prs_from_both_merge_styles_once(self):
        days = {"d": {"o/r": ["feat: a (#1)", "Merge pull request #2 from x/y", "fix: b"]}}
        self.assertEqual(weekly.totals(days), {"commits": 2, "prs_merged": 2, "repos": 1, "days": 1})

    def retro(self):
        return weekly.render_retro("2026-W47", "2026-11-13", {"d": {"o/r": ["feat: a"]}}, {}, {}, None, 8)

    def test_publishing_removes_the_draft_flag_and_an_unwritten_section(self):
        text = weekly.finalize_post(self.retro(), keep_draft=False)
        self.assertNotRegex(text, r"(?m)^draft: true$")
        self.assertNotIn("In my own words", text)

    def test_written_notes_survive_publishing(self):
        text = self.retro().replace("<!-- weekly: your notes go here; an empty section is removed on publish -->", "A good week.")
        self.assertIn("A good week.", weekly.finalize_post(text, keep_draft=False))

    def test_keep_drafts_leaves_the_flag(self):
        self.assertRegex(weekly.finalize_post(self.retro(), keep_draft=True), r"(?m)^draft: true$")


class EndToEnd(Repo):
    """A whole run against a small hub: the promise is what it does NOT change."""

    def setUp(self):
        super().setUp()
        for rel, text in (("_data/fleet.yml", "switches: {}\n"), ("_data/work_queue.yml", "schema: work-queue/v1\norder: []\npriority: {}\nnotes: {}\n"),
                          ("pages/posts/2026-01-01-old.md", "---\ntitle: old\ndraft: true\n---\n\nold\n")):
            path = self.repo / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        g(self.repo, "add", "-A")
        g(self.repo, "commit", "-q", "-m", "feat: the hub (#1)")
        g(self.repo, "push", "-q", "origin", "main")
        self.unmerged = self.branch("feature/unmerged")
        g(self.repo, "branch", "merged-branch")
        (self.repo / "README.md").write_text("uncommitted\n")
        self.state = self.tmp / "state"
        self.archive = self.tmp / "archive"

    def fingerprint(self):
        return (g(self.repo, "for-each-ref"), g(self.repo, "status", "--porcelain"), g(self.repo, "worktree", "list"),
                g(self.repo, "rev-parse", "HEAD"), g(self.origin, "for-each-ref"))

    def go(self, **flags):
        args = argparse.Namespace(scheduled=False, apply=False, offline=True, no_plan=True, **flags)
        with mock.patch.object(weekly, "refresh", return_value={"ok": True, "notes": []}) as refresh, \
                mock.patch.object(weekly, "notify"), mock.patch("builtins.print"):
            code = weekly.cmd_run(args, self.repo, self.state, self.archive, live=NOBODY, prs_for=lambda _: [],
                                  now=datetime.now(timezone.utc))
        return code, refresh

    def latest(self):
        return weekly.run_dirs(self.state)[-1]

    def test_a_preview_changes_nothing_and_still_saves_and_drafts(self):
        before = self.fingerprint()
        code, refresh = self.go()
        self.assertEqual(code, 0)
        self.assertEqual(self.fingerprint(), before)
        refresh.assert_not_called()
        rec = weekly.read_run(self.latest())
        self.assertEqual([w["branch"] for w in rec["wip"]], ["feature/unmerged"])
        self.assertEqual([b["branch"] for b in rec["removal"]["branches"]], ["merged-branch"])
        self.assertEqual(rec["drafts"], ["2026-01-01-old.md"])
        self.assertTrue(list(self.archive.rglob("hub.bundle")))
        self.assertTrue(list(self.archive.rglob("hub--checkout-*.patch")))
        self.assertTrue(any(p.endswith("-weekly-retro.md") for p in rec["posts"]))
        self.assertIn("Would remove", (self.latest() / "report.md").read_text())

    def test_an_active_run_tidies_and_leaves_unmerged_and_uncommitted_work(self):
        args = argparse.Namespace(scheduled=False, apply=True, offline=True, no_plan=True)
        with mock.patch.object(weekly, "refresh", return_value={"ok": True, "notes": []}) as refresh, \
                mock.patch.object(weekly, "notify"), mock.patch("builtins.print"):
            weekly.cmd_run(args, self.repo, self.state, self.archive, live=NOBODY, prs_for=lambda _: [], now=LATER)
        refresh.assert_called_once()
        self.assertNotIn("merged-branch", g(self.repo, "branch", "--list"))
        self.assertEqual(g(self.repo, "rev-parse", "feature/unmerged"), self.unmerged)
        self.assertIn("README.md", g(self.repo, "status", "--porcelain"))

    def test_a_scheduled_run_stops_at_the_switch_before_touching_anything(self):
        (self.repo / "_data/fleet.yml").write_text(
            "switches:\n  global: {state: 'off', reason: away}\n")
        args = argparse.Namespace(scheduled=True, apply=False, offline=True, no_plan=True)
        with mock.patch("builtins.print"):
            code = weekly.cmd_run(args, self.repo, self.state, self.archive, live=NOBODY, prs_for=lambda _: [])
        self.assertEqual(code, 3)
        self.assertFalse(self.state.exists())

    def confirm(self, **flags):
        args = argparse.Namespace(apply=False, keep_drafts=False, publish=[], allow=[], **flags)
        with mock.patch("builtins.print"):
            return weekly.cmd_confirm(args, self.repo, self.state)

    def test_confirm_without_apply_writes_nothing_anywhere(self):
        self.go()
        before = self.fingerprint()
        with mock.patch.object(weekly, "push_wip") as push, mock.patch.object(weekly, "apply_board") as board, \
                mock.patch.object(weekly, "open_weekly_pr") as pr:
            self.assertEqual(self.confirm(), 0)
        push.assert_not_called(), board.assert_not_called(), pr.assert_not_called()
        self.assertEqual(self.fingerprint(), before)
        self.assertFalse((self.latest() / "confirm.json").exists())

    def test_confirm_refuses_a_stale_run(self):
        self.go()
        args = argparse.Namespace(apply=True, keep_drafts=False, publish=[], allow=[])
        with mock.patch("builtins.print"), mock.patch.object(weekly, "push_wip") as push:
            code = weekly.cmd_confirm(args, self.repo, self.state, now=datetime.now(timezone.utc) + timedelta(days=30))
        self.assertEqual(code, 1)
        push.assert_not_called()

    def test_the_weekly_pr_publishes_the_posts_and_an_older_draft_only_when_named(self):
        self.go()
        rec, cfg = weekly.read_run(self.latest()), weekly.load_config({})
        files = weekly.weekly_pr_files(self.repo, rec, self.latest(), cfg, False, [])
        retro = next(k for k in files if k.endswith("-weekly-retro.md"))
        self.assertNotIn("draft: true", files[retro])
        self.assertNotIn("pages/posts/2026-01-01-old.md", files)
        self.assertIn(weekly.SNAPSHOT, files)
        named = weekly.weekly_pr_files(self.repo, rec, self.latest(), cfg, False, ["2026-01-01-old.md"])
        self.assertNotIn("draft: true", named["pages/posts/2026-01-01-old.md"])

    def test_keep_drafts_lands_the_posts_as_drafts(self):
        self.go()
        rec = weekly.read_run(self.latest())
        files = weekly.weekly_pr_files(self.repo, rec, self.latest(), weekly.load_config({}), True, [])
        retro = next(k for k in files if k.endswith("-weekly-retro.md"))
        self.assertIn("draft: true", files[retro])

    def test_the_public_snapshot_keeps_history_and_holds_no_local_paths(self):
        self.go()
        rec = weekly.read_run(self.latest())
        doc = weekly.snapshot_doc(rec, {"history": [{"week": "2026-W01"}]}, weekly.load_config({}))
        self.assertEqual(doc["schema"], weekly.PLAN_SCHEMA)
        self.assertEqual(len(doc["history"]), 2)
        self.assertNotIn(str(self.tmp), json.dumps(doc, default=str))


def failing(verb, real_git=weekly.git):
    """weekly.git with one git verb broken, as a timeout or a corrupt index would break it."""
    def fake(repo, *args, **kwargs):
        if verb in args:
            return subprocess.CompletedProcess(args, 128, "", "boom")
        return real_git(repo, *args, **kwargs)
    return fake


class ReviewFindings(Worktrees):
    """Each test reproduces a defect the independent review proved on throwaway repos."""

    def inv(self, live=NOBODY):
        row = {"name": "repo", "path": self.repo, "branch": "main"}
        return weekly.inventory_repo(row, CFG, live, lambda _: [], True, LATER)

    # -- loss
    def test_kilo_is_not_regenerable_so_its_worktrees_survive_a_dead_parent(self):
        commit(self.repo, ".gitignore", ".kilo/\n", "ignore")
        parent = self.add("wt", "-b", "x")
        inner = parent / ".kilo" / "worktrees" / "inner"
        g(self.repo, "worktree", "add", "-q", "--detach", str(inner))
        (inner / ".env").write_text("SECRET=1\n")
        self.assertEqual(self.state(parent)["state"], "holds-ignored")

    def test_a_worktree_nested_under_a_regenerable_path_still_blocks_its_parent(self):
        commit(self.repo, ".gitignore", "node_modules/\n", "ignore")
        parent = self.add("wt", "-b", "x")
        g(self.repo, "worktree", "add", "-q", "--detach", str(parent / "node_modules" / "inner"))
        row = next(w for w in self.inv()["worktrees"] if w["path"] == weekly.real(parent))
        self.assertEqual(row["state"], "holds-worktree")

    def test_a_missing_worktree_is_never_pruned_and_its_commits_are_bundled(self):
        path = self.add("wt", "--detach")
        sha = commit(path, "lost.txt", "only here\n", "orphan")
        shutil.rmtree(path)
        inv = self.inv()
        self.assertEqual(weekly.removals([inv])["worktrees"], [])
        dest = self.tmp / "archive"
        [saved] = weekly.save([inv], dest, CFG)
        self.assertTrue(saved["ok"], saved)
        weekly.tidy(weekly.removals([inv]), [saved], CFG, NOBODY, LATER)
        self.assertIn("wt", g(self.repo, "worktree", "list"))
        fresh = self.tmp / "fresh"
        subprocess.run(["git", "clone", "-q", str(self.origin), str(fresh)], check=True, env=ENV, capture_output=True)
        g(fresh, "fetch", "-q", str(dest / "repo.bundle"), "refs/weekly/keep-0:refs/heads/found")
        self.assertEqual(g(fresh, "rev-parse", "found"), sha)

    def test_detached_commits_in_the_checkout_are_bundled(self):
        g(self.repo, "checkout", "-q", "--detach")
        sha = commit(self.repo, "lost.txt", "only here\n", "orphan")
        inv = self.inv()
        self.assertEqual(inv["detached_unique"], 1)
        dest = self.tmp / "archive"
        weekly.save([inv], dest, CFG)
        self.assertIn(sha, g(self.repo, "bundle", "list-heads", str(dest / "repo.bundle")))

    # -- fail closed
    def test_a_failed_status_keeps_the_worktree(self):
        path = self.add("wt", "-b", "x")
        with mock.patch.object(weekly, "git", failing("status")):
            self.assertEqual(self.state(path)["state"], "unknown")

    def test_a_failed_rev_list_keeps_the_worktree(self):
        path = self.add("wt", "--detach")
        with mock.patch.object(weekly, "git", failing("rev-list")):
            self.assertEqual(self.state(path)["state"], "unknown")

    def test_a_failed_ignored_check_keeps_the_worktree(self):
        path = self.add("wt", "-b", "x")
        real_git = weekly.git

        def fake(repo, *args, **kwargs):
            if "--ignored" in args:
                return subprocess.CompletedProcess(args, 128, "", "boom")
            return real_git(repo, *args, **kwargs)
        with mock.patch.object(weekly, "git", fake):
            self.assertEqual(self.state(path)["state"], "unknown")

    def test_a_repo_that_cannot_be_read_is_reported_and_touches_nothing(self):
        self.branch("feature/a")
        with mock.patch.object(weekly, "git", failing("rev-list")):
            inv = self.inv()
        self.assertEqual(inv["state"], "unreadable")
        self.assertEqual(weekly.removals([inv]), {"worktrees": [], "branches": []})

    def test_if_lsof_fails_nothing_is_removed(self):
        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 1, "", "boom")
        with mock.patch.object(weekly, "run", fake_run), mock.patch.object(weekly, "expand", lambda _: self.tmp / "no-sessions"):
            live = weekly.live_state()
        self.assertIn("lsof", live["degraded"])
        path = self.add("wt", "-b", "merged-here")
        inv = self.inv()
        done = weekly.tidy(weekly.removals([inv]), [{"repo": "repo", "ok": True}], CFG, {**live, "fixed": True}, LATER)
        self.assertTrue(path.exists())
        self.assertEqual((done["worktrees"], done["branches"]), ([], []))
        self.assertIn("could not read what is in use", done["skipped"][0])

    def test_a_failed_fetch_is_recorded(self):
        g(self.repo, "remote", "set-url", "origin", str(self.tmp / "gone.git"))
        row = {"name": "repo", "path": self.repo, "branch": "main"}
        self.assertTrue(weekly.inventory_repo(row, CFG, NOBODY, lambda _: [], False, LATER)["fetch_failed"])

    # -- proof
    def test_a_whitespace_only_difference_is_not_merged(self):
        (self.repo / "run.sh").write_text("rm(ab)\n")
        g(self.repo, "add", "-A"), g(self.repo, "commit", "-q", "-m", "base"), g(self.repo, "push", "-q", "origin", "main")
        g(self.repo, "checkout", "-q", "-b", "feature/a")
        commit(self.repo, "run.sh", "rm(a b)\n", "two arguments")
        g(self.repo, "checkout", "-q", "main")
        commit(self.repo, "run.sh", "rm(a  b)\n", "looks the same to a patch-id")
        g(self.repo, "push", "-q", "origin", "main")
        self.assertEqual(self.classify("feature/a")["state"], "local-only")

    def test_a_merge_only_branch_with_real_content_is_not_merged(self):
        commit(self.repo, "next.txt", "next\n", "next")
        g(self.repo, "push", "-q", "origin", "main")
        g(self.repo, "checkout", "-q", "-b", "m", "HEAD~1")
        g(self.repo, "merge", "-q", "--no-ff", "--no-commit", "main")
        (self.repo / "extra.txt").write_text("only in the merge\n")
        g(self.repo, "add", "-A"), g(self.repo, "commit", "-q", "-m", "merge with real content")
        g(self.repo, "checkout", "-q", "main")
        self.assertEqual(self.classify("m")["state"], "local-only")

    def test_a_branch_that_added_and_removed_work_is_not_merged(self):
        g(self.repo, "checkout", "-q", "-b", "m")
        commit(self.repo, "idea.txt", "an idea\n", "try an idea")
        g(self.repo, "rm", "-q", "idea.txt"), g(self.repo, "commit", "-q", "-m", "take it out")
        g(self.repo, "checkout", "-q", "main")
        self.assertEqual(self.classify("m")["state"], "local-only")

    def test_a_multi_commit_squash_needs_its_pr_as_proof(self):
        g(self.repo, "checkout", "-q", "-b", "m")
        commit(self.repo, "a.txt", "a\n", "a")
        tip = commit(self.repo, "b.txt", "b\n", "b")
        g(self.repo, "checkout", "-q", "main")
        (self.repo / "a.txt").write_text("a\n")
        commit(self.repo, "b.txt", "b\n", "squash")
        g(self.repo, "push", "-q", "origin", "main")
        self.assertEqual(self.classify("m")["state"], "local-only")
        pr = {"headRefName": "m", "state": "MERGED", "headRefOid": tip, "number": 3, "baseRefName": "main"}
        self.assertEqual(self.classify("m", [pr])["state"], "merged")

    def test_a_pr_merged_into_another_branch_proves_nothing(self):
        tip = self.branch("feature/a")
        pr = {"headRefName": "feature/a", "state": "MERGED", "headRefOid": tip, "number": 7, "baseRefName": "develop"}
        self.assertEqual(self.classify("feature/a", [pr])["state"], "local-only")

    # -- save
    def test_a_failed_bundle_still_keeps_the_uncommitted_work(self):
        self.branch("feature/a")
        (self.repo / "README.md").write_text("edited\n")
        inv = self.inv()
        g(self.repo, "branch", "-D", "feature/a")  # deleted mid-run
        [saved] = weekly.save([inv], self.tmp / "archive", CFG)
        self.assertFalse(saved["ok"])
        self.assertTrue(saved["snapshots"][0]["patch"])

    def test_an_unreadable_file_does_not_stop_the_save(self):
        secret = self.repo / "locked.txt"
        secret.write_text("x\n")
        secret.chmod(0)
        self.addCleanup(secret.chmod, 0o600)
        [saved] = weekly.save([self.inv()], self.tmp / "archive", CFG)
        self.assertTrue(saved["ok"], saved)
        self.assertEqual(saved["snapshots"][0]["skipped"], ["locked.txt"])

    def test_same_named_worktrees_do_not_overwrite_each_others_snapshot(self):
        a, b = self.add("one/wt", "-b", "x"), self.add("two/wt", "-b", "y")
        (a / "a.txt").write_text("a\n")
        (b / "b.txt").write_text("b\n")
        [saved] = weekly.save([self.inv()], self.tmp / "archive", CFG)
        self.assertEqual(len({s["label"] for s in saved["snapshots"]}), 2)

    def test_a_tag_with_a_branchs_name_does_not_break_the_repo(self):
        self.branch("feature/a")
        g(self.repo, "tag", "feature/a", "main")
        inv = self.inv()
        self.assertEqual(inv["state"], "ok")
        self.assertEqual([b["name"] for b in inv["branches"]], ["feature/a"])
        [saved] = weekly.save([inv], self.tmp / "archive", CFG)
        self.assertTrue(saved["ok"], saved)

    def test_an_open_pr_with_unpushed_commits_is_still_saved_off_the_mac(self):
        tip = self.branch("feature/a")
        prs = [{"headRefName": "feature/a", "state": "OPEN", "headRefOid": tip, "number": 9}]
        row = {"name": "repo", "path": self.repo, "branch": "main"}
        inv = weekly.inventory_repo(row, CFG, NOBODY, lambda _: prs, False, LATER)
        self.assertEqual([w["branch"] for w in weekly.wip_candidates([inv])], ["feature/a"])


class Scan(Repo):
    def hits(self, tip):
        return weekly.scan_commits(self.repo, tip)

    def test_a_token_in_a_commit_message(self):
        g(self.repo, "checkout", "-q", "-b", "a")
        tip = commit(self.repo, "f.txt", "x\n", f"oops {FAKE_TOKEN}")
        self.assertEqual(len(self.hits(tip)), 1)

    def test_a_binary_key_store_by_name(self):
        g(self.repo, "checkout", "-q", "-b", "a")
        (self.repo / "cert.p12").write_bytes(b"\x00\x01binary\x00")
        g(self.repo, "add", "-A"), g(self.repo, "commit", "-q", "-m", "c")
        self.assertIn("cert.p12", self.hits(g(self.repo, "rev-parse", "HEAD"))[0])

    def test_a_token_inside_a_binary(self):
        g(self.repo, "checkout", "-q", "-b", "a")
        (self.repo / "blob.bin").write_bytes(b"\x00\x00" + FAKE_TOKEN.encode() + b"\x00")
        g(self.repo, "add", "-A"), g(self.repo, "commit", "-q", "-m", "c")
        self.assertEqual(self.hits(g(self.repo, "rev-parse", "HEAD")), ["blob.bin"])

    def test_a_token_added_only_by_a_merge(self):
        self.branch("side", file="side.txt", text="s\n")
        g(self.repo, "checkout", "-q", "-b", "a")
        g(self.repo, "merge", "-q", "--no-ff", "--no-commit", "side")
        (self.repo / "evil.txt").write_text(f"k={FAKE_TOKEN}\n")
        g(self.repo, "add", "-A"), g(self.repo, "commit", "-q", "-m", "merge")
        self.assertIn("evil.txt", self.hits(g(self.repo, "rev-parse", "HEAD")))

    def test_a_rename_to_a_secret_name(self):
        g(self.repo, "checkout", "-q", "-b", "a")
        commit(self.repo, "settings.txt", "A=1\n", "c")
        g(self.repo, "mv", "settings.txt", ".env"), g(self.repo, "commit", "-q", "-m", "rename")
        self.assertTrue(any(".env" in h for h in self.hits(g(self.repo, "rev-parse", "HEAD"))))

    def test_a_token_after_a_carriage_return(self):
        g(self.repo, "checkout", "-q", "-b", "a")
        (self.repo / "cr.txt").write_bytes(b"a\r" + FAKE_TOKEN.encode() + b"\n")
        g(self.repo, "add", "-A"), g(self.repo, "commit", "-q", "-m", "c")
        self.assertEqual(self.hits(g(self.repo, "rev-parse", "HEAD")), ["cr.txt"])

    def test_a_key_file_with_a_space_in_its_name(self):
        tip = self.branch("a", file="my key.pem", text="x\n")
        self.assertIn("my key.pem", self.hits(tip)[0])

    def test_an_aws_key(self):
        tip = self.branch("a", file="aws.txt", text="id=AKIA" + "ABCDEFGHIJKLMNOP\n")
        self.assertEqual(self.hits(tip), ["aws.txt"])

    def test_a_failed_read_counts_as_a_hit(self):
        tip = self.branch("a")
        with mock.patch.object(weekly, "git", failing("rev-list")):
            self.assertTrue(self.hits(tip))

    def test_a_submodule_pointer_is_not_a_hit(self):
        lib = self.tmp / "lib"
        subprocess.run(["git", "init", "-q", "-b", "main", str(lib)], check=True, env=ENV)
        commit(lib, "lib.txt", "lib\n", "lib")
        g(self.repo, "checkout", "-q", "-b", "a")
        g(self.repo, "submodule", "add", "-q", str(lib), "projects/lib")
        g(self.repo, "commit", "-q", "-m", "add lib")
        self.assertEqual(self.hits(g(self.repo, "rev-parse", "HEAD")), [])


class Publishing(EndToEnd):
    open_pr = ""

    def rec(self):
        return weekly.read_run(self.latest())

    def files(self, publish=()):
        return weekly.weekly_pr_files(self.repo, self.rec(), self.latest(), weekly.load_config({}), False, list(publish))

    def test_an_uncommitted_post_edit_is_not_published(self):
        self.go()
        (self.repo / "pages/posts/2026-01-01-old.md").write_text("---\ntitle: old\ndraft: true\n---\n\nUNCOMMITTED\n")
        self.assertNotIn("UNCOMMITTED", self.files(["2026-01-01-old.md"])["pages/posts/2026-01-01-old.md"])

    def test_a_draft_that_is_not_on_main_is_refused(self):
        self.go()
        with self.assertRaises(SystemExit):
            self.files(["2099-01-01-nope.md"])

    def test_a_stale_checkout_does_not_revert_a_newer_pin(self):
        self.go()
        rec = self.rec()
        rec["plan"] = {"lanes": {lane: [] for lane in weekly.LANES}}
        other = self.tmp / "other"
        subprocess.run(["git", "clone", "-q", str(self.origin), str(other)], check=True, env=ENV, capture_output=True)
        commit(other, "_data/work_queue.yml", "schema: work-queue/v1\norder: ['issue:o/r#1']\npriority: {}\nnotes: {}\n", "pin")
        g(other, "push", "-q", "origin", "main")
        g(self.repo, "fetch", "-q", "origin", "main")
        rec["open_keys"] = ["issue:o/r#1"]
        files = weekly.weekly_pr_files(self.repo, rec, self.latest(), weekly.load_config({}), False, [])
        self.assertIn("issue:o/r#1", files[weekly.QUEUE])

    def gh(self, cmd, **kwargs):
        if cmd[:3] == ["gh", "pr", "list"]:
            return subprocess.CompletedProcess(cmd, 0, self.open_pr, "")
        if cmd[0] == "gh":
            return subprocess.CompletedProcess(cmd, 0, "https://example.test/pr/1\n", "")
        return self.real_run(cmd, **kwargs)

    def test_the_pr_makes_no_local_branch_and_leaves_an_existing_one_alone(self):
        self.go()
        rec = self.rec()
        stamp = rec["id"].split("-", 1)[0].lower()
        mine = f"chore/weekly-{rec['week'].lower()}-{stamp}"
        g(self.repo, "branch", mine)
        g(self.repo, "checkout", "-q", mine)
        kept = commit(self.repo, "mine.txt", "unpushed\n", "the maintainer's own commit")
        g(self.repo, "checkout", "-q", "main")
        before = g(self.repo, "status", "--porcelain")
        self.real_run = weekly.run
        with mock.patch.object(weekly, "run", self.gh):
            self.assertIn("example.test", weekly.open_weekly_pr(self.repo, rec, {"a.txt": "a\n"}, CFG))
        self.assertEqual(g(self.repo, "rev-parse", mine), kept)
        self.assertEqual(g(self.repo, "status", "--porcelain"), before)
        self.assertEqual(g(self.repo, "worktree", "list").count("\n"), 0)

    def test_a_second_confirm_does_not_overwrite_a_commit_on_the_pr_branch(self):
        self.go()
        rec = self.rec()
        self.real_run = weekly.run
        with mock.patch.object(weekly, "run", self.gh):
            weekly.open_weekly_pr(self.repo, rec, {"a.txt": "a\n"}, CFG)
        branch = g(self.origin, "for-each-ref", "--format=%(refname)", "refs/heads/chore")
        other = self.tmp / "other"
        subprocess.run(["git", "clone", "-q", "-b", branch.replace("refs/heads/", ""), str(self.origin), str(other)],
                       check=True, env=ENV, capture_output=True)
        edit = commit(other, "note.md", "my edit\n", "the maintainer's edit")
        g(other, "push", "-q", "origin", f"HEAD:{branch}")
        with mock.patch.object(weekly, "run", self.gh):
            weekly.open_weekly_pr(self.repo, rec, {"a.txt": "different\n"}, CFG)
        self.assertEqual(g(self.origin, "rev-parse", branch), edit)

    def test_a_second_weekly_pr_is_not_opened_beside_the_first(self):
        self.go()
        self.open_pr = "https://example.test/pr/9\n"
        self.real_run = weekly.run
        with mock.patch.object(weekly, "run", self.gh):
            self.assertIn("skipped", weekly.open_weekly_pr(self.repo, self.rec(), {"a.txt": "a\n"}, CFG))
        self.assertEqual(g(self.origin, "for-each-ref", "refs/heads/chore"), "")

    def test_a_post_that_has_landed_is_not_overwritten(self):
        self.go()
        rec = self.rec()
        retro = next(n for n in rec["posts"] if n.endswith("-weekly-retro.md"))
        other = self.tmp / "other"
        subprocess.run(["git", "clone", "-q", str(self.origin), str(other)], check=True, env=ENV, capture_output=True)
        commit(other, f"pages/posts/{retro}", "published and edited\n", "publish")
        g(other, "push", "-q", "origin", "main")
        g(self.repo, "fetch", "-q", "origin", "main")
        self.assertNotIn(f"pages/posts/{retro}", self.files())

    def test_a_pin_added_after_the_run_survives(self):
        self.go()
        rec = self.rec()
        rec["plan"] = {"lanes": {lane: [] for lane in weekly.LANES}}
        rec["open_keys"], rec["pinned"] = [], []
        other = self.tmp / "other"
        subprocess.run(["git", "clone", "-q", str(self.origin), str(other)], check=True, env=ENV, capture_output=True)
        commit(other, "_data/work_queue.yml", "schema: work-queue/v1\norder: ['issue:o/r#5']\npriority: {}\nnotes: {}\n", "pin")
        g(other, "push", "-q", "origin", "main")
        g(self.repo, "fetch", "-q", "origin", "main")
        files = weekly.weekly_pr_files(self.repo, rec, self.latest(), weekly.load_config({}), False, [])
        self.assertIn("issue:o/r#5", files[weekly.QUEUE])

    def test_a_stale_roadmap_edit_does_not_stop_the_confirm(self):
        self.go()
        commit(self.repo, "_data/roadmap.yml", "roadmap: []\n", "roadmap")
        g(self.repo, "push", "-q", "origin", "main")
        pm = self.repo / ".fleet" / "pm"
        pm.mkdir(parents=True)
        (pm / "model.json").write_text("{}")
        (pm / "review.json").write_text(json.dumps({"roadmap_edits": [{"id": "FF-9999", "to": "shipped"}]}))
        self.assertNotIn(weekly.ROADMAP, self.files())

    def test_a_failed_read_of_main_refuses_the_confirm(self):
        self.go()
        args = argparse.Namespace(apply=True, keep_drafts=False, publish=[], allow=[])
        with mock.patch.object(weekly, "git", failing("ls-tree")), mock.patch.object(weekly, "push_wip") as push, \
                mock.patch("builtins.print"), mock.patch("sys.stderr"):
            self.assertEqual(weekly.cmd_confirm(args, self.repo, self.state), 1)
        push.assert_not_called()

    def test_main_is_never_pushed_by_the_pr(self):
        self.go()
        before = g(self.origin, "rev-parse", "main")
        self.real_run = weekly.run
        with mock.patch.object(weekly, "run", self.gh):
            weekly.open_weekly_pr(self.repo, self.rec(), {"a.txt": "a\n"}, CFG)
        self.assertEqual(g(self.origin, "rev-parse", "main"), before)

    def test_a_failed_board_batch_is_not_recorded_done_and_fails_the_confirm(self):
        self.go()
        plan = self.repo / ".fleet" / "pm"
        plan.mkdir(parents=True)
        (plan / "board-plan.json").write_text(json.dumps({"batches": [{"index": 1}, {"index": 2}]}))
        args = argparse.Namespace(apply=True, keep_drafts=False, publish=[], allow=[])
        bad = [{"index": 1, "ok": False, "note": "batch 1: skipped"}]
        with mock.patch.object(weekly, "apply_board", return_value=bad), mock.patch.object(weekly, "push_wip", return_value="pushed"), \
                mock.patch.object(weekly, "open_weekly_pr", return_value="https://example.test/pr/1"), mock.patch("builtins.print"):
            code = weekly.cmd_confirm(args, self.repo, self.state)
        self.assertEqual(code, 1)
        self.assertEqual(json.loads((self.latest() / "confirm.json").read_text())["batches"], [])


class Paths(EndToEnd):
    def test_a_relative_archive_still_lands_in_one_place(self):
        cwd = os.getcwd()
        self.addCleanup(os.chdir, cwd)
        os.chdir(self.tmp)
        with mock.patch.object(weekly, "live_state", return_value=NOBODY), mock.patch("builtins.print"):
            code = cli.main(["--root", str(self.repo), "--state-dir", "st", "--archive", "rel-archive", "close", "--offline", "--no-plan"])
        self.assertEqual(code, 0)
        self.assertTrue(list((self.tmp / "rel-archive").rglob("hub.bundle")))
        self.assertFalse(list(self.repo.parent.glob("repo/rel-archive")))


class Release(EndToEnd):
    def held_run(self):
        self.go()
        rec = weekly.read_run(self.latest())
        rec["wip"][0]["blocked"] = ["config.txt"]
        (self.latest() / "run.json").write_text(json.dumps(rec))

    def confirm_with(self, allow):
        args = argparse.Namespace(apply=True, keep_drafts=False, publish=[], allow=allow)
        with mock.patch.object(weekly, "push_wip", return_value="pushed") as push, mock.patch.object(weekly, "apply_board", return_value=[]), \
                mock.patch.object(weekly, "open_weekly_pr", return_value="https://example.test/pr/1"), mock.patch("builtins.print"):
            weekly.cmd_confirm(args, self.repo, self.state)
        return push

    def test_a_held_branch_is_not_pushed(self):
        self.held_run()
        self.confirm_with([]).assert_not_called()

    def test_it_is_pushed_only_when_named(self):
        self.held_run()
        push = self.confirm_with(["hub:feature/unmerged"])
        self.assertEqual(push.call_args[0][0]["branch"], "feature/unmerged")
        self.assertEqual(push.call_args[0][0]["blocked"], [])

    def test_naming_another_branch_releases_nothing(self):
        self.held_run()
        self.confirm_with(["hub:something-else"]).assert_not_called()

    def test_the_same_branch_name_in_another_repo_is_not_released(self):
        self.held_run()
        self.confirm_with(["other-repo:feature/unmerged"]).assert_not_called()
        self.confirm_with(["feature/unmerged"]).assert_not_called()

    def test_a_branch_that_could_not_be_scanned_cannot_be_released(self):
        self.go()
        rec = weekly.read_run(self.latest())
        rec["wip"][0]["blocked"] = ["(600 commits is too many to scan)"]
        (self.latest() / "run.json").write_text(json.dumps(rec))
        self.confirm_with(["hub:feature/unmerged"]).assert_not_called()

    def test_a_file_that_could_not_be_read_cannot_be_released(self):
        self.go()
        rec = weekly.read_run(self.latest())
        rec["wip"][0]["blocked"] = ["big.bin (could not be read)"]
        (self.latest() / "run.json").write_text(json.dumps(rec))
        self.confirm_with(["hub:feature/unmerged"]).assert_not_called()


class Refresh(Repo):
    def setUp(self):
        super().setUp()
        self.hub = self.tmp / "hub"
        subprocess.run(["git", "clone", "-q", str(self.origin), str(self.hub)], check=True, env=ENV, capture_output=True)
        script = self.hub / "tools" / "update-submodules.sh"
        script.parent.mkdir()
        self.calls = self.tmp / "calls.txt"
        script.write_text(f'#!/usr/bin/env bash\necho "$@" >> {self.calls}\n')
        g(self.hub, "add", "-A"), g(self.hub, "commit", "-q", "-m", "script"), g(self.hub, "push", "-q", "origin", "main")
        self.sub = self.hub / "projects" / "sub"
        subprocess.run(["git", "clone", "-q", str(self.origin), str(self.sub)], check=True, env=ENV, capture_output=True)

    def row(self, **fields):
        base = {"name": "sub", "path": str(self.hub / "projects" / "sub"), "branch": "main", "state": "ok", "head_branch": "main",
                "head": "0" * 40, "detached_unique": 0, "worktrees": []}
        return {**base, **fields}

    def go(self, row, live=NOBODY):
        return weekly.refresh(self.hub, [{"name": "hub"}, row], live)

    def called(self):
        return self.calls.read_text() if self.calls.exists() else ""

    def test_a_submodule_on_main_is_refreshed(self):
        self.go(self.row())
        self.assertIn("projects/sub", self.called())

    def test_a_feature_branch_is_left_where_it_is(self):
        g(self.sub, "checkout", "-q", "-b", "feature/x")  # after the inventory: only a fresh read sees it
        result = self.go(self.row())
        self.assertEqual(self.called(), "")
        self.assertIn("left on feature/x", result["notes"][0])

    def test_a_session_in_the_checkout_stops_its_refresh(self):
        path = str(self.hub / "projects" / "sub")
        result = self.go(self.row(), {**NOBODY, "sessions": [{"cwd": path, "name": "x"}]})
        self.assertEqual(self.called(), "")
        self.assertIn("in use", result["notes"][0])

    def test_a_process_in_the_checkout_stops_its_refresh_too(self):
        path = weekly.real(self.hub / "projects" / "sub")
        result = self.go(self.row(), {**NOBODY, "paths": [path + "/src"]})
        self.assertEqual(self.called(), "")
        self.assertIn("in use", result["notes"][0])

    def test_if_what_is_in_use_cannot_be_read_nothing_moves(self):
        result = self.go(self.row(), {**NOBODY, "degraded": ["lsof"]})
        self.assertFalse(result["ok"])
        self.assertEqual(self.called(), "")

    def test_only_this_submodules_pointer_is_unstaged(self):
        sub = self.hub / "tools" / "update-submodules.sh"
        sub.write_text('#!/usr/bin/env bash\necho staged-later > elsewhere.txt\ngit add elsewhere.txt\n')
        self.go(self.row(path=str(self.hub / "tools"), name="sub"))
        self.assertIn("elsewhere.txt", g(self.hub, "diff", "--cached", "--name-only"))

    def test_a_session_in_a_linked_worktree_does_not(self):
        wt = str(self.hub / "projects" / "sub" / ".claude" / "worktrees" / "w")
        self.go(self.row(worktrees=[{"path": wt}]), {**NOBODY, "sessions": [{"cwd": wt, "name": "x"}]})
        self.assertIn("projects/sub", self.called())

    def test_detached_commits_are_anchored_to_a_branch_before_moving(self):
        sub = self.repo
        g(sub, "checkout", "-q", "--detach")
        sha = commit(sub, "lost.txt", "only here\n", "orphan")
        self.go(self.row(path=str(sub), head_branch=None, head="0" * 40, detached_unique=0))
        self.assertEqual(g(sub, "rev-parse", f"weekly/detached-{sha[:8]}"), sha)  # found at the moment of moving
        self.assertTrue(self.called())

    def test_commits_that_cannot_be_anchored_keep_the_repo_where_it_is(self):
        sub = self.repo
        g(sub, "checkout", "-q", "--detach")
        sha = commit(sub, "lost.txt", "only here\n", "orphan")
        g(sub, "branch", "weekly/detached-" + sha[:8] + "/blocks", "main")  # a ref in the way of the name
        result = self.go(self.row(path=str(sub), head_branch=None))
        self.assertEqual(self.called(), "")
        self.assertIn("could not be anchored", result["notes"][0])

    def test_someone_elses_staged_work_stops_the_refresh_and_is_left_staged(self):
        (self.hub / "staged.txt").write_text("in progress\n")
        g(self.hub, "add", "staged.txt")
        result = self.go(self.row())
        self.assertFalse(result["ok"])
        self.assertEqual(self.called(), "")
        self.assertIn("staged.txt", g(self.hub, "diff", "--cached", "--name-only"))


class Hidden(unittest.TestCase):
    def test_a_private_repo_never_reaches_the_chronicles(self):
        inv = [{"state": "ok", "nwo": "o/secret", "path": ".", "branch": "main"}]
        with mock.patch.object(weekly, "out", return_value="2026-11-06\tfeat: hidden project"):
            now = datetime(2026, 11, 7, tzinfo=timezone.utc)
            self.assertEqual(weekly.activity(inv, now, now, "^$", ["o/secret"]), {})
            self.assertTrue(weekly.activity(inv, now, now, "^$", []))


if __name__ == "__main__":
    unittest.main()
