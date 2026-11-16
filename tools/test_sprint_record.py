#!/usr/bin/env python3
"""Tests for tools/sprint_record.py — the live expedite-sprint record (`sprint/v1`,
constitution § 27.7). The fixture records are tools/test_sprint_record_fixture.yml;
each test writes what it needs into a scratch directory, never into _data/.
Offline, no pytest:  python3 tools/test_sprint_record.py"""
from __future__ import annotations

import copy
import datetime as dt
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sprint_record as sr  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "test_sprint_record_fixture.yml"
NOW = dt.datetime(2026, 11, 15, 12, 0, tzinfo=dt.timezone.utc)
FLEET = {"hub": {"repo": "bamr87/bamr87"}}


def fixtures() -> list[dict]:
    return [d for d in yaml.safe_load_all(FIXTURE.read_text(encoding="utf-8")) if d]


def active() -> dict:
    return copy.deepcopy(next(d for d in fixtures() if d["state"] == "active"))


def lint(record: dict, *, fleet=None, order=None, now=NOW) -> tuple[list[str], list[str]]:
    queue = order if order is not None else [f"issue:{record.get('item')}"]
    return sr.lint_record(record, name=record.get("slug"), fleet=fleet or FLEET, queue_order=queue, now=now)


class Tree:
    """A scratch _data: a sprints directory, a fleet.yml and a work_queue.yml."""

    def __init__(self, records: list[dict], *, order: list[str] | None = None, fleet: dict | None = None):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.dir = root / "sprints"
        self.dir.mkdir()
        for r in records:
            (self.dir / f"{r['slug']}.yml").write_text(yaml.safe_dump(r, sort_keys=False), encoding="utf-8")
        self.fleet = root / "fleet.yml"
        self.fleet.write_text(yaml.safe_dump(fleet or FLEET), encoding="utf-8")
        self.queue = root / "work_queue.yml"
        if order is None:
            order = [f"issue:{r['item']}" for r in records if r.get("state") == "active"]
        self.queue.write_text(yaml.safe_dump({"schema": "work-queue/v1", "order": order}), encoding="utf-8")

    def lint(self):
        return sr.lint_dir(self.dir, self.fleet, self.queue, now=NOW)

    def doc(self):
        return sr.document(self.dir, self.fleet, self.queue, now=NOW)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.tmp.cleanup()


