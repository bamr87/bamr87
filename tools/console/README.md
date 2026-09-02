# Harness Console

The local control plane's **front end**: one service that lets you view, manage, orchestrate, and deploy the fleet's AI harnesses from a browser, using exactly the `tools/` entrypoints the CLI and CI run. It is the credentialed, write-capable twin of the read-only Jekyll boards on GitHub Pages ([docs/HARNESS-OPS.md](../../docs/HARNESS-OPS.md), "The two planes").

## Run it

```bash
tools/dash console              # native: bootstraps .venv-console (latest deps), serves http://127.0.0.1:4001
tools/dash console --docker     # the compose service (same devenv image, loopback port 4001)
docker compose up -d console    # same thing
CONSOLE_RELOAD=1 tools/dash console   # auto-reload while editing app.py / core.py
```

The console is one of the local stack's three services; `docker compose up -d phoenix` starts the trace store it links to (http://127.0.0.1:6006), and `tools/dash lake sync` fills the data lake the Traces tab reads (see [docs/HARNESS-OPS.md](../../docs/HARNESS-OPS.md), "The local stack").

Credentials are inherited from the process environment (`gh auth login`, or `GH_TOKEN` / `FLEET_TOKEN` / the Claude tokens in `.env` for the compose service). The console only ever reports which credential **names** are present. Set `DASH_CONSOLE_TOKEN` to require `Authorization: Bearer …` on the API when the console is reachable beyond localhost. Independently of that, the console answers only to loopback `Host` values: binding to 127.0.0.1 does not by itself stop a hostile page from resolving its own hostname to 127.0.0.1 (DNS rebinding) and then talking to this origin as same-origin, which on a console that can dispatch workflows and run `--apply` fan-outs is a real lever. Front it with another hostname by naming that hostname in `DASH_CONSOLE_ALLOWED_HOSTS` (comma-separated) — and set the token as well.

## What it does

| Tab | View | Manage |
| --- | --- | --- |
| Overview | hero attention count, KPI tiles (AI workflows, scheduled runs vs cap, projected spend vs ceiling, baseline coverage, trip wires, standing failures), the ranked attention queue, signal freshness | **Act** on a finding → pre-filled operation |
| Harnesses | per-repo deployment matrix (kind, auth shape, kit version, agent context, secret state, load, cost, baseline) with filters | refresh the inventory (live / offline), **deploy the kit to gap repos** (dry-run → apply), dispatch `harness-fanout` in CI |
| Schedules | throughput vs caps, AI crons by UTC hour with collisions, the fleet calendar | — (retune a cron or a cap; findings name which) |
| Loops | every control-plane loop with cadence + output freshness | run the loop's local half, dispatch it in CI |
| Costs | Claude spend + Actions minutes trends, week-over-week, projected monthly vs budget, by-day tables | refresh the ledgers |
| Traces | **the local stack**: the data lake (`.dash-lake/fleet.sqlite` — size, last sync, per-repo runs/AI runs/workflows/issues, agent spend and models parsed from run logs), Phoenix reachability + export ledger, the newest agent runs with their trace ids, and the **Lines** view (every workflow in GitFactory's vocabulary: `blueprint@hash` provenance, `vars.*_ENABLED` gate, triggers/crons, model, auth, last verdict) | **sync** the lake from GitHub, **export** traces to Phoenix (dry run by default; local Claude Code sessions optional), open Phoenix |
| Fleet | registry, triage inbox, credential ages | status / audit / triage / secrets audit / reconcile |
| Contract | the `harnesses:` block of `_data/fleet.yml` as a form; read-only schedule, caps, token contract | **save** (comments preserved) → git diff shown; the commit stays with you |
| Jobs | every job with live log tailing and cancel | run any allowlisted operation with its parameters |

## What it refuses to do

- Run anything outside the allowlist in `core.py` (`OPS`): parameters are validated by regex/range and become argv elements, never a shell string.
- Write to GitHub without an explicit confirm (`apply`, `dispatch`) — and only one such job runs at a time.
- Commit, push, or merge. Generated data lands in the working tree; you review it in git.
- Publish the lake. `.dash-lake/` is gitignored (it holds run logs); traces go only to the Phoenix endpoint you configured, and `PHOENIX_API_KEY`, when set, is forwarded and never shown.

## Files

`core.py` (logic, tested by `test_console.py` on PyYAML alone) · `app.py` (FastAPI routes, including `/api/lake`, `/api/lake/runs`, `/api/lake/lines`) · `static/index.html` (the page) · `run.sh` · `requirements.txt` (always-latest; carries the OpenTelemetry SDK + OTLP/HTTP exporter for `lake export`).
