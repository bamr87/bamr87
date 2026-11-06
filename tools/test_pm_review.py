#!/usr/bin/env python3
# ============================================================================
# File:          tools/test_pm_review.py
# Description:   Offline tests for tools/pm_review.py, the routine PM review. The scope is the hub
#                plus fleet-owned registry repos; the gather speaks only GETs and GraphQL queries
#                against a recording fake `gh`; each lane's rules (project, roadmap, release,
#                hygiene) hold on small models; the board ops form a preview the § 11 service
#                accepts and `dash projects apply` takes; the roadmap edits go through the Work
#                board's editor; the public snapshot never lists a private repo's items; and the
#                workflow that runs it never applies. No network, PyYAML only.
# Usage:         python3 tools/test_pm_review.py   (run by python-tests.yml and run-all-tests.sh)
# ============================================================================
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pm_review as pm  # noqa: E402

pb = pm.pb
HUB = "bamr87/bamr87"
NOW = "2026-11-05T07:07:00Z"
FLEET = {"hub": {"repo": HUB, "default_branch": "main", "owners": ["bamr87", "year-of-ai"]}}
REGISTRY = [
    {"name": "alpha", "repo_url": "https://github.com/bamr87/alpha", "branch": "main", "status": "active",
     "release": {"engine": "release-please"}},
    {"name": "site", "repo_url": "https://github.com/year-of-ai/site.git", "status": "maintenance"},
    {"name": "skills", "repo_url": "https://github.com/microsoft/skills", "status": "active"},
    {"name": "old", "repo_url": "https://github.com/bamr87/old", "status": "archived"},
    {"name": "alpha-again", "repo_url": "https://github.com/bamr87/alpha", "status": "active"},
    {"name": "no-url", "status": "active"},
]
DECISIONS = {"board": {"status": {"closed": "Done", "needs-amr": "Needs Amr", "default": "Triaged", "pr": "In review",
                                  "pr_draft": "In progress"},
                       "priority": {"default": "P2"}, "area": {"default": "platform"}}}
FRAMEWORK = {"labels": {"canonical": {
    "P0": {"field": "Priority", "value": "P0"}, "P1": {"field": "Priority", "value": "P1"},
    "P2": {"field": "Priority", "value": "P2"}, "P3": {"field": "Priority", "value": "P3"},
    "agent:ready": {"field": "Status", "value": "Ready"}, "agent:in-pr": {"field": "Status", "value": "In review"},
    "agent:blocked": {"field": "Status", "value": "Blocked"}, "agent:hold": {"field": "Status", "value": "Blocked"}}}}


def field(fid: str, *names: str) -> dict:
    return {"id": fid, "type": "SINGLE_SELECT", "options": {n: f"{fid}_{i}" for i, n in enumerate(names)}}


PROJECT = {"id": "PVT_1", "title": "Fleet", "url": "https://github.com/users/bamr87/projects/14", "fields": {
    "Status": field("F_status", "Inbox", "Triage", "Ready", "Needs Amr", "In progress", "In review", "Hold", "Done"),
    "Priority": field("F_prio", "P0", "P1", "P2", "P3"),
    "CI": field("F_ci", "Green", "Red", "Pending", "None"),
    "Merge state": field("F_merge", "Clean", "Conflicting", "Behind", "Blocked", "Unknown")}}


def item(n: int, kind: str = "issue", labels=(), repo: str = HUB, **kw) -> dict:
    return {"repo": repo, "number": n, "node_id": f"N_{n}", "title": kw.pop("title", f"item {n}"), "state": "open",
            "labels": list(labels), "kind": kind, "draft": kw.pop("draft", False), "author": "bamr87",
            "created_at": kw.pop("created_at", "2026-11-01T00:00:00Z"), "updated_at": kw.pop("updated_at", "2026-11-04T00:00:00Z"),
            "comments": 0, "milestone": None, "url": f"https://github.com/{repo}/issues/{n}", **kw}


def on_board(n: int, repo: str = HUB, state: str = "OPEN", kind: str = "issue", archived: bool = False, **fields) -> dict:
    return {"repo": repo, "number": n, "item_id": f"I_{n}", "kind": kind, "state": state, "archived": archived,
            "fields": {k.replace("_", " "): v for k, v in fields.items()}, "title": f"item {n}"}


def repo(items=(), nwo: str = HUB, **kw) -> dict:
    return {"repo": nwo, "name": nwo.split("/")[1], "branch": "main", "status": "active", "hub": nwo == HUB,
            "registry_release": {}, "private": False, "archived": False, "default_branch": "main",
            "items": list(items), "prs": kw.pop("prs", {}), "comments": kw.pop("comments", {}),
            "release": kw.pop("release", {}), "epics": kw.pop("epics", {}), **kw}


def model(repos=(), board=(), available: bool = True, **kw) -> dict:
    b = {"available": True, "owner": "bamr87", "number": 14, "project": PROJECT, "items": list(board), "truncated": False} \
        if available else {"available": False, "error": "graphql_unavailable: INSUFFICIENT_SCOPES", "owner": "bamr87", "number": 14}
    return {"schema": pm.MODEL_SCHEMA, "generated_at": NOW, "hub": HUB, "repos": list(repos), "board": b,
            "roadmap": kw.pop("roadmap", []), "roadmap_issues": kw.pop("roadmap_issues", {}), "triage": kw.pop("triage", {}),
            "partial": False, **kw}


def run(m: dict, cfg: dict | None = None, allow: set[str] | None = None) -> dict:
    return pm.align(m, cfg or pm.load_config({}), DECISIONS, FRAMEWORK, allow)


