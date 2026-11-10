# Harness Console MCP layer

The Harness Console's HTTP API as a Model Context Protocol server, so Claude Code, Cursor, Grok Bots or any other MCP client can read the fleet's control plane — and, only when the operator turns it on, act on it. Feature HUB-031, PRD FR26 / NFR9.

It lives in `tools/console/mcp_layer/` (`server.py`, `client.py`), is built on the official MCP Python SDK (`mcp` v2, `MCPServer`), and is started by `tools/console/mcp.sh` or `tools/dash mcp`.

## How it fits

```
MCP client ──stdio──▶ mcp_layer.server ──HTTP + Bearer DASH_CONSOLE_TOKEN──▶ console :4001 (fleet-console-1)
remote agent ──streamable HTTP :4002/mcp + Bearer HARNESS_MCP_TOKEN──┘
```

The layer is a thin client of the console: every tool is one or two GET calls to existing `/api/*` routes, so the console's Host allowlist, token guard, operation allowlist and confirm-before-GitHub-write gate stay the only enforcement. It runs on the host next to the console rather than inside it: the console container is untouched, the layer can be restarted on its own, and stdio clients need a local process anyway.

It absorbed the older `fleet` server (`tools/fleetcore/mcp_server.py`, stdlib, stdio only). Its read tools (`fleet_overview`, `fleet_apps`, `fleet_inbox`, `fleet_work`, `fleet_workflows`, `workflow_lint`) are now tools of this layer and still read the committed signals and the checkout directly, so they work without a console. The old server's `TOOLS` table is the list: `test_mcp_layer.py` fails when a tool in it is not served here (the workflow atlas's two were missing from the merge until 2026-11-10). Its action tools survive as aliases (`console_ops`, `console_jobs`, `console_job_log`, and `console_run` / `console_cancel` with `--fleet-compat` or writes on). `.mcp.json` keeps the server name `fleet`, now launching `tools/console/mcp.sh --fleet-compat`, so existing `mcp__fleet__*` permissions keep working. `python3 tools/fleetcore/mcp_server.py` delegates to this layer; `FLEET_MCP_STDLIB=1` runs the old stdlib loop.

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
| `HARNESS_MCP_ALLOW_WRITES` | off | `1` registers the broad write tools (and every scope) |
| `HARNESS_MCP_SCOPES` | empty | comma list of narrow write scopes: `jobs` (`job_dispatch`, `job_cancel`), `work` (`work_apply`); unknown names grant nothing ([Scoped write access](#scoped-write-access-harness_mcp_scopes)) |
| `HARNESS_MCP_AUDIT` | `<repo>/.fleet/mcp/audit.jsonl` | the scoped-write audit file (gitignored); the sidecar writes `/audit/audit.jsonl`, which is `.fleet/mcp/` on the host |
| `HARNESS_MCP_MAX_CHARS` | `60000` | larger results come back as `{truncated, total_chars, json_prefix}` |
| `QDRANT_URL` / `OLLAMA_URL` | the `_data/fleet.yml` URLs | where the code index is reached from THIS process (the contract's are the browser's) |
| `QDRANT_COLLECTION` | the fullest `ws-` collection | the code index's collection name, when the store's listing should not decide |

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

### A remote client that says "connected" but lists zero tools

A remote agent such as Grok Bot runs off this machine, so it cannot launch `mcp.sh` over stdio here. Its supported connector is **streamable HTTP**: the tunnel's `https://<host>/mcp` URL (from `tools/dash mcp --tunnel-url`) with the header `Authorization: Bearer <HARNESS_MCP_TOKEN>`. A connector registered as **stdio** that runs a helper script to forward to the tunnel is not this interface, and it fails in a way that looks healthy: the client sees the helper process start and reports "connected", while the helper's own requests never get a tool list through. The server answers each of a bridge's usual mistakes with an error the helper may swallow:

| What the helper does | What the server answers |
| --- | --- |
| no or wrong bearer token | `401 unauthorized` (never logged by the server) |
| `Accept: application/json` only | `406 Not Acceptable` — it must also accept `text/event-stream` |
| `tools/list` without the `Mcp-Session-Id` header from `initialize` | `400 Bad Request: Missing session ID` |
| an old session after 30 idle minutes | `404` — the client must send `initialize` again |
| the legacy HTTP+SSE transport (`GET /sse`) | `404` — only streamable HTTP is served |
| a tunnel hostname from before the tunnel restarted | Cloudflare `530`, or no answer |

Check the server side with the handshake a connector must complete. It reads the token in-process, prints tool names only, and exits non-zero on zero tools:

```bash
.venv-mcp/bin/python tools/console/smoke_mcp_layer.py --url "$(tools/dash mcp --tunnel-url)" console_overview
```

If that lists the tools and the remote client still shows none, the fault is in the client's connector configuration: replace the stdio helper with a streamable-HTTP connector to the current URL and header, then reconnect it. A successful `console_overview` call made by the remote client itself is the proof; an HTTP 200 on `initialize`, or a tool list fetched from this Mac, is not. Each successful `initialize` logs `Created new transport with session ID` in `docker logs fleet-mcp-1`, so a connector that never logs one never reached the server with a valid token.

## Always-on sidecar (compose profile `mcp`)

```bash
docker compose --profile mcp up -d mcp     # 127.0.0.1:4002/mcp, healthy when /mcp answers 401
docker compose --profile mcp stop mcp
```

Opt-in, never started by a plain `docker compose up`. `python:3.14-slim`, repo mounted read-only, venv in the `venv-mcp` volume, token read from the mounted `.env`, talks to `http://console:4001` with `Host: 127.0.0.1:4001`. It does not restart or depend on `console`. Writes stay off unless `HARNESS_MCP_ALLOW_WRITES=1`; `HARNESS_MCP_SCOPES=jobs,work` in the environment or `.env` grants only the scoped tools. Its one writable mount is `.fleet/mcp/` → `/audit`, where the scoped-write audit lands. It runs the main checkout's code, so a change to `mcp_layer/` reaches it only after the checkout has it and the sidecar is recreated (`docker compose --profile mcp up -d --no-deps mcp`); that does not restart the tunnel, so the tunnel's URL stays the same.

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
import httpx2, anyio   # mcp v2's HTTP client package
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

async def main():
    http = httpx2.AsyncClient(headers={"Authorization": "Bearer <HARNESS_MCP_TOKEN>"})
    async with Client(streamable_http_client("http://127.0.0.1:4002/mcp", http_client=http)) as c:
        print([t.name for t in (await c.list_tools()).tools])
        print(await c.call_tool("console_overview", {}))

anyio.run(main)
```

## Tool catalog

Read tools are annotated `readOnlyHint: true`. Lists come back as `{count, items}`.

| Tool | Console route | What it answers |
| --- | --- | --- |
| `console_overview` | `/api/health`, `/api/state` | Is the console up, git head, signal freshness, tripped wires, harness totals, whether writes are on (`mcp_writes_enabled`) and which scopes are granted (`mcp_scopes`) |
| `fleet_status` | `/api/fleet` | Every registry project: health, triage, CI, docker (`q`, `sort`, `limit`) |
| `fleet_docker` | `/api/fleet/docker` | Containers on every Docker host, with a reason per unreachable host; errors when none answers (the console's container holds no Docker socket by design) |
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
| `code_search` | `/api/index/search`, `/api/index/harmonize` | Semantic search over the worktrees (`mode`: search, harmonize) |
| `index_coverage` | `/api/index/coverage` | What the code index covers, which collection it read and where it asked |
| `deep_dive` | `/api/data/deep_dive` | Deep-dive cycle progress and per-repo status |
| `work_board` | `/api/work` | One page of the Work board (`lane`, `repo`, `kind`, `stage`, `priority`, `q`, `limit`, `offset`, `summary`) |
| `work_item` | `/api/work/item` | One item's drill-down: its board row and source record (`key`) |
| `work_preview` | `/api/work`, `POST /api/work/preview` | What a prioritising plan would change — writes nothing: the console's change lines, each item before → after, the files an apply would edit, `undo_plan` and the `plan_id` that `work_apply` needs |
| `loops` | `/api/state` `loops` | The control-plane loops |
| `refine_status` | `/api/refine` | Harness refinement (docs/HARNESS-REFINEMENT.md): the hub's surface check, the fleet sweep's totals, one Propose–Probe–Compose plan per agent step with its ceiling, the library's count, the evidence trees and the review queue; `section` returns one key in full (surface, fleet_surface, plans, library, evidence, reviews, config) |
| `refine_library` | `/api/refine` `library` | The experience library's lessons (cue, lesson, evidence, confidence, verdicts), newest first (`loop`, `domain`, `limit`) — data to re-verify, never a rule |
| `refine_reviews` | `/api/refine` `reviews` | Every local loop-run attempt whose dry-run preview has not been filed, with whether its step can file (`can_apply`) |
| `fleet_overview` / `fleet_apps` / `fleet_inbox` / `fleet_work` | committed signals (`tools/fleetcore`) | The merged `fleet` server's views; no console needed |
| `fleet_workflows` | the checkout's `.github/` (dash-gen `workflow_atlas`) | The workflow atlas: every hub workflow and composite action with its triggers, crons, Claude call sites, kill switch and findings; `workflow` returns one in full, `health` adds run health and failure causes from the local lake over `days` ([docs/WORKFLOW-ATLAS.md](../../../docs/WORKFLOW-ATLAS.md)); no console needed |
| `workflow_lint` | dash-gen `workflow_atlas.lint_text` | A draft workflow's findings against the hub's standards and `_data/fleet.yml` (`text`, `id`); nothing is written |
| `console_ops` / `console_jobs` / `console_job_log` | as `ops_list` / `jobs_list` / `job_log` | Legacy `fleet` names |

Write tools — registered only with `HARNESS_MCP_ALLOW_WRITES=1`, annotated `destructiveHint: true`, and each refuses unless called with `confirm=true` (the agent's host must ask the human first):

| Tool | Console route | Effect |
| --- | --- | --- |
| `run_op` | `POST /api/jobs` | Start an allowlisted operation (`op`, `params`) |
| `run_op` with `op: loop-run` | `POST /api/jobs` | The JEV loop runner as a job: `params: {loop, step, target, rehearse}` — a dry run that files nothing; `rehearse: true` is $0, a live attempt spends and needs the console's confirm; `apply: true` files the reviewed preview through the engine's publish gate (constitution § 11.8, the OPS remote-write path) and needs `confirm=true` like every GitHub write — refused up front for a step whose `agent_steps` entry says `can_apply: false` (its filer cannot file yet, #488); `run_id` publishes an earlier reviewed preview, with `item` naming it by the preview's key (`owner/repo`, or `owner/repo:path` for the doctor) when the run has several |
| `cancel_job` | `POST /api/jobs/{id}/cancel` | Cancel a running job |
| `console_run` / `console_cancel` | as `run_op` / `cancel_job` | Legacy `fleet` names (also with `--fleet-compat`; the console's confirm gate still applies) |
| `workflow_kill_switch` | `POST /api/github/repos/{owner}/{repo}/actions` | `workflow.enable` / `workflow.disable` by `workflow_id` (needs the console's GitHub writes on) |

Resources: `harness://overview`, `harness://health`, `harness://ops`, `harness://deep-dive`, `harness://live`.

## Scoped write access (`HARNESS_MCP_SCOPES`)

`HARNESS_MCP_ALLOW_WRITES=1` is all or nothing. `run_op` passes the console's own confirm, so one flag the agent sets reaches every allowlisted operation: `secrets-push`, `keys-rotate`, `config-sync`, the deploys, CI `dispatch`, `observe-reset` and live `loop-run`. Over a public tunnel that is too much. `HARNESS_MCP_SCOPES` grants narrow slices instead, and leaves the broad tools unregistered:

| Scope | Tools | What they can do |
| --- | --- | --- |
| `jobs` | `job_dispatch(op, params, confirm, wait_s)`, `job_cancel(job_id, confirm)` | Start one op from a fixed allowlist of local, $0 reports and checks: `config-show`, `status`, `audit`, `drift`, `schema-lint`, `workflows-lint`, `observe-status`, `observe-verify`, `lake-status` and `refine-surface`. None of them writes to GitHub, reads or writes a secret, or starts or destroys a container. `job_cancel` stops only a job of one of those ops. |
| `work` | `work_apply(plan, plan_id, confirm)` | Apply a prioritising Work-board plan that `work_preview` returned: `priority`, `pins`, `unpin` and `notes`. It writes `_data/work_queue.yml` (and, for a `roadmap:FF-…` key's priority, `_data/roadmap.yml`) in the console's working tree and commits nothing. Committing the file is the approval the loops read ([docs/WORK-BOARD.md](../../../docs/WORK-BOARD.md)). |

These guards apply to every scoped call, and the console's own gates still apply behind them:

- **Approval.** Every call needs `confirm=true`, which the agent's host sets only after asking the person. `work_apply` also needs the `plan_id` from a `work_preview` of the same plan. An id that no longer matches the plan, or the board, is refused: the preview has to be shown again.
- **Allowlists and validation.** An op off the list, a parameter the op does not declare, a parameter value that is not a short plain token (`[A-Za-z0-9._/-]`, at most 64 characters), a plan field outside the four, more than 25 items in a plan, or a note longer than 500 characters is refused before the console is asked. `stage` moves change GitHub labels and roadmap status edits change a roadmap entry's lifecycle, so they stay on the console's Work board.
- **Defence in depth.** `job_dispatch` re-reads the op's card from `/api/ops` and refuses it if the console marks it `remote_write`, spending or unavailable. It always sends the console `confirm=false`, so the console's own gate refuses anything remote even if the list here were wrong. `work_apply` sends `confirm=false` too, and the console needs `confirm` only for a label move.
- **Bounded execution.** Each op has a wall clock: `config-show` gets 120 s, the others 300–900 s. A daemon thread cancels a dispatched job that passes its limit. At most 2 dispatched jobs run at once and 20 start per hour, and `work_apply` is limited to 30 per hour. `wait_s` (up to 120) waits for the job and returns the end of its log; `job_log` reads it later. The limits live in this process, so a restarted server forgets the deadlines of jobs it had started. Each allowlisted op still ends on its own.
- **Audit.** Every scoped call is written as one JSON line, whether it ran, was refused or failed: time, tool, scope, op or plan, `plan_id`, job id, the outcome and the reason, the transport and the client's self-reported name. For `work_apply` the line also holds the per-change results and the diff. It goes to `HARNESS_MCP_AUDIT` (default `.fleet/mcp/audit.jsonl`, gitignored) and to stderr as `harness-mcp audit {…}`, which is the record wherever the file cannot be written. Token-shaped strings are scrubbed first. The client name is a label, not an identity: the bearer token is the gate.
- **Undo.** `work_preview` and `work_apply` return `undo_plan`, the plan that puts every named item back as it was: its override or computed priority, its note and its lane's pin order. Preview it and apply it like any other plan, or restore the file from git.
- **Annotations.** Like every write tool, the scoped ones are marked `destructiveHint: true` (NFR9), so a host asks before each call. They are also marked `openWorldHint: false`, because they change only local state.

Neither scope writes to GitHub, so neither is a write-back path under constitution § 11. Under § 13.6 their actions are reversible, local and $0. The person's `confirm` comes before each one, and each is audited. A scope can only narrow what the console allows. Turning a scope on for the sidecar is a runtime change on the Mac: set `HARNESS_MCP_SCOPES` in `.env` or the environment, then recreate the `mcp` service.

## Result size

`HARNESS_MCP_MAX_CHARS` (60,000) is the last line of defence: a result over it becomes `{truncated, total_chars, json_prefix}`, which an agent reads as nothing useful. So a tool whose route answers with the whole of something pages instead of relying on the clip. `work_board` is the one that needs it — `/api/work` is ~390,000 characters over ~400 items, a quarter of it each item's `detail` record — so it defaults to `summary=true` and 40 items (~25,000 characters) and reports `matched`, `matched_by_lane` and `next_offset` so the rest can be walked. `summary=false` returns full items and caps `limit` at 25; one item's whole record is `work_item` / `fleet_work`. `fleet_status`, `jobs_list`, `lake_runs`, `workflow_lines` and `job_log` take the same shape of limit.

## Reaching the planes from a container

The MCP sidecar and the console run in containers, and the `_data/fleet.yml` URLs are the **browser's** (loopback — they are also the links the console renders). Every server-side probe therefore goes through `fleet_observe.probe_url`, which prefers `ES_URL`, `KIBANA_URL`, `GRAFANA_URL`, `QDRANT_URL`, `OLLAMA_URL`, `PROMETHEUS_URL` — set on `console` and `devenv` in `docker-compose.yml` to the service-DNS form. The code index missed this and asked the container's own `127.0.0.1:6333`, so `index_coverage` and `code_search` reported "Qdrant has no collection" against a store holding 17,341 points. Kilo's collection name is a hash of the workspace **root path**, which differs between the host (`/Users/bamr87/bamr87`) and a container (`/workspace`), so it is never recomputed: the store is listed and a `ws-` collection chosen (the fullest, when there are several). `QDRANT_COLLECTION` overrides that choice and wins even when the store cannot be listed. `index_coverage` returns `qdrant`, `collection`, `collections` and `collection_source` so a wrong pick is visible rather than looking like an index that covers nothing.

## Tests

```bash
tools/console/mcp.sh --list-tools >/dev/null   # bootstrap .venv-mcp once
.venv-mcp/bin/python tools/console/test_mcp_layer.py      # unit: mocked HTTP, the protocol, HTTP auth, scopes
.venv-mcp/bin/python tools/console/smoke_mcp_layer.py     # live: stdio against the running console
.venv-mcp/bin/python tools/console/smoke_mcp_layer.py --url http://127.0.0.1:4002/mcp   # live: the HTTP sidecar
```

`test_mcp_layer.py` skips cleanly where `mcp` is not installed. It covers the scoped tools too: which tools each scope registers, the refusals (no confirm, an op off the allowlist, an undeclared parameter, a stale `plan_id`, a `stage` move), the running and hourly caps, the watchdog's cancel, the round trip of a plan and its `undo_plan`, and the audit's scrubbing. The smoke test lists tools and resources and calls a few read tools, printing sizes and top-level keys only. With `--url` it runs the remote handshake against a running HTTP server, reading the bearer token in-process, and fails when no tools are listed.

## Not yet

- No `/mcp` route on the console itself (the sidecar covers always-on).
- `live_snapshot` and `sessions` need `/api/live` from bamr87/bamr87#432; on a console without it they return a tool error naming the PR.
- No SSE streaming of `/api/live/stream` as MCP notifications yet.
