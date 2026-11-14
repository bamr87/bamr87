#!/usr/bin/env python3
# ============================================================================
# File:          tools/test_projects_backfill.py
# Description:   Offline tests for tools/projects_backfill.py — the decisions file validates and
#                compiles into allowlisted ops, batches respect the § 11 per-plan cap, the REST
#                state reader and executor speak the service's shapes against a recording fake `gh`,
#                apply refuses without the flag and without --confirm and then never calls gh,
#                board items plan adds-then-fields from recorded project data, Status / Priority /
#                Area derive from labels in the pipeline's precedence, and the applied ledger appends
#                without touching the rest of the file. No network, PyYAML only.
# Usage:         python3 tools/test_projects_backfill.py   (run by python-tests.yml and run-all-tests.sh)
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
import projects_backfill as pb  # noqa: E402

REPO = "bamr87/bamr87"
DECISIONS = {
    "schema": pb.SCHEMA, "repo": REPO, "project": {"owner": "bamr87", "number": 14},
    "issues": {
        "close": [{"number": 469, "reason": "completed", "why": "shipped in #475"},
                  {"number": 359, "reason": "not_planned", "why": "self-resolved"}],
        "labels": [{"number": 511, "add": ["feature", "P2"], "why": "phase of #526"},
                   {"number": 364, "remove": ["agent:queued"], "why": "stale"},
                   {"number": 504, "add": ["feature"], "remove": ["enhancement"], "why": "alias"}],
        "sub_issues": [{"parent": 454, "children": [465, 466], "why": "phases"}],
    },
    "board": {"status": {"closed": "Done", "needs-amr": "Needs Amr", "human-review": "Triaged", "default": "Triaged",
                         "pr": "In review", "pr_draft": "In progress"},
              "priority": {"default": "P2"},
              "area": {"labels": {"ci": "ci", "docs": "docs", "test": "ci"},
                       "keywords": {"agents": ["agent", "loop"], "site": ["site quality"]}, "default": "platform"}},
    "applied": [],
}
FRAMEWORK = {
    "schema": "projects/v1",
    "fields": {"Status": {"options": ["Inbox", "Triaged", "Ready", "In progress", "In review", "Blocked", "Done"]},
               "Priority": {"options": ["P0", "P1", "P2", "P3"]},
               "Area": {"options": ["platform", "ci", "docs", "security", "deps", "agents", "site", "ux"]}},
    "labels": {"canonical": {
        "P0": {"field": "Priority", "value": "P0"}, "P1": {"field": "Priority", "value": "P1"},
        "P2": {"field": "Priority", "value": "P2"}, "P3": {"field": "Priority", "value": "P3"},
        "agent:queued": {"field": "Status", "value": "Ready"}, "agent:ready": {"field": "Status", "value": "Ready"},
        "agent:in-pr": {"field": "Status", "value": "In review"}, "agent:blocked": {"field": "Status", "value": "Blocked"},
        "agent:hold": {"field": "Status", "value": "Blocked"}, "agent:done": {"field": "Status", "value": "Done"},
        "area:docs": {"field": "Area", "value": "docs"}, "area:a11y": {"field": "Area", "value": "ux"},
        "security": {"field": "Area", "value": "security"}, "dependencies": {"field": "Area", "value": "deps"}}},
}
ISSUES = {
    469: {"id": 1469, "number": 469, "state": "open", "title": "P0 service layer", "labels": [{"name": "roadmap"}, {"name": "P2"}]},
    359: {"id": 1359, "number": 359, "state": "open", "title": "lifehacker ci tag race", "labels": [{"name": "fleet-doctor"}]},
    511: {"id": 1511, "number": 511, "state": "open", "title": "Fleet-wide agent pause switch", "labels": [{"name": "deep-dive"}]},
    364: {"id": 1364, "number": 364, "state": "open", "title": "Site quality: fleet WARN rollup",
          "labels": [{"name": "agent:queued"}, {"name": "agent:blocked"}, {"name": "P2"}]},
    504: {"id": 1504, "number": 504, "state": "open", "title": "console a11y", "labels": [{"name": "enhancement"}]},
    454: {"id": 1454, "number": 454, "state": "open", "title": "Kaizen", "labels": [{"name": "roadmap"}]},
    465: {"id": 1465, "number": 465, "state": "open", "title": "[kaizen] doc", "labels": []},
    466: {"id": 1466, "number": 466, "state": "open", "title": "[kaizen] loop", "labels": []},
}
SUB_ISSUES = {454: [{"id": 1465}]}  # #465 already linked, #466 not