def prun(m: dict, cfg: dict | None = None, allow: set[str] | None = None) -> dict:
    """The project lane alone: the fixtures' unlabelled issues are the hygiene lane's business."""
    return run(m, {**(cfg or pm.load_config({})), "lanes": ["project"]}, allow)


def kinds(result: dict) -> list[str]:
    return sorted(f["kind"] for f in result["findings"])


def ops_of(result: dict, fields: tuple[str, ...] | None = None) -> list[tuple]:
    """The planned ops; with `fields`, only the field sets on those (a test of Status is not one of CI)."""
    return [(o["op"], o["number"], o.get("field"), o.get("value")) for o in result["ops"]
            if fields is None or o.get("field") in fields]


class ScopeTests(unittest.TestCase):
    def test_scope_is_the_hub_plus_fleet_owned_registry_repos(self):
        rows = pm.fleet_scope(FLEET, REGISTRY, pm.load_config({}))
        self.assertEqual([r["repo"] for r in rows], [HUB, "bamr87/alpha", "year-of-ai/site"])  # no mirror, archived, duplicate
        self.assertTrue(rows[0]["hub"])
        self.assertEqual(rows[1]["registry_release"], {"engine": "release-please"})

    def test_config_merges_fleet_yml_over_the_defaults(self):
        cfg = pm.load_config({"pm": {"thresholds": {"pr_idle_days": 3}, "lanes": ["project"]}})
        self.assertEqual(cfg["thresholds"]["pr_idle_days"], 3)
        self.assertEqual(cfg["thresholds"]["stale_in_progress_days"], pm.DEFAULTS["thresholds"]["stale_in_progress_days"])
        self.assertEqual(cfg["lanes"], ["project"])

    def test_committed_pm_block_uses_only_known_keys(self):
        block = (yaml.safe_load(pm.FLEET.read_text()) or {}).get("pm") or {}
        self.assertTrue(block, "_data/fleet.yml has no pm: block")
        self.assertLessEqual(set(block), set(pm.DEFAULTS))
        for key in ("board", "thresholds", "comments", "release", "snapshot", "scope", "project"):
            self.assertLessEqual(set(block.get(key) or {}), set(pm.DEFAULTS[key]), key)
        self.assertLessEqual(set(block["lanes"]), set(pm.LANES))


