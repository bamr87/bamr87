#!/usr/bin/env python3
"""Tests for tools/fleetcore/assistlog.py — what the console's assistant did, read back from its two
records: the page bridge's audit and its rows of the AI ledger. Offline, no pytest:
python3 tools/test_fleetcore_assistlog.py"""
from __future__ import annotations

import contextlib
import datetime as dt
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

HUB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HUB / "tools"))
from fleetcore import assistlog as al  # noqa: E402

NOW = dt.datetime(2026, 11, 20, 12, 0, tzinfo=dt.timezone.utc)


def line(**row) -> str:
    base = {"id": "aaaaaaaaaaaa", "at": "2026-11-20T10:00:00+00:00", "session": "abcd1234", "client": "dock",
            "kind": "console", "action": "snapshot", "target": "", "mode": "look", "outcome": "ok", "ms": 40}
    return json.dumps({**base, **row})


class Tmp(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="assistlog-"))
        self.audit = self.dir / "assist" / "page-audit.jsonl"
        self.audit.parent.mkdir(parents=True)
        self.ledger = self.dir / "ledger.json"

    def write_audit(self, *lines: str, rotated: tuple[str, ...] = ()) -> None:
        self.audit.write_text("\n".join(lines) + "\n", encoding="utf-8")
        if rotated:
            self.audit.with_suffix(".jsonl.1").write_text("\n".join(rotated) + "\n", encoding="utf-8")

    def write_ledger(self, *runs: dict) -> None:
        self.ledger.write_text(json.dumps({"version": 2, "runs": {r["session_id"]: r for r in runs}}), encoding="utf-8")


def run(session: str, source: str = al.SOURCE, **more) -> dict:
    return {"session_id": session, "timestamp": "2026-11-20T09:00:00+00:00", "source": source,
            "model": "claude-sonnet-5-5", "outcome": "ok", "cost_source": "reported", "total_cost_usd": 0.16,
            "cap_usd": 2.0, "usage": {"turns": 5}, "duration_s": 12.1, "cli_version": "2.1.308", **more}


