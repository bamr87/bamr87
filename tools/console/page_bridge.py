#!/usr/bin/env python3
"""
page_bridge — the broker between an assistant session and the page a person has open.

The console's assistant is a headless Claude Code session on the machine the
console runs on; the page it is asked about is in somebody's browser. This
module is the one path between the two, and it is a queue, not a remote
control: a session's page tool (mcp_layer: page_snapshot, page_click, …) asks
the console to do ONE thing to ONE open page, the page's own code (web/src/
assist/pageBridge.ts) picks the request up on its long poll, decides whether
the person allows it, does it in the DOM and posts back what happened.

What holds (constitution § 10.6, § 13.6; tools/console/README.md "The assistant"):

  allowlist   eight actions, nothing else: snapshot, read, data, highlight
              (LOOK) and navigate, click, fill, press (ACT). Arguments are
              checked here before the page ever sees them: an element is named
              by a ref from the last snapshot, never by a selector or script;
              a path is an in-app path, never a URL; a key is one of KEYS.
  ceiling     _data/fleet.yml assistant.page_access: off (no session opens),
              look (ACT is refused here) or act.
  mode        what the person chose in the dock for THIS page: look, ask (each
              click, fill and key press waits for their yes) or act. The page
              enforces it again, and it alone knows the two things no mode
              lifts: nothing is clicked or typed inside a modal dialog (that
              is where the console asks its confirming questions, § 11.4), and
              a secret field is never read or filled.
  capability  a session id is 128 random bits handed to exactly one MCP server
              process through its environment. A second Claude Code session
              (the interactive one in a terminal) reaches a page only with a
              pairing code the person switched on and read off the dock:
              single use, short lived, and guesses are rate limited.
  caps        sessions, queue depth, commands per minute, argument and result
              sizes, and a wall clock on every command; a page that stopped
              polling is not live and is told so rather than waited on.
  redaction   credential shapes are scrubbed from every result, whatever the
              page sent, and an audit line is scrubbed harder still. This is
              the backstop: the first line is that the page never reads a
              secret field and the console's documents carry credential names
              and presence, never a value.
  audit       one append-only JSONL record per command: when, which session,
              who asked (the dock's session or a paired one), which kind of
              page (the console's own or a fleet page, with its origin), the
              action, its target, the mode, the outcome and how long it took
              (§ 13.5). The same line goes to the console's stderr, which the
              log plane ships; fleetcore.assistlog reads the file back for the
              Assist page, the MCP layer and the lake.

  fleet pages a page of another fleet site or app (templates/assistant/
              fleet-assist.js, ADR 0014) opens a session the same way, from its
              own origin. It gets no token and needs none: a session is an offer
              to be driven, and holding one grants nothing. It has its own
              ceiling (assistant.fleet_pages), its own cap, so it cannot crowd
              out the console's dock, and it is bound to the origin that opened
              it. The console starts no session of its own against one: a fleet
              page is reached by a paired Claude Code session only. The operator
              can end one from the Assist page (`end`), by the eight characters
              the audit log calls it: the id itself never leaves this module.

Stdlib only, no web framework: app.py puts HTTP in front of it and core.py asks
it whether a session exists; test_page_bridge.py drives it with a fake clock.
"""
from __future__ import annotations

import datetime as dt
import hmac
import json
import re
import secrets
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable

LOOK = ("snapshot", "read", "data", "highlight")
ACT = ("navigate", "click", "fill", "press")
ACTIONS = LOOK + ACT
#: what the person chose in the dock
MODES = ("look", "ask", "act")
#: _data/fleet.yml assistant.page_access
CEILINGS = ("off", "look", "act")
#: in `ask` mode these wait for the person's yes; navigating only changes which page they read
ASKS = ("click", "fill", "press")

SID_RX = re.compile(r"^[0-9a-f]{32}$")
#: what the audit log and the operator's view call a session: its first eight characters, never the id
HANDLE_RX = re.compile(r"^[0-9a-f]{8}$")
CMD_RX = re.compile(r"^[0-9a-f]{12}$")
REF_RX = re.compile(r"^e[0-9]{1,5}$")
# An in-app path: one leading slash (never `//host`), URL-safe characters only.
PATH_RX = re.compile(r"^/(?!/)[A-Za-z0-9._~!$&'()*+,;=:@%/?#\[\]-]{0,299}$")
KEYS = ("Enter", "Escape", "Tab", "Space", "Backspace", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight",
        "Home", "End", "PageUp", "PageDown")