class FakeRunner:
    """Records every `gh api` call and answers from the fixtures above."""

    def __init__(self):
        self.calls: list[tuple[str, str, dict | None]] = []

    def __call__(self, args, stdin, env):
        method, path = args[3], args[4]
        body = json.loads(stdin) if stdin else None
        self.calls.append((method, path, body))
        parts = path.split("/")
        if method == "GET" and path.startswith(f"repos/{REPO}/issues/") and path.endswith("/sub_issues"):
            return 0, json.dumps(SUB_ISSUES.get(int(parts[4]), [])), ""
        if method == "GET" and path.startswith(f"repos/{REPO}/issues/"):
            n = int(parts[4])
            return (0, json.dumps(ISSUES[n]), "") if n in ISSUES else (1, "", "HTTP 404: Not Found")
        if method == "POST" and path.endswith("/labels"):
            return 0, json.dumps([{"name": l} for l in body["labels"]]), ""
        if method == "DELETE" and "/labels/" in path:
            return (0, "[]", "") if "agent%3Aqueued" in path or "enhancement" in path else (1, "", "HTTP 404 Label does not exist")
        if method == "PATCH":
            return 0, json.dumps({"state": body.get("state"), "state_reason": body.get("state_reason"), "title": "t"}), ""
        if method == "POST" and path.endswith("/sub_issues"):
            return 0, json.dumps({"number": 466}), ""
        if method == "POST" and path == "graphql":
            return 1, "", "gh: GitHub GraphQL is not available from Claude Code sessions (HTTP 403)"
        return 1, "", f"unexpected {method} {path}"


class DecisionsTests(unittest.TestCase):
    def test_fixture_validates(self):
        self.assertEqual(pb.validate_decisions(DECISIONS), [])

    def test_committed_decisions_file_validates(self):
        self.assertEqual(pb.validate_decisions(pb.yaml.safe_load(pb.DECISIONS.read_text())), [])

    def test_bad_decisions_are_named(self):
        bad = json.loads(json.dumps(DECISIONS))
        bad["issues"]["close"][0]["reason"] = "fixed"
        bad["issues"]["labels"].append({"number": 469, "add": ["P1"], "why": "x"})
        bad["issues"]["labels"].append({"number": 9, "add": ["a"], "remove": ["a"], "why": "x"})
        bad["issues"]["sub_issues"].append({"parent": 359, "children": [1], "why": "x"})
        errs = pb.validate_decisions(bad)
        self.assertTrue(any("reason" in e for e in errs))
        self.assertTrue(any("also being closed" in e for e in errs))
        self.assertTrue(any("both added and removed" in e for e in errs))
        self.assertTrue(any("parent or child is being closed" in e for e in errs))

    def test_compile_order_and_shapes(self):
        ops = pb.compile_issue_ops(DECISIONS, lambda n: 1000 + n)
        names = [o["op"] for o in ops]
        self.assertEqual(names, ["issue.labels.add", "issue.labels.remove", "issue.labels.add", "issue.labels.remove",
                                 "issue.sub_issue.add", "issue.sub_issue.add", "issue.state.set", "issue.state.set"])
        self.assertEqual(ops[0]["labels"], ["P2", "feature"])
        self.assertEqual(ops[4]["sub_issue_id"], 1465)
        self.assertEqual(ops[-1]["state_reason"], "not_planned")
        for o in ops:
            self.assertIn(o["op"], pb.gw.ALLOWLIST)

    def test_chunking_respects_the_cap(self):
        ops = [{"op": "issue.labels.add", "repo": REPO, "number": i, "labels": ["P2"]} for i in range(120)]
        parts = pb.chunk(ops)
        self.assertEqual([len(p) for p in parts], [50, 50, 20])

    def test_registry_allowlist_has_the_hub(self):
        self.assertIn("bamr87/bamr87", pb.registry_repos())