class Audit(Tmp):
    def test_where_the_audit_lives(self):
        self.assertEqual(al.audit_path("/hub", {}), Path("/hub/.fleet/assist/page-audit.jsonl"))
        self.assertEqual(al.audit_path("/hub", {"DASH_CONSOLE_PAGE_AUDIT": "/tmp/x.jsonl"}), Path("/tmp/x.jsonl"))
        self.assertEqual(al.ledger_path({"DASH_AI_LEDGER": "/tmp/l.json"}), Path("/tmp/l.json"))

    def test_a_line_from_before_ids_and_kinds_is_still_read(self):
        old = '{"at": "2026-11-19T19:42:38+00:00", "session": "a2b1682d", "client": "dock", "action": "snapshot", "target": "", "mode": "look", "outcome": "ok", "ms": 45}'
        row = al.audit_row(old)
        self.assertEqual((row["kind"], row["origin"], row["session"], row["ms"]), ("console", None, "a2b1682d", 45))
        self.assertRegex(row["id"], r"^[0-9a-f]{12}$")
        self.assertEqual(row["id"], al.audit_row(old)["id"], "the derived id is the line's own, so reading twice agrees")
        attach = '{"at": "2026-11-19T19:45:25+00:00", "session": "ffff0000", "client": "paired", "action": "attach", "target": "http://127.0.0.1:4000", "mode": "ask", "outcome": "ok", "ms": 0}'
        row = al.audit_row(attach)
        self.assertEqual((row["kind"], row["origin"]), ("fleet", "http://127.0.0.1:4000"),
                         "an old attach line named a fleet page by its target")

    def test_what_is_not_a_record_is_skipped_never_fatal(self):
        for bad in ("", "   ", "not json", "[]", '{"at": "2026-11-20T10:00:00+00:00"}', '{"action": "click", "at": "yesterday"}'):
            self.assertIsNone(al.audit_row(bad), bad)
        self.write_audit(line(), "garbage", line(id="bbbbbbbbbbbb", at="2026-11-20T11:00:00+00:00"))
        self.assertEqual([r["id"] for r in al.read_audit(self.audit)], ["aaaaaaaaaaaa", "bbbbbbbbbbbb"])
        self.assertEqual(al.read_audit(self.dir / "nope.jsonl"), [])

    def test_the_rotated_file_is_read_first(self):
        self.write_audit(line(id="new000000000", at="2026-11-20T11:00:00+00:00"),
                         rotated=(line(id="old000000000", at="2026-11-01T11:00:00+00:00"),))
        self.assertEqual([r["id"] for r in al.read_audit(self.audit)], ["old000000000", "new000000000"])

    def test_a_changed_file_is_read_again_and_an_unchanged_one_is_not(self):
        self.write_audit(line())
        first = al.read_audit(self.audit)
        self.assertEqual(len(first), 1)
        first.append({"mutated": True})
        self.assertEqual(len(al.read_audit(self.audit)), 1, "a caller cannot grow the cached rows")
        self.write_audit(line(), line(id="cccccccccccc", at="2026-11-20T11:30:00+00:00"))
        self.assertEqual(len(al.read_audit(self.audit)), 2)

    def test_the_window(self):
        rows = [al.audit_row(line(id="a", at="2026-11-10T10:00:00+00:00")), al.audit_row(line(id="b"))]
        self.assertEqual([r["id"] for r in al.since(rows, 7, NOW)], ["b"])
        self.assertEqual(len(al.since(rows, 0, NOW)), 2)

    def test_the_summary_counts_commands_apart_from_pairing_and_ends(self):
        rows = [al.audit_row(x) for x in (
            line(id="1", action="snapshot"),
            line(id="2", action="click", outcome="refused", mode="look"),
            line(id="3", action="fill", outcome="declined", mode="ask", client="paired"),
            line(id="4", action="attach", client="paired", kind="fleet", origin="http://127.0.0.1:4000", session="ffff0000"),
            line(id="5", action="click", client="paired", kind="fleet", origin="http://127.0.0.1:4000", session="ffff0000",
                 mode="act", ms=120),
            line(id="6", action="end", client="operator", kind="fleet", origin="http://127.0.0.1:4000", session="ffff0000"),
            line(id="7", action="read", outcome="timeout"),
            line(id="8", action="click", outcome="page"),      # the page's own no: a dialog, a secret field, a stale ref
            line(id="9", action="click", outcome="closed"),    # the session went away while it waited: not a no
        )]
        s = al.summarize_audit(rows)
        self.assertEqual((s["lines"], s["commands"], s["attaches"], s["ended_by_operator"], s["sessions"]), (9, 7, 1, 1, 2))
        self.assertEqual(s["by_outcome"], {"ok": 2, "refused": 1, "declined": 1, "timeout": 1, "page": 1, "closed": 1})
        self.assertEqual(s["by_client"], {"dock": 5, "paired": 2})
        self.assertEqual(s["by_kind"], {"console": 6, "fleet": 1})
        self.assertEqual(s["origins"], {"http://127.0.0.1:4000": 3})
        self.assertEqual((s["no"], s["no_pct"]), (4, 57.1))
        self.assertEqual((s["ok_ms_p50"], s["ok_ms_p95"]), (40, 120))
        empty = al.summarize_audit([])
        self.assertEqual((empty["commands"], empty["no_pct"], empty["first"], empty["ok_ms_p50"]), (0, None, None, None))


class Runs(Tmp):
    def test_only_the_assistants_rows_are_its_messages(self):
        self.write_ledger(run("s1"), run("s2", source="jev loop repo-scout/scout"),
                          run("s3", timestamp="2026-11-20T10:00:00+00:00", outcome="budget_hit", cost_source="estimated",
                              total_cost_usd=2.0))
        rows = al.read_runs(self.ledger)
        self.assertEqual([r["session_id"] for r in rows], ["s1", "s3"])
        s = al.summarize_runs(rows)
        self.assertEqual((s["messages"], s["cost_usd"], s["not_ok"], s["budget_hits"], s["cost_unreported"]),
                         (2, 2.16, 1, 1, 1))
        self.assertEqual(s["by_outcome"], {"ok": 1, "budget_hit": 1})
        self.assertEqual(s["not_ok_pct"], 50.0)
        self.assertEqual(s["cost_label"], "API-equivalent (estimate)")

    def test_a_missing_or_broken_ledger_is_no_rows(self):
        self.assertEqual(al.read_runs(self.dir / "nope.json"), [])
        self.ledger.write_text("{not json", encoding="utf-8")
        self.assertEqual(al.read_runs(self.ledger), [])
        self.ledger.write_text(json.dumps({"runs": "nonsense"}), encoding="utf-8")
        self.assertEqual(al.read_runs(self.ledger), [])
        none = al.summarize_runs([])
        self.assertEqual((none["messages"], none["cost_usd"], none["not_ok_pct"]), (0, None, None))

    def test_an_unknown_cost_stays_unknown(self):
        self.write_ledger(run("s1", total_cost_usd=None, cost_source=None))
        (row,) = al.read_runs(self.ledger)
        self.assertIsNone(row["cost_usd"])
        self.assertEqual(al.summarize_runs([row])["cost_unreported"], 1)