# Read off a screen and typed into a terminal: no 0/O, no 1/I/L.
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LEN = 8

MAX_SESSIONS = 6
MAX_FLEET_SESSIONS = 12      # pages of other fleet sites: their own cap, so they cannot crowd out the dock
MAX_QUEUE = 4
COMMANDS_PER_MIN = 40
POLL_MAX_S = 25.0            # one long poll; the page asks again at once
LIVE_S = 45.0                # a page that has not polled for this long is not listening
IDLE_S = 30 * 60.0           # a session nobody polled for this long is dropped
LOOK_TIMEOUT_S = 15.0
ACT_TIMEOUT_S = 20.0
APPROVAL_S = 90.0            # how long an `ask` waits for the person
PAIR_TTL_S = 10 * 60.0
PAIR_FAILS = 5               # wrong codes inside PAIR_WINDOW_S before attach locks
PAIR_WINDOW_S = 60.0
TEXT_MAX = 4000              # one fill
NOTE_MAX = 200
KEY_MAX = 200                # a page_data key
RESULT_MAX_CHARS = 60_000
SNAPSHOT_MAX_CHARS = 24_000  # the page's own default; a tool may ask for less
AUDIT_MAX_BYTES = 2_000_000
ENDED_TTL_S = 10 * 60.0      # how long an ended session's page and its paired session are told WHY it is gone
ENDED_WHY = ("the operator ended this page's sharing from the console. The person on the page can share it "
             "again from its panel")
#: what a fleet page may say about itself (fleet-assist.js `facts`): short strings, shown to the session that pairs
PAGE_FACTS = ("repo", "branch", "source", "route", "framework", "env", "version", "base", "title", "path", "kit")
FACT_MAX = 300
ORIGIN_RX = re.compile(r"^https?://[A-Za-z0-9.\-]+(:\d{1,5})?$|^https?://\[[0-9A-Fa-f:.]+\](:\d{1,5})?$")

# Credential SHAPES, scrubbed from every result a page sends: GitHub, Anthropic, Slack and AWS key forms, a
# JWT, a bearer credential, a private key header. Deliberately not "any long run": a page is full of run ids,
# commit shas and slugs a session needs to read, and a rule that eats those teaches it nothing.
TOKEN_RX = re.compile(r"(gh[pousr]_[A-Za-z0-9]{16,}|github_pat_[A-Za-z0-9_]{16,}|sk-ant-[A-Za-z0-9_-]{8,}"
                      r"|xox[abprs]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16}"
                      r"|eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,}"
                      r"|(?i:bearer)\s+[A-Za-z0-9._~+/=-]{8,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)")
# An audit line holds a ref, a path or a key name, so it takes the MCP layer's stricter pattern as well (kept
# in step by test_page_bridge.py): the shapes above, any bearer value, any 40+ character run.
SECRETISH_RX = re.compile(r"(gh[pousr]_[A-Za-z0-9]{16,}|github_pat_[A-Za-z0-9_]{16,}|sk-ant-[A-Za-z0-9_-]{8,}"
                          r"|(?i:bearer)\s+\S+|[A-Za-z0-9_\-]{40,})")


class NoSession(KeyError):
    """No open page session has this id (never opened, closed, or dropped as idle)."""


class Busy(RuntimeError):
    """A cap said no: too many sessions, a full queue, or too many commands this minute."""


class Ended(NoSession):
    """The operator ended this session from the console (PageBridge.end): said apart from a session that was
    closed or dropped, so the page and a paired session can tell the person what happened."""


class Ambiguous(RuntimeError):
    """More than one session answers to that eight-character id: refused, never guessed."""


class Refused(PermissionError):
    """The ceiling, the mode or the pairing rules do not allow it."""


