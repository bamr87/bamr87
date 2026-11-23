#!/usr/bin/env python3
"""
assist_eval_console — a recorded console for the assistant's eval set (evals/console-assist, docs/EVALS.md).

The mirror of assist_standin.py: the stand-in scripts the model and keeps the page real; this keeps the
model real and records the page. One case of the eval set is played on 127.0.0.1:<free port>:

  POST /api/assist/page-command   what the MCP layer's page tools call. The REAL broker (page_bridge.PageBridge)
                                  sits in front, so the argument checks, the ceiling, the Look-mode refusal and
                                  the answer's shape are the broker's own code, not a copy. Behind it a thread
                                  plays the page from the case's recording: named states, each with the outline a
                                  snapshot returns and what a command answers there, refusals included.
  POST /api/assist/page-attach    the broker's own answer to a pairing code (no page of a case offers one).
  GET  /api/...                   the documents the case recorded for the fleet read tools (its `api:`, over
                                  the set's shared ones); anything else is a JSON 404 that says it is not part
                                  of this recording.

Every request is appended, in order, with what it answered, to the JSONL log it was given: that log is what
the eval grades. Loopback only, no token read or needed, no header ever logged, a fill recorded by its
length, nothing written but that log. No model, no network beyond loopback, stdlib only.

A recording (a case's `input.page`, over the set's shared `page:` block):

    mode: act                      # look | ask | act: what the person chose in the dock
    start: form                    # optional; the first state otherwise
    states:
      form:
        route: /ops/assist
        outline: |                 # what page_snapshot returns, in the page's own format (pageBridge.ts)
          == the page ==
            [e1] button "Run"
        rules:                     # first match wins; a key left out matches anything
          - {action: click, ref: e1, goto: dialog}                        # done: the result is composed
          - {action: click, ref: e2, answer: {ok: false, kind: page, error: "…"}}   # the page's refusal, verbatim
    data: {'["ops"]': {...}}       # page_data documents

A command no rule covers is answered the way the page itself would where that is known (a ref the snapshot
does not list, a region read, a highlight, a path another state is at) and otherwise left unanswered, which
the broker reports as "the page could not do it"; the log row says `recorded: false`, so a verdict that rests
on a gap can be seen.

    python3 tools/console/assist_eval_console.py --case <id> [--log PATH]   # play one case until Ctrl-C
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import page_bridge  # noqa: E402 — the broker itself; stdlib only

ROOT = _HERE.parents[1]
#: where the page's own sentences live: the console page's half of the bridge, and the fleet kit's payload
#: (ADR 0014 P2 changes the console page's half; a recording is held to whichever of the two says its words)
PAGE_SOURCES = ("tools/console/web/src/assist/pageBridge.ts", "templates/assistant/fleet-assist.js")
NAV_SOURCE = "tools/console/web/src/nav.ts"
LINKS_SOURCE = "tools/console/web/src/lib/links.ts"
#: what each action may be matched on in a rule (page_bridge.check holds the wire's own list)
RULE_ARGS = {"read": ("ref",), "data": ("key",), "highlight": ("ref",), "navigate": ("path",),
             "click": ("ref",), "fill": ("ref", "text"), "press": ("key", "ref")}
NEGATIVE_KINDS = ("page", "declined", "refused")
REF_IN_OUTLINE_RX = re.compile(r"\[(e\d{1,5})\]")
CONTROL_RX = re.compile(r"\[(e\d{1,5})\]\s+([a-z][a-z ]*?)(?:\s+\"((?:[^\"\\]|\\.)*)\")?(?=\s|$)")
BODY_MAX = 1_000_000
LOG_VALUE_MAX = 4000


# --------------------------------------------------------------------------- #
# the recording: reading it
# --------------------------------------------------------------------------- #
def merged_page(page: dict, defaults: dict | None) -> dict:
    """A case's page over the set's shared block (the page list, the snapshot's note, the page's sentences)."""
    out = dict(defaults or {})
    out.update(page or {})
    out["says"] = {**((defaults or {}).get("says") or {}), **((page or {}).get("says") or {})}
    return out


def refs_in(outline: str) -> list[str]:
    """Every ref an outline lists, in order, once."""
    return list(dict.fromkeys(REF_IN_OUTLINE_RX.findall(outline or "")))


def element(outline: str, ref: str) -> dict | None:
    """What an outline says about one ref: its line, its kind and name when it is a control, and for a region
    (a table) the more deeply indented lines under it."""
    lines = (outline or "").splitlines()
    for i, line in enumerate(lines):
        if f"[{ref}]" not in line:
            continue
        m = next((m for m in CONTROL_RX.finditer(line) if m.group(1) == ref), None)
        depth = len(line) - len(line.lstrip())
        under = []
        for rest in lines[i + 1:]:
            if rest.strip() and len(rest) - len(rest.lstrip()) <= depth:
                break
            under.append(rest.strip())
        return {"line": line.strip(), "kind": m.group(2).strip() if m else "control",
                "name": (m.group(3) or "") if m else "", "under": [u for u in under if u]}
    return None


def _matches(rule: dict, action: str, args: dict) -> bool:
    actions = rule.get("action")
    if action not in (actions if isinstance(actions, list) else [actions]):
        return False
    return all(key not in rule or rule[key] == args.get(key) for key in ("ref", "path", "key", "text"))


# --------------------------------------------------------------------------- #
# the recording: checking it offline (the eval's --dry-run)
# --------------------------------------------------------------------------- #
def validate_recording(inp: dict, defaults: dict | None = None) -> list[str]:
    """What is wrong with one case's recorded page and documents, as a list of sentences; empty when it can
    be played. Offline: no socket is opened."""
    errs: list[str] = []
    api = inp.get("api")
    if api is not None:
        if not isinstance(api, dict):
            errs.append("input.api must map a GET path to its document")
        else:
            errs += [f"input.api: {p!r} is not an /api/ path" for p in api
                     if not (isinstance(p, str) and p.startswith("/api/") and "?" not in p)]
    if inp.get("page") is None:
        return errs
    if not isinstance(inp["page"], dict):
        return errs + ["input.page must be a mapping"]
    page = merged_page(inp["page"], defaults)
    if page.get("mode") not in page_bridge.MODES:
        errs.append(f"input.page.mode must be one of {', '.join(page_bridge.MODES)}")
    if page.get("ceiling", "act") not in ("look", "act"):
        errs.append("input.page.ceiling must be look or act")
    states = page.get("states")
    if not isinstance(states, dict) or not states:
        return errs + ["input.page.states must be a non-empty mapping of named page states"]
    if page.get("start", next(iter(states))) not in states:
        errs.append(f"input.page.start {page.get('start')!r} is not a state")
    if page.get("data") is not None and not isinstance(page["data"], dict):
        errs.append("input.page.data must map a page_data key to its document")
    for name, state in states.items():
        where = f"input.page.states.{name}"
        if not isinstance(state, dict):
            errs.append(f"{where}: not a mapping")
            continue
        route = state.get("route")
        if not isinstance(route, str) or not page_bridge.PATH_RX.match(route):
            errs.append(f"{where}.route must be an in-app path")
        outline = state.get("outline")
        if not isinstance(outline, str) or not outline.strip():
            errs.append(f"{where}.outline must be the text a snapshot returns")
            outline = ""
        for key in ("dialogs", "errors", "failed_documents"):
            if not isinstance(state.get(key, []), list):
                errs.append(f"{where}.{key} must be a list")
        known = set(refs_in(outline))
        rules = state.get("rules", [])
        if not isinstance(rules, list):
            errs.append(f"{where}.rules must be a list")
            continue
        for i, rule in enumerate(rules):
            errs += [f"{where}.rules[{i}]: {e}" for e in _rule_errors(rule, known, states)]
    return errs


def _rule_errors(rule: Any, known: set[str], states: dict) -> list[str]:
    if not isinstance(rule, dict):
        return ["not a mapping"]
    errs = []
    actions = rule.get("action")
    actions = actions if isinstance(actions, list) else [actions]
    bad = [a for a in actions if a not in RULE_ARGS]
    if bad or not actions:
        return [f"action must be one of {', '.join(RULE_ARGS)} (a snapshot is the state's own outline), got {bad}"]
    extra = sorted(set(rule) - {"action", "ref", "path", "key", "text", "answer", "result", "goto", "recoverable"})
    if extra:
        errs.append(f"unknown key(s) {extra}")
    for key in ("ref", "path", "key", "text"):
        if key in rule and not all(key in RULE_ARGS[a] for a in actions):
            errs.append(f"{key} is not an argument of {', '.join(map(str, actions))}")
    answer = rule.get("answer")
    negative = isinstance(answer, dict) and answer.get("ok") is False
    if answer is not None:
        if not isinstance(answer, dict) or not isinstance(answer.get("ok"), bool):
            errs.append("answer must be a mapping with ok: true|false")
        elif negative and (answer.get("kind") not in NEGATIVE_KINDS or not str(answer.get("error") or "").strip()):
            errs.append(f"a refusal needs kind ({', '.join(NEGATIVE_KINDS)}) and the error text the page gives")
        elif not negative and "result" not in answer:
            errs.append("answer with ok: true needs its result (or leave answer out: the result is composed)")
    if "ref" in rule and rule["ref"] not in known and not negative:
        # a ref the snapshot does not list can only be one the page refuses (a stale ref)
        errs.append(f"ref {rule['ref']} is not in this state's outline")
    if "key" in rule and "press" in actions and rule["key"] not in page_bridge.KEYS:
        errs.append(f"key {rule['key']!r} is not one the page takes")
    if "goto" in rule:
        if rule["goto"] not in states:
            errs.append(f"goto {rule['goto']!r} is not a state")
        if negative:
            errs.append("a refusal changes nothing: it cannot goto another state")
    if "recoverable" in rule and not negative:
        errs.append("recoverable marks a refusal the session may recover from (a stale ref); this rule is not one")
    if "result" in rule and (answer is not None or not isinstance(rule["result"], dict)):
        errs.append("result is a mapping merged into the composed answer; it cannot ride with answer")
    return errs


# --------------------------------------------------------------------------- #
# the page's own sentences: held to the page's code, never to memory
# --------------------------------------------------------------------------- #
_JS_STRING_RX = re.compile(r"`((?:[^`\\]|\\.)*)`|'((?:[^'\\\n]|\\.)*)'")
_HOLE_RX = re.compile(r"\$\{[^}]*\}")
_STATIC_MIN = 12
_SENTENCES: dict[int, list[re.Pattern]] = {}


def _unescape(text: str) -> str:
    return re.sub(r"\\(.)", lambda m: {"n": "\n", "t": "\t"}.get(m.group(1), m.group(1)), text)


def page_sentences(root: Path = ROOT, sources: tuple[str, ...] = PAGE_SOURCES) -> list[re.Pattern]:
    """Every sentence the page's code can say, as patterns: each string literal of the sources, its `${…}`
    holes open, and every run of neighbouring literals on a line joined with a hole between them (the kit
    builds its sentences with `+`: 'it was not ' + verb + '. Say …'). A source that is not there contributes
    nothing; the caller decides what an empty list means. A pattern with too little fixed text is dropped:
    one that is all holes would vouch for anything."""
    texts = []
    for rel in sources:
        try:
            texts.append((Path(root) / rel).read_text(encoding="utf-8"))
        except OSError:
            continue
    key = hash(tuple(texts))
    if key in _SENTENCES:             # compiled once per content: a set is validated many times in one test run
        return _SENTENCES[key]
    out: list[re.Pattern] = []
    seen: set[str] = set()
    for text in texts:
        for line in text.splitlines():
            parts = []
            for m in _JS_STRING_RX.finditer(line):
                if m.group(1) is not None:
                    parts.append(".*?".join(re.escape(_unescape(p)) for p in _HOLE_RX.split(m.group(1))))
                else:
                    parts.append(re.escape(_unescape(m.group(2))))
            runs = [".*?".join(parts[i:j]) for i in range(len(parts)) for j in range(i + 1, len(parts) + 1)]
            for pattern in runs:
                if pattern not in seen and len(re.sub(r"\.\*\?|\\", "", pattern)) >= _STATIC_MIN:
                    seen.add(pattern)
                    out.append(re.compile(pattern, re.S))
    _SENTENCES[key] = out
    return out


def said_by_page(text: str, sentences: list[re.Pattern]) -> bool:
    """True when the page's code can produce `text`; a `{name}` in it stands for a value the page fills in."""
    concrete = re.sub(r"\{[a-z_]+\}", "X", str(text))
    return any(p.fullmatch(concrete) for p in sentences)


