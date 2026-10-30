# Harness Console MCP layer

The Harness Console's HTTP API as a Model Context Protocol server, so Claude Code, Cursor, Grok Bots or any other MCP client can read the fleet's control plane — and, only when the operator turns it on, act on it. Feature HUB-031, PRD FR26 / NFR9.

It lives in `tools/console/mcp_layer/` (`server.py`, `client.py`), is built on the official MCP Python SDK (`mcp` v2, `MCPServer`), and is started by `tools/console/mcp.sh` or `tools/dash mcp`.

## How it fits

```
MCP client ──stdio──▶ mcp_layer.server ──HTTP + Bearer DASH_CONSOLE_TOKEN──▶ console :4001 (fleet-console-1)
remote agent ──streamable HTTP :4002/mcp + Bearer HARNESS_MCP_TOKEN──┘
```

The layer is a thin client of the console: every tool is one or two GET calls to existing `/api/*` routes, so the console's Host allowlist, token guard, operation allowlist and confirm-before-GitHub-write gate stay the only enforcement. It runs on the host next to the console rather than inside it: the console container is untouched, the layer can be restarted on its own, and stdio clients need a local process anyway.

It absorbed the older `fleet` server (`tools/fleetcore/mcp_server.py`, stdlib, stdio only). Its read tools (`fleet_overview`, `fleet_apps`, `fleet_inbox`, `fleet_work`) are now tools of this layer and still read the committed signals directly, so they work without a console. Its action tools survive as aliases (`console_ops`, `console_jobs`, `console_job_log`, and `console_run` / `console_cancel` with `--fleet-compat` or writes on). `.mcp.json` keeps the server name `fleet`, now launching `tools/console/mcp.sh --fleet-compat`, so existing `mcp__fleet__*` permissions keep working. `python3 tools/fleetcore/mcp_server.py` delegates to this layer; `FLEET_MCP_STDLIB=1` runs the old stdlib loop.

## Run it

```bash
tools/dash mcp                  # stdio (what an MCP host launches)
tools/dash mcp --http           # streamable HTTP on http://127.0.0.1:4002/mcp, bearer auth
tools/dash mcp --http --port 4010 --allow-host my-tunnel.example
tools/dash mcp --tunnel-url     # current URL of the persistent compose mcp-tunnel service
tools/dash mcp --tunnel         # TEMPORARY public URL via a cloudflared quick tunnel (Ctrl-C stops it)
tools/dash mcp --fleet-compat   # also register the legacy fleet action tools (what .mcp.json uses)
tools/dash mcp --list-tools     # print the catalog (read / WRITE) and exit
```

`mcp.sh` creates `.venv-mcp` at the repo root (gitignored) on first run, installs `requirements-mcp.txt` at latest when it changes, unsets `PYTHONPATH` so the shell's site-packages cannot shadow the venv, and keeps stdout clean for the stdio channel.

| Variable | Default | Meaning |
| --- | --- | --- |
| `DASH_CONSOLE_URL` | `http://127.0.0.1:4001` | the console to wrap |
| `DASH_CONSOLE_TOKEN` | `.env` line | the console's bearer token; parsed from `.env`, never sourced or printed |
| `HARNESS_MCP_TOKEN` | `.env` line | bearer token HTTP clients must send; `--http` refuses to start without one and never falls back to `DASH_CONSOLE_TOKEN` |
| `HARNESS_MCP_DOTENV` | `<repo>/.env` | which `.env` to parse for the tokens |
| `DASH_CONSOLE_HOST_HEADER` | unset | Host header sent to the console (the sidecar uses `127.0.0.1:4001` to pass its loopback allowlist) |
| `HARNESS_MCP_FLEET_COMPAT` | off | `1` = `--fleet-compat` |
| `HARNESS_MCP_HOST` / `HARNESS_MCP_PORT` | `127.0.0.1` / `4002` | HTTP bind; a non-loopback host prints a warning |
| `HARNESS_MCP_ALLOW_WRITES` | off | `1` registers the write tools |
| `HARNESS_MCP_MAX_CHARS` | `60000` | larger results come back as `{truncated, total_chars, json_prefix}` |

HTTP security: bearer token compared in constant time on every request (401 otherwise), DNS-rebinding protection with a loopback Host/Origin allowlist (421 otherwise), loopback bind by default. `HARNESS_MCP_TOKEN` is separate from the console token, so the console token never leaves the machine; the console token is rejected by the MCP endpoint.

## Client setup

Claude Code — the repo's `.mcp.json` already registers it as `fleet`; or add it by hand:

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

