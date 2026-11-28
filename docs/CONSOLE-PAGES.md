# The public site is the console

> The public site is the Harness Console built static: the API snapshot it reads, connecting GitHub or a running console from the page, and what is never published.

`https://bamr87.github.io/bamr87/` is the Harness Console's own page, built static. It used to be a separate Jekyll site with its own boards. Since 2026-10 it is one React app (`tools/console/web/`) built two ways:

| Build | Served by | Data comes from | Base |
| --- | --- | --- | --- |
| **Console** | `tools/dash console` (FastAPI, with the Django backend beside it on `/admin/` and `/api/v1/`; 127.0.0.1:4001) | the console's live `/api` | `/` |
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

- one `index.html` per route, with its own title, description, canonical link and Open Graph tags, so a deep link returns 200; every page's card image is the profile's wide `site.image` (a large card), or the avatar when none is set
- `404.html`
- `sitemap.xml`, `feed.xml` (Atom) and `robots.txt`
- `theme.css`
- `manifest.json` (when, from which commit, by which run)

`build-dash.yml` then adds the machine API (`dash-gen machine-api`: `/api/v1/*.json`, `llms.txt`).

## Content

| What | Where |
| --- | --- |
| Identity (name, title, links, avatar), the Home description and the link-card image (`site.description`, `site.image`) | `_data/profile.yml`; images under `tools/console/web/public/` |
| Long-form pages | `pages/profile/<slug>.md`, routed at `/<slug>`; the four in `nav.ts` `PROFILE_PAGES` |
| Posts | `pages/posts/YYYY-MM-DD-<slug>.md`, at `/blog/<slug>`; a series entry (`site_docs.SERIES`: the daily chronicle, the weekly retro) and a slug two files share are at `/blog/YYYY-MM-DD-<slug>`; the excerpt is `excerpt`, else `description`, else the first paragraph; `draft: true` shows only on a console (layout: `pages/SCHEMA.md`) |
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

## Site builds: the same console at another address

The console can be published more than once. `_data/profile.yml` `site:` is the site this page has always been; `sites:` beside it declares the others, and `CONSOLE_SITE=<key>` builds one. A site build is the same app and the same documents with that entry laid over `site:`, so its identity is a setting and not a line of code ([ADR 0011](adr/0011-one-framework-many-instances.md)). Built without `CONSOLE_SITE`, nothing changes: `sites:` is build configuration and is never part of a published document.

| Setting (`sites.<key>.`) | What it decides | Read by |
| --- | --- | --- |
| `title`, `name`, `description`, `image` | the header brand, every page's title and link card, who the site is by | `site_docs.site_settings` into the site document and `snapshot.py`'s pages |
| `url` | the default `SITE_URL`; its path is the default `CONSOLE_BASE` | `build-pages.sh` |
| `mark` | the tab icon and the header mark, a file in `tools/console/web/public/` | compiled in (`VITE_SITE_MARK`) |
| `front_door` | what `/` is: `home` (the profile) or `desktop` (the bashOS desktop; the profile Home moves to `/home`) | compiled in (`VITE_FRONT_DOOR`): the routes exist before any document is read |
| `desktop.icons` | `apps`: an icon per framed frontend; `repos`: an icon for every repo, its frontend where it has one and the generated repo app where it has not | the Desktop page, from the site document |
| `desktop.pinned` | registry ids shown first on the desktop and offered on its Welcome window; an id the registry does not declare is dropped | the Desktop page |
| `desktop.welcome` | the Welcome window's first paragraph | the Desktop page |

`site_docs.py` checks an entry when it is built: a site the file does not declare, a front door or icon set that does not exist, and a mark that is not a file of `web/public/` stop the build.

A site build differs from the default build in four ways, and only these:

