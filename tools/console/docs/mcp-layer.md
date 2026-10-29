# Harness Console MCP layer

The Harness Console's HTTP API as a Model Context Protocol server, so Claude Code, Cursor, Grok Bots or any other MCP client can read the fleet's control plane — and, only when the operator turns it on, act on it. Feature HUB-031, PRD FR26 / NFR9.

It lives in `tools/console/mcp_layer/` (`server.py`, `client.py`), is built on the official MCP Python SDK (`mcp` v2, `MCPServer`), and is started by `tools/console/mcp.sh` or `tools/dash mcp`.

## How it fits

```
MCP client ──stdio──▶ mcp_layer.server ──HTTP + Bearer DASH_CONSOLE_TOKEN──▶ console :4001 (fleet-console-1)
remote agent ──streamable HTTP :4002/mcp + Bearer HARNESS_MCP_TOKEN──┘
```

The layer is a thin client of the console: every tool is one or two GET calls to existing `/api/*` routes, so the console's Host allowlist, token guard, operation allowlist and confirm-before-GitHub-write gate stay the only enforcement. It runs on the host next to the console rather than inside it: the console container is untouched, the layer can be restarted on its own, and stdio clients need a local process anyway.

It complements the older `fleet` server (`tools/fleetcore/mcp_server.py`, stdlib, stdio only), which reads the committed signals directly and works without a console. This one wraps the running console — live data, the lake, the code index, the deep dive, spend — and adds streamable HTTP for remote agents.

## Run it

```bash
tools/dash mcp                  # stdio (what an MCP host launches)
tools/dash mcp --http           # streamable HTTP on http://127.0.0.1:4002/mcp, bearer auth
tools/dash mcp --http --port 4010 --allow-host my-tunnel.example
tools/dash mcp --list-tools     # print the catalog (read / WRITE) and exit
```

`mcp.sh` creates `.venv-mcp` at the repo root (gitignored) on first run, installs `requirements-mcp.txt` at latest when it changes, unsets `PYTHONPATH` so the shell's site-packages cannot shadow the venv, and keeps stdout clean for the stdio channel.

| Variable | Default | Meaning |
| --- | --- | --- |
| `DASH_CONSOLE_URL` | `http://127.0.0.1:4001` | the console to wrap |
| `DASH_CONSOLE_TOKEN` | `.env` line | the console's bearer token; parsed from `.env`, never sourced or printed |
| `HARNESS_MCP_TOKEN` | `DASH_CONSOLE_TOKEN` | bearer token HTTP clients must send; `--http` refuses to start without one |
| `HARNESS_MCP_HOST` / `HARNESS_MCP_PORT` | `127.0.0.1` / `4002` | HTTP bind; a non-loopback host prints a warning |
| `HARNESS_MCP_ALLOW_WRITES` | off | `1` registers the write tools |
| `HARNESS_MCP_MAX_CHARS` | `60000` | larger results come back as `{truncated, total_chars, json_prefix}` |

HTTP security: bearer token compared in constant time on every request (401 otherwise), DNS-rebinding protection with a loopback Host/Origin allowlist (421 otherwise), loopback bind by default. Use a separate `HARNESS_MCP_TOKEN` for remote agents so the console token never leaves the machine.

## Client setup

Claude Code — the repo's `.mcp.json` already registers it as `harness-console`; or add it by hand:

```bash
claude mcp add harness-console -- /Users/bamr87/bamr87/tools/console/mcp.sh
# remote / HTTP:
claude mcp add --transport http harness-console http://127.0.0.1:4002/mcp --header "Authorization: Bearer $HARNESS_MCP_TOKEN"
```

Cursor — `.cursor/mcp.json` (project) or `~/.cursor/mcp.json` (global):

```json
{
  "mcpServers": {
    "harness-console": { "command": "/Users/bamr87/bamr87/tools/console/mcp.sh", "args": [] },
    "harness-console-http": {
      "url": "http://127.0.0.1:4002/mcp",
      "headers": { "Authorization": "Bearer ${env:HARNESS_MCP_TOKEN}" }
    }
  }
}
```

Generic HTTP clients (Grok Bots, other remote agents): MCP streamable HTTP at `POST /mcp` with `Authorization: Bearer <HARNESS_MCP_TOKEN>` and `Accept: application/json, text/event-stream`. A remote agent off this machine needs a tunnel (for example Tailscale or Cloudflare Tunnel) to `127.0.0.1:4002`; pass the tunnel's hostname with `--allow-host`.

```bash
curl -s -X POST http://127.0.0.1:4002/mcp \
  -H "Authorization: Bearer $HARNESS_MCP_TOKEN" -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"0"}}}'
```