class RestTests(unittest.TestCase):
    def setUp(self):
        self.runner = FakeRunner()
        self.api = pb.IssueApi(pb.Gh(run=self.runner))

    def test_state_shapes_match_the_service(self):
        st = self.api.state({"op": "issue.labels.add", "repo": REPO, "number": 364, "labels": ["P2"]})
        self.assertEqual(st["labels"], ["P2", "agent:blocked", "agent:queued"])
        st = self.api.state({"op": "issue.sub_issue.add", "repo": REPO, "number": 454, "sub_issue_id": 1465})
        self.assertEqual(st, {"sub_issue_id": 1465})
        st = self.api.state({"op": "issue.sub_issue.add", "repo": REPO, "number": 454, "sub_issue_id": 1466})
        self.assertEqual(st, {"sub_issue_id": None})
        self.assertIsNone(self.api.state({"op": "issue.state.set", "repo": REPO, "number": 999, "state": "closed"}))

    def test_plan_marks_satisfied_ops_as_noops(self):
        ops = pb.compile_issue_ops(DECISIONS, lambda n: self.api.issue_id(REPO, n))
        batches = pb.plan_batches(ops, self.api.state, {REPO})
        self.assertEqual(len(batches), 1)
        rows = {(r["op"], r["target"]): r for r in batches[0]["rows"]}
        self.assertTrue(rows[("issue.sub_issue.add", f"{REPO}:number=454")]["noop"] or
                        any(r["noop"] for r in batches[0]["rows"] if r["op"] == "issue.sub_issue.add"))
        self.assertEqual(batches[0]["changes"], 7)
        again = pb.plan_batches(ops, self.api.state, {REPO})
        self.assertEqual(again[0]["plan_id"], batches[0]["plan_id"], "plan ids are deterministic")

    def test_executor_maps_ops_to_rest_calls(self):
        self.api.execute({"op": "issue.labels.add", "repo": REPO, "number": 511, "labels": ["P2", "feature"]})
        self.api.execute({"op": "issue.labels.remove", "repo": REPO, "number": 364, "labels": ["agent:queued"]})
        self.api.execute({"op": "issue.state.set", "repo": REPO, "number": 469, "state": "closed", "state_reason": "completed"})
        self.api.execute({"op": "issue.sub_issue.add", "repo": REPO, "number": 454, "sub_issue_id": 1466})
        writes = [(m, p, b) for m, p, b in self.runner.calls if m != "GET"]
        self.assertEqual(writes, [
            ("POST", f"repos/{REPO}/issues/511/labels", {"labels": ["P2", "feature"]}),
            ("DELETE", f"repos/{REPO}/issues/364/labels/agent%3Aqueued", None),
            ("PATCH", f"repos/{REPO}/issues/469", {"state": "closed", "state_reason": "completed"}),
            ("POST", f"repos/{REPO}/issues/454/sub_issues", {"sub_issue_id": 1466}),
        ])
        with self.assertRaises(pb.GhError):
            self.api.execute({"op": "pr.draft.set", "repo": REPO, "number": 1, "draft": True})

    def test_apply_refuses_without_flag_and_confirm(self):
        ops = pb.compile_issue_ops(DECISIONS, lambda n: self.api.issue_id(REPO, n))
        batches = pb.plan_batches(ops, self.api.state, {REPO})
        before = len(self.runner.calls)
        with tempfile.TemporaryDirectory() as td:
            audit = Path(td) / "audit.jsonl"
            old = os.environ.pop(pb.gw.FLAG, None)
            try:
                res = pb.gw.apply(batches[0]["plan_id"], ops, self.api.state, self.api.execute, confirm=True, audit=audit)
                self.assertIn("disabled", res["refused"])
                os.environ[pb.gw.FLAG] = "1"
                res = pb.gw.apply(batches[0]["plan_id"], ops, self.api.state, self.api.execute, confirm=False, audit=audit)
                self.assertIn("confirm", res["refused"])
            finally:
                os.environ.pop(pb.gw.FLAG, None)
                if old is not None:
                    os.environ[pb.gw.FLAG] = old
            self.assertFalse(audit.exists())
        self.assertEqual([c for c in self.runner.calls[before:] if c[0] != "GET"], [], "a refusal never writes")

    def test_apply_with_flag_writes_and_audits(self):
        ops = pb.compile_issue_ops(DECISIONS, lambda n: self.api.issue_id(REPO, n))
        batches = pb.plan_batches(ops, self.api.state, {REPO})
        with tempfile.TemporaryDirectory() as td:
            audit = Path(td) / "audit.jsonl"
            old = os.environ.get(pb.gw.FLAG)
            os.environ[pb.gw.FLAG] = "1"
            try:
                res = pb.gw.apply(batches[0]["plan_id"], ops, self.api.state, self.api.execute, confirm=True, audit=audit,
                                  actor="test", repo_allow={REPO})
            finally:
                os.environ.pop(pb.gw.FLAG, None)
                if old is not None:
                    os.environ[pb.gw.FLAG] = old
            self.assertEqual(res["applied"], 7)
            lines = [json.loads(l) for l in audit.read_text().splitlines()]
            self.assertEqual(len(lines), 8)
            self.assertEqual({l["result"] for l in lines}, {"applied", "noop"})
        writes = [c for c in self.runner.calls if c[0] in ("POST", "PATCH", "DELETE")]
        self.assertEqual(len(writes), 7)


