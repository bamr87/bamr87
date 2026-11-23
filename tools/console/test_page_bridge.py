#!/usr/bin/env python3
"""The page bridge (page_bridge.py): the broker between an assistant session's page tools and the page a
person has open — its allowlist, the ceiling and the mode, the ask flag, liveness, caps, pairing, redaction
and the audit line. Stdlib only, no console, no browser: a thread plays the page.

    python3 tools/console/test_page_bridge.py
"""
from __future__ import annotations

import json
import re
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import page_bridge as pb  # noqa: E402


class Page(threading.Thread):
    """A browser tab's side of one session: poll, answer each command with `answer(command)`, stop on None."""

    def __init__(self, bridge: pb.PageBridge, sid: str, answer):
        super().__init__(daemon=True)
        self.bridge, self.sid, self.answer = bridge, sid, answer
        self.seen: list[dict] = []
        self.stop = threading.Event()

    def run(self) -> None:
        while not self.stop.is_set():
            try:
                got = self.bridge.next(self.sid, 0.2)
            except pb.NoSession:
                return
            cmd = got["command"]
            if cmd is None:
                continue
            self.seen.append(cmd)
            reply = self.answer(cmd)
            if reply is None:
                continue
            self.bridge.result(self.sid, cmd["id"], **reply)


def ok(result):
    return lambda cmd: {"ok": True, "result": result}


class Check(unittest.TestCase):
    def test_only_the_eight_actions_and_only_their_arguments(self):
        self.assertEqual(set(pb.ACTIONS), {"snapshot", "read", "data", "highlight", "navigate", "click", "fill", "press"})
        for action, args in (("eval", {}), ("click", {"selector": "#run"}), ("click", {"ref": "e1", "script": "x"}),
                             ("snapshot", {"ref": "e1"}), ("navigate", {"url": "https://example.com"})):
            with self.assertRaises(ValueError, msg=f"{action} {args}"):
                pb.check(action, args)

    def test_an_element_is_a_ref_from_a_snapshot_never_a_selector(self):
        self.assertEqual(pb.check("click", {"ref": "e12"}), {"ref": "e12"})
        for ref in ("#main button", "12", "e", "e123456", "E1", None, 3, "e1 "):
            with self.assertRaises(ValueError, msg=repr(ref)):
                pb.check("click", {"ref": ref})

    def test_a_path_is_in_app_never_a_url(self):
        self.assertEqual(pb.check("navigate", {"path": "/loops/repo_scout?tab=runs#top"})["path"],
                         "/loops/repo_scout?tab=runs#top")
        for path in ("https://example.com/", "//example.com/x", "loops", "", "/a b", "/x\\y", "javascript:alert(1)",
                     "/" + "a" * 300, None):
            with self.assertRaises(ValueError, msg=repr(path)):
                pb.check("navigate", {"path": path})

    def test_keys_text_and_sizes_are_bounded(self):
        self.assertEqual(pb.check("press", {"key": "Escape"}), {"key": "Escape"})
        self.assertEqual(pb.check("press", {"key": "Enter", "ref": "e2"}), {"key": "Enter", "ref": "e2"})
        for key in ("a", "F12", "Meta", "Control+A", ""):
            with self.assertRaises(ValueError, msg=key):
                pb.check("press", {"key": key})
        self.assertEqual(pb.check("fill", {"ref": "e1", "text": ""}), {"ref": "e1", "text": "", "submit": False})
        with self.assertRaises(ValueError):
            pb.check("fill", {"ref": "e1", "text": "x" * (pb.TEXT_MAX + 1)})
        with self.assertRaises(ValueError):
            pb.check("fill", {"ref": "e1", "text": "ok", "submit": "yes"})
        self.assertEqual(pb.check("snapshot", {"max_chars": 10})["max_chars"], 500)
        self.assertEqual(pb.check("snapshot", {"max_chars": 10**9})["max_chars"], pb.SNAPSHOT_MAX_CHARS)
        self.assertEqual(pb.check("highlight", {"ref": "e1", "note": "x" * 999})["note"], "x" * pb.NOTE_MAX)

    def test_a_fill_is_recorded_by_its_length_never_its_text(self):
        target = pb.target_of("fill", {"ref": "e4", "text": "the launch codes", "submit": True})
        self.assertNotIn("launch", target)
        self.assertEqual(target, "e4 (16 chars, then Enter)")


