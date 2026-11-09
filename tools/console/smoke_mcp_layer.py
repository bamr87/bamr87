#!/usr/bin/env python3
"""Live smoke test: connect to the MCP server, list its tools and call a few read tools.
Prints sizes and keys, never payload secrets.

    python3 tools/console/smoke_mcp_layer.py [tool ...]                (stdio: spawns the server)
    python3 tools/console/smoke_mcp_layer.py --url URL [tool ...]      (streamable HTTP, e.g. the tunnel)

--url speaks to a running HTTP server — 127.0.0.1:4002/mcp or the tunnel's
https://<host>/mcp — with `Authorization: Bearer <HARNESS_MCP_TOKEN>`, the
token read from the environment or the repo's .env inside this process and
never printed. It is the handshake a remote client such as a Grok connector
must complete: initialize, notifications/initialized, tools/list, tools/call.
It exits non-zero when the server lists fewer than --min-tools tools (default
1), so "connected, but zero tools" fails here instead of looking healthy.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import anyio
from mcp import Client, StdioServerParameters

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
DEFAULT = ["console_overview", "harness_health", "deep_dive", "jobs_list", "live_snapshot"]


@asynccontextmanager
async def connect(url: str | None):
    if not url:
        params = StdioServerParameters(command=sys.executable, args=["-m", "mcp_layer.server"], cwd=str(HERE),
                                      # stdio clients start servers with a minimal env; pass the console settings through
                                      env={k: v for k, v in os.environ.items()
                                           if k.startswith(("DASH_CONSOLE_", "HARNESS_MCP_")) or k in ("PATH", "HOME")})
        async with Client(params) as cl:
            yield cl
        return
    import httpx2
    from mcp.client.streamable_http import streamable_http_client
    from mcp_layer.client import dotenv_value
    token = os.environ.get("HARNESS_MCP_TOKEN") or dotenv_value("HARNESS_MCP_TOKEN")
    if not token:
        raise SystemExit("smoke: --url needs HARNESS_MCP_TOKEN (environment or the repo's .env)")
    async with httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"}, timeout=60) as http:
        async with Client(streamable_http_client(url, http_client=http)) as cl:
            yield cl


async def main(url: str | None, names: list[str], min_tools: int) -> int:
    failures = 0
    async with connect(url) as cl:
        tools = (await cl.list_tools()).tools
        print(f"tools: {len(tools)} -> {', '.join(t.name for t in tools)}")
        if len(tools) < min_tools:
            print(f"FAIL: {len(tools)} tool(s) listed, expected at least {min_tools}")
            return 2
        res = (await cl.list_resources()).resources
        print(f"resources: {', '.join(str(r.uri) for r in res)}")
        for n in names:
            r = await cl.call_tool(n, {})
            text = "".join(getattr(b, "text", "") for b in r.content)
            err = getattr(r, "is_error", False)
            try:
                d = json.loads(text)
                shape = list(d)[:8] if isinstance(d, dict) else f"list[{len(d)}]"
            except ValueError:
                shape = text[:160]
            print(f"{'ERR ' if err else 'ok  '} {n}: {len(text)} chars, {shape}")
            failures += bool(err) and n != "live_snapshot"  # live needs #432
    return 1 if failures else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--url", help="streamable HTTP endpoint (…/mcp); default: spawn the server over stdio")
    ap.add_argument("--min-tools", type=int, default=1, help="fail when fewer tools are listed (default 1)")
    ap.add_argument("tools", nargs="*", help=f"read tools to call (default: {' '.join(DEFAULT)})")
    a = ap.parse_args()
    try:
        sys.exit(anyio.run(main, a.url, a.tools or DEFAULT, a.min_tools))
    except Exception as e:  # noqa: BLE001 — one line on what failed, never a token
        while isinstance(e, BaseExceptionGroup) and e.exceptions:
            e = e.exceptions[0]
        print(f"FAIL: the MCP handshake did not complete: {type(e).__name__}: {str(e)[:200]}")
        sys.exit(3)
