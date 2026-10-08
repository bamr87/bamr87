"""A stdlib client for the Harness Console's job API — how the TUI joins the same runtime.

The console process owns the operation allowlist and the job manager; the
browser page is one client of its API and the terminal dash is another. A job
started in either shows in both, and every gate (the allowlist, parameter
validation, confirm-before-GitHub-write) is enforced server-side — the TUI
cannot run anything the page could not.

DASH_CONSOLE_URL picks the endpoint:

  http://127.0.0.1:4001      default — a native `tools/dash console`
  unix:///path/console.sock  the socket the compose `console` service also
                             listens on; only containers that mount its volume
                             reach it (the `tui` service), so no hostname is
                             added to the console's DNS-rebinding allowlist
  (empty)                    no console: the TUI stays read-only

DASH_CONSOLE_TOKEN is sent as a bearer token when set, as the page does.
"""
from __future__ import annotations

import http.client
import json
import os
import re
import socket
from urllib.parse import urlencode, urlsplit

DEFAULT_URL = "http://127.0.0.1:4001"
JOB_ID = re.compile(r"^[0-9a-f]{12}$")  # core.Job ids: uuid4().hex[:12]


class ConsoleError(RuntimeError):
    pass


class _UnixConnection(http.client.HTTPConnection):
    def __init__(self, path: str, timeout: float):
        super().__init__("localhost", timeout=timeout)  # Host: localhost — loopback to the guard
        self._path = path

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self._path)


class ConsoleClient:
    def __init__(self, url: str | None = None, token: str | None = None, timeout: float = 5.0):
        self.url = DEFAULT_URL if url is None else url.strip()
        self.token = token if token is not None else (os.environ.get("DASH_CONSOLE_TOKEN") or "")
        self.timeout = timeout

    @classmethod
    def from_env(cls) -> "ConsoleClient":
        return cls(os.environ.get("DASH_CONSOLE_URL", DEFAULT_URL))

    @property
    def enabled(self) -> bool:
        return bool(self.url)

    def _connection(self) -> http.client.HTTPConnection:
        if self.url.startswith("unix://"):
            return _UnixConnection(self.url[len("unix://"):], self.timeout)
        parts = urlsplit(self.url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ConsoleError(f"DASH_CONSOLE_URL {self.url!r} is not http(s):// or unix://")
        cls = http.client.HTTPSConnection if parts.scheme == "https" else http.client.HTTPConnection
        return cls(parts.hostname, parts.port, timeout=self.timeout)

    def _call(self, method: str, path: str, body: dict | None = None):
        if not self.enabled:
            raise ConsoleError("no console configured (DASH_CONSOLE_URL is empty)")
        headers = {"Accept": "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        try:
            conn = self._connection()
            conn.request(method, path, body=data, headers=headers)
            resp = conn.getresponse()
            raw = resp.read()
            conn.close()
        except (OSError, http.client.HTTPException) as exc:
            raise ConsoleError(f"console unreachable at {self.url}: {exc}") from exc
        try:
            payload = json.loads(raw or b"null")
        except json.JSONDecodeError:
            payload = None
        if resp.status >= 400:
            detail = payload.get("detail") if isinstance(payload, dict) else None
            raise ConsoleError(detail or f"{resp.status} {resp.reason}")
        return payload

    def health(self) -> dict:
        return self._call("GET", "/api/health")

    def ops(self) -> list[dict]:
        return self._call("GET", "/api/ops")

    def jobs(self) -> list[dict]:
        return self._call("GET", "/api/jobs")

    def submit(self, op: str, params: dict | None = None, confirm: bool = False) -> dict:
        return self._call("POST", "/api/jobs", {"op": op, "params": params or {}, "confirm": confirm})

    @staticmethod
    def _job(job_id: str) -> str:
        # It lands in a URL path, and an MCP agent supplies it: only the
        # console's own id shape gets through.
        if not JOB_ID.match(str(job_id)):
            raise ConsoleError(f"not a console job id: {job_id!r}")
        return job_id

    def tail(self, job_id: str, offset: int = 0) -> dict:
        return self._call("GET", f"/api/jobs/{self._job(job_id)}?{urlencode({'offset': int(offset)})}")

    def cancel(self, job_id: str) -> dict:
        return self._call("POST", f"/api/jobs/{self._job(job_id)}/cancel")