class Bridge(unittest.TestCase):
    def setUp(self):
        self.audit = Path(tempfile.mkdtemp(prefix="page-bridge-")) / "assist" / "page-audit.jsonl"
        self.ceiling = "act"
        self.b = pb.PageBridge(audit_path=self.audit, ceiling=lambda: self.ceiling)
        self.pages: list[Page] = []

    def tearDown(self):
        for p in self.pages:
            p.stop.set()

    def page(self, mode="act", answer=None) -> tuple[str, Page]:
        sid = self.b.open(mode)["sid"]
        p = Page(self.b, sid, answer or ok({"done": True}))
        p.start()
        self.pages.append(p)
        return sid, p

    def lines(self) -> list[dict]:
        return [json.loads(line) for line in self.audit.read_text().splitlines()] if self.audit.exists() else []

    # -- the ceiling and the mode --------------------------------------------
    def test_the_ceiling_off_opens_nothing_and_look_opens_look(self):
        self.ceiling = "off"
        with self.assertRaises(pb.Refused):
            self.b.open("ask")
        self.ceiling = "look"
        view = self.b.open("act")
        self.assertEqual((view["mode"], view["ceiling"]), ("look", "look"))
        with self.assertRaises(pb.Refused):
            self.b.set_mode(view["sid"], "act")
        with self.assertRaises(ValueError):
            self.b.open("root")

    def test_a_look_round_trip_scrubs_and_caps_what_the_page_sent(self):
        token = "ghp_" + "a" * 36
        run_id, sha = "20261101T120000Z-repo-scout-scout-aaaaaa", "836a1b33" * 5
        sid, page = self.page(answer=ok({"route": "/auth", "text": f"FLEET_TOKEN is {token}",
                                         "rows": ["Authorization: Bearer abc.def-ghi_jkl", "sk-ant-api03-abcdefgh",
                                                  "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.c2lnbmF0dXJl"],
                                         "ids": [run_id, sha]}))
        out = self.b.command(sid, "snapshot", {})
        self.assertTrue(out["ok"])
        sent = json.dumps(out)
        for secret in (token, "abc.def-ghi_jkl", "api03-abcdefgh", "eyJzdWIiOiIxMjM0In0"):
            self.assertNotIn(secret, sent)
        self.assertEqual(out["result"]["ids"], [run_id, sha], "a run id and a commit sha are not credentials")
        self.assertEqual(out["result"]["route"], "/auth")
        self.assertEqual(page.seen[0]["action"], "snapshot")
        self.assertFalse(page.seen[0]["ask"])
        sid2, _ = self.page(answer=ok({"text": "word " * 40_000}))
        big = self.b.command(sid2, "read", {"ref": "e1"})["result"]
        self.assertTrue(big["truncated"])
        self.assertLessEqual(len(big["text"]), pb.RESULT_MAX_CHARS)

    def test_look_mode_refuses_every_action_before_the_page_sees_it(self):
        sid, page = self.page(mode="look")
        for action, args in (("navigate", {"path": "/jobs"}), ("click", {"ref": "e1"}),
                             ("fill", {"ref": "e1", "text": "x"}), ("press", {"key": "Enter"})):
            out = self.b.command(sid, action, args)
            self.assertEqual((out["ok"], out["kind"]), (False, "refused"), action)
            self.assertIn("Look only", out["error"])
        self.assertTrue(self.b.command(sid, "highlight", {"ref": "e1"})["ok"])
        self.assertEqual([c["action"] for c in page.seen], ["highlight"])

    def test_the_look_ceiling_refuses_actions_whatever_the_mode_says(self):
        sid, page = self.page(mode="act")
        self.ceiling = "look"
        out = self.b.command(sid, "click", {"ref": "e1"})
        self.assertEqual(out["kind"], "refused")
        self.assertIn("page_access", out["error"])
        self.ceiling = "off"
        self.assertEqual(self.b.command(sid, "snapshot", {})["kind"], "refused")
        self.assertEqual(page.seen, [])

    def test_ask_mode_marks_clicks_fills_and_keys_for_the_persons_yes_and_not_navigation(self):
        sid, page = self.page(mode="ask")
        for action, args in (("navigate", {"path": "/jobs"}), ("click", {"ref": "e1"}),
                             ("fill", {"ref": "e2", "text": "x"}), ("press", {"key": "Enter"}), ("read", {"ref": "e1"})):
            self.assertTrue(self.b.command(sid, action, args)["ok"], action)
        self.assertEqual({c["action"]: c["ask"] for c in page.seen},
                         {"navigate": False, "click": True, "fill": True, "press": True, "read": False})
        self.b.set_mode(sid, "act")
        self.b.command(sid, "click", {"ref": "e1"})
        self.assertFalse(page.seen[-1]["ask"])

    def test_a_decline_and_a_page_rule_come_back_as_answers(self):
        sid, _ = self.page(mode="ask", answer=lambda cmd: {"ok": False, "kind": "declined", "error": "the person said no"})
        out = self.b.command(sid, "click", {"ref": "e1"})
        self.assertEqual((out["ok"], out["kind"], out["error"]), (False, "declined", "the person said no"))
        sid2, _ = self.page(answer=lambda cmd: {"ok": False, "kind": "nonsense", "error": "inside a modal dialog"})
        self.assertEqual(self.b.command(sid2, "click", {"ref": "e1"})["kind"], "page")

    # -- liveness, timeouts, closing -----------------------------------------
    def test_a_page_that_is_not_polling_is_said_not_waited_on(self):
        with mock.patch.object(pb, "LIVE_S", 0.0):
            sid = self.b.open("act")["sid"]
            out = self.b.command(sid, "snapshot", {})
        self.assertEqual(out["kind"], "refused")
        self.assertIn("not listening", out["error"])

    def test_a_page_that_never_answers_times_out(self):
        sid, page = self.page(answer=lambda cmd: None)
        with mock.patch.object(pb, "LOOK_TIMEOUT_S", 0.3):
            out = self.b.command(sid, "snapshot", {})
        self.assertEqual((out["ok"], out["kind"]), (False, "timeout"))
        # a late answer to a command nobody waits on is ignored, not an error
        self.b.result(sid, page.seen[0]["id"], True, {"late": True})

    def test_an_unanswered_ask_says_the_person_did_not_answer(self):
        sid, _ = self.page(mode="ask", answer=lambda cmd: None)
        with mock.patch.object(pb, "APPROVAL_S", 0.2), mock.patch.object(pb, "ACT_TIMEOUT_S", 0.1):
            out = self.b.command(sid, "click", {"ref": "e1"})
        self.assertEqual(out["kind"], "timeout")
        self.assertIn("did not answer", out["error"])

    def test_closing_the_page_ends_what_a_session_was_waiting_on(self):
        sid, _ = self.page(answer=lambda cmd: None)
        got: dict = {}
        t = threading.Thread(target=lambda: got.update(self.b.command(sid, "snapshot", {})))
        t.start()
        while not self.b._sessions[sid].pending:
            pass
        self.assertTrue(self.b.close(sid))
        t.join(5)
        self.assertEqual(got["kind"], "closed")
        self.assertFalse(self.b.has(sid))
        with self.assertRaises(pb.NoSession):
            self.b.command(sid, "snapshot", {})
        self.assertFalse(self.b.close(sid))
        for bad in ("", "nope", "../x", None):
            with self.assertRaises(pb.NoSession):
                self.b.describe(bad)

    # -- caps -----------------------------------------------------------------
    def test_live_pages_fill_the_session_cap_and_a_silent_one_makes_room(self):
        for _ in range(pb.MAX_SESSIONS):
            self.page()
        with self.assertRaises(pb.Busy):
            self.b.open("ask")
        silent = self.pages[0]
        silent.stop.set()
        silent.join(5)
        with mock.patch.object(pb, "LIVE_S", 0.0):
            # every page is "not live" for this call; the least recently seen one is dropped
            self.assertTrue(self.b.open("ask")["sid"])
        self.assertEqual(len(self.b._sessions), pb.MAX_SESSIONS)

    def test_commands_per_minute_are_capped(self):
        sid, _ = self.page()
        with mock.patch.object(pb, "COMMANDS_PER_MIN", 3):
            for _ in range(3):
                self.assertTrue(self.b.command(sid, "snapshot", {})["ok"])
            with self.assertRaises(pb.Busy):
                self.b.command(sid, "snapshot", {})

    # -- pairing --------------------------------------------------------------
    def test_pairing_is_off_until_the_person_switches_it_on_and_a_code_is_spent_once(self):
        sid, _ = self.page(mode="ask")
        self.assertFalse(self.b.describe(sid)["pairing"])
        self.assertNotIn("code", self.b.describe(sid))
        with self.assertRaises(pb.Refused):
            self.b.attach("ABCDEFGH")
        view = self.b.pair(sid)
        code = view["code"]
        self.assertTrue(re.fullmatch(f"[{pb.CODE_ALPHABET}]{{{pb.CODE_LEN}}}", code), code)
        got = self.b.attach(f" {code[:4].lower()}-{code[4:].lower()} ")
        self.assertEqual((got["sid"], got["mode"], got["paired"]), (sid, "ask", 1))
        self.assertNotIn("code", got)
        with self.assertRaises(pb.Refused):
            self.b.attach(code)
        self.assertFalse(self.b.describe(sid)["pairing"])
        self.b.pair(sid)
        self.b.pair(sid, on=False)
        self.assertNotIn("code", self.b.describe(sid))

    def test_wrong_codes_lock_pairing_for_everyone_until_the_window_clears(self):
        sid, _ = self.page()
        code = self.b.pair(sid)["code"]
        for _ in range(pb.PAIR_FAILS):
            with self.assertRaises(pb.Refused):
                self.b.attach("Z" * pb.CODE_LEN if code != "Z" * pb.CODE_LEN else "Y" * pb.CODE_LEN)
        with self.assertRaises(pb.Busy):
            self.b.attach(code)
        with mock.patch.object(pb, "PAIR_WINDOW_S", 0.0):
            self.assertEqual(self.b.attach(code)["sid"], sid)

    def test_a_code_expires(self):
        sid, _ = self.page()
        with mock.patch.object(pb, "PAIR_TTL_S", -1.0):
            code = self.b.pair(sid).get("code")
        self.assertIsNone(code)
        self.assertFalse(self.b.describe(sid)["pairing"])

    # -- audit ----------------------------------------------------------------
    def test_every_command_leaves_one_audit_line_without_the_typed_text_or_a_token(self):
        sid, _ = self.page(mode="ask")
        self.b.command(sid, "fill", {"ref": "e7", "text": "hunter2 hunter2", "submit": True}, client="paired")
        self.b.command(sid, "navigate", {"path": "/jobs?t=" + "k" * 44})
        self.b.set_mode(sid, "look")
        self.b.command(sid, "click", {"ref": "e1"})
        rows = self.lines()
        self.assertEqual([(r["action"], r["client"], r["outcome"], r["mode"]) for r in rows],
                         [("fill", "paired", "ok", "ask"), ("navigate", "dock", "ok", "ask"),
                          ("click", "dock", "refused", "look")])
        self.assertEqual(rows[0]["target"], "e7 (15 chars, then Enter)")
        text = self.audit.read_text()
        self.assertNotIn("hunter2", text)
        self.assertNotIn("k" * 44, text)
        self.assertEqual(rows[0]["session"], sid[:8])
        self.assertNotIn(sid, text, "the audit names a session by a prefix, never the whole capability")

    def test_the_secret_pattern_is_the_mcp_layers(self):
        """Two modules scrub with one pattern; the MCP layer needs the `mcp` package to import, so the two
        definitions are compared as source text (string pieces joined, indentation ignored)."""
        here = Path(__file__).resolve().parent

        def literal(path: Path) -> str:
            m = re.search(r"SECRETISH_RX = re\.compile\((.*?)\)\n", path.read_text(encoding="utf-8"), re.S)
            self.assertIsNotNone(m, path)
            return "".join(re.findall(r'r"((?:[^"\\]|\\.)*)"', m.group(1)))

        mine, theirs = literal(here / "page_bridge.py"), literal(here / "mcp_layer" / "server.py")
        self.assertTrue(mine)
        self.assertEqual(mine, theirs)
        self.assertEqual(mine, pb.SECRETISH_RX.pattern)


