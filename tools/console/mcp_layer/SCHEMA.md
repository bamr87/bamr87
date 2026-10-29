---
schema: "0.1"
coverage: listed
---

# SCHEMA — tools/console/mcp_layer

> The Harness Console's HTTP API as an MCP server for any AI agent — ../docs/mcp-layer.md.

## Structure

| entry | kind | purpose | rules |
|---|---|---|---|
| `__init__.py` | file | Package marker | required |
| `server.py` | file | The MCP server (`MCPServer`): read tools and resources, write tools only with `HARNESS_MCP_ALLOW_WRITES=1` (destructive, `confirm=true`), stdio and streamable HTTP with bearer auth and a loopback Host allowlist | required |
| `client.py` | file | Stdlib HTTP client for the console; reads `DASH_CONSOLE_TOKEN` from env or parses `.env`, never prints it | required |

## Placement

- A new read tool → a function in `server.py` over an existing console route, annotated read-only, with a test in `../test_mcp_layer.py` and a row in the docs catalog.
- A new write tool → only inside the `allow_writes` block, annotated destructive, refusing without `confirm=true`, calling a console route that keeps its own allowlist or confirm gate. Never a free-form command, merge, push or settings change.
