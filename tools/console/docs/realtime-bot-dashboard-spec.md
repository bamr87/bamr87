# Real-time bot-activity dashboard — spec

Status: implemented on local branch `grokbot/live-dashboard` (not pushed). Route: **`/live`** (sidebar: Spend → "Live activity").

## Goal
One console page that shows, refreshing every ~5 s without reload: active/idle Claude Code sessions, running console jobs with a live log tail, Claude + GitHub Actions spend vs budget, harness health scorecard, and deep-dive cycle progress. Reuse the console's existing documents (`/api/state`, `/api/jobs`, `/api/data/deep_dive`, `/api/observability`) and the local observability stack instead of a separate app.

## Build note (prerequisite)
`npm install` in `tools/console/web` failed with ERESOLVE: `@mantine/charts@latest` (9.7.4) peers on `@mantine/core@9.7.4` while `@mantine/modals` pins core 9.7.3 (a publish skew; deps are `*`, no lockfile). Fix:
- `web/.npmrc`: `legacy-peer-deps=true` (so `run.sh`'s own `npm install` also succeeds).
- `web/package.json`: add `react-is` — recharts needs it as a peer, and legacy-peer-deps stops npm auto-installing peers, which made `vite build` fail to resolve `react-is`.
- `dist/` is NOT baked into the image: the container bind-mounts the repo at `/workspace`, so a host `npm run build` is served immediately (no image rebuild). The container's own `node_modules` is a named volume (`fleet_console-web-modules`), separate from the host's.

## Existing real-time plumbing (inventory)
- No SSE anywhere before this work. One WebSocket: `/api/tui` (`app.py` → `tui_bridge.py`) — a PTY bridge for the Terminal page; not a data feed.
- Polling via TanStack Query `refetchInterval` in `web/src/api/hooks.ts`: `useJobs` (2 s while a job runs, else 6 s), `useTuiStatus` (10 s), GitHub log (15 s).
- Job logs: `GET /api/jobs/{id}?offset=N` incremental tail (`core.JobManager.tail`), used by `web/src/jobs/JobLog.tsx`.
- Pages reused as data: `/costs` (`state.harnesses.trends`), `/harnesses/health` (`state.health.scorecard`), `/deep-dive` (`/api/data/deep_dive`), `/activity` (lake runs), `/observe/*` (`/api/observability`).

## Data sources → panel
| Panel | Source | Endpoint / transport | Reachability |
|---|---|---|---|
| Claude Code sessions | host `ps` (claude CLI, `claude -p`, VS Code ext, Claude Desktop): pid, cpu, rss, age, cwd; active = cpu ≥ 1% | host collector `tools/console/live_collector.py` writes `.dash-live/sessions.json` every 5 s; console reads it in `/api/live` | Container can't see host processes; repo is bind-mounted, so the file is the bridge. Stale (>30 s) → panel says "collector not running". |
| Claude live usage | Prometheus `claude_code_cost_usage_USD_total`, `claude_code_token_usage_tokens_total`, `claude_code_session_count_total` (Claude Code OTel → collector → Prometheus) — `increase(...[24h])` | `/api/live` queries `PROMETHEUS_URL` (default `http://host.docker.internal:9090`; compose already sets `http://prometheus:9090` on the shared `fleet` network) | `127.0.0.1` inside the container is not the host; use the service name or `host.docker.internal`. |
| Claude CI spend vs budget | `state.harnesses.trends.ai_cost_usd` (`_data/ai_usage.yml`, `dash ai`) vs `harnesses.budget.monthly_ai_usd` (`_data/fleet.yml`) | `/api/live` (from `core.load_state()`) | file |
| Actions minutes vs budget | `state.harnesses.trends.actions_minutes` (`_data/actions_usage.yml`) vs `monthly_actions_minutes` | same | file |
| Running jobs + log tail | `core.JobManager` | `/api/live` lists jobs; tail via existing `/api/jobs/{id}?offset` polled 2 s | in-process |
| Harness scorecard | `state.health.scorecard` (`_data/harness_health.yml`) | `/api/live` | file |
| Deep-dive | `_data/deep_dive.json` (from `tools/deep_dive.py` / `_data/deep-dive.yml`) `summary` | `/api/live` | file |
| Observability planes | `core.observability_planes()` | `/api/live` (probe cached 30 s) | as in /observe |

## Live refresh
- `GET /api/live` — one JSON snapshot (all panels), token-guarded like every `/api` route.
- `GET /api/live/stream` — SSE (`text/event-stream`), one `data:` snapshot every 5 s. The browser reads it with `fetch` + ReadableStream (not `EventSource`, which can't send the `Authorization: Bearer` header the console token needs). Hook: `useLive()` in `web/src/api/live.ts`; on stream error it falls back to polling `/api/live` every 5 s and the page shows which transport is active ("SSE" / "polling").
- Job log tail reuses `/api/jobs/{id}?offset` polling.

## Page / routes
- `web/src/pages/Live.tsx`, route `live` in `web/src/main.tsx`, nav item in `web/src/nav.ts` under Spend next to Agent activity; panels link out to `/costs`, `/harnesses/health`, `/deep-dive`, `/jobs/:id`, `/activity`, `/observe/metrics`.

## Running the host collector
`python3 tools/console/live_collector.py` (loops, 5 s; `--once` for a single write). Output `.dash-live/sessions.json` (gitignored). Read-only: never signals processes.

## Acceptance criteria
1. `npm run build` passes; served bundle contains Deep dive and Live pages; `/deep-dive`, `/live` return 200.
2. `/api/live` returns all sections; `/api/live/stream` emits a new event every ~5 s with changing `generated_at`/session cpu.
3. With the collector running, sessions list host Claude processes with cpu/age/cwd.
4. Budgets show value vs ceiling; missing ceiling renders "budget unset".

## Open questions
- Run the collector under launchd so it survives reboot (not done; started manually with nohup).
- Live per-session Claude cost (join Prometheus `session_id` label to pids) — not mapped.
- Live GitHub Actions minutes (billing API) — currently the daily ledger, not real-time.