class NewestPoll(unittest.TestCase):
    """A page that reloads, or loads its next address, leaves its last poll waiting with nobody behind it."""

    def test_only_the_newest_poll_of_a_session_is_handed_a_command(self):
        b = pb.PageBridge()
        sid = b.open("act")["sid"]
        got: dict = {}
        old = threading.Thread(target=lambda: got.update(old=b.next(sid, 5.0)), daemon=True)
        old.start()
        for _ in range(200):                        # until the old poll is waiting
            if b._sessions[sid].polling:
                break
            threading.Event().wait(0.01)
        new = threading.Thread(target=lambda: got.update(new=b.next(sid, 5.0)), daemon=True)
        new.start()
        old.join(2.0)
        self.assertFalse(old.is_alive(), "the older poll stood down as soon as a newer one arrived")
        self.assertIsNone(got["old"]["command"])
        self.assertTrue(got["old"]["superseded"])
        asked: dict = {}
        ask = threading.Thread(target=lambda: asked.update(out=b.command(sid, "snapshot")), daemon=True)
        ask.start()
        new.join(2.0)
        self.assertEqual(got["new"]["command"]["action"], "snapshot", "the command went to the poll that has a page")
        b.result(sid, got["new"]["command"]["id"], True, {"outline": "x"})
        ask.join(2.0)
        self.assertTrue(asked["out"]["ok"])