Generic HTTP clients (Grok Bots, other remote agents): MCP streamable HTTP at `POST /mcp` with `Authorization: Bearer <HARNESS_MCP_TOKEN>` and `Accept: application/json, text/event-stream`. A remote agent off this machine needs a tunnel to the HTTP server; pass the tunnel's hostname with `--allow-host`.

## Always-on sidecar (compose profile `mcp`)

```bash
docker compose --profile mcp up -d mcp     # 127.0.0.1:4002/mcp, healthy when /mcp answers 401
docker compose --profile mcp stop mcp
```

Opt-in, never started by a plain `docker compose up`. `python:3.13-slim`, repo mounted read-only, venv in the `venv-mcp` volume, token read from the mounted `.env`, talks to `http://console:4001` with `Host: 127.0.0.1:4001`. It does not restart or depend on `console`. Writes stay off unless `HARNESS_MCP_ALLOW_WRITES=1`.

## Remote access (persistent quick tunnel — compose `mcp-tunnel`)

```bash
docker compose --profile mcp --profile mcp-tunnel up -d mcp mcp-tunnel
tools/dash mcp --tunnel-url     # prints https://<random>.trycloudflare.com/mcp, writes .dash-live/mcp-tunnel-url
```

An opt-in cloudflared quick tunnel to the `mcp` service, `restart: unless-stopped`. It rewrites Host to `127.0.0.1:4002` so the server's loopback Host check passes; the bearer `HARNESS_MCP_TOKEN` is the gate and writes stay off. Its metrics port (`127.0.0.1:${HARNESS_MCP_TUNNEL_METRICS_PORT:-4003}`) serves `/quicktunnel`, which `--tunnel-url` reads. **The hostname is not stable**: it changes whenever the container restarts, so a connector pointing at it must be updated.

### Stable hostname (needs a one-time interactive sign-in)

Named Cloudflare Tunnel (requires a domain on Cloudflare):

```bash
docker run -it --rm -v ~/.cloudflared:/home/nonroot/.cloudflared cloudflare/cloudflared:latest tunnel login
docker run --rm -v ~/.cloudflared:/home/nonroot/.cloudflared cloudflare/cloudflared:latest tunnel create harness-mcp
docker run --rm -v ~/.cloudflared:/home/nonroot/.cloudflared cloudflare/cloudflared:latest tunnel route dns harness-mcp mcp.<your-domain>
```

Then run `tunnel run harness-mcp` with an ingress to `http://mcp:4002` and set `HARNESS_MCP_ALLOW_HOSTS=mcp.<your-domain>` on the `mcp` service (comma-separated; added to `--allow-host`). Alternatives: Tailscale Funnel or an ngrok static domain.

## Remote access (temporary tunnel)

```bash
tools/dash mcp --tunnel [--port 4012]
```

Starts a cloudflared quick tunnel (native `cloudflared`, else the `cloudflare/cloudflared` image via `host.docker.internal`), waits for its `*.trycloudflare.com` hostname, prints the TEMPORARY public endpoint, and runs the HTTP server in the foreground with `--allow-host <that host>`. Ctrl-C (or any exit) stops the tunnel container. The URL changes every run and is public, so the bearer token is the only gate: use it for a session, not as a standing service. For a permanent endpoint use a named Cloudflare Tunnel or Tailscale to `127.0.0.1:4002` and `--allow-host <hostname>`.

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
| `fleet_overview` / `fleet_apps` / `fleet_inbox` / `fleet_work` | committed signals (`tools/fleetcore`) | The merged `fleet` server's views; no console needed |
| `console_ops` / `console_jobs` / `console_job_log` | as `ops_list` / `jobs_list` / `job_log` | Legacy `fleet` names |

Write tools — registered only with `HARNESS_MCP_ALLOW_WRITES=1`, annotated `destructiveHint: true`, and each refuses unless called with `confirm=true` (the agent's host must ask the human first):

| Tool | Console route | Effect |
| --- | --- | --- |
| `run_op` | `POST /api/jobs` | Start an allowlisted operation (`op`, `params`) |
| `cancel_job` | `POST /api/jobs/{id}/cancel` | Cancel a running job |
| `console_run` / `console_cancel` | as `run_op` / `cancel_job` | Legacy `fleet` names (also with `--fleet-compat`; the console's confirm gate still applies) |
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

- No `/mcp` route on the console itself (the sidecar covers always-on).
- `live_snapshot` and `sessions` need `/api/live` from bamr87/bamr87#432; on a console without it they return a tool error naming the PR.
- No SSE streaming of `/api/live/stream` as MCP notifications yet.
