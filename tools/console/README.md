# Harness Console

The local control plane's **front end**: one service that lets you view, manage, orchestrate, and deploy the fleet's AI harnesses from a browser, using exactly the `tools/` entrypoints the CLI and CI run. The same page, built static, **is** the public site on GitHub Pages — https://bamr87.github.io/bamr87/ — where it reads a snapshot of this API instead of the API itself, and where a visitor can connect GitHub or a running console to get the write path back ([docs/CONSOLE-PAGES.md](../../docs/CONSOLE-PAGES.md); [docs/HARNESS-OPS.md](../../docs/HARNESS-OPS.md), "The two planes").

## Run it

```bash
tools/dash console              # native: bootstraps .venv-console (latest deps), serves http://127.0.0.1:4001
tools/dash console --docker     # the compose service (same devenv image, loopback port 4001)
docker compose up -d console    # same thing
CONSOLE_RELOAD=1 tools/dash console   # auto-reload while editing app.py / core.py
cd tools/console/web && npm run dev   # the page with hot reload on :5173, proxied to a running console
```

For the dev server's Terminal page, start the console with `DASH_CONSOLE_ALLOWED_ORIGINS=http://localhost:5173`, so the WebSocket admits that origin.

The console is the **runtime** of the local control plane, and this page is one of its two front ends. AI agents are a third, through the `fleet` MCP server ([`tools/fleetcore/mcp_server.py`](../fleetcore/README.md)), whose action tools go through this same job API and confirm gate. The terminal dash (`tools/dash tui`, `tools/tui/`) is the other human one: it reads the same views from [`tools/fleetcore/`](../fleetcore/README.md), binds the same keys (keys v1) in the same bashOS palette, and submits jobs to this process's API, so a job started in either one shows up in both. The page also runs the terminal dash itself, on its Terminal page. Under Docker the TUI reaches it over a Unix socket (`CONSOLE_UDS`, `serve.py`) in a volume only the `tui` service mounts, which keeps the DNS-rebinding allowlist loopback-only.

The console is one of the local stack's three services; `docker compose up -d phoenix` starts the trace store it links to (http://127.0.0.1:6006), and `tools/dash lake sync` fills the data lake the Traces page reads (see [docs/HARNESS-OPS.md](../../docs/HARNESS-OPS.md), "The local stack").

Credentials are inherited from the process environment (`gh auth login`, or `GH_TOKEN` / `FLEET_TOKEN` / the Claude tokens in `.env` for the compose service) — and, since 0.3, they can also be handed to the console **on the Credentials page** when it starts without them: a pasted value lives in this process's environment (which is exactly what a job inherits) and dies with the process, a GitHub token can instead go to `gh auth login --with-token` over stdin so the CLI's own store keeps it, and writing anything to the gitignored `.env` (mode 600) is a separate, explicitly confirmed step. Values are never returned, logged, or placed on a command line; every status document reports credential **names**, presence and provenance only. `DASH_CONSOLE_AUTH=off` refuses every credential write; set `DASH_CONSOLE_TOKEN` to require `Authorization: Bearer …` on the API when the console is reachable beyond localhost. Independently of that, the console answers only to loopback `Host` values: binding to 127.0.0.1 does not by itself stop a hostile page from resolving its own hostname to 127.0.0.1 (DNS rebinding) and then talking to this origin as same-origin, which on a console that can dispatch workflows and run `--apply` fan-outs is a real lever. Front it with another hostname by naming that hostname in `DASH_CONSOLE_ALLOWED_HOSTS` (comma-separated) — and set the token as well.

## The page

A React + TypeScript app on **Mantine** (app shell, Spotlight palette, modals, notifications), **TanStack Query** (one cache for every API document) and **React Router** (every view is a URL), built with Vite from [`web/`](web/README.md) into `web/dist/`, which `app.py` serves. `run.sh` rebuilds it whenever a source file is newer than the last build, at latest versions and without a lockfile, like the venv. Without `npm` the API still serves, and `/` says how to build the page.

Nine sections, each a group of pages, with a drill-down for every entity. Every repo name, operation, job, loop, site and config block is a link to its own page.