class FleetPages(unittest.TestCase):
    """Pages of the fleet's other sites (templates/assistant/fleet-assist.js): the same bridge, held apart."""

    ORIGIN = "http://127.0.0.1:4010"

    def setUp(self):
        self.audit = Path(tempfile.mkdtemp(prefix="page-bridge-")) / "assist" / "page-audit.jsonl"
        self.fleet = "act"
        self.b = pb.PageBridge(audit_path=self.audit, ceiling=lambda: "act")
        self.b.fleet_ceiling = lambda: self.fleet

    def test_fleet_pages_are_off_until_the_console_wires_their_ceiling(self):
        b = pb.PageBridge()
        with self.assertRaises(pb.Refused) as e:
            b.open("ask", self.ORIGIN)
        self.assertIn("assistant.fleet_pages", str(e.exception))
        self.assertEqual(b.open("ask")["kind"], "console", "the console's own page is not held to that ceiling")

    def test_a_fleet_session_says_what_page_it_is_in_short_scrubbed_facts(self):
        token = "ghp_" + "a" * 36
        v = self.b.open("ask", self.ORIGIN, {"repo": "bamr87/it-journey", "source": "pages/about.md",
                                             "title": "About\n  us " + token, "junk": "dropped", "branch": 7,
                                             "path": "/x" * 400})
        self.assertEqual((v["kind"], v["origin"], v["mode"]), ("fleet", self.ORIGIN, "ask"))
        self.assertEqual(set(v["page"]), {"repo", "source", "title", "path"})
        self.assertEqual(v["page"]["title"], "About us <redacted>")
        self.assertEqual(len(v["page"]["path"]), pb.FACT_MAX)
        for bad in ("javascript:alert(1)", "http://host/path", "http://user@host", "ftp://host", ""):
            with self.assertRaises(ValueError, msg=bad):
                self.b.open("ask", bad)

    def test_a_session_answers_only_to_the_origin_that_opened_it(self):
        sid = self.b.open("ask", self.ORIGIN)["sid"]
        other = "http://127.0.0.1:9999"
        for call in (lambda: self.b.fleet_next(sid, other, 0), lambda: self.b.fleet_mode(sid, other, "look"),
                     lambda: self.b.fleet_pair(sid, other), lambda: self.b.fleet_result(sid, other, "0" * 12, True),
                     lambda: self.b.fleet_close(sid, other)):
            with self.assertRaises(pb.NoSession):
                call()
        mine = self.b.open("ask")["sid"]              # the console's own page is no fleet page
        with self.assertRaises(pb.NoSession):
            self.b.fleet_pair(mine, self.ORIGIN)
        self.assertEqual(self.b.fleet_mode(sid, self.ORIGIN, "act")["mode"], "act")
        self.assertTrue(self.b.fleet_close(sid, self.ORIGIN))

    def test_the_docked_assistant_is_never_started_against_a_fleet_page(self):
        sid = self.b.open("ask", self.ORIGIN, {"repo": "bamr87/x"})["sid"]
        self.assertFalse(self.b.has(sid), "core._assist asks has() before it hands a session a page")
        self.assertTrue(self.b.has(self.b.open("ask")["sid"]))
        listed = self.b.sessions()
        self.assertEqual([s["kind"] for s in listed], ["fleet", "console"])
        self.assertNotIn(sid, json.dumps(listed), "the listing is for the operator's eyes: no session id")
        self.assertEqual(listed[0]["id"], sid[:8])

    def test_fleet_pages_and_the_dock_have_separate_caps(self):
        for _ in range(pb.MAX_SESSIONS):
            self.b.open("ask")
        fleet = [self.b.open("ask", self.ORIGIN)["sid"] for _ in range(pb.MAX_FLEET_SESSIONS)]
        with self.assertRaises(pb.Busy):
            self.b.open("ask", self.ORIGIN)
        with self.assertRaises(pb.Busy):
            self.b.open("ask")
        self.b.fleet_close(fleet[0], self.ORIGIN)
        self.assertEqual(self.b.open("ask", self.ORIGIN)["kind"], "fleet")

    def test_the_fleet_ceiling_is_its_own_setting(self):
        self.fleet = "look"
        sid = self.b.open("act", self.ORIGIN)["sid"]
        self.assertEqual(self.b.describe(sid)["mode"], "look")
        with self.assertRaises(pb.Refused) as e:
            self.b.fleet_mode(sid, self.ORIGIN, "act")
        self.assertIn("assistant.fleet_pages", str(e.exception))
        out = self.b.command(sid, "click", {"ref": "e1"})
        self.assertEqual((out["ok"], out["kind"]), (False, "refused"))
        self.assertIn("assistant.fleet_pages", out["error"])
        self.fleet = "off"
        self.assertIn("is off", self.b.command(sid, "snapshot")["error"])

    def test_a_page_says_where_it_is_on_every_poll_and_pairing_tells_the_session(self):
        sid = self.b.open("ask", self.ORIGIN, {"repo": "bamr87/x", "source": "index.md"})["sid"]
        self.b.fleet_next(sid, self.ORIGIN, 0, {"repo": "bamr87/x", "source": "pages/about.md", "path": "/about/"})
        code = self.b.fleet_pair(sid, self.ORIGIN)["code"]
        view = self.b.attach(code)
        self.assertEqual((view["kind"], view["origin"]), ("fleet", self.ORIGIN))
        self.assertEqual(view["page"]["source"], "pages/about.md", "a site of plain pages keeps its session across loads")
        line = json.loads(self.audit.read_text().splitlines()[-1])
        self.assertEqual((line["action"], line["target"]), ("attach", self.ORIGIN))