def scrub(obj: Any) -> Any:
    """`obj` with every credential-shaped string replaced, through dicts and lists."""
    if isinstance(obj, str):
        return TOKEN_RX.sub("<redacted>", obj)
    if isinstance(obj, dict):
        return {str(k): scrub(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [scrub(v) for v in obj]
    return obj


def page_facts(page: Any) -> dict:
    """What a fleet page says about itself, cut down to PAGE_FACTS: short, single-line, scrubbed strings.
    It is the page's word, so it is data for the session that reads it, never an instruction."""
    if not isinstance(page, dict):
        return {}
    out = {}
    for key in PAGE_FACTS:
        value = page.get(key)
        if isinstance(value, str) and value.strip():
            out[key] = scrub(" ".join(value.split())[:FACT_MAX])
    return out


def _int(value: Any, name: str, low: int, high: int, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    return max(low, min(high, value))


def _ref(args: dict) -> str:
    ref = args.get("ref")
    if not isinstance(ref, str) or not REF_RX.match(ref):
        raise ValueError("ref must be an element ref from the last page_snapshot (e1, e2, …), never a selector")
    return ref


def check(action: str, args: dict | None) -> dict:
    """The arguments of one action, cleaned, or ValueError saying what is wrong. Anything the action does not
    take is refused rather than dropped: a caller that sent `selector` or `script` should hear it is not a thing."""
    if action not in ACTIONS:
        raise ValueError(f"action must be one of {', '.join(ACTIONS)}")
    if args is None:
        args = {}
    if not isinstance(args, dict):
        raise ValueError("args must be an object")
    takes = {"snapshot": ("max_chars",), "read": ("ref", "max_chars"), "data": ("key", "max_chars"),
             "highlight": ("ref", "note"), "navigate": ("path",), "click": ("ref",),
             "fill": ("ref", "text", "submit"), "press": ("key", "ref")}[action]
    extra = sorted(set(args) - set(takes))
    if extra:
        raise ValueError(f"{action} takes {', '.join(takes)} only, not {', '.join(map(str, extra))}")
    out: dict = {}
    if action in ("snapshot", "read", "data"):
        out["max_chars"] = _int(args.get("max_chars"), "max_chars", 500, SNAPSHOT_MAX_CHARS, SNAPSHOT_MAX_CHARS)
    if action in ("read", "highlight", "click", "fill"):
        out["ref"] = _ref(args)
    if action == "data":
        key = args.get("key", "")
        if not isinstance(key, str) or len(key) > KEY_MAX or "\0" in key:
            raise ValueError(f"key must be a string of at most {KEY_MAX} characters")
        out["key"] = key.strip()
    if action == "highlight":
        note = args.get("note", "")
        if not isinstance(note, str):
            raise ValueError("note must be a string")
        out["note"] = " ".join(note.split())[:NOTE_MAX]
    if action == "navigate":
        path = args.get("path")
        if not isinstance(path, str) or not PATH_RX.match(path) or "\\" in path:
            raise ValueError("path must be an in-app path starting with one / (for example /loops), never a URL")
        out["path"] = path
    if action == "fill":
        text = args.get("text")
        if not isinstance(text, str) or len(text) > TEXT_MAX or "\0" in text:
            raise ValueError(f"text must be a string of at most {TEXT_MAX} characters, with no NUL")
        out["text"] = text
        submit = args.get("submit", False)
        if not isinstance(submit, bool):
            raise ValueError("submit must be true or false")
        out["submit"] = submit
    if action == "press":
        key = args.get("key")
        if key not in KEYS:
            raise ValueError(f"key must be one of {', '.join(KEYS)}")
        out["key"] = key
        if args.get("ref") not in (None, ""):
            out["ref"] = _ref(args)
    return out


def target_of(action: str, args: dict) -> str:
    """What an audit line and the dock's activity list say an action was aimed at. A fill is recorded by its
    length, never its text."""
    if action == "navigate":
        return args.get("path", "")
    if action == "press":
        return f"{args.get('key', '')}{' on ' + args['ref'] if args.get('ref') else ''}"
    if action == "fill":
        return f"{args.get('ref', '')} ({len(args.get('text', ''))} chars{', then Enter' if args.get('submit') else ''})"
    if action == "data":
        return args.get("key", "") or "(list)"
    return args.get("ref", "")


class _Pending:
    __slots__ = ("id", "action", "args", "ask", "client", "done", "payload", "taken")

    def __init__(self, action: str, args: dict, ask: bool, client: str):
        self.id = secrets.token_hex(6)
        self.action, self.args, self.ask, self.client = action, args, ask, client
        self.done = False
        self.taken = False
        self.payload: dict = {}


class _Session:
    def __init__(self, mode: str, now: float, origin: str | None = None, page: dict | None = None):
        self.sid = secrets.token_hex(16)
        self.mode = mode
        #: None for the console's own page; the origin a fleet page opened it from
        self.origin = origin
        self.page = page or {}
        self.created = dt.datetime.now(dt.timezone.utc)
        self.seen = now
        self.polling = 0
        #: counts this session's long polls; only the newest one is handed a command (see PageBridge.next)
        self.poll_gen = 0
        self.queue: deque[_Pending] = deque()
        self.pending: dict[str, _Pending] = {}
        self.stamps: deque[float] = deque()
        self.commands = 0
        self.paired = 0
        self.code: str | None = None
        self.code_until = 0.0


class PageBridge:
    """Every open page session of this console process. In memory on purpose: a session is a browser tab's
    live connection, so it means nothing after a restart."""

    def __init__(self, audit_path: Path | None = None, clock: Callable[[], float] = time.monotonic,
                 ceiling: Callable[[], str] | None = None):
        self.audit_path = audit_path
        #: where each audit line is ALSO printed (app.py sets the console's stderr, which the log plane
        #: ships); None in tests and wherever nothing collects it
        self.audit_stream: Any = None
        self.clock = clock
        #: reads _data/fleet.yml assistant.page_access; app.py wires core.assistant_page_access in
        self.ceiling: Callable[[], str] = ceiling or (lambda: "act")
        #: the same for pages of other fleet sites (assistant.fleet_pages); off until app.py wires it
        self.fleet_ceiling: Callable[[], str] = lambda: "off"
        self._cv = threading.Condition()
        self._sessions: dict[str, _Session] = {}
        #: sessions the operator ended -> until when their callers are told so (ENDED_TTL_S)
        self._ended: dict[str, float] = {}
        self._pair_fails: deque[float] = deque()

    # -- sessions ------------------------------------------------------------
    def _get(self, sid: str) -> _Session:
        s = self._sessions.get(sid) if isinstance(sid, str) and SID_RX.match(sid) else None
        if s is None:
            raise self._gone(sid, "no such page session — it was closed or dropped as idle; reopen the assistant")
        return s

    def _gone(self, sid: Any, why: str) -> NoSession:
        """The exception for a session that is not here: Ended while the operator's end is still remembered."""
        if isinstance(sid, str) and self._ended.get(sid, 0.0) > self.clock():
            return Ended(ENDED_WHY)
        return NoSession(why)

    def _sweep(self, now: float) -> None:
        for sid in [k for k, s in self._sessions.items() if not s.polling and now - s.seen > IDLE_S]:
            self._drop(sid, "the page session was dropped as idle")
        for sid in [k for k, until in self._ended.items() if until <= now]:
            del self._ended[sid]

    def _drop(self, sid: str, why: str) -> None:
        s = self._sessions.pop(sid, None)
        if s is None:
            return
        for p in s.pending.values():
            if not p.done:
                p.done, p.payload = True, {"ok": False, "kind": "closed", "error": why}
        self._cv.notify_all()

    def _live(self, s: _Session, now: float) -> bool:
        return s.polling > 0 or now - s.seen < LIVE_S

    def _ceiling(self, s: _Session) -> str:
        ceiling = self.fleet_ceiling() if s.origin else self.ceiling()
        return ceiling if ceiling in CEILINGS else "off"

    def _setting(self, s: _Session) -> str:
        return "assistant.fleet_pages" if s.origin else "assistant.page_access"

    def _get_fleet(self, sid: str, origin: str) -> _Session:
        """A fleet page's session, for the origin that opened it. Another origin is told what a stranger is."""
        s = self._get(sid)
        if not s.origin or s.origin != origin:
            raise NoSession("no such page session — it was closed or dropped as idle; share the page again")
        return s

    def end(self, handle: str) -> dict:
        """The operator ends one fleet page's sharing from the console (the Assist page's End). The session is
        named by the eight characters `sessions()` and the audit log show, so its id, which is the capability,
        is never sent anywhere to do this. Unknown: NoSession. Two sessions with the same eight characters:
        Ambiguous, never a guess. Whatever a session was waiting on is told why, the page's next poll and a
        paired session's next tool are told the same for ENDED_TTL_S, and one audit line records it. The
        console's own tabs are not ended this way: closing the dock does that."""
        if not (isinstance(handle, str) and HANDLE_RX.match(handle)):
            raise ValueError("id must be the eight characters the shared pages list shows")
        with self._cv:
            now = self.clock()
            self._sweep(now)
            hits = [s for s in self._sessions.values() if s.origin and s.sid.startswith(handle)]
            if not hits:
                raise NoSession("no fleet page is sharing itself under that id — it was closed or dropped as idle")
            if len(hits) > 1:
                raise Ambiguous("more than one shared page answers to that id — nothing was ended; reload the list")
            s = hits[0]
            out = {"ended": True, "id": s.sid[:8], "origin": s.origin, "page": dict(s.page), "paired": s.paired,
                   "commands": s.commands}
            self._ended[s.sid] = now + ENDED_TTL_S
            self._drop(s.sid, ENDED_WHY)
        self._audit(s.sid, "operator", "end", s.origin or "", s.mode, "ok", 0.0, s)
        return out

    def _view(self, s: _Session, now: float, code: bool = False) -> dict:
        ceiling = self._ceiling(s)
        out = {"sid": s.sid, "mode": s.mode, "ceiling": ceiling, "live": self._live(s, now),
               "created": s.created.isoformat(timespec="seconds"), "commands": s.commands, "paired": s.paired,
               "pairing": bool(s.code and now < s.code_until), "poll_s": POLL_MAX_S, "approval_s": APPROVAL_S}
        if s.origin:
            out.update(kind="fleet", origin=s.origin, page=dict(s.page))
        else:
            out["kind"] = "console"
        if code and out["pairing"]:
            out["code"] = s.code
            out["code_ttl_s"] = int(s.code_until - now)
        return out

    def open(self, mode: str = "ask", origin: str | None = None, page: Any = None) -> dict:
        """A page starts listening. Refused while its ceiling is off; a mode above the ceiling opens as look.
        `origin` marks a page of another fleet site (app.py has already checked it against the fleet's
        registered addresses): it is held to assistant.fleet_pages and counted against its own cap."""
        if mode not in MODES:
            raise ValueError(f"mode must be one of {', '.join(MODES)}")
        if origin is not None and not (isinstance(origin, str) and ORIGIN_RX.match(origin)):
            raise ValueError("origin must be a plain scheme://host[:port]")
        fleet = origin is not None
        ceiling = self.fleet_ceiling() if fleet else self.ceiling()
        if ceiling not in CEILINGS or ceiling == "off":
            raise Refused("fleet pages are off: _data/fleet.yml assistant.fleet_pages is off" if fleet else
                          "page access is off: _data/fleet.yml assistant.page_access is off")
        if ceiling == "look":
            mode = "look"
        cap = MAX_FLEET_SESSIONS if fleet else MAX_SESSIONS
        with self._cv:
            now = self.clock()
            self._sweep(now)
            mine = [s for s in self._sessions.values() if bool(s.origin) == fleet]
            if len(mine) >= cap:
                # the least recently seen page that is not listening makes room; a wall of live ones does not
                idle = sorted((s for s in mine if not self._live(s, now)), key=lambda s: s.seen)
                if not idle:
                    raise Busy(f"{cap} pages already share themselves with the assistant — close one")
                self._drop(idle[0].sid, "the page session made room for a newer one")
            s = _Session(mode, now, origin, page_facts(page) if fleet else None)
            self._sessions[s.sid] = s
            return self._view(s, now)

    def close(self, sid: str) -> bool:
        with self._cv:
            if sid not in self._sessions:
                return False
            self._drop(sid, "the person closed the assistant on that page")
            return True

    def has(self, sid: str) -> bool:
        """True for an open session of the console's own page: the only kind the docked assistant is started
        against (core._assist). A fleet page's session is reached by pairing, never handed to a job."""
        with self._cv:
            s = self._sessions.get(sid) if isinstance(sid, str) else None
            return s is not None and not s.origin

    def sessions(self) -> list[dict]:
        """Every open session, for the operator's eyes: which pages are shared right now. No session id: the
        first eight characters are what the audit log calls it."""
        with self._cv:
            now = self.clock()
            self._sweep(now)
            return [{"id": s.sid[:8], "kind": "fleet" if s.origin else "console", "origin": s.origin,
                     "page": dict(s.page), "mode": s.mode, "live": self._live(s, now), "paired": s.paired,
                     "commands": s.commands, "created": s.created.isoformat(timespec="seconds")}
                    for s in sorted(self._sessions.values(), key=lambda s: s.created)]

    # -- a fleet page's own calls: every one names the origin it came from ---------
    def fleet_close(self, sid: str, origin: str) -> bool:
        with self._cv:
            self._get_fleet(sid, origin)
            self._drop(sid, "the person closed the assistant on that page")
            return True

    def fleet_mode(self, sid: str, origin: str, mode: str) -> dict:
        with self._cv:
            self._get_fleet(sid, origin)
        return self.set_mode(sid, mode)

    def fleet_pair(self, sid: str, origin: str, on: bool = True) -> dict:
        with self._cv:
            self._get_fleet(sid, origin)
        return self.pair(sid, on)

    def fleet_next(self, sid: str, origin: str, wait_s: float = POLL_MAX_S, page: Any = None) -> dict:
        """A fleet page's long poll. It says where it is now on each one: a site of plain pages moves by
        loading a new address, and the same session carries on there."""
        with self._cv:
            s = self._get_fleet(sid, origin)
            facts = page_facts(page)
            if facts:
                s.page = facts
        return self.next(sid, wait_s)

    def fleet_result(self, sid: str, origin: str, cmd_id: str, ok: bool, result: Any = None,
                     error: str | None = None, kind: str | None = None) -> None:
        with self._cv:
            self._get_fleet(sid, origin)
        self.result(sid, cmd_id, ok, result, error, kind)

    def describe(self, sid: str) -> dict:
        """What the page's own dock shows about its session, the pairing code included while one is on."""
        with self._cv:
            return self._view(self._get(sid), self.clock(), code=True)

    def set_mode(self, sid: str, mode: str) -> dict:
        if mode not in MODES:
            raise ValueError(f"mode must be one of {', '.join(MODES)}")
        with self._cv:
            s = self._get(sid)
            if mode != "look" and self._ceiling(s) != "act":
                raise Refused(f"page actions are off: _data/fleet.yml {self._setting(s)} is not act")
            s.mode = mode
            return self._view(s, self.clock(), code=True)

    # -- pairing -------------------------------------------------------------
    def pair(self, sid: str, on: bool = True) -> dict:
        """The person switches pairing on (a fresh single-use code) or off. Only the page's own routes call it."""
        with self._cv:
            s = self._get(sid)
            now = self.clock()
            if on:
                s.code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LEN))
                s.code_until = now + PAIR_TTL_S
            else:
                s.code, s.code_until = None, 0.0
            return self._view(s, now, code=True)

    def attach(self, code: str) -> dict:
        """A second session presents a pairing code. The code is spent on success; wrong codes are counted
        across every session, and past PAIR_FAILS in PAIR_WINDOW_S nobody attaches until the window clears."""
        clean = re.sub(r"[\s-]", "", str(code or "")).upper()
        with self._cv:
            now = self.clock()
            while self._pair_fails and now - self._pair_fails[0] > PAIR_WINDOW_S:
                self._pair_fails.popleft()
            if len(self._pair_fails) >= PAIR_FAILS:
                raise Busy("too many wrong pairing codes — wait a minute, then read the code off the dock again")
            match = None
            for s in self._sessions.values():
                if s.code and now < s.code_until and hmac.compare_digest(s.code.encode(), clean.encode()):
                    match = s
            if match is None or len(clean) != CODE_LEN:
                self._pair_fails.append(now)
                raise Refused("that pairing code is not on any open page: switch pairing on in the assistant dock "
                              "and use the code it shows (single use, ten minutes)")
            match.code, match.code_until = None, 0.0
            match.paired += 1
            view = self._view(match, now)
        self._audit(match.sid, "paired", "attach", match.origin or "", view["mode"], "ok", 0.0, match)
        return view

    # -- the page's side -----------------------------------------------------
    def next(self, sid: str, wait_s: float = POLL_MAX_S) -> dict:
        """The page's long poll: the next command for it, or none after `wait_s`. Being asked is what keeps a
        session live.

        Only the newest poll of a session is handed a command. A page that reloads, or loads its next address
        (a site of plain pages moves that way and keeps its session), leaves its last poll waiting here with
        nobody on the other end; a command handed to that one would be lost. So an older poll stands down the
        moment a newer one arrives."""
        wait_s = max(0.0, min(float(wait_s), POLL_MAX_S))
        with self._cv:
            s = self._get(sid)
            s.polling += 1
            s.poll_gen += 1
            mine = s.poll_gen
            self._cv.notify_all()
            try:
                deadline = self.clock() + wait_s
                while True:
                    now = self.clock()
                    s.seen = now
                    if sid not in self._sessions:
                        raise self._gone(sid, "the page session was closed")
                    if s.poll_gen != mine:
                        return {"command": None, "session": self._view(s, now, code=True), "superseded": True}
                    if s.queue:
                        p = s.queue.popleft()
                        p.taken = True
                        return {"command": {"id": p.id, "action": p.action, "args": p.args, "ask": p.ask,
                                            "client": p.client}, "session": self._view(s, now, code=True)}
                    left = deadline - now
                    if left <= 0:
                        return {"command": None, "session": self._view(s, now, code=True)}
                    self._cv.wait(timeout=min(left, 1.0))
            finally:
                s.polling -= 1
                s.seen = self.clock()

    def result(self, sid: str, cmd_id: str, ok: bool, result: Any = None, error: str | None = None,
               kind: str | None = None) -> None:
        """The page says what happened to one command. Unknown or already answered ids are ignored: the
        session that asked has stopped waiting."""
        with self._cv:
            s = self._get(sid)
            p = s.pending.get(cmd_id) if isinstance(cmd_id, str) and CMD_RX.match(cmd_id) else None
            if p is None or p.done:
                return
            if ok:
                payload: dict = {"ok": True, "result": _fit(scrub(result))}
            else:
                payload = {"ok": False, "kind": kind if kind in ("declined", "refused", "page") else "page",
                           "error": scrub(str(error or "the page could not do it"))[:2000]}
            p.done, p.payload = True, payload
            self._cv.notify_all()

    # -- the session's side --------------------------------------------------
    def command(self, sid: str, action: str, args: dict | None = None, client: str = "dock") -> dict:
        """One action on one page, from a session's page tool: checked, queued for the page, and waited on.
        Always answers a document: {ok: true, result} or {ok: false, kind, error} — a refusal, a decline and a
        timeout are things the session should read and act on, not transport errors."""
        clean = check(action, args)
        client = "paired" if client == "paired" else "dock"
        started = time.monotonic()
        with self._cv:
            s = self._get(sid)
            now = self.clock()
            mode, ceiling = s.mode, self._ceiling(s)
            refusal = None
            if ceiling == "off":
                refusal = f"page access is off: _data/fleet.yml {self._setting(s)} is off"
            elif action in ACT and ceiling != "act":
                refusal = f"page actions are off: _data/fleet.yml {self._setting(s)} is look"
            elif action in ACT and mode == "look":
                refusal = (f"the person set this page to Look only, so {action} is not allowed. Say what you "
                           "would do and where, and let them do it or switch the dock to Ask or Act")
            if refusal is None and not self._live(s, now):
                refusal = ("the page is not listening: the assistant dock is closed or its tab is asleep. "
                           "Ask the person to open it")
            if refusal is None:
                while s.stamps and now - s.stamps[0] > 60.0:
                    s.stamps.popleft()
                if len(s.stamps) >= COMMANDS_PER_MIN:
                    raise Busy(f"more than {COMMANDS_PER_MIN} page commands in a minute — slow down")
                if len(s.queue) >= MAX_QUEUE:
                    raise Busy("the page is still working through earlier commands — wait for them")
            if refusal is not None:
                out = {"ok": False, "kind": "refused", "error": refusal}
            else:
                ask = mode == "ask" and action in ASKS
                p = _Pending(action, clean, ask, client)
                s.pending[p.id] = p
                s.queue.append(p)
                s.stamps.append(now)
                s.commands += 1
                self._cv.notify_all()
                limit = (APPROVAL_S + ACT_TIMEOUT_S) if ask else (ACT_TIMEOUT_S if action in ACT else LOOK_TIMEOUT_S)
                deadline = now + limit
                while not p.done:
                    left = deadline - self.clock()
                    if left <= 0:
                        break
                    self._cv.wait(timeout=min(left, 1.0))
                s.pending.pop(p.id, None)
                if p.done:
                    out = p.payload
                else:
                    if p in s.queue:
                        s.queue.remove(p)
                    out = {"ok": False, "kind": "timeout",
                           "error": ("the person did not answer within "
                                     f"{int(APPROVAL_S)} s, so it was not done" if ask and p.taken else
                                     "the page did not answer in time — it may be busy, asleep or closed")}
        outcome = "ok" if out.get("ok") else str(out.get("kind") or "failed")
        self._audit(sid, client, action, target_of(action, clean), mode, outcome, time.monotonic() - started, s)
        return {**out, "action": action, "mode": mode}

    # -- audit ---------------------------------------------------------------
    def _audit(self, sid: str, client: str, action: str, target: str, mode: str, outcome: str, took_s: float,
               session: _Session | None = None) -> None:
        """One line per command, attach and operator's end. `id` makes a line addressable (the lake keys on it);
        `kind` says whose page it was, and a fleet page's line names its origin and the repo the page said it
        is. Never the session id, never typed text (target_of), and the target is scrubbed twice over."""
        path, stream = self.audit_path, self.audit_stream
        if path is None and stream is None:
            return
        row = {"id": secrets.token_hex(6), "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
               "session": sid[:8], "client": client, "kind": "fleet" if session is not None and session.origin
               else "console", "action": action,
               "target": SECRETISH_RX.sub("<redacted>", scrub(target))[:300], "mode": mode,
               "outcome": outcome, "ms": int(took_s * 1000)}
        if session is not None and session.origin:
            row["origin"] = session.origin
            if session.page.get("repo"):
                row["repo"] = SECRETISH_RX.sub("<redacted>", str(session.page["repo"]))[:120]
        line = json.dumps(row, ensure_ascii=False)
        if stream is not None:
            try:
                print("page-bridge audit " + line, file=stream, flush=True)
            except (OSError, ValueError) as exc:
                print(f"page_bridge: audit line not printed: {exc}", flush=True)
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists() and path.stat().st_size > AUDIT_MAX_BYTES:
                path.replace(path.with_suffix(path.suffix + ".1"))
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError as exc:
            # The command already happened on the page; an unwritable audit file must be said, not swallowed.
            print(f"page_bridge: audit line not written to {path}: {exc}", flush=True)


def _fit(result: Any) -> Any:
    """A result no larger than RESULT_MAX_CHARS as JSON; a larger one is cut and says so."""
    try:
        text = json.dumps(result, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(result)
        result = text
    if len(text) <= RESULT_MAX_CHARS:
        return result
    return {"truncated": True, "chars": len(text), "text": text[:RESULT_MAX_CHARS],
            "note": "cut at the bridge's result cap — ask for a narrower read (a ref, a smaller max_chars)"}


#: the one bridge of a console process: app.py serves it, core.py asks it whether a session exists
BRIDGE = PageBridge()