```python
import httpx, anyio
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

async def main():
    http = httpx.AsyncClient(headers={"Authorization": "Bearer <HARNESS_MCP_TOKEN>"})
    async with Client(streamable_http_client("http://127.0.0.1:4002/mcp", http_client=http)) as c:
        print([t.name for t in (await c.list_tools()).tools])
        print(await c.call_tool("console_overview", {}))

anyio.run(main)
```

## Tool catalog

Read tools are annotated `readOnlyHint: true`. Lists come back as `{count, items}`.

| Tool | Console route | What it answers |
| --- | --- | --- |
| `console_overview` | `/api/health`, `/api/state` | Is the console up, git head, signal freshness, tripped wires, harness totals, whether writes are on |
| `fleet_status` | `/api/fleet` | Every registry project: health, triage, CI, docker (`q`, `sort`, `limit`) |
| `fleet_docker` | `/api/fleet/docker` | Containers on every Docker host |
| `project_detail` | `/api/project/{name}` | One project's drill-down |
| `harness_health` | `/api/state` `health` | Six-layer scorecard and trip wires, tripped first |
| `harness_scorecard` | `/api/state` `harnesses` | Per-repo AI harness inventory, trends, attention; `repo` for one entry |
| `live_snapshot` | `/api/live` | Sessions, Claude live usage, jobs, spend, health, deep dive (needs bamr87/bamr87#432) |
| `sessions` | `/api/live` `sessions` | Active and idle local agent sessions (needs #432) |
| `agent_activity` | `/api/lake/review` | Local sessions + CI agent runs, analysed (`days`, `repo`, `limit`) |
| `ops_list` | `/api/ops` | The allowlisted operations and their params |
| `jobs_list` | `/api/jobs` | Recent jobs (`status`, `limit`) |
| `job_log` | `/api/jobs/{id}` | A job's status and log tail (`offset`, `tail_chars`) |
| `spend_vs_budget` | `/api/state` `usage` + `contract` | Claude spend and Actions minutes vs the `_data/fleet.yml` budgets |
| `lake_status` | `/api/lake` | The data lake (traces plane) |
| `lake_runs` | `/api/lake/runs` | Recent runs / traces (`limit`) |
| `workflow_lines` | `/api/lake/lines` | Every workflow with provenance and kill switch (`filter`: all, failing, noswitch, ai) |
| `observability` | `/api/observability` | Log and metrics planes (Elasticsearch/Kibana, Prometheus/Grafana, Phoenix) |
| `code_search` | `/api/index/search`, `/api/index/harmonize` | Semantic search over the worktrees |
| `index_coverage` | `/api/index/coverage` | What the code index covers |
| `deep_dive` | `/api/data/deep_dive` | Deep-dive cycle progress and per-repo status |
| `work_board` | `/api/work` | The Work board lanes |
| `loops` | `/api/state` `loops` | The control-plane loops |

Write tools — registered only with `HARNESS_MCP_ALLOW_WRITES=1`, annotated `destructiveHint: true`, and each refuses unless called with `confirm=true` (the agent's host must ask the human first):

| Tool | Console route | Effect |
| --- | --- | --- |
| `run_op` | `POST /api/jobs` | Start an allowlisted operation (`op`, `params`) |
| `cancel_job` | `POST /api/jobs/{id}/cancel` | Cancel a running job |
| `workflow_kill_switch` | `POST /api/github/repos/{owner}/{repo}/actions` | `workflow.enable` / `workflow.disable` by `workflow_id` (needs the console's GitHub writes on) |

Resources: `harness://overview`, `harness://health`, `harness://ops`, `harness://deep-dive`, `harness://live`.

## Tests

```bash
tools/console/mcp.sh --list-tools >/dev/null   # bootstrap .venv-mcp once
.venv-mcp/bin/python tools/console/test_mcp_layer.py      # unit: mocked HTTP, the protocol, HTTP auth
.venv-mcp/bin/python tools/console/smoke_mcp_layer.py     # live: stdio against the running console
```

`test_mcp_layer.py` skips cleanly where `mcp` is not installed. The smoke test lists tools and resources and calls a few read tools, printing sizes and top-level keys only.

## Not yet

- No sidecar in `docker-compose.yml` and no `/mcp` route on the console: mounting it inside the console would mean restarting `fleet-console-1` and sharing its process; a compose service under an opt-in profile is the natural next step if remote agents need it always on.
- `live_snapshot` and `sessions` need `/api/live` from bamr87/bamr87#432; on a console without it they return a tool error naming the PR.
- No SSE streaming of `/api/live/stream` as MCP notifications yet.
