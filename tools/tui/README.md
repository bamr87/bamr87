# tools/tui — terminal command center

The TTY twin of the Jekyll dash: the home page, `/monitor/`, `/triage/` and `/harness/` in one Textual app, over the same YAML, plus a Jobs tab on the Harness Console's runtime. Its data, keys and colours come from [`tools/fleetcore/`](../fleetcore/README.md), the core the browser console renders too. There's no second inventory, and it never runs a write itself.

```
tools/dash tui            # native: bootstraps .venv-tui at latest
tools/dash tui --docker   # the same app in the `tui` compose service (see "In Docker")
```

## What it reads

| Source | Page twin | Committed? | Missing → |
| --- | --- | --- | --- |
| `_data/projects.yml` | home | yes | — (the roster) |
| `_data/project_health.yml` (+ `_meta`) | `/monitor/` | **no** — ephemeral, `dash-gen health` | Monitor tab explains, `R` fills it (~3 min) |
| `_data/fleet_triage.yml` | `/triage/` | yes, daily (fleet-pulse) | Inbox tab explains |
| `_data/harness_health.yml` | `/harness/` | yes, daily (fleet-pulse) | Harness tab explains |
| `docker ps -a` on each `DASH_DOCKER_HOST` | `/docker/` (live half) | — | Docker tab names the host and its error |

Because triage and harness are committed, a fresh clone already shows red/amber attention, the fleet inbox and the trip wires. Only the `/monitor/` health columns need a `dash-gen health` run. The status line under the KPIs shows the age of every source and marks one **STALE** past `_data/fleet.yml` `harness.trip_wires.stale_data_days`, the same threshold as the harness's own `stale-data` wire. Files that change on disk (a `git pull`, the daily workspace sync, `dash-gen` in another shell) are reloaded on the next 15 s tick.

## Tabs

| # | Tab | Shows | `enter` |
| --- | --- | --- | --- |
| 1 | **Apps** | Every registry project: health, CI, last commit, triage score, open issues/PRs, failing workflows, security alerts, checkout, containers. The detail pane follows the cursor. | Opens this project's items in the Inbox |
| 2 | **Inbox** | The fleet inbox (flagged items, highest priority first). From a drill-down: **all** of one repo's open items from `by_repo`, ranked with the same priorities. | Opens the issue / PR / run |
| 3 | **Attention** | Red/amber on _either_ signal (health or triage), worst first | Repo's items |
| 4 | **Monitor** | The `/monitor/` health board | Repo's items |
| 5 | **Harness** | Trip wires (tripped first), then the scorecard with its desired direction and threshold | — |
| 6 | **Docker** | Containers on every host, attributed to their registry project | — (`o` opens the owning repo) |
| 7 | **Jobs** | The console's jobs: the same list as the browser's Jobs tab, whichever surface started them. `:` (or `ctrl+p`) lists the console's operations; picking one submits it, and an operation the console says writes to GitHub asks first | Shows the job's log, tailing while it runs (`d` cancels) |

## Keys

keys v1 ([`fleetcore/keys.py`](../fleetcore/keys.py)): the browser console binds the same table.

| Key | Action |
| --- | --- |
| `1`–`7` · `]` / `[` | go to tab · next / previous tab |
| `j` / `k` · `g` / `G` | down / up · top / bottom (arrows and page keys work too) |
| `/` · `esc` | focus search · back: leave the search, then the inbox drill-down, then the filters |
| `:` | the console's operations (the command palette, also `ctrl+p`) |
| `s` | cycle sort (featured / name / health / triage / alerts / recent / stars) |
| `c` / `t` / `h` / `f` | cycle category / status / health level (either signal) / featured only. `x` clears them all |
| `o` / `l` / `y` | open the repo (or, on the Inbox, the item) / open `live_url` / copy the link. With no browser to hand it to (Docker, SSH) the link is shown instead |
| `r` / `R` | reload YAML, re-poll Docker and the jobs / run `tools/dash-gen health` (progress streams into the status line) |
| `d` | cancel the selected job (Jobs tab; asks first) |
| `?` | key help |
| `q` | quit |

## In Docker

`tools/dash tui --docker` is `docker compose run --rm tui`, which starts `console` first if it isn't up. It runs the workspace image (`.devcontainer/Dockerfile`, built on first use; `docker compose build tui` picks up later changes) running `tools/tui/run.sh` over the bind-mounted repo. The service sits behind the `tui` profile, so `dash up` never starts it. It is interactive, so you run it rather than bring it up.

| Grant | For | Opt out |
| --- | --- | --- |
| `venv-tui` volume over `/workspace/.venv-tui` | the Linux venv, kept apart from the macOS one a native run uses | — |
| `/var/run/docker.sock` (`:ro`) + `group_add` | `local` in the Docker tab. The group is root (0) on Docker Desktop; set `DOCKER_GID` to the host's `docker` group elsewhere | `DASH_DOCKER_HOST=` |
| `~/.ssh` read-only | `ssh://forge`: the alias, its key, its known_hosts | `TUI_SSH_DIR=<empty dir>` |
| `GH_TOKEN` from `.env` (as console) | `R` → `dash-gen health` | — |
| the `console-run` volume (the console's Unix socket) and `DASH_CONSOLE_TOKEN` | the Jobs tab and `:` reach the same runtime as the browser | `DASH_CONSOLE_URL=` |

The socket reaches the whole Docker API whatever the `:ro` says, so a holder could already mount `~/.ssh` itself. The SSH mount adds parity, not reach. Logging is `none`: the container's output is a full-screen TTY, and with the fleet labels Filebeat would otherwise ship every repaint. `TERM`, `COLORTERM`, `DASH_DOCKER_HOST` and `TUI_SKIP_INSTALL` pass through from your shell.

## Docker hosts

`DASH_DOCKER_HOST` is a comma-separated list. `local` means this machine's current Docker context, which is where `tools/dash up` runs the shared core. Anything else goes to `docker -H`. The default is `local,ssh://forge` (see [`docs/FORGE-HOST.md`](../../docs/FORGE-HOST.md)). Set it to an empty string to turn polling off.

A container belongs to a registry project by, strongest first:

1. **its `com.bamr87.fleet.project` label** (UPS-OPS-17). The legacy `bamr87.project` label is also honoured. A labelled container is attributed to that project or to _nothing_: the hub's own services say `bamr87`, which is not a registry row, so they are never guessed onto a lookalike.
2. its compose project name, then its container name, then a `<name>-…` prefix. The longest name wins, so `cv-builder-pro-web-1` goes to `cv-builder-pro`, not `cv`.

## Layout

| File | Role |
| --- | --- |
| `app.py` | The Textual UI over `tools/fleetcore` (data, Docker inventory, keys, theme, the console client) |
| `run.sh` | Bootstraps `.venv-tui` at latest and execs `app.py` |

Tests: `python3 tools/test_tui_fleet.py` covers the data, and `.venv-tui/bin/python tools/tui/test_app.py` drives the screen headlessly with Textual's Pilot (layout, cursor stability, drill-down, markup safety, the streamed refresh). `tools/run-all-tests.sh` runs both, and skips the second with a reason when Textual isn't installed.

It does not commit, and it shells out only for `docker ps` and, on `R`, `dash-gen health`. Everything else is a job submitted to the console (`DASH_CONSOLE_URL`, default `http://127.0.0.1:4001`), which is the credentialed write plane: its allowlist and confirm gate apply to a job from here exactly as they do to one from the browser.