class Observed(unittest.TestCase):
    """What the audit says about whose page a command reached, and where a copy of each line goes."""

    ORIGIN = "http://127.0.0.1:4010"

    def setUp(self):
        self.audit = Path(tempfile.mkdtemp(prefix="page-bridge-")) / "assist" / "page-audit.jsonl"
        self.b = pb.PageBridge(audit_path=self.audit, ceiling=lambda: "act")
        self.b.fleet_ceiling = lambda: "act"

    def lines(self) -> list[dict]:
        return [json.loads(line) for line in self.audit.read_text().splitlines()] if self.audit.exists() else []

    def test_a_line_says_whose_page_it_was_and_has_an_id_of_its_own(self):
        con = self.b.open("look")["sid"]
        fleet = self.b.open("look", self.ORIGIN, {"repo": "bamr87/it-journey", "source": "index.md"})["sid"]
        self.b.command(con, "click", {"ref": "e1"})       # refused by the mode, before any page is needed
        self.b.command(fleet, "click", {"ref": "e1"}, client="paired")
        a, b = self.lines()
        self.assertEqual((a["kind"], a.get("origin"), a.get("repo")), ("console", None, None))
        self.assertEqual((b["kind"], b["origin"], b["repo"], b["client"]),
                         ("fleet", self.ORIGIN, "bamr87/it-journey", "paired"))
        self.assertRegex(a["id"], r"^[0-9a-f]{12}$")
        self.assertNotEqual(a["id"], b["id"], "a line is addressable: the lake keys on its id")
        text = self.audit.read_text()
        self.assertNotIn(con, text)
        self.assertNotIn(fleet, text)

    def test_each_line_is_also_printed_where_the_log_plane_collects_it(self):
        import io
        out = io.StringIO()
        self.b.audit_stream = out
        sid = self.b.open("look")["sid"]
        self.b.command(sid, "fill", {"ref": "e2", "text": "hunter2"})
        printed = out.getvalue().strip().splitlines()
        self.assertEqual(len(printed), 1)
        self.assertTrue(printed[0].startswith("page-bridge audit {"))
        row = json.loads(printed[0].removeprefix("page-bridge audit "))
        self.assertEqual(row, self.lines()[0], "the printed line is the file's line")
        self.assertNotIn("hunter2", printed[0])
        self.assertNotIn(sid, printed[0])

    def test_a_bridge_with_a_stream_and_no_file_still_records(self):
        import io
        b = pb.PageBridge(ceiling=lambda: "act")
        b.audit_stream = out = io.StringIO()
        b.command(b.open("look")["sid"], "navigate", {"path": "/jobs"})
        self.assertIn('"action": "navigate"', out.getvalue())


