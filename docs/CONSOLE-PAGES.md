# The public site is the console

> The public site is the Harness Console built static: the API snapshot it reads, connecting GitHub or a running console from the page, and what is never published.

`https://bamr87.github.io/bamr87/` is the Harness Console's own page, built static. It used to be a separate Jekyll site with its own boards. Since 2026-10 it is one React app (`tools/console/web/`) built two ways:

| Build | Served by | Data comes from | Base |
| --- | --- | --- | --- |
| **Console** | `tools/dash console` (FastAPI, 127.0.0.1:4001) | the console's live `/api` | `/` |
| **Public** | GitHub Pages (`build-dash.yml`) | a snapshot of the same `/api` documents, written at build time | `/bamr87/` |

The two builds show the same pages: the profile (Home, About, Experience, Portfolio, Writing, Services, Contact) and every console section (Overview, Fleet, Harnesses, Spend, Observe, Content, Operate, Settings).

## The three modes of the public page

`web/src/api/backend.ts` decides which backend answers. Pages call `api('/api/…')` and do not need to know which one did.

| Mode | When | What the page can do |
| --- | --- | --- |
| **Snapshot** | the default for every visitor | read everything the build published; nothing writes |
| **Snapshot + GitHub** | a GitHub token is pasted on **Connect** | everything above, plus live repo views and the console's GitHub writes (issues, PR conversations, re-run or cancel runs, enable or disable workflows) and **dispatching the control-plane workflows** — straight from the browser to `api.github.com` (`web/src/api/ghdirect.ts`) |
| **Remote console** | a console URL and its token are given on **Connect** | everything the console can do: run any operation with a live log, edit `_data/fleet.yml`, manage credentials, read the data lake, open the terminal dash |

The GitHub mode applies the console's own rules, read from the snapshot (`github/fleet.json`, written by the same `github_link.fleet_repos()` and `core.DISPATCHABLE`): the same nine write actions and the same validation. It writes only to fleet repos the hub owns. Every write asks for confirmation first and is recorded in the tab's action log. It can dispatch only the allowlisted workflows, with only the inputs each one declares. A dispatched workflow shows up on **Jobs**, and its steps stream in as the log.

The token stays in the tab (sessionStorage) unless the visitor ticks *Remember on this device*, and it is sent only to `api.github.com`. Use a [fine-grained token](https://github.com/settings/personal-access-tokens/new) scoped to the fleet repos, with **Actions**, **Issues** and **Pull requests** read/write and **Contents** and **Metadata** read. The OAuth App flows stay console-only, because GitHub's OAuth endpoints do not answer a browser (no CORS).

## Connecting the public page to a console

```bash
DASH_CONSOLE_TOKEN=$(openssl rand -hex 24) tools/dash console
# open https://bamr87.github.io/bamr87/connect, paste http://127.0.0.1:4001 and the token
```

`app.py` (`remote_page`) answers CORS for `https://bamr87.github.io` (`DASH_CONSOLE_PAGES_ORIGIN` to change it, empty to switch it off; `DASH_CONSOLE_ALLOWED_ORIGINS` adds more). It answers only while the console requires its token. That origin is shared by every Pages site the account publishes, not only this one, so the token is what tells this page apart from the others. Without a token the console answers the preflight (including Chrome's Private Network Access opt-in) and then refuses the request with a reason the page can show. The terminal's WebSocket (`tui_bridge.py`) admits the origin under the same rule.

Chrome and Firefox let an `https://` page reach `http://127.0.0.1`. Safari does not, so open the console directly there.

## What the snapshot publishes, and what it never does

`tools/console/snapshot.py` writes `<out>/snapshot/<path>.json` for each GET document the page reads, at the path the API would serve it from (`/api/state` → `snapshot/state.json`). It renders them with the functions `app.py` routes to (`core`, `fleetcore`, `site_docs`, `github_link`). The parameterised views are the exceptions:

- `fleet/<sort>.json` is one file per sort key. The page applies `q` and `health` with fleetcore's own predicate.
- `project/<name>.json` is one file per registry project.

The snapshot never publishes, whatever the build machine holds (`test_pages.py` asserts each of these):

- the local data lake (core is pointed at an empty lake before it is imported)
- the probes of local services (Phoenix, Kibana, Grafana, Qdrant, Docker)
- credentials, including their presence (no `auth` document is written)
- absolute paths of the build machine
- draft posts (`draft: true`)

Beside the documents it writes:

- one `index.html` per route, with its own title, description, canonical link and Open Graph tags, so a deep link returns 200
- `404.html`
- `sitemap.xml`, `feed.xml` (Atom) and `robots.txt`
- `theme.css`
- `manifest.json` (when, from which commit, by which run)

`build-dash.yml` then adds the machine API (`dash-gen machine-api`: `/api/v1/*.json`, `llms.txt`).

## Content

| What | Where |
| --- | --- |
| Identity (name, title, links, avatar) | `_data/profile.yml` |
| Long-form pages | `pages/profile/<slug>.md`, routed at `/<slug>`; the four in `nav.ts` `PROFILE_PAGES` |
| Posts | `pages/posts/YYYY-MM-DD-<slug>.md`, at `/blog/<slug>`; `draft: true` shows only on a console |
| Registries the pages read | `site_docs.PUBLIC_DATA` — the only `_data` files served at `/api/data/<name>` |

Markdown is rendered in the browser with `marked` and sanitized with DOMPurify. The public build also carries a Content-Security-Policy `<meta>`, because Pages cannot send headers: no inline script, network access only to itself, `api.github.com` and a console.

## The retired Jekyll URLs

`web/src/lib/legacy.ts` redirects each old board to the page that replaced it, and the build writes a stub for each so the old link returns 200 first:

| Old | New |
| --- | --- |
| `/dashboard/`, `/monitor/` | `/projects` |
| `/cockpit/`, `/actions/`, `/ai-usage/` | `/costs` (attribution tables included) |
| `/ai-activity/` | `/activity` |
| `/triage/` | `/inbox` |
| `/harness/` | `/harnesses/health` |
| `/issue-pipeline/` | `/loops/issue_pipeline` |
| `/docker/` | `/containers` (the recorded Docker view) |
| `/resume/` | `/experience` |
| `/docs/` | `/portfolio` |

## Build it

```bash
tools/console/build-pages.sh                 # what CI publishes → tools/console/web/dist-pages (base /bamr87/)
tools/dash serve                             # the same at the root, served on http://127.0.0.1:4000
python3 tools/console/test_pages.py          # the snapshot's guarantees + the remote-page door
node verify/runner.mjs                       # the user scenarios (verify/verify.yml builds at the root)
```