class ProjectLaneTests(unittest.TestCase):
    def test_untracked_item_is_added_and_a_repo_outside_the_registry_is_only_reported(self):
        m = model([repo([item(1)]), repo([item(2, repo="bamr87/x")], nwo="bamr87/x")])
        res = prun(m, allow={HUB})
        self.assertEqual(kinds(res), ["untracked", "untracked"])
        self.assertEqual(res["ops"], [{"op": "item.add", "project_id": "PVT_1", "content_id": "N_1", "repo": HUB,
                                       "number": 1, "kind": "issue", "basis": "untracked"}])
        self.assertEqual([f["auto"] for f in res["findings"]], [True, False])
        self.assertEqual(res["coverage"]["pct"], 0.0)

    def test_missing_fields_are_set_through_the_alias_the_live_project_uses(self):
        res = prun(model([repo([item(1, labels=["P1"]), item(2)])], [on_board(1), on_board(2)]))
        self.assertEqual(ops_of(res), [("item.set_field", 1, "Status", "Triage"), ("item.set_field", 2, "Status", "Triage"),
                                       ("item.set_field", 1, "Priority", "P1"), ("item.set_field", 2, "Priority", "P2")])
        why = {f["ref"]: f["proposal"] for f in res["findings"] if f["kind"] == "priority_missing"}
        self.assertIn("label P1", why[f"{HUB}#1"])
        self.assertIn("default", why[f"{HUB}#2"])

    def test_a_status_with_no_option_and_no_alias_is_said_not_guessed(self):
        cfg = pm.load_config({"pm": {"board": {"aliases": {"Triaged": "Backlog"}}}})  # an alias the project does not have
        res = prun(model([repo([item(1)])], [on_board(1, Priority="P2")]), cfg)
        self.assertEqual(kinds(res), ["option_missing"])
        self.assertEqual(res["ops"], [])

    def test_pull_request_state_moves_status_but_never_over_a_held_one(self):
        prs = {"1": {"draft": False}, "2": {"draft": True}, "3": {"draft": False}}
        items = [item(1, "pr"), item(2, "pr"), item(3, "pr")]
        board = [on_board(1, Status="Triage", Priority="P2"), on_board(2, Status="In review", Priority="P2"),
                 on_board(3, Status="Hold", Priority="P2")]
        res = prun(model([repo(items, prs=prs)], board))
        self.assertEqual(ops_of(res, ("Status",)), [("item.set_field", 1, "Status", "In review"), ("item.set_field", 2, "Status", "In progress")])

    def test_a_linked_pull_request_moves_an_issue_on_only_from_an_early_status(self):
        prs = {"10": {"draft": False, "closes": [f"{HUB}#1", f"{HUB}#2"]}, "11": {"draft": True, "closes": [f"{HUB}#3"]}}
        items = [item(1), item(2), item(3), item(10, "pr"), item(11, "pr")]
        board = [on_board(1, Status="Ready", Priority="P2"), on_board(2, Status="In progress", Priority="P2"),
                 on_board(3, Status="Triage", Priority="P2"), on_board(10, Status="In review", Priority="P2"),
                 on_board(11, Status="In progress", Priority="P2")]
        res = prun(model([repo(items, prs=prs)], board))
        self.assertEqual(ops_of(res, ("Status",)), [("item.set_field", 1, "Status", "In review"), ("item.set_field", 3, "Status", "In progress")])

    def test_needs_amr_label_is_mirrored_first(self):
        res = prun(model([repo([item(1, labels=["needs-amr"])])], [on_board(1, Status="Ready", Priority="P2")]))
        self.assertEqual(ops_of(res), [("item.set_field", 1, "Status", "Needs Amr")])
        self.assertEqual(res["findings"][0]["severity"], "high")

    def test_closed_on_github_becomes_done_whatever_the_project_said(self):
        board = [on_board(1, state="CLOSED", Status="Needs Amr"), on_board(2, state="MERGED", kind="pr", Status="In review"),
                 on_board(3, state="CLOSED", Status="Done"), on_board(4, state="CLOSED", archived=True, Status="Ready"),
                 on_board(5, repo="someone/else", state="CLOSED", Status="Ready")]
        res = prun(model([repo([])], board), allow={HUB})
        self.assertEqual(ops_of(res), [("item.set_field", 1, "Status", "Done"), ("item.set_field", 2, "Status", "Done")])
        self.assertEqual(kinds(res), ["board_unregistered", "closed_not_done", "closed_not_done"])

    def test_ci_and_merge_state_are_mirrored_and_an_unknown_state_is_left_alone(self):
        self.assertEqual(pm.pr_mirror({"ci": "FAILURE", "merge_state": "DIRTY"}), {"CI": "Red", "Merge state": "Conflicting"})
        self.assertEqual(pm.pr_mirror({"ci": None, "merge_state": "UNKNOWN", "mergeable": "UNKNOWN"}), {"CI": "None"})
        self.assertEqual(pm.pr_mirror({"ci": "SUCCESS", "merge_state": "DRAFT", "mergeable": "MERGEABLE"}), {"CI": "Green", "Merge state": "Clean"})
        prs = {"1": {"draft": False, "ci": "FAILURE", "merge_state": "BEHIND"}}
        board = [on_board(1, kind="pr", Status="In review", Priority="P2", CI="Green", Merge_state="Behind")]
        res = prun(model([repo([item(1, "pr")], prs=prs)], board))
        self.assertEqual(ops_of(res), [("item.set_field", 1, "CI", "Red")])
        self.assertIn("pr_state_not_mirrored", kinds(res))

    def test_priority_conflict_and_done_but_open_are_reported_never_planned(self):
        board = [on_board(1, Status="Ready", Priority="P1"), on_board(2, Status="Done", Priority="P2")]
        res = prun(model([repo([item(1, labels=["P2"]), item(2, labels=["P2"])])], board))
        self.assertEqual(kinds(res), ["done_but_open", "priority_conflict"])
        self.assertEqual(res["ops"], [])
        self.assertIn("project wins", res["findings"][0]["proposal"] + res["findings"][1]["proposal"])

    def test_stale_in_progress_and_a_finished_epic(self):
        items = [item(1, updated_at="2026-10-01T00:00:00Z"), item(2, labels=["epic"])]
        board = [on_board(1, Status="In progress", Priority="P2"), on_board(2, Status="In progress", Priority="P1")]
        res = prun(model([repo(items, epics={"2": {"total": 3, "closed": 3}})], board))
        self.assertEqual(kinds(res), ["epic_complete", "stale_in_progress"])
        self.assertEqual(res["ops"], [])

    def test_an_unreadable_project_plans_nothing_and_says_why(self):
        res = prun(model([repo([item(1), item(2, "pr")])], available=False))
        self.assertEqual(kinds(res), ["board_unreadable"])
        self.assertEqual(res["ops"], [])
        self.assertIsNone(res["coverage"]["pct"])
        self.assertEqual(res["coverage"]["open_items"], 2)

    def test_queues_count_open_items_only(self):
        board = [on_board(1, Status="Needs Amr"), on_board(2, state="MERGED", kind="pr", Status="Needs Amr"),
                 on_board(3, Status="Ready", Owner_agent="Fleet Doctor")]
        q = prun(model([repo([item(1), item(3)])], board))["queues"]
        self.assertEqual([x["ref"] for x in q["needs_amr"]], [f"{HUB}#1"])
        self.assertEqual(q["by_status"], {"Needs Amr": 1, "Ready": 1})
        self.assertEqual(q["by_owner_agent"], {"(none)": 1, "Fleet Doctor": 1})

    def test_ops_are_ordered_gate_then_done_then_fields_then_adds_hub_first(self):
        repos = [repo([item(7, repo="bamr87/alpha")], nwo="bamr87/alpha"), repo([item(1, labels=["needs-amr"]), item(2), item(3)])]
        board = [on_board(1, Status="Ready", Priority="P2"), on_board(2), on_board(9, state="CLOSED", Status="Ready")]
        res = prun(model(repos, board))
        self.assertEqual([o["basis"] for o in res["ops"]],
                         ["gate_not_mirrored", "closed_not_done", "status_missing", "priority_missing", "untracked", "untracked"])
        self.assertEqual([o["repo"] for o in res["ops"]][-2:], [HUB, "bamr87/alpha"])