class SprintRecordTests(unittest.TestCase):
    # --- a valid record passes --------------------------------------------------
    def test_the_fixture_records_lint_clean(self):
        records = fixtures()
        self.assertEqual({r["state"] for r in records}, {"active", "stopped"})
        with Tree(records) as t:
            res = t.lint()
        self.assertEqual(res["errors"], [])
        self.assertEqual(res["warnings"], [])
        self.assertEqual(res["active"], ["fixture-inquiry-form"])

    def test_the_hub_tree_lints_clean(self):
        res = sr.lint_dir()
        self.assertEqual(res["errors"], [], res["errors"])
        self.assertLessEqual(len(res["active"]), 1)
        self.assertTrue((sr.SPRINTS_DIR / "SCHEMA.md").is_file() and (sr.SPRINTS_DIR / "README.md").is_file())

    # --- WIP 1 ------------------------------------------------------------------
    def test_two_active_sprints_are_refused(self):
        second = active()
        second["slug"] = "fixture-second"
        second["item"] = "example-org/example-site#99"
        with Tree([active(), second]) as t:
            res = t.lint()
        self.assertTrue(any("2 active expedite sprints" in e and "WIP 1" in e for e in res["errors"]), res["errors"])

    # --- the gates: in order, Amr's, each opening its phase ---------------------
    def test_a_merge_gate_before_the_spec_gate_is_refused(self):
        r = active()
        r["gates"]["merge"] = {"by": "bamr87", "at": "2026-11-14T10:00:00Z", "ref": "https://github.com/example-org/example-site/pull/15"}
        r["gates"]["spec"] = None
        r["phase"] = 1
        errors, _ = lint(r)
        self.assertTrue(any("merge gate passed before the spec gate" in e for e in errors), errors)

    def test_a_merge_gate_dated_before_the_spec_gate_is_refused(self):
        r = active()
        r["gates"]["merge"] = {"by": "bamr87", "at": "2026-11-13T09:00:00Z", "ref": "https://github.com/example-org/example-site/pull/15"}
        errors, _ = lint(r)
        self.assertTrue(any("merge gate is dated" in e and "before the spec gate" in e for e in errors), errors)
        r["gates"]["merge"]["at"] = "2026-11-15T09:00:00Z"
        self.assertEqual(lint(r)[0], [])

    def test_a_phase_needs_the_gate_that_opens_it(self):
        r = active()
        r["gates"]["spec"] = None
        errors, _ = lint(r)
        self.assertTrue(any("phase 3 (test) needs the spec gate" in e for e in errors), errors)
        r["phase"] = 4
        r["gates"]["spec"] = active()["gates"]["spec"]
        errors, _ = lint(r)
        self.assertTrue(any("phase 4 (deploy) needs the merge gate" in e for e in errors), errors)

    def test_only_the_maintainer_passes_a_gate(self):
        r = active()
        r["gates"]["spec"]["by"] = "claude-code"
        errors, _ = lint(r)
        self.assertTrue(any("gates.spec.by" in e and "§ 27.2" in e for e in errors), errors)
        r["gates"]["spec"]["by"] = "github-actions[bot]"
        self.assertTrue(any("gates.spec.by" in e for e in lint(r)[0]))
        r["gates"]["spec"]["by"] = "BAMR87"                  # a login, compared as GitHub does
        self.assertEqual(lint(r)[0], [])

    def test_an_active_sprint_is_declared_in_the_work_queue(self):
        errors, _ = lint(active(), order=[])
        self.assertTrue(any("not in _data/work_queue.yml `order:`" in e for e in errors), errors)

    def test_a_gate_records_who_when_and_where(self):
        r = active()
        del r["gates"]["spec"]["ref"]
        errors, _ = lint(r)
        self.assertIn("`gates.spec.ref` is required", errors)
        r = active()
        del r["gates"]["merge"]
        self.assertTrue(any("gates.merge` is missing" in e for e in lint(r)[0]))

    # --- no secrets -------------------------------------------------------------
    def test_a_secret_like_value_is_refused_and_never_repeated(self):
        token = "ghp_" + "A1b2C3d4E5" * 4
        r = active()
        r["notes"] = f"deploy with {token}"
        errors, _ = lint(r)
        self.assertTrue(any("secret-looking value" in e and "`notes`" in e for e in errors), errors)
        self.assertFalse(any(token in e for e in errors))
        r = active()
        r["gates"]["spec"]["by"] = token                   # a field another rule would quote
        errors, _ = lint(r)
        self.assertFalse(any(token in e for e in errors), errors)
        for shaped in ("sk-ant-api03-abcdefghijkl", "Bearer abcdef0123456789xyz", "https://user:pa55word@example.org/x"):
            r = active()
            r["items"][0]["title"] = shaped
            self.assertTrue(any("secret-looking" in e for e in lint(r)[0]), shaped)

    def test_a_key_that_names_a_credential_is_refused(self):
        r = active()
        r["dora"] = {"api_key": "not-a-real-one"}
        self.assertTrue(any("`dora.api_key`" in e for e in lint(r)[0]))

    def test_a_record_with_a_secret_is_withheld_from_the_document(self):
        r = active()
        token = "github_pat_" + "x1Y2z3" * 5
        r["notes"] = token
        with Tree([r]) as t:
            doc = t.doc()
        self.assertTrue(doc["sprints"][0]["withheld"])
        self.assertNotIn(token, json.dumps(doc))
        self.assertNotIn("notes", doc["sprints"][0])

    # --- money is labelled, finite and inside the appetite ----------------------
    def test_an_unlabelled_usd_figure_is_refused(self):
        r = active()
        del r["spend"]["label"]
        errors, _ = lint(r)
        self.assertTrue(any("`spend.usd`: an unlabelled USD figure" in e for e in errors), errors)
        r = active()
        r["cost_usd"] = 4
        self.assertTrue(any("`cost_usd`: an unlabelled USD figure" in e for e in lint(r)[0]))
        r = active()
        r["trip_wires"][0]["rule"] = "Spend passes $20"
        self.assertTrue(any("dollar figure in text" in e for e in lint(r)[0]))
        r["trip_wires"][0]["rule"] = f"Spend passes $20 {sr.COST_LABEL}"
        self.assertEqual(lint(r)[0], [])

    def test_a_non_finite_usd_figure_is_refused(self):
        for bad in (float("nan"), float("inf"), -1, "ten", True):
            r = active()
            r["spend"]["usd"] = bad
            self.assertTrue(any("finite number" in e for e in lint(r)[0]), bad)

    def test_the_cap_is_the_appetite_and_the_fleet_ceiling(self):
        r = active()
        r["spend"]["cap_usd"] = 30
        self.assertTrue(any("must equal `appetite.usd`" in e for e in lint(r)[0]))
        ceiling = {"hub": {"repo": "bamr87/bamr87"}, "budget": {"sprints": {"fixture-inquiry-form": {"usd": 20, "hours": 16}}}}
        self.assertTrue(any("budget.sprints.fixture-inquiry-form" in e for e in lint(active(), fleet=ceiling)[0]))
        ceiling["budget"]["sprints"]["fixture-inquiry-form"]["usd"] = 25
        self.assertEqual(lint(active(), fleet=ceiling)[0], [])
        # #689's declaration shape: the work-queue item and the end of the time box agree too
        declared = ceiling["budget"]["sprints"]["fixture-inquiry-form"]
        declared.update(item="issue:example-org/example-site#12", ends="2026-11-18T17:00:00Z")
        self.assertEqual(lint(active(), fleet=ceiling)[0], [])
        declared.update(item="issue:example-org/example-site#99", ends=dt.date(2026, 11, 20))
        errors = lint(active(), fleet=ceiling)[0]
        self.assertTrue(any("budget.sprints.fixture-inquiry-form.item" in e for e in errors), errors)
        self.assertTrue(any("budget.sprints.fixture-inquiry-form.ends" in e for e in errors), errors)
        other = {"hub": {"repo": "bamr87/bamr87"}, "budget": {"sprints": {"another": {"usd": 5}}}}
        self.assertTrue(any("declares no ceiling" in w for w in lint(active(), fleet=other)[1]))

    # --- the circuit breaker ----------------------------------------------------
    def test_an_active_sprint_at_its_cap_must_stop(self):
        r = active()
        r["spend"]["usd"] = 25
        errors, _ = lint(r)
        self.assertTrue(any("circuit breaker" in e and "reason `cap`" in e for e in errors), errors)
        r["state"] = "stopped"
        r["stop"] = {"at": "2026-11-15T09:00:00Z", "reason": "cap", "filed": ["example-org/example-site#15"]}
        errors, _ = lint(r)
        self.assertEqual(errors, [])

    def test_a_finished_time_box_warns(self):
        _, warnings = lint(active(), now=dt.datetime(2026, 11, 19, tzinfo=dt.timezone.utc))
        self.assertTrue(any("time box ended" in w for w in warnings), warnings)

    def test_the_lifecycle_needs_its_records(self):
        r = active()
        r["state"] = "stopped"
        self.assertTrue(any("records its stop" in e for e in lint(r)[0]))
        r = active()
        r["state"] = "done"
        errors, _ = lint(r)
        self.assertTrue(any("`done` sprint needs the merge gate" in e for e in errors))
        self.assertTrue(any("retro" in e for e in errors))
        r = active()
        r["state"] = "proposed"
        self.assertTrue(any("not `proposed`" in e for e in lint(r)[0]))

    # --- the shape --------------------------------------------------------------
    def test_the_slug_names_the_file_and_unknown_keys_are_refused(self):
        r = active()
        errors, _ = sr.lint_record(r, name="other-name", fleet=FLEET, queue_order=[f"issue:{r['item']}"], now=NOW)
        self.assertTrue(any("must agree" in e for e in errors))
        r["phasse"] = 2
        self.assertTrue(any("`phasse`: unknown key" in e for e in lint(r)[0]))
        for bad in ({"item": "not a ref"}, {"phase": 9}, {"state": "paused"}, {"schema": "sprint/v2"}):
            r = active()
            r.update(bad)
            self.assertTrue(lint(r)[0], bad)

    def test_invalid_yaml_is_a_finding_not_a_crash(self):
        with Tree([]) as t:
            (t.dir / "broken.yml").write_text("slug: [unclosed\n", encoding="utf-8")
            res = t.lint()
            doc = t.doc()
        self.assertTrue(any(e.startswith("broken: not valid YAML") for e in res["errors"]))
        self.assertTrue(doc["sprints"][0]["withheld"])

    # --- the console's document -------------------------------------------------
    def test_the_document_orders_and_summarises_the_records(self):
        with Tree(fixtures()) as t:
            doc = t.doc()
            scratch = t.tmp.name
        self.assertEqual(doc["schema"], sr.DOC_SCHEMA)
        self.assertEqual(doc["active"], "fixture-inquiry-form")
        self.assertEqual([s["slug"] for s in doc["sprints"]], ["fixture-inquiry-form", "fixture-quote-calculator"])
        first = doc["sprints"][0]
        self.assertEqual((first["phase_name"], first["gates_passed"]), ("test", 2))
        self.assertAlmostEqual(first["spend_ratio"], 9.4 / 25)
        self.assertEqual(first["gates"]["declaration"]["at"], "2026-11-12T09:05:00Z")
        self.assertEqual(doc["cost_label"], sr.COST_LABEL)
        text = json.dumps(doc)
        self.assertNotIn(scratch, text)
        self.assertNotIn("/Users/", text)
        self.assertEqual(first["path"], "fixture-inquiry-form.yml")

    def test_an_empty_directory_is_an_empty_document(self):
        with Tree([]) as t:
            doc = t.doc()
        self.assertEqual((doc["count"], doc["active"], doc["sprints"], doc["errors"]), (0, None, [], []))
        missing = sr.document(Path(tempfile.gettempdir()) / "no-such-sprints-dir", now=NOW)
        self.assertEqual(missing["sprints"], [])

    def test_the_cli_exit_status_follows_the_errors(self):
        with Tree(fixtures()) as t:
            out = io.StringIO()
            with redirect_stdout(out):
                rc = sr.main(["lint", "--dir", str(t.dir), "--fleet", str(t.fleet), "--queue", str(t.queue)])
            self.assertEqual(rc, 0, out.getvalue())
            self.assertTrue(out.getvalue().strip().splitlines()[-1].startswith("sprint records: 2 record(s), 1 active"))
            second = active()
            second["slug"] = "fixture-second"
            (t.dir / "fixture-second.yml").write_text(yaml.safe_dump(second), encoding="utf-8")
            out = io.StringIO()
            with redirect_stdout(out):
                rc = sr.main(["lint", "--dir", str(t.dir), "--fleet", str(t.fleet), "--queue", str(t.queue)])
            self.assertEqual(rc, 1)
            self.assertIn("  ✗ ", out.getvalue())


if __name__ == "__main__":
    unittest.main()