| Section | Pages | Drill-downs |
| --- | --- | --- |
| **Profile** | **Home** (who, the fleet's vital signs, featured projects, writing), **About**, **Experience**, **Portfolio** (every project as a card), **Writing**, **Services**, **Contact** | `/blog/:slug` — a post |
| **Overview** (`/overview`) | attention count, eight KPI tiles (each a link to the page that explains it), the ranked attention queue with each finding's lever, signal freshness with a refresh per source | a finding → its project; its lever → the operation or page |
| **Fleet** | **Projects** (the TUI's Apps view from `/api/fleet`, filtered and sorted by fleetcore on the server), **Inbox** (flagged items, filter by kind), **Roadmap**, **Features** (the fleet feature index), **Engagements** (the estimate/actuals ledger), **GitHub** (connect through the OAuth App; every repo the account sees; the action log), **Containers** | **`/projects/:name`** — everything joined on one project (`/api/project/:name`): health, CI, triage, open work, failing workflows, its harness workflows and crons, its runs and workflows in the lake, its content site, a live **GitHub** tab (below), and repo-scoped actions (deploy the kit, auth order, lake sync, evolution dispatch); `/github/:owner/:repo` — the same live view for any repo the account can see |
| **Harnesses** | **Inventory** (the deployment matrix, deploy to gap repos), **Health** (trip wires + scorecard), **Schedules** (caps, AI crons per UTC hour, the calendar), **Loops**, **Workflows** (the workflow atlas: every hub workflow and composite action, the standards as checks, run health with each failure classified from the lake, retirement candidates, and a designer that scaffolds a workflow inside the rules — [docs/WORKFLOW-ATLAS.md](../../docs/WORKFLOW-ATLAS.md)), **Work board** (every open issue, PR, roadmap spec, spec package and backlog item on six lanes, in the order the loops take them; drag to reorder, move and reprioritise; throughput per loop) | `/workflows/:id` — triggers and their fleet.yml keys, jobs, the actions it stands on, Claude call sites, findings, its runs and why they failed, and a dispatch form typed from its own inputs; `/workflows/actions/:id` — inputs, outputs, callers; `/loops/:id` — schedule, committed outputs and their freshness, the local-half operations, a CI dispatch, the loop's jobs; `/work?item=<key>` — an item's drawer: issue gaps and thread, the spec packages a PR changes read at its head, the roadmap entry, a spec's tasks and open questions, a BACKLOG.md line |
| **Spend** | **Costs** (Claude spend and Actions minutes vs budget), **Agent activity** (`/api/lake/review`: local sessions + CI agent runs, findings, cost by repo, tool use) | repos → their project's Runs tab; runs → GitHub |
| **Observe** | **Traces** (the lake + Phoenix: sync, extract sessions, export), **Lines** (every workflow with provenance and kill switch), **Logs** (Kibana), **Metrics** (Grafana), **Code index** (Qdrant search + harmonize + coverage) | a plane that is not running renders as an invitation to start it |
| **Content** | **Content sites** (the atlas) | `/content/:site` — plan (narrative, pillar targets, add a pillar), suggestions (approve / reject), directives (move, add, file as issues — dry run, then confirm-gated apply), activity charts, documents. Every write goes to `_data/editorial.yml` in the working tree and shows its diff |
| **Operate** | **Jobs**, **Operations** (the allowlist, grouped), **Toolbox** (scripts, skills, kits), **Terminal** | `/jobs/:id` — live log, cancel, run again with the same parameters; `/ops/:id` — the parameter form, the loops it belongs to, its jobs |
| **Settings** | **Config** (`_data/fleet.yml`, one top-level block per page: `/config/:section`), **Connect** (on the public build: a GitHub token or a console), **Credentials** (this console's credentials, gh login, the token contract and ages, rotate from `.env`, Anthropic API keys, AI auth order) | — |

Running an operation works the same from any button, form or palette pick. A GitHub-writing operation says in plain words what it will do and asks first (the server refuses a write without `confirm=true` anyway). The job then opens in a side drawer on its live log, so the page you were on stays put. A job that succeeds refreshes every document, because its output is new data in the working tree.

**Jobs keep their history.** The index (`jobs.json`) and every job's log live in `DASH_CONSOLE_JOBS` — under Docker the `console-run` volume, so a restart or a recreated container keeps them; a job that was running when the process died comes back `interrupted`. Jobs past the newest 200 are dropped with their logs, and **Clear finished** / **Clear failed** on the Jobs page (`DELETE /api/jobs?status=…`) forget finished jobs and delete their logs — never a running one. The page groups the list two ways: every run, newest first, filtered by status, operation group and text; or **By operation**, one row per operation with its latest result, run count and success rate. Two guards stop jobs that cannot succeed: the **lake writers** (`lake-sync`, `lake-sessions`, `lake-export`, `observe-ship`, `content-sync` — `exclusive="lake"`) run one at a time, a second answering 409 with the job that holds the lake rather than dying on `database is locked`; and **Docker-backed** operations (`observe-up`/`down`/`reset`) report themselves unavailable when this process has no `docker compose` and daemon — the case in the console's own container, which is never given the socket — with the host command to run instead. Test files point `DASH_CONSOLE_JOBS` at a temp dir before importing the console, because importing `app` builds a job manager on whatever directory that names.

### GitHub, through the console's OAuth App

The **GitHub** page connects the console to GitHub through an [OAuth App](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps) you register once (`github_link.py`):

1. Create the app at github.com/settings/applications/new. Set the callback URL to `http://127.0.0.1/api/github/oauth/callback` (GitHub accepts a loopback callback on any port), and tick **Enable Device Flow**.
2. Give the console its client ID, and optionally its secret, as `GITHUB_OAUTH_CLIENT_ID` and `GITHUB_OAUTH_CLIENT_SECRET`. Paste them on the GitHub page, set them on the Credentials page, or put them in `.env` (compose passes both through).
3. Press **Connect**.

| Flow | Needs | How it goes |
| --- | --- | --- |
| **Device code** (default) | the client ID | GitHub shows a short code; you type it at github.com/login/device and the console polls for the token, at most once per GitHub's interval. Works natively, in Docker and over SSH |
| **Browser redirect** | ID + secret | GitHub's authorize page, back to `/api/github/oauth/callback`. A single-use `state` minted by an authenticated request, plus PKCE (S256), protects the return. The callback cannot carry the console's bearer token, so the state is its guard |

The token never reaches the page. It goes where you chose: **this console session** (`GH_TOKEN`, inherited by every job, gone when the console stops), **the gh CLI's login** (`gh auth login --with-token` over stdin), or **the session plus `.env`** (explicit confirm). The console then acts as that account. It resolves its identity the way `gh` does (`GH_TOKEN`, then `GITHUB_TOKEN`, then gh's stored login), so the page, the jobs and the terminal dash agree. **Disconnect** clears the session token and, when the secret is known, revokes it at GitHub.

Repo management reads every repo the account can see, and **writes only to fleet repos the hub owns**: the registry's repos under the hub's owner, plus `hub.repo` and `hub.shared`. An external mirror such as `microsoft/skills` stays read-only. The writes are:

- **Issues:** open, comment, close (completed or not planned), reopen, add and remove labels.
- **Pull requests:** comment and label. The console never merges.
- **Runs:** re-run failed jobs, cancel.
- **Workflows:** enable and disable.

Each write states what it will do and asks first, and the server refuses one without `confirm=true`. Each is recorded in the action log on the GitHub page. Nothing merges, deletes, pushes or changes repo settings. `DASH_CONSOLE_GITHUB_WRITES=off` makes the surface read-only, and `DASH_CONSOLE_AUTH=off` also refuses connecting.

### The Work board

**Harnesses → Work board** (`/work`, [docs/WORK-BOARD.md](../../docs/WORK-BOARD.md)) puts every open item in the fleet on six lanes (triage, ready, in flight, review, blocked, on hold), in the order the loops will take them, and marks what each loop's next run takes. Dragging stages a plan: within a lane it pins the order, across lanes it moves an issue (its `agent:` labels) or a roadmap spec (its `status:`), and across the P0–P3 columns it reprioritises. `POST /api/work/preview` redraws the board as the plan would leave it, cut lines and throughput included. **Apply** (`POST /api/work/apply`) asks once, then moves the labels through the same GitHub write path as the GitHub page (`issue.labels`: fleet-scoped, confirm-gated, logged). It writes `_data/work_queue.yml` and the `roadmap.yml` lines in the working tree, returns the diff, and commits nothing. A PR, a spec package and a `BACKLOG.md` item can be pinned and reprioritised but not moved, because their state belongs to the PR, `spec.md` and the append-only backlog. Spec packages and backlog items are read from submodule checkouts, so the public snapshot's board is read-only and has neither.

### Per-project health on startup

`_data/project_health.yml` is gitignored and only `dash-gen health` writes it, so a fresh clone used to show blank health and red/amber/green 0/0/0. On startup the console checks it (with `_data/project_health_meta.yml`) and, when it is missing, undated, or older than `harness.trip_wires.stale_data_days`, starts the allowlisted **health** operation as an ordinary job. The job shows on the Jobs page and runs in the background. It is cancelled after `CONSOLE_AUTO_HEALTH_TIMEOUT` seconds (default 300). It needs a GitHub token like the manual operation does; without one it fails and the page stays as before. `CONSOLE_AUTO_HEALTH=0` turns it off.

### The terminal dash, inside the page

**Operate → Terminal** runs the real terminal dash (`tools/tui/app.py`, Textual), not a re-implementation. `tui_bridge.py` starts it on a pseudo-terminal and relays it over the `/api/tui` WebSocket, and xterm.js draws it in the TUI's own bashOS dark palette (`/api/theme`). It joins this process's runtime (`DASH_CONSOLE_URL` points back here), so a job its `:` palette starts appears on the Jobs page, behind the same allowlist and confirm gate. Its `o` / `l` keys open links in a new tab of *this* browser through a private OSC sequence, rather than on the machine running the console. At most `CONSOLE_TUI_MAX` (default 4) sessions run at once, and closing the page hangs up the session's whole process group.

No HTTP middleware sees a WebSocket handshake, and CORS does not apply to one, so the bridge makes its own checks before any process exists:

- the **Host** allowlist, repeated from the HTTP guard;
- the **Origin** must be this console's own page, which stops cross-site WebSocket hijacking (add a dev origin with `DASH_CONSOLE_ALLOWED_ORIGINS`);
- when `DASH_CONSOLE_TOKEN` is set, the first frame must carry it, because a browser cannot put a bearer token on a WebSocket.

## The public site

`build-pages.sh` builds this page a second way — base `/bamr87/`, `VITE_STATIC=1` — and `snapshot.py` writes every GET document the page reads as a file beside it, rendered by the same functions the routes above call. That is what `build-dash.yml` publishes. It also adds the profile: Home, About, Experience, Portfolio, Writing, Services and Contact (`site_docs.py`, from `_data/profile.yml` and `pages/`), served here too at `/api/site*` and `/api/data/{name}`.

On that page, `/connect` lets a visitor add:

- **A GitHub token.** The page then makes this console's GitHub writes and workflow dispatches itself, from the browser, under the same rules.
- **This console's URL and token.** `remote_page` answers CORS for `https://bamr87.github.io` (`DASH_CONSOLE_PAGES_ORIGIN`) only while `DASH_CONSOLE_TOKEN` is set, and the Terminal page's WebSocket follows the same rule. That origin is every Pages site the account has, so the token is what tells this one apart.

The snapshot never carries the lake, a credential (not even its presence), a local probe, a local path or a draft; `test_pages.py` holds each of those. `/diagrams/<name>.html` serves the archify diagrams the Harness health page embeds, sandboxed.

## Keys

keys v1, from `/api/keys` ([`tools/fleetcore/keys.py`](../fleetcore/keys.py)), the table the TUI binds:

- `?` shows the sheet, and `:` (or ⌘K) opens the palette: every page, project, loop, content site, config block and operation.
- `/` focuses the page's search box, `esc` goes back, `1`–`9` jump to a section (1 is the profile), and `]` / `[` step through the pages.
- On a list, `j` / `k` / `g` / `G` move, `enter` opens the row's drill-down, `o` / `l` / `y` open the repo, open the live site, or copy the link, and `s` cycles the sort.
- `r` re-reads every document and `R` runs the live health refresh.
- Typing in a field, holding ctrl/⌘/alt, or focus inside the terminal leaves the key alone.

## What it refuses to do

- Run anything outside the allowlist in `core.py` (`OPS`): parameters are validated by regex/range and become argv elements, never a shell string. The Terminal page runs exactly one program, the terminal dash, and that program submits its jobs through the same allowlist.
- Write to GitHub without an explicit confirm (`apply`, `dispatch`) — and only one such job runs at a time.
- Write to a repo the hub does not own, or merge, delete or push through its GitHub page. Its GitHub writes are issues, runs and workflows, each confirmed and logged.
- Commit, push, or merge. Generated data lands in the working tree; you review it in git.
- Invent contract structure. The Config form edits declared keys only: a key `fleet.yml` does not already carry is shown read-only, and the policy keys the file itself calls non-negotiable (`rotation.hub_first`, `issue_pipeline.autonomy.never_merge`) are not offered at all.
- Hand a credential back. Values go in; names, presence and provenance come out. A token pasted for `gh` travels on stdin, and `.env` is written only on an explicit confirm — never if git tracks it.
- Publish the lake. `.dash-lake/` is gitignored (it holds run logs); traces go only to the Phoenix endpoint you configured, and `PHOENIX_API_KEY`, when set, is forwarded and never shown.

## Files

`core.py` (logic, tested by `test_console.py` on PyYAML alone) · `github_link.py` (the OAuth App flows and fleet repo management, stdlib HTTP only) · `tui_bridge.py` (the Terminal page's pty-over-WebSocket bridge and its handshake checks) · `serve.py` (TCP + Unix socket, one process) · `app.py` (FastAPI routes, the CSP, and the page fallback) · `web/` (the page: React + Mantine, built to `web/dist/`) · `run.sh` · `requirements.txt` (always-latest; carries the OpenTelemetry SDK + OTLP/HTTP exporter for `lake export`, `websockets` for `/api/tui`, the TUI's own requirements, and `httpx2`, starlette's TestClient dependency, without which the DNS-rebinding test cannot run). `design-system/` is the React package of the console's earlier hand-written look, kept for the Claude Design sync.

The page's policy is `script-src 'self'`: the bundle has no inline script, so an injected `<script>` cannot run. Styles allow `'unsafe-inline'` because Mantine and xterm.js set style attributes. `/docs` keeps the narrow frame policy because Swagger UI boots inline from a CDN.