class PlanTests(unittest.TestCase):
    def test_the_preview_is_one_dash_projects_apply_takes(self):
        items = [item(n) for n in range(1, 121)]
        m = model([repo(items)], [on_board(500, state="CLOSED", Status="Ready")])
        res = prun(m, allow={HUB})
        preview = pm.board_preview(m, res, {HUB})
        self.assertEqual(preview["schema"], pb.PLAN_SCHEMA)
        self.assertEqual(preview["record"], "audit-only")
        self.assertEqual([len(b["ops"]) for b in preview["batches"]], [50, 50, 21])
        self.assertTrue(all(b["board"] for b in preview["batches"]))
        self.assertEqual(preview["board"]["adds"], 120)
        self.assertEqual(preview["board"]["field_sets"], 1)
        for b in preview["batches"]:  # every op is on the § 11 allowlist and the plan id is the service's own
            again = pb.gw.plan(b["ops"], pm.offline_board(m).state, {HUB})
            self.assertEqual(again["plan_id"], b["plan_id"])
            self.assertEqual(again["changes"], len(b["ops"]))

    def test_an_op_for_a_repo_outside_the_registry_would_be_refused_by_the_service(self):
        m = model([repo([item(1, repo="bamr87/x")], nwo="bamr87/x")])
        res = prun(m, allow=None)  # no allowlist at align time: the op is planned…
        with self.assertRaises(pb.gw.Refused):  # …and the service still refuses it
            pm.board_preview(m, res, {HUB})

    def test_nothing_to_do_is_an_empty_preview(self):
        m = model([repo([item(1)])], [on_board(1, Status="Ready", Priority="P2")])
        preview = pm.board_preview(m, prun(m), {HUB})
        self.assertEqual(preview["batches"], [])
        self.assertEqual(preview["board"]["status"], "nothing to do")

    def test_apply_stays_off_without_the_flag(self):
        m = model([repo([item(1)])])
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stderr(io.StringIO()) as err:
            path = pb.write_preview(pm.board_preview(m, prun(m, allow={HUB}), {HUB}), Path(tmp) / "board-plan.json")
            self.assertEqual(pb.main(["apply", str(path), "--confirm"]), 1)
        self.assertIn("writes are off", err.getvalue())

    def test_applying_a_pm_preview_audits_it_and_leaves_the_decisions_ledger_alone(self):
        m = model([repo([item(1)])])
        preview = pm.board_preview(m, prun(m, allow={HUB}), {HUB})
        added, ledger, caps = [], [], []

        class FakeBoard:
            error = None

            def __init__(self, *_a, **k):
                caps.append(k.get("max_items"))

            def load(self):
                return True

            def state(self, op):
                return {"present": False}

            def execute(self, op):
                added.append(op["number"])
                return {"item_id": "I_new"}

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(pb, "Board", FakeBoard), \
                mock.patch.object(pb, "record_applied", lambda *a: ledger.append(a)), \
                mock.patch.object(pb, "AUDIT", Path(tmp) / "audit.jsonl"), mock.patch.object(pb, "registry_repos", lambda: {HUB}), \
                mock.patch.dict(os.environ, {pb.gw.FLAG: "1"}), contextlib.redirect_stdout(io.StringIO()):
            path = pb.write_preview(preview, Path(tmp) / "board-plan.json")
            self.assertEqual(pb.main(["apply", str(path), "--confirm"]), 0)
            self.assertEqual((added, ledger), ([1], []))
            self.assertEqual(caps, [pm.BOARD_MAX_ITEMS])  # applied against as many items as it was planned against
            self.assertIn('"result": "applied"', (Path(tmp) / "audit.jsonl").read_text())
            del preview["record"]  # the reviewed backfill pass still appends to its ledger
            path = pb.write_preview(preview, Path(tmp) / "backfill-plan.json")
            self.assertEqual(pb.main(["apply", str(path), "--confirm"]), 0)
            self.assertEqual(len(ledger), 1)

    def test_drain_names_the_hourly_cap(self):
        self.assertEqual(pm.drain(0, 0), "nothing to apply")
        self.assertEqual(pm.drain(40, 1), "1 batch(es)")
        self.assertIn("about 3 hours", pm.drain(531, 11))


ROADMAP_TEXT = """# header kept byte for byte
- id: FF-0001
  title: shipped already
  status: approved
  priority: P2
  issue_url: https://github.com/bamr87/bamr87/issues/130

- id: FF-0002
  title: >-
    folded
    prose
  status: backlog
  priority: P1
  issue_url: https://github.com/bamr87/bamr87/issues/5
"""


class RoadmapLaneTests(unittest.TestCase):
    def entries(self):
        return [
            {"id": "FF-0001", "title": "a", "status": "approved", "priority": "P2", "issue_url": f"https://github.com/{HUB}/issues/130"},
            {"id": "FF-0002", "title": "b", "status": "backlog", "priority": "P1", "issue_url": f"https://github.com/{HUB}/issues/5"},
            {"id": "FF-0003", "title": "c", "status": "in-progress", "priority": "P1", "issue_url": None},
            {"id": "FF-0004", "title": "d", "status": "approved", "priority": "P2", "issue_url": f"https://github.com/{HUB}/issues/6"},
            {"id": "FF-0005", "title": "e", "status": "proposed", "priority": "P3", "created": "2026-06-21", "issue_url": None},
            {"id": "FF-0006", "title": "f", "status": "shipped", "priority": "P3", "issue_url": None},
            {"id": "FF-0007", "title": "g", "status": "approved", "priority": "P1", "issue_url": f"https://github.com/{HUB}/issues/7"},
        ]

    def test_roadmap_follows_the_issues_it_names(self):
        items = [item(5, labels=["P2"]), item(7, labels=["P1"]), item(20, "pr"), item(30, labels=["roadmap", "epic"]),
                 item(31, labels=["roadmap"])]
        states = {f"{HUB}#130": {"state": "closed", "state_reason": "completed", "labels": []},
                  f"{HUB}#5": {"state": "open", "labels": ["P2"]},
                  f"{HUB}#6": {"state": "closed", "state_reason": "not_planned", "labels": []},
                  f"{HUB}#7": {"state": "open", "labels": ["P1"]}}
        m = model([repo(items, prs={"20": {"draft": True, "closes": [f"{HUB}#5"]}})], available=False,
                  roadmap=self.entries(), roadmap_issues=states)
        res = run(m, pm.load_config({"pm": {"lanes": ["roadmap"]}}))
        self.assertEqual(res["roadmap_edits"], [
            {"id": "FF-0001", "from": "approved", "to": "shipped", "why": f"{HUB}#130 closed as completed"},
            {"id": "FF-0002", "from": "backlog", "to": "in-progress", "why": f"{HUB}#20 is open against it"}])
        self.assertEqual(kinds(res), ["roadmap_declined", "roadmap_priority_drift", "roadmap_proposed_aging", "roadmap_shipped",
                                      "roadmap_started", "roadmap_unlinked", "roadmap_untracked_epic"])
        self.assertEqual(res["roadmap"]["labelled_without_entry"], 1)
        self.assertEqual(res["roadmap"]["active_unlinked"], 1)
        self.assertEqual(res["ops"], [])  # the roadmap lane never plans a GitHub write

    def test_the_project_status_can_start_a_roadmap_entry(self):
        e = [{"id": "FF-0007", "title": "g", "status": "approved", "priority": "P1", "issue_url": f"https://github.com/{HUB}/issues/7"}]
        m = model([repo([item(7, labels=["P1"])])], [on_board(7, Status="In progress", Priority="P1")], roadmap=e,
                  roadmap_issues={f"{HUB}#7": {"state": "open", "labels": ["P1"]}})
        self.assertEqual(run(m)["roadmap_edits"], [{"id": "FF-0007", "from": "approved", "to": "in-progress",
                                                    "why": "the project says In progress"}])

    def test_edits_touch_only_the_status_lines(self):
        new = pm.apply_roadmap_edits(ROADMAP_TEXT, [{"id": "FF-0001", "to": "shipped"}, {"id": "FF-0002", "to": "in-progress"}])
        self.assertEqual([e["status"] for e in yaml.safe_load(new)], ["shipped", "in-progress"])
        changed = [(a, b) for a, b in zip(ROADMAP_TEXT.splitlines(), new.splitlines()) if a != b]
        self.assertEqual(changed, [("  status: approved", "  status: shipped"), ("  status: backlog", "  status: in-progress")])
        with self.assertRaises(ValueError):
            pm.apply_roadmap_edits(ROADMAP_TEXT, [{"id": "FF-0099", "to": "shipped"}])


