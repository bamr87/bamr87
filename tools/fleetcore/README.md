# tools/fleetcore — one core, three surfaces

The Harness Console (browser, `tools/console/`) and the terminal dash (TTY, `tools/tui/`) used to load the same YAML twice, through two loaders with two ideas of "stale", and to draw the same red dot in two different reds. This package is what they now share.

| Module | Browser console | Terminal dash |
| --- | --- | --- |
| `fleet.py` + `views.py` | `/api/fleet`, `/api/fleet/docker`, `/api/project/:name` → **Projects**, **Inbox**, **Containers** and each project's page | Apps, Inbox, Attention, Monitor, Harness, Docker tabs |
| `yamlio.py` | every committed signal the console reads (`core.load_yaml`, `site_docs`, the frame policy): parsed once per version of the file, not once per request | the same reads through `fleet.py` |
| `apps.py` | `/api/apps` → **Desktop** (an icon per app, each in a window; the Fleet window from `repos`), **Apps** (every fleet frontend, framed at its live or local address) and the origins in the console's Content-Security-Policy | — (planned: the Apps tab opens and checks a frontend); today `tools/dash apps` |
| `keys.py` (keys v1) | `/api/keys` → the page's key handler and `?` sheet | its Bindings, footer and `?` panel |
| `theme.py` (bashOS palette) | `/theme.css` (Mantine's variables point at it) and `/api/theme` (the Terminal page's xterm colours) | the `bashos-dark` Textual theme |
| `client.py` | — (the console *is* the runtime) | the **Jobs** tab and the `:` palette submit jobs to the console |
| `loopjob.py` | `/api/jobs/:id` → `loop` on a `loop-run` job (the Job page's run summary) | the Jobs tab's summary under a finished loop-run |
| `nodes.py` | `/api/nodes` → **Nodes** (a card per node, the drift and the placement table) and the **Overview**'s placement-drift line; MCP `fleet_nodes`; all from `status_doc()`, which `tools/dash node status --json` prints ([docs/PLATFORM.md](../../docs/PLATFORM.md#surfaces)) | the Docker tab's Node column (`host_nodes()`: a Docker host → its node, read from the model, never probed); `tools/dash node` and `tools/dash infra` |
| `clouds.py` | — (planned: `/api/clouds`, a Clouds page and MCP `fleet_clouds`, ADR 0018 P1); today `tools/dash cloud`, all from `status_doc()` ([docs/CLOUDS.md](../../docs/CLOUDS.md#the-document)) | — (planned) |
| `graph.py` | `/api/graph` (one question per request: summary, find, show, impact, lineage, path, check) and the `graph-check` operation; a Graph page is planned | — (planned); today `tools/dash graph` |
| `learn.py` | `/api/learn` (each loop's outcomes, estimate, plan and replay, shadow only) and the `learn-status` / `learn-plan` operations; a Learning page is planned | — (planned); today `tools/dash learn` |
| `workflows.py` | — (planned: the Studio's read views, ADR 0007 S2); today the MCP's `fleet_workflows` with `fleet=true` | — (planned); today `tools/dash workflows --fleet` |
| `prqueue.py` | `/api/prs` → **PR queue** (`/prs`): every open pull request with its checks collapsed, the gate, the merge method and who moves it next; the plan and apply around it are `tools/console/pr_queue.py`, and the MCP's `pr_queue` | — (planned); today `tools/dash prs` |
| `stars.py`, `stars_ai.py`, `stars_grafana.py` | `/api/stars` → **Stars** (`/stars`): the open-source radar, the committed `_data/stars.json` the model builds, with the AI pass laid over it (`stars_ai`); the MCP's `fleet_stars` reads `query()` slices; the SessionStart hook reads `brief()`; the `fleet-stars` Grafana dashboard is `stars_grafana`'s render | `tools/dash stars` (the same model, `tools/stargazer.py`) |
| `assistlog.py` | `/api/assist/activity` → **Assist** (*How it is observed*: the assistant's messages from the AI ledger and its page activity from the page bridge's audit) | — (a terminal reads it with `tools/dash apps assist activity`; MCP `assist_activity`; the lake with `lake assist`) |
| `mcp_server.py` | — | — (the third surface: AI agents, below) |

## One runtime

The console process owns the operation allowlist and the job manager. The browser page is one client of its API and the TUI is another, so a job started in either one shows up in both, and every gate (allowlist, parameter validation, confirm before a GitHub write) runs server-side.

| How it runs | `DASH_CONSOLE_URL` the TUI uses |
| --- | --- |
| native `tools/dash console` + `tools/dash tui` | `http://127.0.0.1:4001` (the default) |
| `tools/dash tui --docker` | `unix:///home/vscode/.dash-run/console.sock`. The `console` service also listens on a Unix socket in the `console-run` volume, which only the `tui` service mounts. Reaching that file is the authorization, so no hostname joins the console's DNS-rebinding allowlist and no secret has to be shared. |
| no console | empty: the Jobs tab says how to start one, and the TUI stays read-only |

`DASH_CONSOLE_TOKEN`, when the console requires it, is sent as a bearer token, as the page does.

## For agents: the `fleet` MCP server

`mcp_server.py` made the console AI-native; it is now merged into the Harness Console MCP layer ([`tools/console/docs/mcp-layer.md`](../console/docs/mcp-layer.md)), which reuses its tools and keeps the name. It's registered in the repo's [`.mcp.json`](../../.mcp.json) as `fleet`, so Claude Code in this repo (or any MCP host) gets what a person gets in the browser or the terminal, and no more.

| Tool | Does | Needs the console |
| --- | --- | --- |
| `fleet_overview` | KPIs, signal freshness, tripped harness wires, the red repos | no |
| `fleet_apps` | the Apps view: filter by text and level, sort like the dashboards | no |
| `fleet_inbox` | the flagged inbox, or every open item of one repo; a `merge` item (a green, clean fix PR) carries `clears` | no |
| `fleet_docker` | containers on every `DASH_DOCKER_HOST`, attributed to projects | no |
| `fleet_nodes` | where hub workloads run: each node's role, on/off state, reachability (`up` · `unknown` · `off`), capacity and hub services, the placement rows and the drift; a node that is off is never probed ([docs/PLATFORM.md](../../docs/PLATFORM.md#surfaces)) | no |
| `fleet_work` | the Work board in the loops' order: lanes, each loop's cap and next run, the human's pins and overrides first ([docs/WORK-BOARD.md](../../docs/WORK-BOARD.md)) | no |
| `fleet_workflows` | the hub's workflows and composite actions as one model with every lint finding; one in full with `workflow`; run health and failure causes from the lake with `health`; with `fleet=true` the fleet model (`fleet-workflows/v1`, `workflows.py`): every repository's read time or why it was not read, its findings and its checks' states ([docs/WORKFLOW-ATLAS.md](../../docs/WORKFLOW-ATLAS.md#the-fleet-model)) | no |
| `workflow_lint` | a draft workflow's findings against the hub's standards and `_data/fleet.yml` — nothing is written | no |
| `fleet_graph` | the fleet graph: what the control plane manages and how it relates; `action` is summary, find, show, impact (what depends on a node), lineage (what it needs), path or check ([docs/FLEET-GRAPH.md](../../docs/FLEET-GRAPH.md)) | no |
| `fleet_learning` | outcome learning in shadow: what happened to each loop's output, the landing estimate per loop and per repo, the plan for the next slots, the replay test and the backlog advice ([docs/LEARNING.md](../../docs/LEARNING.md)); `available: false` when this machine has no lake | no |
| `console_ops` | the console's allowlisted operations and which can write to GitHub | yes |
| `console_run` | run one as a job, the same job the browser and the TUI list. A writing operation is refused unless `confirm=true` | yes |
| `console_jobs` · `console_job_log` · `console_cancel` | list jobs, follow a log by offset, cancel | yes |

Notes:

- **Transport:** MCP over stdio, standard library only, no SDK.
- **Gates:** the actions go through `client.py`, so the console's allowlist, parameter validation and confirm gate apply to an agent exactly as to a person. Tool annotations mark the read tools `readOnlyHint` and `console_run` / `console_cancel` `destructiveHint`, so a host can ask before calling them.
- **Token:** when `DASH_CONSOLE_TOKEN` isn't in the environment, the server reads that one line from the repo's `.env`. It parses the file and never sources it.

To try it by hand: `FLEET_MCP_STDLIB=1 python3 tools/fleetcore/mcp_server.py` (without the variable it delegates to the merged layer), then send newline-delimited JSON-RPC (`initialize`, `tools/list`, `tools/call`).

## Tests

`python3 tools/test_fleetcore_assistlog.py` (the assistant's two records read back, and the activity document), `python3 tools/test_fleetcore_clouds.py` (the cloud map: recognition from data alone, how a deployment signs in, the findings, the document, and that the reader names no provider), `python3 tools/test_fleetcore_graph.py` (the graph: model, builders, checks, the hub's own graph), `python3 tools/test_fleetcore_learn.py` (outcomes, the estimate, the plan, the replay, the lake reader), `python3 tools/test_fleetcore_prqueue.py` (the PR queue: the check collapse, the gate, who moves next, batches, the triage hint, plan identity), `python3 tools/test_fleetcore_workflows.py` (the fleet workflow model and the sync that fills it, over a fake GitHub), `python3 tools/test_tui_fleet.py` (data layer), `python3 tools/test_fleetcore_apps.py` (the launcher: targets, the ports join, embed rules, address resolution), `python3 tools/test_fleetcore_yamlio.py` (the reader: what `yaml.safe_load` builds, one parse per version of a file, never a stale one), `python3 tools/test_fleetcore.py` (keys, theme, client, the MCP protocol, and the inbox priorities and merge items held equal to `fleet_triage`) and `python3 tools/test_fleetcore_nodes.py` (placement, overlays, the link key, the infra gate, and the committed model), all on PyYAML alone. `tools/console/test_console.py` asserts the console serves exactly these objects and reaches the job API over the socket. `tools/tui/test_app.py` drives the keys and the Jobs tab against a fake console.
