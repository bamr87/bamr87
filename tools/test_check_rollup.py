#!/usr/bin/env python3
"""Offline tests for tools/check_rollup.py, the one rule every PR reducer reads a commit's checks by: a
CANCELLED check run is set aside when a later run of the same check (workflow and name) on the commit
exists, and nothing else is. The reducers' own cases live beside them (test_weekly_dispositions.py,
console/test_decision_index.py, test_pm_review.py). Run: python3 tools/test_check_rollup.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_rollup as cr  # noqa: E402


def flat(conclusion, started, completed=None, status="COMPLETED", name="Visual evidence gate", workflow="Evidence gate"):
    """A check run as `gh pr view --json statusCheckRollup` flattens it."""
    return {"__typename": "CheckRun", "workflowName": workflow, "name": name, "status": status, "conclusion": conclusion,
            "startedAt": started, "completedAt": completed or started}


def nested(conclusion, started, completed=None, status="COMPLETED", name="Visual evidence gate", workflow="Evidence gate"):
    """The same run as GraphQL returns it under ROLLUP_FIELDS."""
    return {"__typename": "CheckRun", "name": name, "status": status, "conclusion": conclusion, "startedAt": started,
            "completedAt": completed or started, "checkSuite": {"workflowRun": {"workflow": {"name": workflow}}}}


T0, T1, T2 = "2026-11-14T05:31:38Z", "2026-11-14T05:31:43Z", "2026-11-14T05:40:00Z"


class Current(unittest.TestCase):
    def test_a_cancelled_run_a_later_run_superseded_is_set_aside_in_either_shape(self):
        for make in (flat, nested):
            cancelled, passed = make("CANCELLED", T0), make("SUCCESS", T1)
            keep, aside = cr.current([cancelled, passed])
            self.assertEqual((keep, aside), ([passed], [cancelled]), make.__name__)

    def test_the_latest_run_of_a_check_is_never_set_aside(self):
        runs = [flat("CANCELLED", T0), flat("CANCELLED", T1), flat("CANCELLED", T2)]
        keep, aside = cr.current(runs)
        self.assertEqual((keep, len(aside)), ([runs[2]], 2))
        self.assertEqual(cr.current([flat("CANCELLED", T0)]), ([flat("CANCELLED", T0)], []))

    def test_only_a_cancellation_is_set_aside(self):
        for conclusion in ("FAILURE", "TIMED_OUT", "STARTUP_FAILURE", "ACTION_REQUIRED", "SKIPPED", "SUCCESS"):
            rows = [flat(conclusion, T0), flat("SUCCESS", T1)]
            self.assertEqual(cr.current(rows), (rows, []), conclusion)

    def test_a_check_is_its_workflow_and_its_name(self):
        cancelled = flat("CANCELLED", T0)
        for other in (flat("SUCCESS", T1, name="build"), flat("SUCCESS", T1, workflow="CI")):
            self.assertEqual(cr.current([cancelled, other])[1], [])
        no_workflow = [flat("CANCELLED", T0, workflow=""), flat("SUCCESS", T1, workflow="")]
        self.assertEqual(cr.current(no_workflow)[1], [], "a third-party app's check run is judged as it stands")
        third_party = [{"__typename": "CheckRun", "name": "x", "status": "COMPLETED", "conclusion": c, "startedAt": t,
                        "completedAt": t, "checkSuite": {"workflowRun": None}} for c, t in (("CANCELLED", T0), ("SUCCESS", T1))]
        self.assertEqual(cr.current(third_party)[1], [])

    def test_runs_that_started_in_the_same_second_are_ordered_by_their_end(self):
        cancelled = flat("CANCELLED", T0, "2026-11-14T05:31:39Z")
        later = flat("SUCCESS", T0, "2026-11-14T05:32:07Z")
        self.assertEqual(cr.current([later, cancelled])[1], [cancelled])
        twin = flat("SUCCESS", T0, "2026-11-14T05:31:39Z")
        self.assertEqual(cr.current([cancelled, twin])[1], [], "a tie on both stamps proves nothing")
        running = flat(None, T0, None, status="IN_PROGRESS")
        running["completedAt"] = None
        self.assertEqual(cr.current([cancelled, running])[1], [cancelled], "a run still going ends after it")

    def test_a_run_that_has_not_started_is_later_and_an_unreadable_time_is_not(self):
        cancelled = flat("CANCELLED", T0)
        queued = {**flat(None, T0, status="QUEUED"), "startedAt": None, "completedAt": None}
        self.assertEqual(cr.current([cancelled, queued])[1], [cancelled])
        for bad in (None, "", "yesterday", 17):
            self.assertEqual(cr.current([cancelled, {**flat("SUCCESS", T1), "startedAt": bad}])[1], [], bad)
            self.assertEqual(cr.current([{**cancelled, "startedAt": bad}, flat("SUCCESS", T1)])[1], [], bad)

    def test_status_contexts_and_junk_pass_through(self):
        status = {"__typename": "StatusContext", "context": "ci/x", "state": "FAILURE"}
        flattened = {"context": "ci/y", "state": "SUCCESS"}
        rows = [status, flattened, flat("CANCELLED", T0), flat("SUCCESS", T1)]
        keep, aside = cr.current([*rows, "junk", None, 3])
        self.assertEqual((keep, aside), ([status, flattened, rows[3]], [rows[2]]))
        self.assertEqual(cr.current(None), ([], []))


class Verdict(unittest.TestCase):
    def test_states(self):
        ok = flat("SUCCESS", T1)
        self.assertEqual(cr.verdict([ok, flat("SKIPPED", T1, name="b"), flat("NEUTRAL", T1, name="c")]), "SUCCESS")
        self.assertEqual(cr.verdict([ok, flat(None, T1, status="IN_PROGRESS", name="b")]), "PENDING")
        self.assertEqual(cr.verdict([ok, {"__typename": "StatusContext", "context": "s", "state": "EXPECTED"}]), "PENDING")
        for bad in ("FAILURE", "CANCELLED", "TIMED_OUT", "STALE", "", None):
            self.assertEqual(cr.verdict([ok, flat(bad, T1, name="b")]), "FAILURE", bad)
        for state in ("FAILURE", "ERROR", "", None):
            self.assertEqual(cr.verdict([ok, {"__typename": "StatusContext", "context": "s", "state": state}]), "FAILURE", state)
        self.assertIsNone(cr.verdict([]))


class CorrectedState(unittest.TestCase):
    @staticmethod
    def rollup(*nodes, state="FAILURE", more=False):
        return {"state": state, "contexts": {"pageInfo": {"hasNextPage": more}, "nodes": list(nodes)}}

    def test_only_a_red_that_was_a_superseded_cancellation_is_taken_back(self):
        cancelled, passed = nested("CANCELLED", T0), nested("SUCCESS", T1)
        self.assertEqual(cr.corrected_state(self.rollup(cancelled, passed)), "SUCCESS")
        self.assertEqual(cr.corrected_state(self.rollup(cancelled, passed, state="ERROR")), "SUCCESS")
        running = {**nested(None, T1, status="IN_PROGRESS"), "completedAt": None}
        self.assertEqual(cr.corrected_state(self.rollup(cancelled, running)), "PENDING")
        failed_elsewhere = nested("FAILURE", T1, name="build")
        self.assertEqual(cr.corrected_state(self.rollup(cancelled, passed, failed_elsewhere)), "FAILURE")
        self.assertEqual(cr.corrected_state(self.rollup(cancelled, passed, failed_elsewhere, state="ERROR")), "ERROR")
        self.assertEqual(cr.corrected_state(self.rollup(cancelled)), "FAILURE")

    def test_anything_it_cannot_prove_is_github_s_state(self):
        cancelled, passed = nested("CANCELLED", T0), nested("SUCCESS", T1)
        self.assertEqual(cr.corrected_state(self.rollup(cancelled, passed, more=True)), "FAILURE", "a second page")
        self.assertEqual(cr.corrected_state({"state": "FAILURE", "contexts": {"nodes": [cancelled, passed]}}), "FAILURE",
                         "no pageInfo: not known to be the whole")
        self.assertEqual(cr.corrected_state({"state": "FAILURE"}), "FAILURE")
        self.assertEqual(cr.corrected_state({"state": "FAILURE", "contexts": {"pageInfo": {"hasNextPage": False}, "nodes": None}}), "FAILURE")
        for state in ("SUCCESS", "PENDING", "EXPECTED", None):
            self.assertEqual(cr.corrected_state(self.rollup(cancelled, state=state)), state, "it never turns anything red")
        self.assertIsNone(cr.corrected_state(None))
        self.assertIsNone(cr.corrected_state({}))

    def test_the_selection_names_every_field_the_rule_reads(self):
        for field in ("state", "contexts(first:100)", "hasNextPage", "__typename", "name", "status", "conclusion",
                      "startedAt", "completedAt", "workflow{ name }", "context"):
            self.assertIn(field, cr.ROLLUP_FIELDS, field)
        self.assertNotIn("mutation", cr.ROLLUP_FIELDS)


if __name__ == "__main__":
    unittest.main()