class OperatorEnds(unittest.TestCase):
    """The operator ends a fleet page's sharing from the console, by the eight characters the list shows."""

    ORIGIN = "http://127.0.0.1:4010"

    def setUp(self):
        self.audit = Path(tempfile.mkdtemp(prefix="page-bridge-")) / "assist" / "page-audit.jsonl"
        self.now = [1000.0]
        self.b = pb.PageBridge(audit_path=self.audit, ceiling=lambda: "act", clock=lambda: self.now[0])
        self.b.fleet_ceiling = lambda: "act"

    def test_the_list_names_a_session_by_eight_characters_and_end_takes_only_those(self):
        sid = self.b.open("ask", self.ORIGIN, {"repo": "bamr87/x"})["sid"]
        row = [s for s in self.b.sessions() if s["kind"] == "fleet"][0]
        self.assertEqual(row["id"], sid[:8])
        self.assertNotIn(sid, json.dumps(self.b.sessions()))
        for bad in (sid, sid[:7], sid[:8].upper() + "!", "", None, 12345678):
            with self.assertRaises(ValueError):
                self.b.end(bad)
        out = self.b.end(row["id"])
        self.assertEqual((out["ended"], out["id"], out["origin"]), (True, sid[:8], self.ORIGIN))
        self.assertNotIn(sid, json.dumps(out))
        self.assertEqual(self.b.sessions(), [])

    def test_an_unknown_id_is_refused_and_an_ambiguous_one_is_never_guessed(self):
        with self.assertRaises(pb.NoSession):
            self.b.end("0" * 8)
        a = self.b.open("ask", self.ORIGIN)["sid"]
        b = self.b.open("ask", self.ORIGIN)["sid"]
        twin = self.b._sessions.pop(b)          # force the collision 32 bits make unlikely
        twin.sid = a[:8] + b[8:]
        self.b._sessions[twin.sid] = twin
        with self.assertRaises(pb.Ambiguous):
            self.b.end(a[:8])
        self.assertEqual(len(self.b.sessions()), 2, "nothing was ended")

    def test_the_consoles_own_tab_is_not_ended_this_way(self):
        sid = self.b.open("ask")["sid"]
        with self.assertRaises(pb.NoSession):
            self.b.end(sid[:8])
        self.assertTrue(self.b.has(sid))

    def test_the_page_and_a_paired_session_are_both_told_who_ended_it(self):
        sid = self.b.open("act", self.ORIGIN, {"repo": "bamr87/x"})["sid"]
        self.b.end(sid[:8])
        with self.assertRaises(pb.Ended) as page_side:
            self.b.fleet_next(sid, self.ORIGIN, 0)
        self.assertIn("operator ended", str(page_side.exception.args[0]))
        with self.assertRaises(pb.Ended) as session_side:
            self.b.command(sid, "snapshot", client="paired")
        self.assertIn("operator ended", str(session_side.exception.args[0]))
        self.assertIsInstance(page_side.exception, pb.NoSession, "a caller that only knows NoSession still stops")
        # the reason is remembered for a while, then the session is simply gone
        self.now[0] += pb.ENDED_TTL_S + 1
        with self.assertRaises(pb.NoSession) as later:
            self.b.command(sid, "snapshot", client="paired")
        self.assertNotIsInstance(later.exception, pb.Ended)

    def test_a_command_in_flight_is_answered_with_the_reason(self):
        b = pb.PageBridge(audit_path=self.audit, ceiling=lambda: "act")      # the real clock: a thread waits on it
        b.fleet_ceiling = lambda: "act"
        sid = b.open("act", self.ORIGIN)["sid"]
        b.fleet_next(sid, self.ORIGIN, 0)                                    # the page is live and takes nothing
        got: dict = {}
        t = threading.Thread(target=lambda: got.update(b.command(sid, "snapshot", client="paired")), daemon=True)
        t.start()
        for _ in range(200):
            if b._sessions[sid].pending:
                break
            threading.Event().wait(0.01)
        b.end(sid[:8])
        t.join(5)
        self.assertEqual((got.get("ok"), got.get("kind")), (False, "closed"))
        self.assertIn("operator ended", got["error"])

    def test_ending_leaves_one_audit_line(self):
        sid = self.b.open("ask", self.ORIGIN, {"repo": "bamr87/x"})["sid"]
        self.b.end(sid[:8])
        (line,) = [json.loads(x) for x in self.audit.read_text().splitlines()]
        self.assertEqual((line["action"], line["client"], line["outcome"], line["kind"], line["origin"], line["session"]),
                         ("end", "operator", "ok", "fleet", self.ORIGIN, sid[:8]))


