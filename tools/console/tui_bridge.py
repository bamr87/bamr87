#!/usr/bin/env python3
"""tui_bridge — the terminal dash (tools/tui) inside the console page.

The browser's Terminal page opens a WebSocket to /api/tui; this module runs the
REAL Textual app (`tools/tui/app.py`) on a pseudo-terminal and relays bytes
both ways, and the page draws them with xterm.js. Nothing is re-implemented:
it is the same process `tools/dash tui` starts, joined to the same console
runtime (DASH_CONSOLE_URL points back at this process), so its Jobs tab and
`:` palette submit through the same allowlist and confirm gate as the page.

Wire protocol (one socket per session):

  client → server   text   {"type":"hello","token":"…","cols":N,"rows":N}   first frame, always
                    text   {"type":"resize","cols":N,"rows":N}
                    binary keystrokes (UTF-8 bytes, exactly what xterm.js emits)
  server → client   binary terminal output
                    text   {"type":"ready"} · {"type":"exit","code":N} · {"type":"error","message":"…"}

Why the checks below exist. FastAPI's HTTP middleware never sees a WebSocket
handshake, so the console's Host guard does not apply here and is repeated.
And a WebSocket is not subject to CORS: any page in the operator's browser can
open ws://127.0.0.1:4001/api/tui, and its Host header would be the loopback
one. Only the Origin header tells that page apart from the console's own, so a
handshake whose Origin is not this console is refused before a process exists
(cross-site WebSocket hijacking). A browser cannot put a bearer token on a
WebSocket, so when DASH_CONSOLE_TOKEN is set the first frame must carry it.
"""
from __future__ import annotations

import asyncio
import fcntl
import json
import os
import secrets as _secrets
import select
import signal
import struct
import subprocess
import sys
import termios
from pathlib import Path
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parents[2]
TUI_APP = REPO_ROOT / "tools" / "tui" / "app.py"
MAX_SESSIONS = int(os.environ.get("CONSOLE_TUI_MAX") or 4)
HELLO_TIMEOUT = 10.0
READ_CHUNK = 65536

# Close codes (4000–4999 are the application's own).
CLOSE_FORBIDDEN = 4403
CLOSE_UNAUTHORIZED = 4401
CLOSE_BUSY = 4429
CLOSE_UNAVAILABLE = 4501
CLOSE_PROTOCOL = 4400

# The child acquires the pty as its CONTROLLING terminal, then becomes the TUI.
# Popen's start_new_session gives it a fresh session; TIOCSCTTY on stdin is
# what makes the kernel deliver SIGWINCH on resize (Textual relayouts on it).
# Done in the child's own interpreter rather than in a preexec_fn, which is
# unsafe in a process with threads (the job manager's).
_EXEC_SHIM = ("import fcntl, os, sys, termios; "
              "fcntl.ioctl(0, termios.TIOCSCTTY, 0); "
              "os.execv(sys.argv[1], sys.argv[1:])")


def textual_available() -> bool:
    import importlib.util
    try:
        return importlib.util.find_spec("textual") is not None
    except (ImportError, ValueError):
        return False


def origin_allowed(origin: str | None, host: str | None, extra: set[str]) -> bool:
    """True when the handshake comes from this console's own page.

    The Origin's host:port must equal the Host the request was sent to — the
    page and the socket are the same origin — or be named explicitly in
    DASH_CONSOLE_ALLOWED_ORIGINS (the Vite dev server, a proxy). A missing
    Origin is refused: every browser sends one on a WebSocket, so only a
    non-browser client omits it, and that client can reach the API anyway.
    """
    if not origin or origin == "null":
        return False
    if origin.rstrip("/").lower() in extra:
        return True
    try:
        netloc = urlsplit(origin).netloc.lower()
    except ValueError:
        return False
    return bool(host) and netloc == host.strip().lower()


def token_ok(sent: str | None) -> bool:
    expected = os.environ.get("DASH_CONSOLE_TOKEN")
    if not expected:
        return True
    return _secrets.compare_digest((sent or "").strip().encode(), expected.strip().encode())


def _clamp(value, lo: int, hi: int, default: int) -> int:
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return default


def set_winsize(fd: int, cols: int, rows: int) -> None:
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


class TuiSession:
    """One Textual process on one pseudo-terminal."""

    def __init__(self, self_url: str, cols: int, rows: int):
        master, slave = os.openpty()
        set_winsize(master, cols, rows)
        env = dict(os.environ)
        env.update({
            "TERM": "xterm-256color",
            "COLORTERM": "truecolor",
            # The TUI joins THIS runtime: a job it submits shows in the page.
            "DASH_CONSOLE_URL": self_url,
            "DASH_TUI_EMBEDDED": "1",
        })
        # The same default run.sh exports; an explicit setting (even empty) wins.
        env.setdefault("DASH_DOCKER_HOST", "local,ssh://forge")
        env.pop("CONSOLE_UDS", None)
        argv = [sys.executable, "-c", _EXEC_SHIM, sys.executable, str(TUI_APP)]
        try:
            self.proc = subprocess.Popen(argv, stdin=slave, stdout=slave, stderr=slave,
                                         cwd=str(REPO_ROOT), env=env, start_new_session=True,
                                         close_fds=True)
        finally:
            os.close(slave)
        self.fd = master
        os.set_blocking(master, False)

    def write(self, data: bytes) -> None:
        view = memoryview(data)
        while view:
            try:
                n = os.write(self.fd, view)
            except BlockingIOError:
                select.select([], [self.fd], [], 1.0)  # a large paste filled the pty buffer
                continue
            view = view[n:]

    def resize(self, cols: int, rows: int) -> None:
        try:
            set_winsize(self.fd, cols, rows)
        except OSError:
            pass

    def close(self) -> int | None:
        """Hang up the whole process group, then make sure it is gone."""
        if self.proc.poll() is None:
            for sig, wait in ((signal.SIGHUP, 1.5), (signal.SIGTERM, 1.5), (signal.SIGKILL, 2.0)):
                try:
                    os.killpg(self.proc.pid, sig)
                except (ProcessLookupError, PermissionError):
                    break
                try:
                    self.proc.wait(timeout=wait)
                    break
                except subprocess.TimeoutExpired:
                    continue
        try:
            os.close(self.fd)
        except OSError:
            pass
        return self.proc.poll()