class Activity(Tmp):
    def test_the_document_joins_both_records_newest_first_and_names_no_whole_session(self):
        self.write_audit(line(id="1", at="2026-11-20T10:00:00+00:00"), line(id="2", at="2026-11-20T11:00:00+00:00"),
                         line(id="0", at="2026-10-01T10:00:00+00:00"))
        sid = "a3922fc8-4d7f-4ceb-905f-e6210b4d3ad4"
        self.write_ledger(run(sid))
        doc = al.activity(self.dir, days=7, limit=10, audit=self.audit, ledger=self.ledger, now=NOW)
        self.assertEqual((doc["schema"], doc["agent"], doc["window_days"]), ("assist-activity/v1", "local:console-assist", 7))
        self.assertEqual([r["id"] for r in doc["page_audit"]["recent"]], ["2", "1"], "newest first, inside the window")
        self.assertEqual(doc["page_audit"]["summary"]["commands"], 2)
        self.assertEqual(doc["messages"]["summary"]["messages"], 1)
        self.assertEqual(doc["messages"]["recent"][0]["session_id"], "a3922fc8")
        self.assertNotIn(sid, json.dumps(doc), "a session is named by its first eight characters")
        every = al.activity(self.dir, days=0, limit=1, audit=self.audit, ledger=self.ledger, now=NOW)
        self.assertEqual(every["page_audit"]["summary"]["commands"], 3)
        self.assertEqual(len(every["page_audit"]["recent"]), 1)

    def test_nothing_recorded_is_an_empty_document_not_an_error(self):
        doc = al.activity(self.dir, audit=self.dir / "no.jsonl", ledger=self.dir / "no.json", now=NOW)
        self.assertFalse(doc["page_audit"]["exists"])
        self.assertFalse(doc["messages"]["exists"])
        self.assertEqual((doc["page_audit"]["summary"]["commands"], doc["messages"]["summary"]["messages"]), (0, 0))
        self.assertIn("no file at", al.table(doc))

    def test_the_published_build_gets_no_path_and_no_rows(self):
        blank = al.blank()
        self.assertEqual((blank["page_audit"]["path"], blank["messages"]["ledger"], blank["generated_at"]), (None, None, None))
        self.assertEqual((blank["page_audit"]["recent"], blank["messages"]["recent"]), ([], []))
        self.assertNotIn(str(Path.home()), json.dumps(blank))

    def test_the_table_and_the_command(self):
        self.write_audit(line(id="1", action="click", outcome="refused", mode="look"),
                         line(id="2", action="attach", client="paired", kind="fleet", origin="http://127.0.0.1:4000"))
        self.write_ledger(run("s1"))
        text = al.table(al.activity(self.dir, days=0, audit=self.audit, ledger=self.ledger, now=NOW))
        self.assertIn("1 message(s) · $0.1600 API-equivalent (estimate) · 1 ok", text)
        self.assertIn("1 command(s) on 1 session(s) · 1 refused", text)
        self.assertIn("fleet pages by origin: 1 http://127.0.0.1:4000", text)
        saved = {k: os.environ.get(k) for k in ("DASH_CONSOLE_PAGE_AUDIT", "DASH_AI_LEDGER")}
        os.environ["DASH_CONSOLE_PAGE_AUDIT"], os.environ["DASH_AI_LEDGER"] = str(self.audit), str(self.ledger)
        try:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(al.main(["--days", "0", "--json"]), 0)
            self.assertEqual(json.loads(out.getvalue())["messages"]["summary"]["messages"], 1)
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


if __name__ == "__main__":
    unittest.main()