def link_paths(root: Path = ROOT) -> dict[str, str]:
    """`to.<name>()` → its path in the default build (web/src/lib/links.ts): a constant, or the `else` branch of a
    build-time ternary such as `(DESKTOP_FIRST ? '/home' : '/')`, since the default front door is `home`."""
    try:
        text = (Path(root) / LINKS_SOURCE).read_text(encoding="utf-8")
    except OSError:
        return {}
    out = {name: path for name, path in re.findall(r"^\s+(\w+): \(\) => '([^']+)',?$", text, re.M)}
    out.update(re.findall(r"^\s+(\w+): \(\) => \(\w+ \? '[^']+' : '([^']+)'\),?$", text, re.M))
    return out


def nav_pairs(root: Path = ROOT) -> set[str]:
    """`Label /path` for every page of the console's navigation (web/src/nav.ts), as a snapshot's `pages` says it;
    a `to: to.<name>()` entry resolves through lib/links.ts to its default-build path."""
    try:
        text = (Path(root) / NAV_SOURCE).read_text(encoding="utf-8")
    except OSError:
        return set()
    pairs = {f"{label} {to}" for label, to in re.findall(r"label: '([^']+)', to: '([^']+)'", text)}
    links = link_paths(root)
    pairs |= {f"{label} {links[name]}" for label, name in re.findall(r"label: '([^']+)', to: to\.(\w+)\(\)", text)
              if name in links}
    return pairs