class BoardTests(unittest.TestCase):
    def test_derive_fields_precedence(self):
        d = lambda labels, **kw: pb.derive_fields({"kind": "issue", "state": "open", "title": "", "labels": labels, **kw},
                                                  DECISIONS, FRAMEWORK)
        self.assertEqual(d(["agent:hold", "agent:ready"])["Status"], "Blocked")
        self.assertEqual(d(["agent:in-pr", "agent:blocked"])["Status"], "In review")
        self.assertEqual(d(["agent:queued", "needs-amr"])["Status"], "Needs Amr")
        self.assertEqual(d(["human-review"])["Status"], "Triaged")
        self.assertEqual(d(["feature", "P1"])["Status"], "Triaged")
        self.assertEqual(d(["feature", "P1"])["Priority"], "P1")
        self.assertEqual(d(["feature"])["Priority"], "P2")
        self.assertEqual(d(["ci", "security"])["Area"], "security")
        self.assertEqual(d(["ci"])["Area"], "ci")
        self.assertEqual(d(["feature"], title="repo-scout agent loop")["Area"], "agents")
        self.assertEqual(d(["feature"], title="Site quality: fleet WARN rollup")["Area"], "site")
        self.assertEqual(d(["feature"], title="something else")["Area"], "platform")
        closed = pb.derive_fields({"kind": "issue", "state": "closed", "labels": [], "title": ""}, DECISIONS, FRAMEWORK)
        self.assertEqual(closed["Status"], "Done")
        pr = pb.derive_fields({"kind": "pr", "state": "open", "labels": [], "title": "", "draft": True}, DECISIONS, FRAMEWORK)
        self.assertEqual(pr["Status"], "In progress")
        pr = pb.derive_fields({"kind": "pr", "state": "open", "labels": [], "title": "", "draft": False}, DECISIONS, FRAMEWORK)
        self.assertEqual(pr["Status"], "In review")

    def test_needs_amr_falls_back_when_the_project_has_no_such_option(self):
        got = pb.derive_fields({"kind": "issue", "state": "open", "title": "", "labels": ["needs-amr"]}, DECISIONS, FRAMEWORK,
                               options={"Status": ["Triaged", "Blocked", "Done"]})
        self.assertEqual(got["Status"], "Blocked")

    def test_board_ops_add_then_fields(self):
        board = pb.Board(pb.Gh(run=FakeRunner()), "bamr87", 14)
        board.project = {"id": "PVT_fleet", "title": "Fleet", "fields": {
            "Status": {"id": "F_s", "type": "SINGLE_SELECT", "options": {"Triaged": "o1", "Blocked": "o2", "Done": "o3"}},
            "Priority": {"id": "F_p", "type": "SINGLE_SELECT", "options": {"P1": "p1", "P2": "p2"}},
            "Area": {"id": "F_a", "type": "SINGLE_SELECT", "options": {"platform": "a1", "ci": "a2"}}}}
        board.items[(REPO, 511)] = {"item_id": "PVTI_511", "fields": {"Status": "Triaged", "Priority": "P3"}, "repo": REPO, "number": 511}
        targets = [
            {"repo": REPO, "number": 511, "node_id": "I_511", "title": "x", "state": "open", "labels": ["feature", "P2", "ci"], "kind": "issue"},
            {"repo": REPO, "number": 512, "node_id": "I_512", "title": "y", "state": "open", "labels": ["P1"], "kind": "issue"},
            {"repo": REPO, "number": 513, "node_id": "I_513", "title": "z", "state": "open", "labels": ["P0", "agent:blocked"], "kind": "issue"},
        ]
        board.items[(REPO, 513)] = {"item_id": "PVTI_513", "fields": {}, "repo": REPO, "number": 513}
        ops, notes = pb.board_ops(board, targets, DECISIONS, FRAMEWORK)
        kinds = [(o["op"], o["number"], o.get("field"), o.get("value")) for o in ops]
        self.assertIn(("item.add", 512, None, None), kinds)
        self.assertIn(("item.set_field", 511, "Priority", "P2"), kinds)
        self.assertIn(("item.set_field", 511, "Area", "ci"), kinds)
        self.assertNotIn(("item.set_field", 511, "Status", "Triaged"), kinds, "unchanged fields are not planned")
        self.assertIn(("item.set_field", 513, "Status", "Blocked"), kinds)
        self.assertTrue(any("P0" in n and "513" in n for n in notes), "an option the project lacks is a note, not an op")
        for o in ops:
            self.assertIn(o["op"], pb.gw.ALLOWLIST)
        batches = pb.plan_batches(ops, board.state, {REPO})
        self.assertEqual(batches[0]["changes"], len(ops))

    def test_board_load_says_graphql_unavailable(self):
        board = pb.Board(pb.Gh(run=FakeRunner()), "bamr87", 14)
        self.assertFalse(board.load())
        self.assertTrue(board.error.startswith("graphql_unavailable"), board.error)


