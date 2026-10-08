# tools/fleetcore — one core, three surfaces

The Harness Console (browser, `tools/console/`) and the terminal dash (TTY, `tools/tui/`) used to load the same YAML twice, through two loaders with two ideas of "stale", and to draw the same red dot in two different reds. This package is what they now share.

| Module | Browser console | Terminal dash |
| --- | --- | --- |
| `fleet.py` + `views.py` | `/api/fleet`, `/api/fleet/docker` → the **Apps** tab | Apps, Inbox, Attention, Monitor, Harness, Docker tabs |
| `keys.py` (keys v1) | `/api/keys` → the page's key handler and `?` sheet | its Bindings, footer and `?` panel |
| `theme.py` (bashOS palette) | `/theme.css` | the `bashos-dark` Textual theme |
| `client.py` | — (the console *is* the runtime) | the **Jobs** tab and the `:` palette submit jobs to the console |
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

`mcp_server.py` makes the console AI-native. It's registered in the repo's [`.mcp.json`](../../.mcp.json) as `fleet`, so Claude Code in this repo (or any MCP host) gets what a person gets in the browser or the terminal, and no more.

| Tool | Does | Needs the console |
| --- | --- | --- |
| `fleet_overview` | KPIs, signal freshness, tripped harness wires, the red repos | no |
| `fleet_apps` | the Apps view: filter by text and level, sort like the dashboards | no |
| `fleet_inbox` | the flagged inbox, or every open item of one repo | no |
| `fleet_docker` | containers on every `DASH_DOCKER_HOST`, attributed to projects | no |
| `console_ops` | the console's allowlisted operations and which can write to GitHub | yes |
| `console_run` | run one as a job, the same job the browser and the TUI list. A writing operation is refused unless `confirm=true` | yes |
| `console_jobs` · `console_job_log` · `console_cancel` | list jobs, follow a log by offset, cancel | yes |

Notes:

- **Transport:** MCP over stdio, standard library only, no SDK.
- **Gates:** the actions go through `client.py`, so the console's allowlist, parameter validation and confirm gate apply to an agent exactly as to a person. Tool annotations mark the read tools `readOnlyHint` and `console_run` / `console_cancel` `destructiveHint`, so a host can ask before calling them.
- **Token:** when `DASH_CONSOLE_TOKEN` isn't in the environment, the server reads that one line from the repo's `.env`. It parses the file and never sources it.

To try it by hand: `python3 tools/fleetcore/mcp_server.py`, then send newline-delimited JSON-RPC (`initialize`, `tools/list`, `tools/call`).

## Tests

`python3 tools/test_tui_fleet.py` (data layer) and `python3 tools/test_fleetcore.py` (keys, theme, client, the MCP protocol), both on PyYAML alone. `tools/console/test_console.py` asserts the console serves exactly these objects and reaches the job API over the socket. `tools/tui/test_app.py` drives the keys and the Jobs tab against a fake console.