def recorded_refusals(inp: dict, defaults: dict | None = None) -> list[tuple[str, str]]:
    """(where, text) of every sentence a recording puts in the page's mouth: its refusals and its shared says."""
    out: list[tuple[str, str]] = []
    if not isinstance(inp.get("page"), dict):
        return out
    page = merged_page(inp["page"], defaults)
    for name, state in (page.get("states") or {}).items():
        for i, rule in enumerate((state or {}).get("rules") or [] if isinstance(state, dict) else []):
            answer = rule.get("answer") if isinstance(rule, dict) else None
            if isinstance(answer, dict) and answer.get("ok") is False:
                out.append((f"states.{name}.rules[{i}]", str(answer.get("error") or "")))
    return out


# --------------------------------------------------------------------------- #
# the console
# --------------------------------------------------------------------------- #
class RecordedConsole:
    """One case, served on loopback until stop(). Use it as a context manager, or start() / stop()."""

    def __init__(self, inp: dict, log_path: Path | str, *, defaults: dict | None = None, case_id: str = "",
                 shared_api: dict | None = None):
        self.case_id = case_id
        #: the set's shared documents (its top-level `api:`), with the case's own over them
        self.api = {**(shared_api or {}), **(inp.get("api") or {})}
        self.page = merged_page(inp["page"], defaults) if isinstance(inp.get("page"), dict) else None
        self.log_path = Path(log_path)
        self.bridge = page_bridge.PageBridge(ceiling=lambda: (self.page or {}).get("ceiling", "act"))
        self.sid: str | None = None
        self.mode: str | None = None
        self.state: str | None = None
        self.url = ""
        self._n = 0
        self._log_lock = threading.Lock()
        self._page_lock = threading.Lock()     # one page command at a time: its row and its answer stay paired
        self._facts: dict | None = None
        self._server: ThreadingHTTPServer | None = None
        self._threads: list[threading.Thread] = []

    # -- life ----------------------------------------------------------------
    def start(self) -> "RecordedConsole":
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_path.write_text("", encoding="utf-8")
        if self.page is not None:
            self.state = self.page.get("start") or next(iter(self.page["states"]))
            view = self.bridge.open(self.page["mode"])
            # the broker's reading of the mode: a look ceiling opens every page as look
            self.sid, self.mode = view["sid"], view["mode"]
            self._threads.append(threading.Thread(target=self._play_page, name="recorded-page", daemon=True))
        console = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self):  # noqa: N802 — http.server's name
                console._serve(self, "GET")

            def do_POST(self):  # noqa: N802
                console._serve(self, "POST")

            def log_message(self, *_):   # the JSONL log is the record; nothing goes to stderr
                return

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}"
        # a short poll: stop() waits for one, and a run starts and stops a console per case
        self._threads.append(threading.Thread(target=self._server.serve_forever, kwargs={"poll_interval": 0.05},
                                              name="recorded-console", daemon=True))
        for t in self._threads:
            t.start()
        return self

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self.sid:
            self.bridge.close(self.sid)      # the page's long poll ends with the session
        for t in self._threads:
            t.join(timeout=10)
        self._threads = []

    def __enter__(self) -> "RecordedConsole":
        return self.start()

    def __exit__(self, *_) -> None:
        self.stop()

    def rows(self) -> list[dict]:
        return read_log(self.log_path)

    # -- HTTP ----------------------------------------------------------------
    def _serve(self, h: BaseHTTPRequestHandler, method: str) -> None:
        url = urlsplit(h.path)
        row: dict = {"method": method, "path": url.path}
        body: Any = {}
        if method == "POST":
            try:
                size = int(h.headers.get("Content-Length") or 0)
                body = json.loads(h.rfile.read(min(size, BODY_MAX)) or b"{}") if size <= BODY_MAX else None
            except (ValueError, OSError):
                body = None
            if not isinstance(body, dict):
                return self._send(h, 400, {"detail": "the body must be one JSON object"}, {**row, "kind": "other"})
        if method == "POST" and url.path == "/api/assist/page-command":
            status, doc = self._page_command(body, row)
        elif method == "POST" and url.path == "/api/assist/page-attach":
            row.update(kind="other", recorded=True)
            status, doc = self._broker(self.bridge.attach, str(body.get("code") or "")[:32])
        elif method == "GET" and url.path in self.api:
            row.update(kind="api", query=dict(parse_qsl(url.query)), recorded=True)
            status, doc = 200, self.api[url.path]
        else:
            row.update(kind="api" if method == "GET" else "other", recorded=False)
            if url.query:
                row["query"] = dict(parse_qsl(url.query))
            # the route asked for is in the log row, not echoed back: a response carries nothing a caller sent
            status, doc = 404, {"detail": "that route is not part of this recording (evals/console-assist)"}
        self._send(h, status, doc, row)

    def _send(self, h: BaseHTTPRequestHandler, status: int, doc: Any, row: dict) -> None:
        data = json.dumps(doc, ensure_ascii=False).encode("utf-8")
        self._log({**row, "status": status, "chars": len(data)})
        try:
            h.send_response(status)
            h.send_header("Content-Type", "application/json")
            h.send_header("Content-Length", str(len(data)))
            h.end_headers()
            h.wfile.write(data)
        except OSError as exc:
            self._log({"method": row.get("method"), "path": row.get("path"), "kind": "other",
                       "note": f"the caller went away before the answer was sent: {exc}"})

    def _broker(self, fn, *args) -> tuple[int, Any]:
        """One call into the broker, with the console's own mapping of its refusals to HTTP (app.py `_page`).
        The status is the broker's; the sentence is a fixed one for each kind of refusal, never an exception's
        own text: nothing a caller sent, and nothing an exception carries, is written back into a response."""
        try:
            return 200, fn(*args)
        except page_bridge.NoSession:
            return 404, {"detail": "no such page session — it was closed or dropped as idle; reopen the assistant"}
        except ValueError:
            return 400, {"detail": "that is not a valid page command: the action is one of "
                                   f"{', '.join(page_bridge.ACTIONS)}; an element is a ref from the last snapshot "
                                   "(e12), never a selector; a path is an in-app path, never a URL; a key is one "
                                   f"of {', '.join(page_bridge.KEYS)}"}
        except page_bridge.Refused:
            return 403, {"detail": "the console's ceiling does not allow that: _data/fleet.yml assistant.page_access"}
        except page_bridge.Busy:
            return 429, {"detail": "too many page commands, or the page is still working through earlier ones — "
                                   "slow down and wait for them"}

    def _page_command(self, body: dict, row: dict) -> tuple[int, Any]:
        action, args = str(body.get("action") or ""), body.get("args")
        shown = dict(args) if isinstance(args, dict) else {}
        if isinstance(shown.get("text"), str):
            shown["text_chars"] = len(shown.pop("text"))       # a fill is recorded by its length, as the broker's audit is
        row.update(kind="page", action=action, tool=f"page_{action}", args=shown,
                   client="paired" if body.get("client") == "paired" else "dock")
        with self._page_lock:
            before, self._facts = self.state, None
            status, doc = self._broker(self.bridge.command, str(body.get("sid") or ""), action, args,
                                       str(body.get("client") or "dock"))
            facts = self._facts or {}
            row.update(state=before, state_after=self.state)
        if status != 200:
            # the broker turned it away before any page saw it: a malformed action, no session, a cap
            row.update(ok=False, answer_kind="http", error=doc.get("detail"), refusal=False, recorded=True)
            return status, doc
        ok = bool(doc.get("ok"))
        kind = None if ok else str(doc.get("kind") or "page")
        recorded = facts.get("recorded", True)
        row.update(ok=ok, mode=doc.get("mode"), answer_kind=kind, recorded=recorded,
                   refusal=(not ok) and recorded and (kind in ("refused", "declined")
                                                      or (kind == "page" and not facts.get("recoverable", False))))
        if facts.get("fault"):
            row["fault"] = facts["fault"]
        if ok:
            result = doc.get("result")
            row["result"] = ({k: result.get(k) for k in ("route", "refs", "dialogs")} if action == "snapshot"
                             and isinstance(result, dict) else _clip(result))
        else:
            row["error"] = doc.get("error")
        return status, doc

    def _log(self, row: dict) -> None:
        with self._log_lock:
            self._n += 1
            line = {"n": self._n, "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds"), **row}
            with self.log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(line, ensure_ascii=False) + "\n")

    # -- the page, played from the recording ------------------------------------
    def _play_page(self) -> None:
        while True:
            try:
                got = self.bridge.next(self.sid, 5.0)
            except page_bridge.NoSession:
                return                                    # stop() closed the session
            cmd = got.get("command")
            if not cmd:
                continue
            try:
                ok, result, error, kind, facts = self._answer(cmd["action"], cmd.get("args") or {})
            except (KeyError, TypeError, ValueError, AttributeError) as exc:
                # a recording this player cannot read: the session hears the broker's own "could not do it",
                # and the row carries why, so the fault is the recording's and is seen
                ok, result, error, kind, facts = False, None, None, "page", {"recorded": False,
                                                                           "fault": f"{type(exc).__name__}: {exc}"}
            self._facts = facts
            self.bridge.result(self.sid, cmd["id"], ok, result, error, kind)

    def _snapshot(self) -> dict:
        page, state = self.page, self.page["states"][self.state]
        outline = str(state.get("outline") or "").rstrip("\n")
        return {"route": state["route"], "title": state.get("title") or page.get("title") or "",
                "mode": self.mode, "viewport": page.get("viewport") or {"width": 1280, "height": 800, "scrolled": 0},
                "dialogs": list(state.get("dialogs") or []), "outline": outline, "refs": len(refs_in(outline)),
                "truncated": False, "loading": int(state.get("loading") or 0),
                "failed_documents": list(state.get("failed_documents") or []),
                "errors": list(state.get("errors") or []), "pages": list(page.get("pages") or []),
                "note": page.get("note") or ""}

    def _answer(self, action: str, args: dict) -> tuple[bool, Any, str | None, str | None, dict]:
        """(ok, result, error, kind, facts) for one command in the current state."""
        page, says = self.page, self.page.get("says") or {}
        state = page["states"][self.state]
        outline = str(state.get("outline") or "")
        if action == "snapshot":
            return True, self._snapshot(), None, None, {"recorded": True}
        rule = next((r for r in state.get("rules") or [] if _matches(r, action, args)), None)
        ref = args.get("ref")
        el = element(outline, ref) if ref else None
        if ref and el is None and (rule is None or "ref" not in rule) and says.get("unknown_ref"):
            # what the page says of a ref its last snapshot did not list, before any other rule of the page
            # (pageBridge.ts resolve()); the session takes a new snapshot
            return False, None, says["unknown_ref"].replace("{ref}", str(ref)), "page", {"recorded": True,
                                                                                         "recoverable": True}
        if rule is not None and isinstance(rule.get("answer"), dict):
            a = rule["answer"]
            if a["ok"]:
                if rule.get("goto"):
                    self.state = rule["goto"]
                return True, a.get("result"), None, None, {"recorded": True}
            return False, None, str(a["error"]), a["kind"], {"recorded": True,
                                                              "recoverable": bool(rule.get("recoverable"))}
        if action == "data":
            docs = page.get("data") or {}
            key = str(args.get("key") or "")
            if not key:
                listing = {"documents": [{"key": k, "status": "success", "read_at": page.get("read_at"),
                                          "shown": True} for k in docs]}
                if says.get("data_note"):
                    listing["note"] = says["data_note"]
                return True, listing, None, None, {"recorded": True}
            hit = key if key in docs else next((k for k in docs if k == json.dumps([key])), None)
            if hit is None:
                if says.get("no_document"):
                    return False, None, says["no_document"].replace("{key}", key), "page", {"recorded": True,
                                                                                            "recoverable": True}
                return False, None, None, "page", {"recorded": False}
            text = json.dumps(docs[hit], ensure_ascii=False)
            return True, {"key": hit, "status": "success", "read_at": page.get("read_at"), "chars": len(text),
                          "truncated": False, "document": docs[hit]}, None, None, {"recorded": True}
        if rule is None and action == "read" and el is not None:
            return True, {"ref": ref, "text": "\n".join(el["under"]) or el["line"], "truncated": False}, None, None, \
                {"recorded": True}
        if rule is None and action == "highlight" and el is not None:
            name = el["name"] or (el["under"][0][:80] if el["under"] else "")
            return True, {"highlighted": f"the {el['kind']}" + (f' "{name}"' if name else "")}, None, None, \
                {"recorded": True}
        goto = rule.get("goto") if rule is not None else None
        if rule is None and action == "navigate":
            goto = next((n for n, s in page["states"].items() if s.get("route") == args.get("path")), None)
        if rule is None and goto is None:
            # nothing recorded for this: the page gives no answer, and the broker says so in its own words
            return False, None, None, "page", {"recorded": False}
        before = state["route"]
        if goto:
            self.state = goto
        after = page["states"][self.state]
        tail = {"route": after["route"], "dialogs": list(after.get("dialogs") or [])}
        name = (el or {}).get("name") or (el or {}).get("kind") or ""
        if action == "navigate":
            result: dict = {"route": after["route"], "route_before": before, "base": "/"}
        elif action == "click":
            result = {"clicked": name, "route_before": before, **tail}
        elif action == "fill":
            result = {"filled": name, "chars": len(str(args.get("text") or "")), **tail}
        elif action == "press":
            result = {"pressed": args.get("key"), "on": name or "the page", "effect": "sent to the page", **tail}
        elif action == "highlight":
            result = {"highlighted": f"the {(el or {}).get('kind') or 'control'}" + (f' "{name}"' if name else "")}
        else:   # read
            result = {"ref": ref, "text": "\n".join((el or {}).get("under") or []) or (el or {}).get("line", ""),
                      "truncated": False}
        result.update((rule or {}).get("result") or {})
        return True, result, None, None, {"recorded": True}