def _row(n: int, state: str = "open", closed_at: str | None = None, reason: str | None = None, labels=()) -> dict:
    return {"number": n, "node_id": f"I_{n}", "title": f"item {n}", "state": state, "closed_at": closed_at,
            "state_reason": reason, "labels": [{"name": l} for l in labels]}


OTHER = "bamr87/law-ai"
LISTS = {  # repo -> open rows, closed rows
    REPO: ([_row(1550, labels=["P1"])],
           [_row(700, "closed", "2026-09-01T10:00:00Z", "completed"),
            _row(701, "closed", "2026-10-03T12:00:00Z", "not_planned"),   # the cleanup: excluded
            _row(702, "closed", "2026-10-03T12:00:00Z", "completed"),     # same day, but completed: kept
            _row(703, "closed", "2026-07-01T10:00:00Z", "completed")]),   # before the window
    OTHER: ([_row(208, labels=["P1", "bug"])], [_row(150, "closed", "2026-11-01T00:00:00Z", "completed")]),
}
PROJECT_SIZE = 600  # more than gp.MAX_ITEMS (500): the old read cap


class TargetRunner(FakeRunner):
    """FakeRunner plus issue lists per repo and a 600-item Fleet project over GraphQL."""

    def __call__(self, args, stdin, env):
        method, path = args[3], args[4]
        params = dict(a.split("=", 1) for a in args[5:] if "=" in a and not a.startswith("-"))
        if method == "GET" and path.endswith("/issues") and path.startswith("repos/"):
            self.calls.append((method, path, params))
            repo = path[len("repos/"):-len("/issues")]
            opened, closed = LISTS.get(repo, ([], []))
            if int(params.get("page", 1)) > 1:
                return 0, "[]", ""
            rows = opened if params.get("state") == "open" else closed
            if params.get("since"):
                rows = [r for r in rows if (r.get("closed_at") or "") >= params["since"]]
            return 0, json.dumps(rows), ""
        if method == "POST" and path == "graphql":
            body = json.loads(stdin)
            self.calls.append((method, path, body["variables"]))
            q = body["query"]
            if "projectV2(number" in q:
                return 0, json.dumps({"data": {"user": {"projectV2": {"id": "PVT_fleet", "title": "Fleet", "url": "u",
                                                                       "closed": False, "fields": {"nodes": [
                    {"id": "F_s", "name": "Status", "dataType": "SINGLE_SELECT",
                     "options": [{"id": "o1", "name": "Triaged"}, {"id": "o3", "name": "Done"}]},
                    {"id": "F_p", "name": "Priority", "dataType": "SINGLE_SELECT",
                     "options": [{"id": "p1", "name": "P1"}, {"id": "p2", "name": "P2"}]}]}}}}}), ""
            after = int(body["variables"].get("after") or 0)
            nodes = [{"id": f"PVTI_{n}", "isArchived": False, "type": "ISSUE",
                      "fieldValues": {"nodes": [{"name": "Triaged", "field": {"name": "Status"}},
                                                {"name": "P1", "field": {"name": "Priority"}}]},
                      "content": {"__typename": "Issue", "id": f"I_{n}", "number": n, "title": "t", "state": "OPEN",
                                  "url": "u", "body": "", "repository": {"nameWithOwner": REPO}}}
                     for n in range(1000 + after, min(1000 + after + 100, 1000 + PROJECT_SIZE))]
            end = after + 100
            return 0, json.dumps({"data": {"node": {"items": {"nodes": nodes, "pageInfo": {
                "hasNextPage": end < PROJECT_SIZE, "endCursor": str(end)}}}}}), ""
        return super().__call__(args, stdin, env)