- **Identity.** Its title, mark, description and link card on every page; `snapshot/manifest.json` names the site.
- **Front door.** With `front_door: desktop`, `/` is the desktop and the profile Home is at `/home` (one more page in the build and the sitemap). `/desktop` still answers. The desktop shows the site's title and mark, a search button that opens the palette, and a **Profile** icon. The start menu, the palette and the classic console reach every other page, and the classic console's brand leads back to the desktop.
- **Every repo is an icon.** With `desktop.icons: repos` the dock is grouped (the pinned apps, the framed frontends, the repos that open as the repo app, then Fleet, Profile and Console) and scrolls, so it stays three columns wide. At a phone's width the same groups are the home screen.
- **Frames.** The public page's policy is a `<meta>`, and by default it allows same-origin frames only. A site build also names the launcher's origins, one by one (`fleetcore.apps.target_origins`, the list the console's own policy sends; ADR 0005, decision 4), so its desktop can frame the fleet's live sites. Never a wildcard: admitting an origin is still a registry change. Only an `https://` origin, or plain `http://` to loopback (`127.0.0.1` or `localhost`, any port), is admitted (`web/src/lib/frameOrigin.ts`); any other origin is dropped from `frame-src` and the build prints `frame-src: dropped <origin>`, because a cleartext frame of another host could be rewritten on the wire.

### bash-365: the platform's front door

`sites.bash-365` is the first one: the console as the front door of the bash-365 platform, with the BASH Consulting site (the `bash-365.com` registry entry) pinned as its first app and framed from the live site.

```bash
CONSOLE_SITE=bash-365 tools/console/build-pages.sh    # → tools/console/web/dist-pages, base and URL from sites.bash-365.url
CONSOLE_SITE=bash-365 tools/dash serve                # the same at the root of http://127.0.0.1:4000
node verify/runner.mjs --scenarios verify/sites --base http://127.0.0.1:4000   # its user scenario (verify/sites/site-front-door.yml)
```

The live site can be framed. Measured 2026-11-20: `https://www.bash-365.com/` (Azure Static Web Apps) answers 200 with neither `X-Frame-Options` nor a `frame-ancestors` policy, and `staticwebapp.config.json` in bash-365/bash-365.com sets no `globalHeaders`, so nothing in that repo blocks a frame (ADR 0005, level L1). What does block it on the default public build is this page's own `frame-src 'self'`, which a site build widens as described above. Evidence: `test/evidence/site-front-door/`.

It is served from Azure Static Web Apps, at its own subdomain (`sites.bash-365.url`, `https://os.bash-365.com`). `build-dash.yml` builds it on every run, beside the default build, and its `deploy-portal` job publishes it from `main` while `vars.PORTAL_DEPLOY_ENABLED` is `true`. The job signs in with OIDC and holds a role on that one app, so no secret is stored. The resources are Bicep in [`infra/azure/portal/`](../infra/azure/portal/README.md); the maintainer creates them, adds the DNS record and switches the deploy on, as its runbook says. Response headers come from `infra/azure/portal/staticwebapp.config.json`: the portal is `noindex` while the Jekyll site at www.bash-365.com stays the one search engines read.

A subdomain rather than a path of the main domain, because:

- **A subdomain** (an origin of its own) keeps every fleet app, the BASH site included, cross-origin to the shell. Each is framed with its own storage and cannot read the shell's.
- **A path of the main domain** makes the BASH site same-origin with the shell. The shell then frames it isolated (no `allow-same-origin`), where the zer0 theme's scripts throw on `localStorage` (ADR 0005, "Measured in this change"), and the shell's own stored settings share an origin with every script the Jekyll site loads.

To connect such a page to a running console, name its origin in `DASH_CONSOLE_PAGES_ORIGIN` or `DASH_CONSOLE_ALLOWED_ORIGINS`, as for the default page.

Not built yet: BASH content rendered natively in a window (link previews, glossary tooltips, what a page connects to). A window holds a frame of the live site today; the scene and the per-window view are where that goes.

## Build it

```bash
tools/console/build-pages.sh                 # what CI publishes → tools/console/web/dist-pages (base /bamr87/)
CONSOLE_SITE=bash-365 tools/console/build-pages.sh   # another site of the same console (see "Site builds")
tools/dash serve                             # the same at the root, served on http://127.0.0.1:4000
python3 tools/console/test_pages.py          # the snapshot's guarantees + the remote-page door
node verify/runner.mjs                       # the user scenarios (verify/verify.yml builds at the root)
```
