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

Credentials are inherited from the process environment (`gh auth login`, or `GH_TOKEN` / `FLEET_TOKEN` / the Claude tokens in `.env` for the compose service) — and, since 0.3, they can also be handed to the console **on the Auth tab** when it starts without them: a pasted value lives in this process's environment (which is exactly what a job inherits) and dies with the process, a GitHub token can instead go to `gh auth login --with-token` over stdin so the CLI's own store keeps it, and writing anything to the gitignored `.env` (mode 600) is a separate, explicitly confirmed step. Values are never returned, logged, or placed on a command line; every status document reports credential **names**, presence and provenance only. `DASH_CONSOLE_AUTH=off` refuses every credential write; set `DASH_CONSOLE_TOKEN` to require `Authorization: Bearer …` on the API when the console is reachable beyond localhost. Independently of that, the console answers only to loopback `Host` values: binding to 127.0.0.1 does not by itself stop a hostile page from resolving its own hostname to 127.0.0.1 (DNS rebinding) and then talking to this origin as same-origin, which on a console that can dispatch workflows and run `--apply` fan-outs is a real lever. Front it with another hostname by naming that hostname in `DASH_CONSOLE_ALLOWED_HOSTS` (comma-separated) — and set the token as well.

## What it does

| Tab | View | Manage |
| --- | --- | --- |
| Overview | hero attention count, KPI tiles (AI workflows, scheduled runs vs cap, projected spend vs ceiling, baseline coverage, trip wires, standing failures), the ranked attention queue, signal freshness | **Act** on a finding → pre-filled operation |
| Harnesses | per-repo deployment matrix (kind, auth shape, kit version, agent context, secret state, load, cost, baseline) with filters | refresh the inventory (live / offline), **deploy the kit to gap repos** (dry-run → apply), dispatch `harness-fanout` in CI |
| Schedules | throughput vs caps, AI crons by UTC hour with collisions, the fleet calendar | — (retune a cron or a cap; findings name which) |
| Loops | every control-plane loop with cadence + output freshness | run the loop's local half, dispatch it in CI |
| Costs | Claude spend + Actions minutes trends, week-over-week, projected monthly vs budget, by-day tables | refresh the ledgers |
| Traces | **the local stack**: the data lake (`.dash-lake/fleet.sqlite` — size, last sync, per-repo runs/AI runs/workflows/issues, agent spend and models parsed from run logs), **this machine's Claude Code sessions** — count, shadow-priced cost, turns and tool calls, which is the whole of the lake until a GitHub sync runs — Phoenix reachability + export ledger, the newest agent runs with their trace ids, and the **Lines** view (every workflow in GitFactory's vocabulary: `blueprint@hash` provenance, `vars.*_ENABLED` gate, triggers/crons, model, auth, last verdict) | **sync** the lake from GitHub, **export** traces to Phoenix (dry run by default; local Claude Code sessions optional), open Phoenix |
| Fleet | registry, triage inbox, credential ages | status / audit / triage / secrets audit / reconcile |
| Config | the whole fleet contract (`_data/fleet.yml`) as one form per top-level block — toolchain, schedule, remediation, issue pipeline, evolution, harness, harnesses, rotation, canonical variables | **save a block** (comments preserved, only that block rewritten) → git diff shown; the commit stays with you |
| Auth | which credentials this process holds and where each came from, the gh CLI's login (account, scopes), the Claude credential, and what the token contract declares | **set / clear** a credential for the console (optionally persisted to the gitignored `.env`), **sign in / out** of GitHub, audit the fleet's secrets |
| Jobs | every job with live log tailing and cancel; the log decodes the tools' ANSI colour and follows the tail only while you are already at the bottom, so you can scroll back through a running job | run any allowlisted operation with its parameters |

## What it refuses to do

- Run anything outside the allowlist in `core.py` (`OPS`): parameters are validated by regex/range and become argv elements, never a shell string.
- Write to GitHub without an explicit confirm (`apply`, `dispatch`) — and only one such job runs at a time.
- Commit, push, or merge. Generated data lands in the working tree; you review it in git.
- Invent contract structure. The Config form edits declared keys only: a key `fleet.yml` does not already carry is shown read-only, and the policy keys the file itself calls non-negotiable (`rotation.hub_first`, `issue_pipeline.autonomy.never_merge`) are not offered at all.
- Hand a credential back. Values go in; names, presence and provenance come out. A token pasted for `gh` travels on stdin, and `.env` is written only on an explicit confirm — never if git tracks it.
- Publish the lake. `.dash-lake/` is gitignored (it holds run logs); traces go only to the Phoenix endpoint you configured, and `PHOENIX_API_KEY`, when set, is forwarded and never shown.

## Files

`core.py` (logic, tested by `test_console.py` on PyYAML alone) · `app.py` (FastAPI routes, including `/api/lake*`, `/api/config` and `/api/auth*`) · `static/index.html` (the page) · `run.sh` · `requirements.txt` (always-latest; carries the OpenTelemetry SDK + OTLP/HTTP exporter for `lake export`, and `httpx2` — starlette's TestClient dependency, without which the DNS-rebinding test cannot run).
