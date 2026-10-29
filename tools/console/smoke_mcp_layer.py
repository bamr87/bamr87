#!/usr/bin/env python3
"""Live smoke test: spawn the MCP server over stdio against the running console,
list its tools and call a few read tools. Prints sizes and keys, never payload secrets.

    python3 tools/console/smoke_mcp_layer.py [tool ...]     (needs a running console + token)
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import anyio
from mcp import Client, StdioServerParameters

HERE = Path(__file__).resolve().parent
DEFAULT = ["console_overview", "harness_health", "deep_dive", "jobs_list", "live_snapshot"]


async def main(names: list[str]) -> int:
    params = StdioServerParameters(command=sys.executable, args=["-m", "mcp_layer.server"], cwd=str(HERE),
                                  # stdio clients start servers with a minimal env; pass the console settings through
                                  env={k: v for k, v in os.environ.items()
                                       if k.startswith(("DASH_CONSOLE_", "HARNESS_MCP_")) or k in ("PATH", "HOME")})
    failures = 0
    async with Client(params) as cl:
        tools = (await cl.list_tools()).tools
        print(f"tools: {len(tools)} -> {', '.join(t.name for t in tools)}")
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
    sys.exit(anyio.run(main, sys.argv[1:] or DEFAULT))
