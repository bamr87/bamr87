#!/usr/bin/env python3
"""
Fixture tests for tui_bridge.py — the Terminal page's /api/tui WebSocket.

The bridge is security-relevant: HTTP middleware never sees a WebSocket
handshake and CORS does not apply to one, so it repeats the console's Host
guard and adds an Origin check and a first-frame token check of its own,
before a process exists. Guards that:

  * origin_allowed admits only the console's own origin (same host:port as the
    Host header) or an explicitly allowed one, and refuses a missing, "null",
    look-alike or unparsable Origin;
  * the public Pages origin is admitted only while DASH_CONSOLE_TOKEN is set;
  * token_ok compares in constant time and is open only when no token is set;
  * every rejection path closes with its own code and never starts a process:
    rebound Host (4403), foreign Origin (4403), no/late/garbled hello (4400),
    wrong token (4401), Textual missing (4501), session cap (4429);
  * an admitted session relays bytes both ways on a real pty, clamps and
    applies resizes, ignores garbage control frames, reports the exit code,
    and hangs up the whole process group when the page goes away.

The "TUI" is a tiny stand-in script, so this needs no Textual and no network:

    python3 tools/console/test_tui_bridge.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import textwrap
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import tui_bridge as tb  # noqa: E402

HOSTS = {"127.0.0.1", "localhost"}
SELF = "http://127.0.0.1:4001"


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
class Env:
    """Set/unset environment variables for one block, then restore them."""

    def __init__(self, **kw):
        self.kw, self.saved = kw, {}

    def __enter__(self):
        for k, v in self.kw.items():
            self.saved[k] = os.environ.get(k)
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def __exit__(self, *exc):
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class Patch:
    def __init__(self, obj, **attrs):
        self.obj, self.attrs, self.saved = obj, attrs, {}

    def __enter__(self):
        for k, v in self.attrs.items():
            self.saved[k] = getattr(self.obj, k)
            setattr(self.obj, k, v)

    def __exit__(self, *exc):
        for k, v in self.saved.items():
            setattr(self.obj, k, v)


class FakeWS:
    """The slice of starlette's WebSocket that TuiBridge.serve uses."""

    def __init__(self, host="127.0.0.1:4001", origin=SELF, frames=(), server=("127.0.0.1", 4001)):
        headers = []
        if host is not None:
            headers.append((b"host", host.encode()))
        if origin is not None:
            headers.append((b"origin", origin.encode()))
        self.scope = {"headers": headers, "server": server}
        self.inbox: asyncio.Queue = asyncio.Queue()
        for f in frames:
            self.inbox.put_nowait(f)
        self.accepted = False
        self.closed: tuple[int, str] | None = None
        self.texts: list[dict] = []
        self.binary = b""

    async def accept(self):
        self.accepted = True

    async def close(self, code=1000, reason=""):
        if self.closed is None:
            self.closed = (code, reason)

    async def send_text(self, text):
        self.texts.append(json.loads(text))

    async def send_bytes(self, data):
        self.binary += data

    async def receive(self):
        return await self.inbox.get()

    async def receive_text(self):
        from starlette.websockets import WebSocketDisconnect
        msg = await self.inbox.get()
        if msg.get("type") == "websocket.disconnect":
            raise WebSocketDisconnect(1000)
        return msg["text"]

    def push(self, **msg):
        self.inbox.put_nowait({"type": "websocket.receive", **msg})


def text(obj) -> dict:
    return {"type": "websocket.receive", "text": json.dumps(obj) if not isinstance(obj, str) else obj}


HELLO = text({"type": "hello", "token": "", "cols": 80, "rows": 24})


def run(coro, timeout=20):
    return asyncio.run(asyncio.wait_for(coro, timeout))


def fake_tui(body: str) -> Path:
    p = Path(tempfile.mkdtemp()) / "fake_tui.py"
    p.write_text(textwrap.dedent(body))
    return p


def serve(ws, bridge=None, **patches):
    bridge = bridge or tb.TuiBridge(HOSTS)
    with Patch(tb, **patches):
        run(bridge.serve(ws))
    return bridge


# --------------------------------------------------------------------------- #
# pure checks
# --------------------------------------------------------------------------- #
def test_origin_must_be_this_console_or_explicitly_allowed():
    ok = tb.origin_allowed
    assert ok(SELF, "127.0.0.1:4001", set())
    assert ok("HTTP://LOCALHOST:4001", "localhost:4001", set())  # case-insensitive
    assert not ok("http://127.0.0.1:5173", "127.0.0.1:4001", set())  # other port = other origin
    assert ok("http://127.0.0.1:5173/", "127.0.0.1:4001", {"http://127.0.0.1:5173"})  # named (Vite)
    assert not ok("http://evil.example", "127.0.0.1:4001", set())
    assert not ok("http://127.0.0.1:4001.evil.example", "127.0.0.1:4001", set())
    assert not ok(None, "127.0.0.1:4001", set()) and not ok("", "127.0.0.1:4001", set())
    assert not ok("null", "127.0.0.1:4001", {"null"})  # sandboxed/file pages
    assert not ok(SELF, "", set()) and not ok(SELF, None, set())
    assert not ok("http://[::1", "[::1]:4001", set())  # unparsable


