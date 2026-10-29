"""A tiny HTTP client for the Harness Console API (stdlib only).

The token comes from DASH_CONSOLE_TOKEN, else the DASH_CONSOLE_TOKEN line of the
repo's gitignored .env — parsed, never sourced, never logged or echoed.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def env_file() -> Path:
    """The .env to parse: HARNESS_MCP_DOTENV when set (a worktree pointing at the main checkout's), else <repo>/.env."""
    p = os.environ.get("HARNESS_MCP_DOTENV")
    return Path(p).expanduser() if p else ROOT / ".env"
DEFAULT_URL = "http://127.0.0.1:4001"


class ConsoleError(RuntimeError):
    """The console refused or could not be reached; the message never carries the token."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def dotenv_value(key: str, root: Path | None = None) -> str:
    env = (root / ".env") if root is not None else env_file()
    if not env.is_file():
        return ""
    for line in env.read_text(encoding="utf-8", errors="replace").splitlines():
        k, sep, value = line.strip().partition("=")
        if sep and k.strip() == key:
            return value.strip().strip("'\"")
    return ""


class Console:
    def __init__(self, url: str | None = None, token: str | None = None, timeout: float = 20.0):
        self.url = (url or os.environ.get("DASH_CONSOLE_URL") or DEFAULT_URL).rstrip("/")
        self._token = token if token is not None else (os.environ.get("DASH_CONSOLE_TOKEN") or dotenv_value("DASH_CONSOLE_TOKEN"))
        self.timeout = timeout
        # The console's DNS-rebinding allowlist is loopback names only; a client reaching it by service name
        # (the compose sidecar: http://console:4001) presents a loopback Host instead of widening that list.
        self.host_header = os.environ.get("DASH_CONSOLE_HOST_HEADER", "")

    def __repr__(self) -> str:  # never show the token
        return f"Console(url={self.url!r}, token={'set' if self._token else 'unset'})"

    def request(self, method: str, path: str, query: dict | None = None, body: dict | None = None):
        q = {k: v for k, v in (query or {}).items() if v is not None and v != ""}
        url = self.url + path + (("?" + urllib.parse.urlencode(q)) if q else "")
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Accept", "application/json")
        if self.host_header:
            req.add_header("Host", self.host_header)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        if self._token:
            req.add_header("Authorization", f"Bearer {self._token}")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:500]
            try:
                detail = json.loads(detail).get("detail", detail)
            except (ValueError, AttributeError):
                pass
            raise ConsoleError(f"console {method} {path} -> {e.code}: {detail}", e.code) from None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise ConsoleError(f"console unreachable at {self.url}: {getattr(e, 'reason', e)}") from None
        return json.loads(raw) if raw.strip() else {}

    def get(self, path: str, **query):
        return self.request("GET", path, query=query)

    def post(self, path: str, body: dict):
        return self.request("POST", path, body=body)