class TuiBridge:
    """Admission control + the relay loop. One instance per console process."""

    def __init__(self, allowed_hosts: set[str]):
        self.allowed_hosts = allowed_hosts
        self.allowed_origins = {o.strip().rstrip("/").lower() for o in
                                (os.environ.get("DASH_CONSOLE_ALLOWED_ORIGINS") or "").split(",")
                                if o.strip()}
        self.active = 0

    def status(self) -> dict:
        return {"available": textual_available() and TUI_APP.exists(), "active": self.active,
                "max": MAX_SESSIONS, "app": str(TUI_APP.relative_to(REPO_ROOT))}

    @staticmethod
    def self_url(scope: dict) -> str:
        override = os.environ.get("CONSOLE_SELF_URL")
        if override:
            return override
        server = scope.get("server") or (None, None)
        port = server[1] if isinstance(server, (tuple, list)) and len(server) > 1 else None
        port = port or os.environ.get("CONSOLE_PORT") or 4001
        return f"http://127.0.0.1:{port}"

    def refusal(self, headers: dict) -> tuple[int, str] | None:
        """The handshake checks, before the socket is accepted."""
        host_header = headers.get("host") or ""
        host = host_header.rsplit(":", 1)[0].strip().lower()
        if host and host not in self.allowed_hosts:
            return CLOSE_FORBIDDEN, f"host '{host}' is not allowed"
        if not origin_allowed(headers.get("origin"), host_header, self.allowed_origins):
            return CLOSE_FORBIDDEN, "origin is not this console"
        return None

    async def serve(self, websocket) -> None:
        from starlette.websockets import WebSocketDisconnect

        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in websocket.scope.get("headers", [])}
        refused = self.refusal(headers)
        if refused:
            await websocket.close(code=refused[0], reason=refused[1])
            return
        await websocket.accept()

        async def fail(code: int, message: str) -> None:
            await websocket.send_text(json.dumps({"type": "error", "message": message}))
            await websocket.close(code=code, reason=message[:120])

        try:
            first = await asyncio.wait_for(websocket.receive_text(), timeout=HELLO_TIMEOUT)
            hello = json.loads(first)
            if not isinstance(hello, dict) or hello.get("type") != "hello":
                raise ValueError("expected a hello frame")
        except (asyncio.TimeoutError, ValueError, KeyError, WebSocketDisconnect):
            try:
                await fail(CLOSE_PROTOCOL, "the first frame must be {\"type\":\"hello\"}")
            except Exception:
                pass
            return
        if not token_ok(hello.get("token")):
            await fail(CLOSE_UNAUTHORIZED, "console token required")
            return
        if not (textual_available() and TUI_APP.exists()):
            await fail(CLOSE_UNAVAILABLE, "Textual is not installed in the console's environment — "
                                          "re-run tools/dash console (it installs requirements.txt)")
            return
        if self.active >= MAX_SESSIONS:
            await fail(CLOSE_BUSY, f"{MAX_SESSIONS} terminal sessions are already open — close one first")
            return

        cols = _clamp(hello.get("cols"), 20, 500, 120)
        rows = _clamp(hello.get("rows"), 5, 300, 36)
        self.active += 1
        loop = asyncio.get_running_loop()
        session = None
        out: asyncio.Queue[bytes | None] = asyncio.Queue()
        try:
            session = TuiSession(self.self_url(websocket.scope), cols, rows)

            def readable() -> None:
                try:
                    data = os.read(session.fd, READ_CHUNK)
                except BlockingIOError:
                    return
                except OSError:
                    data = b""
                if not data:
                    loop.remove_reader(session.fd)
                    out.put_nowait(None)
                else:
                    out.put_nowait(data)

            loop.add_reader(session.fd, readable)
            await websocket.send_text(json.dumps({"type": "ready"}))

            async def pump_out() -> None:
                while (chunk := await out.get()) is not None:
                    await websocket.send_bytes(chunk)

            async def pump_in() -> None:
                while True:
                    msg = await websocket.receive()
                    if msg.get("type") == "websocket.disconnect":
                        return
                    if msg.get("bytes") is not None:
                        session.write(msg["bytes"])
                    elif msg.get("text") is not None:
                        try:
                            ctl = json.loads(msg["text"])
                        except ValueError:
                            continue
                        if isinstance(ctl, dict) and ctl.get("type") == "resize":
                            session.resize(_clamp(ctl.get("cols"), 20, 500, cols),
                                           _clamp(ctl.get("rows"), 5, 300, rows))

            tasks = [asyncio.create_task(pump_out()), asyncio.create_task(pump_in())]
            _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for t in pending:
                t.cancel()
        except WebSocketDisconnect:
            pass
        finally:
            code = None
            if session is not None:
                try:
                    loop.remove_reader(session.fd)
                except (ValueError, OSError):
                    pass
                code = await asyncio.to_thread(session.close)
            self.active -= 1
            try:
                await websocket.send_text(json.dumps({"type": "exit", "code": code}))
                await websocket.close()
            except Exception:
                pass