def test_token_is_open_only_without_one_and_compared_exactly():
    with Env(DASH_CONSOLE_TOKEN=None):
        assert tb.token_ok(None) and tb.token_ok("anything")
    with Env(DASH_CONSOLE_TOKEN=" s3cret "):
        assert tb.token_ok("s3cret") and tb.token_ok(" s3cret\n")
        assert not tb.token_ok(None) and not tb.token_ok("") and not tb.token_ok("s3cre")
        assert not tb.token_ok("s3cret2")


def test_clamp_and_self_url():
    assert tb._clamp("999", 20, 500, 120) == 500 and tb._clamp(1, 20, 500, 120) == 20
    assert tb._clamp(None, 20, 500, 120) == 120 and tb._clamp("x", 5, 300, 36) == 36
    with Env(CONSOLE_SELF_URL=None, CONSOLE_PORT=None):
        assert tb.TuiBridge.self_url({"server": ("127.0.0.1", 4123)}) == "http://127.0.0.1:4123"
        assert tb.TuiBridge.self_url({}) == "http://127.0.0.1:4001"
        with Env(CONSOLE_PORT="4999"):
            assert tb.TuiBridge.self_url({"server": None}) == "http://127.0.0.1:4999"
    with Env(CONSOLE_SELF_URL="http://console:4001"):
        assert tb.TuiBridge.self_url({"server": ("x", 1)}) == "http://console:4001"


def test_refusal_checks_host_then_origin_and_gates_the_pages_origin_on_a_token():
    with Env(DASH_CONSOLE_ALLOWED_ORIGINS="http://127.0.0.1:5173/ , ", DASH_CONSOLE_TOKEN=None):
        b = tb.TuiBridge(HOSTS, {"https://bamr87.github.io/"})
        assert b.allowed_origins == {"http://127.0.0.1:5173"}
        assert b.refusal({"host": "127.0.0.1:4001", "origin": SELF}) is None
        assert b.refusal({"host": "rebound.example:4001", "origin": "http://rebound.example:4001"}) == (
            tb.CLOSE_FORBIDDEN, "host 'rebound.example' is not allowed")
        assert b.refusal({"host": "127.0.0.1:4001", "origin": "https://evil.example"})[0] == tb.CLOSE_FORBIDDEN
        assert b.refusal({"host": "127.0.0.1:4001"})[1] == "origin is not this console"
        assert b.refusal({"host": "127.0.0.1:4001", "origin": "http://127.0.0.1:5173"}) is None
        # the shared Pages origin: refused without a token…
        assert b.refusal({"host": "127.0.0.1:4001", "origin": "https://bamr87.github.io"}) is not None
        with Env(DASH_CONSOLE_TOKEN="t"):  # …admitted (then token-checked) with one
            assert b.refusal({"host": "127.0.0.1:4001", "origin": "https://bamr87.github.io"}) is None


def test_status_reports_availability_and_capacity():
    b = tb.TuiBridge(HOSTS)
    with Patch(tb, textual_available=lambda: False):
        s = b.status()
    assert s["available"] is False and s["active"] == 0 and s["max"] == tb.MAX_SESSIONS
    assert s["app"] == "tools/tui/app.py"
    assert isinstance(tb.textual_available(), bool)


# --------------------------------------------------------------------------- #
# rejection paths through serve()
# --------------------------------------------------------------------------- #
def _never_spawn(*a, **k):
    raise AssertionError("a process was started on a refused handshake")


def test_rebound_host_and_foreign_origin_are_closed_before_accept():
    for ws in (FakeWS(host="evil.example:4001", origin="http://evil.example:4001"),
               FakeWS(origin="https://evil.example"), FakeWS(origin=None)):
        serve(ws, TuiSession=_never_spawn)
        assert not ws.accepted and ws.closed[0] == tb.CLOSE_FORBIDDEN, ws.closed


def test_first_frame_must_be_a_hello():
    for frames in ([text("not json")], [text({"type": "resize", "cols": 1})], [text([1, 2])],
                   [{"type": "websocket.disconnect"}]):
        ws = FakeWS(frames=frames)
        serve(ws, TuiSession=_never_spawn)
        assert ws.accepted and ws.closed[0] == tb.CLOSE_PROTOCOL, (frames, ws.closed)
    ws = FakeWS()  # says nothing at all
    serve(ws, TuiSession=_never_spawn, HELLO_TIMEOUT=0.05)
    assert ws.closed[0] == tb.CLOSE_PROTOCOL and ws.texts[0]["type"] == "error"


def test_wrong_or_missing_token_is_refused():
    with Env(DASH_CONSOLE_TOKEN="right"):
        for tok in ("wrong", "", None):
            hello = {"type": "hello", "cols": 80, "rows": 24}
            if tok is not None:
                hello["token"] = tok
            ws = FakeWS(frames=[text(hello)])
            serve(ws, TuiSession=_never_spawn)
            assert ws.closed[0] == tb.CLOSE_UNAUTHORIZED, ws.closed
            assert ws.texts == [{"type": "error", "message": "console token required"}]