def _clip(value: Any) -> Any:
    text = json.dumps(value, ensure_ascii=False, default=str)
    return value if len(text) <= LOG_VALUE_MAX else {"truncated": True, "chars": len(text), "head": text[:LOG_VALUE_MAX]}


def read_log(path: Path | str) -> list[dict]:
    """The rows of a recorded console's log, in order. A line that is not JSON is kept as a row that says so."""
    rows: list[dict] = []
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return rows
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            row = {"kind": "other", "note": "unreadable log line"}
        rows.append(row if isinstance(row, dict) else {"kind": "other", "note": "unreadable log line"})
    return rows


def main(argv: list[str] | None = None) -> int:
    import argparse
    import tempfile
    import time

    import yaml   # the eval set is YAML; only this entry point needs it

    ap = argparse.ArgumentParser(description="Play one console-assist eval case on loopback until Ctrl-C.")
    ap.add_argument("--case", required=True, help="a case id of evals/console-assist/cases.yml")
    ap.add_argument("--cases", type=Path, default=ROOT / "evals" / "console-assist" / "cases.yml")
    ap.add_argument("--log", type=Path, help="the JSONL log to write (default: a new temporary file)")
    a = ap.parse_args(argv)
    data = yaml.safe_load(a.cases.read_text(encoding="utf-8")) or {}
    case = next((c for c in data.get("cases") or [] if c.get("id") == a.case), None)
    if case is None:
        print(f"no case {a.case!r} in {a.cases}", file=sys.stderr)
        return 2
    log = a.log or Path(tempfile.mkdtemp(prefix="assist-eval-console-")) / "console.jsonl"
    with RecordedConsole(case["input"], log, defaults=data.get("page"), case_id=a.case,
                         shared_api=data.get("api")) as console:
        print(f"recorded console for {a.case}: {console.url}  (log: {log})", file=sys.stderr)
        if console.sid:
            print(f"page session: HARNESS_MCP_PAGE_SESSION={console.sid} HARNESS_MCP_SCOPES=page", file=sys.stderr)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            return 0


if __name__ == "__main__":
    sys.exit(main())