class OneContract(unittest.TestCase):
    """The broker, the console's page and the kit's payload each hold the lists the others rely on."""

    HERE = Path(__file__).resolve().parent
    KIT = HERE.parents[1] / "templates" / "assistant" / "fleet-assist.js"
    TS = HERE / "web" / "src" / "assist" / "pageBridge.ts"

    @staticmethod
    def js_list(text: str, name: str) -> tuple:
        m = re.search(rf"const {name}(?::[^=]+)? = \[([^\]]*)\]", text)
        assert m, name
        return tuple(re.findall(r"'([^']+)'", m.group(1)))

    def test_the_kit_payload_and_the_broker_agree_on_every_list(self):
        kit = self.KIT.read_text()
        for name, want in (("LOOK", pb.LOOK), ("ACT", pb.ACT), ("ASKS", pb.ASKS), ("MODES", pb.MODES), ("KEYS", pb.KEYS)):
            self.assertEqual(self.js_list(kit, name), tuple(want), name)
        takes = re.search(r"const TAKES = \{(.*?)\};", kit, re.S).group(1)
        for action in pb.ACTIONS:
            self.assertIn(f"{action}: [", takes)
        self.assertIn(f"const TEXT_MAX = {pb.TEXT_MAX};", kit)
        self.assertIn(f"const SNAPSHOT_MAX = {pb.SNAPSHOT_MAX_CHARS};", kit)

    def test_the_two_pages_name_a_secret_field_the_same_way(self):
        rx = r"const SECRET_NAME = (/.+?/i);"
        self.assertEqual(re.search(rx, self.KIT.read_text()).group(1), re.search(rx, self.TS.read_text()).group(1))
        self.assertEqual(self.js_list(self.TS.read_text(), "ASKS"), tuple(pb.ASKS))
        self.assertEqual(self.js_list(self.TS.read_text(), "ACTS"), tuple(pb.ACT))


if __name__ == "__main__":
    unittest.main()