def test_missing_textual_and_the_session_cap_are_refused():
    ws = FakeWS(frames=[HELLO])
    with Env(DASH_CONSOLE_TOKEN=None):
        serve(ws, TuiSession=_never_spawn, textual_available=lambda: False)
    assert ws.closed[0] == tb.CLOSE_UNAVAILABLE
    b = tb.TuiBridge(HOSTS)
    b.active = tb.MAX_SESSIONS
    ws = FakeWS(frames=[HELLO])
    with Env(DASH_CONSOLE_TOKEN=None):
        serve(ws, b, TuiSession=_never_spawn, textual_available=lambda: True, TUI_APP=Path(__file__))
    assert ws.closed[0] == tb.CLOSE_BUSY and b.active == tb.MAX_SESSIONS


# --------------------------------------------------------------------------- #
# admitted sessions on a real pty
# --------------------------------------------------------------------------- #
ECHO_TUI = """
import os, shutil, sys
print("cols=%d" % shutil.get_terminal_size().columns, flush=True)
print("embedded=" + os.environ.get("DASH_TUI_EMBEDDED", ""), "url=" + os.environ.get("DASH_CONSOLE_URL", ""), flush=True)
line = sys.stdin.readline()
print("GOT:" + line.strip(), flush=True)
sys.exit(3)
"""


def test_admitted_session_relays_both_ways_and_reports_the_exit_code():
    app = fake_tui(ECHO_TUI)
    b = tb.TuiBridge(HOSTS)
    ws = FakeWS(frames=[text({"type": "hello", "token": "t", "cols": 9999, "rows": 1})])

    async def drive():
        task = asyncio.create_task(b.serve(ws))
        for _ in range(200):  # wait for the child's first lines
            if b"url=" in ws.binary:
                break
            await asyncio.sleep(0.02)
        assert b.active == 1
        ws.push(text=json.dumps({"type": "resize", "cols": 100, "rows": 30}))
        ws.push(text="{not json")
        ws.push(text=json.dumps(["ignored"]))
        ws.push(bytes=b"hello-bridge\n")
        await task

    with Env(DASH_CONSOLE_TOKEN="t", CONSOLE_SELF_URL=None, DASH_DOCKER_HOST=None):
        with Patch(tb, TUI_APP=app, textual_available=lambda: True):
            run(drive())
    out = ws.binary.decode(errors="replace")
    assert ws.accepted and ws.texts[0] == {"type": "ready"}, ws.texts
    assert "cols=500" in out, out  # hello cols clamped to 500
    assert "embedded=1" in out and "url=http://127.0.0.1:4001" in out, out
    assert "GOT:hello-bridge" in out, out
    assert ws.texts[-1] == {"type": "exit", "code": 3}, ws.texts
    assert b.active == 0


SLEEPY_TUI = """
import signal, sys, time
signal.signal(signal.SIGHUP, signal.SIG_IGN)   # make close() escalate past SIGHUP
print("up", flush=True)
time.sleep(60)
"""


def test_page_going_away_hangs_up_the_process_group():
    app = fake_tui(SLEEPY_TUI)
    b = tb.TuiBridge(HOSTS)
    ws = FakeWS(frames=[HELLO])
    pids = []
    real = tb.TuiSession

    class Spy(real):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            pids.append(self.proc.pid)

    async def drive():
        task = asyncio.create_task(b.serve(ws))
        for _ in range(200):
            if b"up" in ws.binary:
                break
            await asyncio.sleep(0.02)
        ws.inbox.put_nowait({"type": "websocket.disconnect"})
        await task

    with Env(DASH_CONSOLE_TOKEN=None):
        with Patch(tb, TUI_APP=app, textual_available=lambda: True, TuiSession=Spy):
            t0 = time.monotonic()
            run(drive())
    assert pids, "no session started"
    try:
        os.kill(pids[0], 0)
        alive = True
    except ProcessLookupError:
        alive = False
    assert not alive, "the TUI outlived its page"
    assert ws.texts[-1]["type"] == "exit" and ws.texts[-1]["code"] is not None
    assert time.monotonic() - t0 < 10 and b.active == 0


def test_session_write_resize_and_close_directly():
    app = fake_tui("""
        import sys
        data = sys.stdin.buffer.read(200000)
        print("n=%d" % len(data), flush=True)
    """)
    with Patch(tb, TUI_APP=app):
        s = tb.TuiSession(SELF, 80, 24)
    try:
        s.resize(120, 40)
        s.write(b"x" * 100)
        assert s.proc.poll() is None
    finally:
        code = s.close()
    assert code is not None
    s.resize(10, 10)  # on a closed fd: swallowed
    assert s.close() == code  # idempotent


def main() -> int:
    try:
        import starlette  # noqa: F401
    except ImportError:
        print("  (skipped: starlette not installed)")
        return 0
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ✓ {name}")
            except AssertionError as exc:
                failures += 1
                print(f"  ✗ {name}: {exc}")
    print(f"{'FAIL' if failures else 'OK'} — tui_bridge tests")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