class TargetingTests(unittest.TestCase):
    """#453: registry-wide and closed-window targets, the cleanup exclusion, dedupe past 500 items."""

    def setUp(self):
        self.runner = TargetRunner()
        self.gh = pb.Gh(run=self.runner)

    def test_registry_targets_more_than_one_repo(self):
        repos = pb.target_repos(DECISIONS, "registry", registry=lambda: {OTHER})
        self.assertEqual(repos, sorted({REPO, OTHER}))
        self.assertEqual(pb.target_repos(DECISIONS, "hub"), [REPO], "the default is unchanged")
        targets, counts = pb.board_targets(self.gh, repos, DECISIONS)
        self.assertEqual({t["repo"] for t in targets}, {REPO, OTHER})
        self.assertEqual(set(counts), {REPO, OTHER})

    def test_closed_window_selects_only_the_window_and_derives_done(self):
        items = pb.closed_items(self.gh, REPO, since="2026-08-14", before="2026-11-01")
        self.assertEqual(sorted(t["number"] for t in items), [700, 701, 702])
        targets, counts = pb.board_targets(self.gh, [REPO], DECISIONS, include_open=False,
                                           closed_since="2026-08-14", closed_before="2026-11-01")
        self.assertEqual(sorted(t["number"] for t in targets), [700, 702])
        for t in targets:
            self.assertEqual(pb.derive_fields(t, DECISIONS, FRAMEWORK)["Status"], "Done")
        before_only = pb.closed_items(self.gh, REPO, before="2026-08-14")
        self.assertEqual([t["number"] for t in before_only], [703])

    def test_cleanup_is_excluded(self):
        targets, counts = pb.board_targets(self.gh, [REPO], DECISIONS, include_open=False, closed_since="2026-10-01")
        self.assertNotIn(701, [t["number"] for t in targets])
        self.assertIn(702, [t["number"] for t in targets], "only not_planned on the cleanup day is dropped")
        self.assertEqual(counts[REPO]["excluded"], 1)
        d = json.loads(json.dumps(DECISIONS))
        d["board"]["exclude"] = {"closed_not_planned_on": []}
        targets, _ = pb.board_targets(self.gh, [REPO], d, include_open=False, closed_since="2026-10-01")
        self.assertIn(701, [t["number"] for t in targets], "the decisions file can change the dates")
        d["board"]["exclude"] = {"closed_not_planned_on": ["Oct 3"]}
        self.assertTrue(any("YYYY-MM-DD" in e for e in pb.validate_decisions(d)))

    def test_plan_past_500_items_adds_nothing_already_on_the_project(self):
        old = pb.Gh._subprocess
        pb.Gh._subprocess = staticmethod(self.runner)
        try:
            with tempfile.TemporaryDirectory() as td:
                dec, out = Path(td) / "d.yml", Path(td) / "plan.json"
                dec.write_text(pb.yaml.safe_dump(DECISIONS))
                with contextlib.redirect_stdout(io.StringIO()):
                    rc = pb.main(["plan", "--board", "--json", "--decisions", str(dec), "--out", str(out)])
                self.assertEqual(rc, 0)
                preview = json.loads(out.read_text())
        finally:
            pb.Gh._subprocess = old
        self.assertEqual(preview["board"]["status"], "planned", preview["board"])
        self.assertEqual(preview["board"]["items_on_project"], PROJECT_SIZE)
        self.assertGreaterEqual(preview["max_items"], PROJECT_SIZE, "apply re-reads the project with the same cap")
        board_ops = [o for b in preview["batches"] if b.get("board") for o in b["ops"]]
        self.assertNotIn(("item.add", 1550), [(o["op"], o["number"]) for o in board_ops],
                         "#1550 is item 551 of the project: it is on the board already")


class LedgerTests(unittest.TestCase):
    def test_record_applied_appends_in_place(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "d.yml"
            p.write_text("# header comment\nschema: projects-backfill/v1\nissues:\n  close: []\napplied: []\n")
            pb.record_applied(p, {"plan_id": "abc", "at": "2026-11-04T00:00:00Z", "batch": 1, "applied": 3, "noop": 1})
            pb.record_applied(p, {"plan_id": "def", "at": "2026-11-04T01:00:00Z", "batch": 2, "applied": 0, "noop": 4})
            text = p.read_text()
            self.assertTrue(text.startswith("# header comment\n"))
            d = pb.yaml.safe_load(text)
            self.assertEqual([r["plan_id"] for r in d["applied"]], ["abc", "def"])
            self.assertEqual(d["issues"], {"close": []})


if __name__ == "__main__":
    unittest.main(verbosity=1)