class RoadmapFragmentTests(unittest.TestCase):
    def test_pending_fragment_reads_as_ff_new_slug(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "_data"
            (data / "roadmap.d").mkdir(parents=True)
            (data / "roadmap.yml").write_text("# header\n- id: FF-0001\n  title: one\n  status: shipped\n")
            (data / "roadmap.d" / "two.yml").write_text("id: FF-NEW\ntitle: two\nstatus: proposed\n")
            rows = pm.load_roadmap(data / "roadmap.yml")
            self.assertEqual([r["id"] for r in rows], ["FF-0001", "FF-NEW:two"])
            self.assertTrue(rows[1]["pending"])


class ReleaseLaneTests(unittest.TestCase):
    def test_bump_follows_conventional_commits(self):
        self.assertEqual(pm.bump_of(["feat: a", "fix(x): b", "docs: c", "perf: d"]),
                         {"feat": 1, "fix": 2, "breaking": 0, "other": 1, "bump": "minor"})
        self.assertEqual(pm.bump_of(["feat(api)!: drop v1"])["bump"], "major")
        self.assertEqual(pm.bump_of(["fix: x\n\nBREAKING CHANGE: y"])["bump"], "major")
        self.assertEqual(pm.bump_of(["fix: x"])["bump"], "patch")
        self.assertIsNone(pm.bump_of(["chore: x", "Merge pull request #1"])["bump"])

    def test_release_states_and_what_each_asks_for(self):
        un = {"commits": 12, "sampled": 12, "feat": 3, "fix": 4, "breaking": 0, "bump": "minor"}
        quiet = {"commits": 2, "sampled": 2, "feat": 0, "fix": 0, "breaking": 0, "bump": None}
        pr = {"number": 9, "title": "chore(main): release 1.2.0", "created_at": "2026-10-20T00:00:00Z", "url": "u"}
        repos = [
            repo(nwo="bamr87/waiting", release={"engine": "release-please", "latest": "v1.1.0", "unreleased": un, "release_pr": pr}),
            repo(nwo="bamr87/blocked", release={"engine": "release-please", "latest": "v0.2.0", "unreleased": un}),
            repo(nwo=HUB, release={"engine": "hand-cut", "latest": "v2.0.0", "unreleased": {**un, "commits": 400, "sampled": 100}}),
            repo(nwo="bamr87/small", release={"engine": "none", "latest": "v0.1.0", "unreleased": {**un, "feat": 1, "fix": 1}}),
            repo(nwo="bamr87/current", release={"engine": "release-please", "latest": "v3.0.0", "unreleased": quiet}),
            repo(nwo="bamr87/never", release={"engine": "none", "latest": None}),
        ]
        res = run(model(repos, available=False, triage={"failing": {"bamr87/blocked": 2}}), pm.load_config({"pm": {"lanes": ["release"]}}))
        self.assertEqual({r["repo"].split("/")[1]: r["state"] for r in res["releases"]},
                         {"blocked": "blocked", "waiting": "release_pr_open", "bamr87": "unreleased", "small": "unreleased",
                          "current": "current", "never": "never_released"})
        self.assertEqual(res["releases"][0]["repo"], "bamr87/blocked")  # the blocked one leads the train
        by_kind = {f["kind"]: f for f in res["findings"]}
        self.assertEqual(sorted(by_kind), ["release_blocked", "release_pr_waiting", "release_unreleased"])
        self.assertEqual(by_kind["release_blocked"]["severity"], "high")
        self.assertIn("2 workflow(s) are red", by_kind["release_blocked"]["why"])
        self.assertIn("16 days", by_kind["release_pr_waiting"]["why"])
        self.assertIn("first 100 of 400 commits", by_kind["release_unreleased"]["why"])
        self.assertIn("WORKFLOW-VERSIONING", by_kind["release_unreleased"]["proposal"])  # the hub cuts tags by hand


class HygieneLaneTests(unittest.TestCase):
    def test_pull_requests_replies_and_labels(self):
        prs = {"1": {"draft": False, "mergeable": "CONFLICTING", "ci": "FAILURE", "review": "CHANGES_REQUESTED"},
               "2": {"draft": True, "mergeable": "MERGEABLE", "ci": "SUCCESS"}}
        comments = {"3": [{"author": "visitor", "bot": False, "association": "NONE", "at": "2026-11-04T10:00:00Z"}],
                    "4": [{"author": "bamr87", "bot": False, "association": "OWNER", "at": "2026-11-04T10:00:00Z"},
                          {"author": "visitor", "bot": False, "association": "NONE", "at": "2026-11-03T10:00:00Z"}],
                    "5": [{"author": "github-actions[bot]", "bot": True, "association": "NONE", "at": "2026-11-04T10:00:00Z"}]}
        items = [item(1, "pr", updated_at="2026-10-01T00:00:00Z"), item(2, "pr", updated_at="2026-10-01T00:00:00Z"),
                 item(3, labels=["bug", "P1"]), item(4, labels=["bug", "P1"]), item(5, labels=["feature"])]
        res = run(model([repo(items, prs=prs, comments=comments)], available=False), pm.load_config({"pm": {"lanes": ["hygiene"]}}))
        self.assertEqual(kinds(res), ["awaiting_reply", "pr_changes_requested", "pr_ci_red", "pr_conflicting", "pr_idle", "unlabelled"])
        self.assertEqual([f["ref"] for f in res["findings"] if f["kind"] == "awaiting_reply"], [f"{HUB}#3"])
        self.assertIn("1 open issue(s) carry no priority label", next(f["why"] for f in res["findings"] if f["kind"] == "unlabelled"))

    def test_an_unreachable_repo_is_reported_and_never_read_as_empty(self):
        res = run(model([repo(nwo="bamr87/secret", unreachable="GET repos/bamr87/secret: HTTP 404")], [on_board(1, repo="bamr87/secret", state="CLOSED", Status="Ready")]))
        self.assertEqual(kinds(res), ["closed_not_done", "repo_unreachable"])
        self.assertEqual(res["scope"]["unreachable"], ["bamr87/secret"])


class SnapshotTests(unittest.TestCase):
    def result(self):
        repos = [repo([item(1), item(2)]), repo([item(3, repo="bamr87/secret", title="confidential plan")], nwo="bamr87/secret", private=True)]
        board = [on_board(9, repo="bamr87/secret", Status="Needs Amr"),
                 on_board(77, repo="bamr87/never-read", state="CLOSED", Status="Ready")]  # on the project, outside the review
        m = model(repos, board)
        res = prun(m)
        return m, res, pm.board_preview(m, res, None)

    def test_private_repos_are_counted_and_never_listed(self):
        _m, res, preview = self.result()
        doc = pm.snapshot(res, preview, pm.load_config({}))
        text = yaml.safe_dump(doc)
        self.assertNotIn("confidential plan", text)
        self.assertNotIn("bamr87/secret#", text)
        self.assertNotIn("never-read#", text)  # a repo the review did not read is not known to be public
        self.assertEqual(doc["schema"], pm.SCHEMA)
        self.assertEqual(doc["findings"]["total"], 4)
        self.assertEqual(doc["findings"]["private_omitted"], 2)
        self.assertEqual(doc["queues"]["needs_amr"], [])
        self.assertEqual([r["repo"] for r in doc["coverage"]["by_repo"]], [HUB])
        self.assertEqual(doc["plan"]["board"]["adds"], 3)
        view = pm.public_view(res)
        self.assertEqual(view["private_omitted"], 2)
        self.assertNotIn("confidential plan", pm.markdown(view, preview))
        self.assertIn("confidential plan", pm.markdown(res, preview))  # the local report is whole

    def test_new_findings_and_history_carry_across_runs(self):
        _m, res, preview = self.result()
        cfg = pm.load_config({})
        first = pm.snapshot(res, preview, cfg)
        self.assertEqual(first["findings"]["new"], 0)  # nothing to compare a first run with
        prev = {**first, "seen": first["seen"].split()[0], "history": [{"date": f"2026-10-{d:02d}"} for d in range(1, 31)] + [{"date": "2026-11-05", "findings": 99}]}
        second = pm.snapshot(res, preview, cfg, prev)
        self.assertEqual(second["findings"]["new"], 3)
        self.assertEqual(len(second["history"]), pm.HISTORY_KEEP)
        self.assertEqual(second["history"][-1]["findings"], 4)  # today's row replaced, not appended twice
        self.assertEqual(sum(1 for h in second["history"] if h["date"] == "2026-11-05"), 1)

    def test_the_snapshot_caps_rows_per_kind_and_keeps_the_counts_whole(self):
        m = model([repo([item(n) for n in range(1, 41)])])
        res = prun(m)
        doc = pm.snapshot(res, pm.board_preview(m, res, None), pm.load_config({"pm": {"snapshot": {"max_per_kind": 5}}}))
        self.assertEqual(len(doc["findings"]["items"]), 5)
        self.assertEqual(doc["findings"]["by_kind"]["untracked"], 40)


class FakeGh:
    """Answers `gh api` from fixtures and records every call, so a write would be seen."""

    def __init__(self, graphql_ok: bool = True):
        self.calls: list[tuple[str, str]] = []
        self.graphql_ok = graphql_ok

    def __call__(self, args, stdin, env):
        method, path = args[3], args[4]
        params = dict(a.split("=", 1) for a in args[5:] if "=" in a)
        self.calls.append((method, path))
        if method == "POST" and path == "graphql":
            body = json.loads(stdin)
            assert body["query"].lstrip().startswith("query"), "the review sent something that is not a query"
            if not self.graphql_ok:
                return 1, "", "gh: GitHub GraphQL is not available from Claude Code sessions (HTTP 403)"
            return 0, json.dumps({"data": {"repository": {"pullRequests": {"nodes": [
                {"number": 2, "isDraft": True, "mergeable": "MERGEABLE", "mergeStateStatus": "DRAFT", "reviewDecision": None,
                 "headRefName": "release-please--branches--main", "closingIssuesReferences": {"nodes": [{"number": 1, "repository": {"nameWithOwner": "bamr87/alpha"}}]},
                 "commits": {"nodes": [{"commit": {"statusCheckRollup": {"state": "SUCCESS"}}}]}}]}}}}), ""
        if method != "GET":
            return 1, "", f"unexpected {method} {path}"
        if path == "repos/bamr87/gone":
            return 1, "", "HTTP 404: Not Found"
        if path == "repos/bamr87/alpha":
            return 0, json.dumps({"private": False, "archived": False, "default_branch": "main"}), ""
        if path == "repos/bamr87/alpha/issues":
            if params.get("page") != "1":
                return 0, "[]", ""
            return 0, json.dumps([
                {"number": 1, "node_id": "I_1", "title": "an epic", "labels": [{"name": "epic"}, {"name": "P1"}], "user": {"login": "bamr87"},
                 "created_at": "2026-10-01T00:00:00Z", "updated_at": "2026-11-01T00:00:00Z", "comments": 2, "milestone": {"title": "v1"},
                 "html_url": "https://github.com/bamr87/alpha/issues/1"},
                {"number": 2, "node_id": "PR_2", "title": "chore(main): release 1.2.0", "labels": [], "pull_request": {}, "draft": True,
                 "user": {"login": "github-actions[bot]"}, "created_at": "2026-10-20T00:00:00Z", "updated_at": "2026-11-01T00:00:00Z",
                 "comments": 0, "html_url": "https://github.com/bamr87/alpha/pull/2"}]), ""
        if path == "repos/bamr87/alpha/issues/comments":
            assert params.get("since"), "comments are read since a date, never the whole history"
            return 0, json.dumps([{"issue_url": "https://api.github.com/repos/bamr87/alpha/issues/1", "created_at": "2026-11-04T00:00:00Z",
                                   "author_association": "NONE", "user": {"login": "visitor", "type": "User"}}]), ""
        if path == "repos/bamr87/alpha/releases":
            return 0, json.dumps([{"tag_name": "v1.2.0-rc1", "prerelease": True}, {"tag_name": "v1.1.0", "published_at": "2026-10-01T00:00:00Z"}]), ""
        if path == "repos/bamr87/alpha/compare/v1.1.0...main":
            return 0, json.dumps({"ahead_by": 3, "commits": [{"commit": {"message": m}} for m in ("feat: a", "fix: b", "docs: c")]}), ""
        if path == "repos/bamr87/alpha/issues/1/sub_issues":
            return 0, json.dumps([{"state": "closed"}, {"state": "open"}]), ""
        return 1, "", f"HTTP 404: no fixture for {path}"


class GatherTests(unittest.TestCase):
    ROW = {"repo": "bamr87/alpha", "name": "alpha", "branch": "main", "status": "active", "hub": False,
           "registry_release": {"engine": "release-please"}}

    def test_one_repo_is_read_whole_and_only_read(self):
        fake = FakeGh()
        out = pm.gather_repo(pb.Gh(run=fake), dict(self.ROW), pm.load_config({}), "2026-11-03T00:00:00Z")
        self.assertEqual([(t["number"], t["kind"]) for t in out["items"]], [(1, "issue"), (2, "pr")])
        self.assertEqual(out["items"][0]["milestone"], "v1")
        self.assertEqual(out["prs"]["2"], {"draft": True, "mergeable": "MERGEABLE", "merge_state": "DRAFT", "review": None,
                                           "head": "release-please--branches--main", "ci": "SUCCESS", "closes": ["bamr87/alpha#1"]})
        self.assertEqual(out["comments"]["1"][0]["author"], "visitor")
        self.assertEqual(out["epics"], {"1": {"total": 2, "closed": 1}})
        rel = out["release"]
        self.assertEqual((rel["engine"], rel["latest"], rel["release_pr"]["number"]), ("release-please", "v1.1.0", 2))  # the rc is skipped
        self.assertEqual({k: rel["unreleased"][k] for k in ("commits", "feat", "fix", "bump")}, {"commits": 3, "feat": 1, "fix": 1, "bump": "minor"})
        self.assertTrue(all(m == "GET" or (m, p) == ("POST", "graphql") for m, p in fake.calls), fake.calls)

    def test_a_404_is_unreachable_not_deleted(self):
        out = pm.gather_repo(pb.Gh(run=FakeGh()), {**self.ROW, "repo": "bamr87/gone"}, pm.load_config({}), "2026-11-03T00:00:00Z")
        self.assertIn("404", out["unreachable"])
        self.assertEqual(out["items"], [])

    def test_no_graphql_keeps_the_issue_half(self):
        out = pm.gather_repo(pb.Gh(run=FakeGh(graphql_ok=False)), dict(self.ROW), pm.load_config({}), "2026-11-03T00:00:00Z")
        self.assertEqual(len(out["items"]), 2)
        self.assertEqual(out["prs"], {})
        self.assertIn("GraphQL", out["pr_error"])

    def test_the_module_holds_no_mutation_and_no_writer(self):
        src = Path(pm.__file__).read_text()
        self.assertNotIn("mutation", pm.PRS_Q)
        for needle in ("gh.call(", ".execute(", "gw.apply(", '"POST"', '"PATCH"', '"DELETE"', "os.environ["):
            self.assertNotIn(needle, src, f"tools/pm_review.py must stay read-only: found {needle}")


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        e = [{"id": "FF-0001", "title": "a", "status": "approved", "priority": "P2", "issue_url": f"https://github.com/{HUB}/issues/130"}]
        m = model([repo([item(1), item(2, "pr")], prs={"2": {"draft": False, "ci": "SUCCESS", "merge_state": "CLEAN"}},
                        release={"engine": "hand-cut", "latest": "v2.0.0", "unreleased": {"commits": 9, "sampled": 9, "feat": 6, "fix": 1, "breaking": 0, "bump": "minor"}})],
                  [on_board(2, kind="pr", Status="Triage", Priority="P2")], roadmap=e,
                  roadmap_issues={f"{HUB}#130": {"state": "closed", "state_reason": "completed", "labels": []}})
        self.model = self.dir / "model.json"
        self.model.write_text(json.dumps(m))
        self.out = self.dir / "out"

    def tearDown(self):
        self.tmp.cleanup()

    def cli(self, *argv: str) -> tuple[int, str]:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            rc = pm.main(list(argv))
        return rc, buf.getvalue()

    def test_review_replays_a_model_and_every_view_reads_it(self):
        snap = self.dir / "pm_review.yml"
        rc, text = self.cli("review", "--from", str(self.model), "--out", str(self.out), "--write", "--snapshot", str(snap))
        self.assertEqual(rc, 0)
        self.assertIn("# Fleet PM review — 2026-11-05", text)
        self.assertIn("Nothing was applied", text)
        for name in ("model.json", "review.json", "review.md", "board-plan.json"):
            self.assertTrue((self.out / name).exists(), name)
        doc = yaml.safe_load(snap.read_text())
        self.assertEqual((doc["schema"], doc["coverage"]["open_items"], doc["coverage"]["on_board"]), (pm.SCHEMA, 2, 1))
        rc, text = self.cli("plan", "--out", str(self.out))
        self.assertEqual(rc, 0)
        self.assertIn("Status: 'Triage' → 'In review'", text)
        self.assertIn("tools/dash projects apply", text)
        rc, text = self.cli("releases", "--out", str(self.out))
        self.assertEqual(rc, 0)
        self.assertIn("hand-cut", text)
        rc, text = self.cli("status", "--snapshot", str(snap))
        self.assertEqual(rc, 0)
        self.assertIn("1 of 2 open items on the project", text)

    def test_roadmap_write_edits_the_named_file_only_when_asked(self):
        road = self.dir / "roadmap.yml"
        road.write_text(ROADMAP_TEXT)
        self.cli("review", "--from", str(self.model), "--out", str(self.out), "--quiet")
        rc, text = self.cli("roadmap", "--out", str(self.out), "--roadmap", str(road))
        self.assertEqual((rc, road.read_text()), (0, ROADMAP_TEXT))
        self.assertIn("FF-0001: approved → shipped", text)
        rc, _ = self.cli("roadmap", "--out", str(self.out), "--roadmap", str(road), "--write")
        self.assertEqual(rc, 0)
        self.assertEqual(yaml.safe_load(road.read_text())[0]["status"], "shipped")

    def test_public_mode_writes_no_model_and_a_partial_run_never_reaches_the_snapshot(self):
        rc, _ = self.cli("review", "--from", str(self.model), "--out", str(self.out), "--public", "--quiet")
        self.assertEqual(rc, 0)
        self.assertFalse((self.out / "model.json").exists())
        partial = json.loads(self.model.read_text())
        partial["partial"] = True
        self.model.write_text(json.dumps(partial))
        snap = self.dir / "pm_review.yml"
        rc, _ = self.cli("review", "--from", str(self.model), "--out", str(self.out), "--write", "--snapshot", str(snap))
        self.assertEqual(rc, 1)
        self.assertFalse(snap.exists())

    def test_views_say_so_when_no_review_has_run(self):
        self.assertEqual(self.cli("plan", "--out", str(self.dir / "nowhere"))[0], 1)
        self.assertEqual(self.cli("status", "--snapshot", str(self.dir / "none.yml"))[0], 0)
        self.assertEqual(self.cli()[0], 2)


class WorkflowTests(unittest.TestCase):
    TEXT = (pm.ROOT / ".github" / "workflows" / "fleet-pm.yml").read_text()

    def test_the_loop_reviews_and_never_applies(self):
        doc = yaml.safe_load(self.TEXT)
        runs = "\n".join(str(s.get("run", "")) for j in doc["jobs"].values() for s in j["steps"])
        self.assertIn("tools/pm_review.py review", runs)
        self.assertIn("--public", runs)  # a public job summary never lists a private repo's items
        for needle in ("projects apply", "projects_backfill", "roadmap --write", "gh pr", "gh issue", "gh api", "git push"):
            self.assertNotIn(needle, runs, needle)
        self.assertNotIn("HARNESS_PROJECTS_WRITES", self.TEXT)  # the write flag is never set here

    def test_the_cron_is_switched_and_a_dispatch_is_not(self):
        job = yaml.safe_load(self.TEXT)["jobs"]["review"]
        self.assertEqual(job["if"], "${{ github.event_name != 'schedule' || vars.FLEET_PM_ENABLED == 'true' }}")
        cron = yaml.safe_load(self.TEXT)[True]["schedule"][0]["cron"]
        self.assertEqual(cron, (yaml.safe_load(pm.FLEET.read_text()) or {})["schedule"]["fleet_pm"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
