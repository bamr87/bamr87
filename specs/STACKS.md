# Stack profiles and the applicability matrix

> The fleet's stack families, the canonical toolchain for each, the layout an agent should expect, and which UPS areas bind. A repo can be several kinds.

Kinds: `site` (static/Jekyll/MkDocs), `app` (browser or server-rendered UI), `api` (HTTP service), `lib` (published package), `cli` (command-line tool), `ext` (VS Code extension), `content` (markdown/knowledge/data), `fork` (upstream mirror).

## Applicability matrix

| Area | site | app | api | lib | cli | ext | content | fork |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| REPO | ● | ● | ● | ● | ● | ● | ● (10–13, 17 only) | ○ (what bamr87 adds) |
| AGENT | ● | ● | ● | ● | ● | ● | ● (01–06) | ○ |
| QA | ● | ● | ● | ● | ● | ● | 05, 30–34, 40 | ○ |
| FE | ● | ● | — | — | — | ● (tokens, contract, a11y) | — | — |
| FB | ● | ● | — | — | — | ● (inline, proxy) | — | — |
| BE | — | ● (client, 40–43) | ● | — | — | — | — | — |
| OPS | 03, 33, 40 | ● | ● | 12, 20 | ● (01–03, 10, 12) | 12, 20, 23 | 33 | — |

● all rows for that kind · ○ only for bamr87-added surfaces · — none

## Profiles

### Jekyll site (`site`) — 11 repos

Reference: `zer0-mistakes` (theme), consumers via `remote_theme: bamr87/zer0-mistakes`.

| Aspect | Canonical |
| --- | --- |
| Toolchain | Ruby `3.3` (fleet.yml), `github-pages` gem, Bootstrap 5.3 vendored by the theme |
| Layout | `_config.yml`, `pages/{_posts,_docs,_pages,…}` collections, `_data/`, `assets/{css,js,images}`, `_includes/custom/` (the only theme override seam), `tools/`, `docs/` |
| Required config | `repository`, `branch`, `title`, `description`, `url`/`baseurl`, `page_feedback.enabled: true`, `color_mode_default`, `posthog`/`giscus` blocks as used |
| CI | `standard-ci` (build + htmlproofer) or the theme's own; `markdown-oneline`; Pages deploy |
| Tests | `--strict_front_matter`, htmlproofer; theme repos add Playwright visual |
| Feedback | theme widget (FB-31 makes it work on consumers) |
| Release | release-please `simple` |

### React / Vite app (`app`) — cv-builder-pro, gitorio, aieo/frontend, edgar/fredgar frontend, ai-seed

| Aspect | Canonical |
| --- | --- |
| Toolchain | Node `20` (fleet.yml), Vite latest, React 19, TypeScript strict, Tailwind 4 (`@theme` ← tokens), vitest + Testing Library, Playwright |
| Layout | `src/{app,components/{ui,…},lib/{http,toast},pages\|routes,styles/tokens.css,state}`, `tests/` or colocated, `public/`, `index.html` |
| Shell | `AppShell` (FE-10) mounting skip link, theme toggle, `<FeedbackButton>`, `<Toaster>`, `ErrorBoundary`, `NotFound` route |
| Client | `lib/http.ts` per BE-40; TanStack Query |
| Forms | react-hook-form + zod |
| CI | `standard-ci` (Node branch) or shared active gate; UX audit; Lighthouse |
| Release | release-please `node` |

### Next.js app (`app`) — law-ai/frontend

As React/Vite, plus: App Router, `app/{layout,not-found,(app)/{loading,error}}.tsx` route states, `Metadata` export for FE-25, `ui/base.css` token file. Reference for the UX audit gate.

### Django app / API (`app` + `api`) — djangoerp, barodybroject, edgar/fredgar backend, amrs-project (retire)

| Aspect | Canonical |
| --- | --- |
| Toolchain | Python `3.12`, Django latest, DRF + drf-spectacular, pytest-django, ruff |
| Layout | `src/<project>/` or `<project>/` apps, `templates/base.html` (FE shell, `{% block meta %}`, feedback snippet, `data-bs-theme`), `static/tokens.css`, `tests/`, `pyproject.toml` |
| API | `/api/v1/`, envelope middleware, `/healthz` `/readyz` `/version`, OpenAPI committed |
| Data | Postgres via `DATABASE_URL`; migrations in CI |
| CI | shared active gate; `pytest --cov` |
| Release | release-please `python` |

### FastAPI service (`api`) — aieo/backend, wtd

As Django for ops/API rows; layout `app/{main,api/v1,core/{settings,logging},models,schemas}`, pydantic-settings, `tests/`.

### Rails app (`app`) — zer0-image-generator/web

Rails 8, Turbo/Stimulus, `app/views/layouts/application.html.erb` as the shell (breadcrumbs, flash → toast, feedback snippet), PWA manifest already present; lograge for OPS-10; release-please `ruby` for the gem.

### Python library / CLI (`lib`, `cli`) — README, ai-seed, books, githubai, lawmode, wtd, scripts (bash)

| Aspect | Canonical |
| --- | --- |
| Toolchain | Python `3.12`, `pyproject.toml` (PEP 621), ruff, pytest in `[tool.pytest.ini_options]`, `typer`/`click` for CLIs, `src/` layout |
| Layout | `src/<pkg>/`, `tests/`, `docs/` (MkDocs when a site is wanted), `tools/` |
| CLI UX | `--help` for every command, `--json` output for machine use, exit codes 0/1/2, no interactive prompts under `CI=true` |
| Release | release-please `python`; publish to PyPI via the shared `publish.yml` |

### Bash tooling (`cli`) — scripts, bashcrawl

`set -euo pipefail`, shellcheck-clean, house header, `tools/` layout, `bats` for tests where any exist, release-please `simple`.

### VS Code extension (`ext`) — zpl-viewer, vs-sonic-pi, zer0-cms (= vscode-front-matter), csv-vscoode, lawmode/vscode-extension

| Aspect | Canonical |
| --- | --- |
| Toolchain | Node `20`, TypeScript strict, **esbuild** bundle, **vitest** units, `@vscode/test-electron` integration, ESLint flat, Prettier, `engines.vscode` floor `^1.90` |
| Layout | `src/{extension.ts,commands,webview/{shared/dom.ts,…}}`, `media/{tokens.css,base.css,…}`, `tests/`, `package.json` contributes |
| Webview | `tokens.css` is the only file naming `--vscode-*` (CI grep), strict CSP with nonce, `color-scheme: light dark`, inline feedback trigger in `proxy` mode via the extension host |
| Release | release-please `node` + `vsce`/`ovsx` publish |

### Ruby gem (`lib`) — zer0-mistakes, zer0-image-generator

`gemspec`, `test/` (grandfathered), rubocop, release-please `ruby`, publish to RubyGems.

### Content / knowledge (`content`) — 1987, 2005, books/library, cv, zer0-pages, wargames

README, LICENSE (MIT or CC-BY-4.0), `.editorconfig`, `CLAUDE.md`, markdown-oneline gate, front matter per FE-40 when rendered by a site, no build/tests expected. `cv` additionally carries the `CVData` contract (BE-32).

### Fork (`fork`) — skills, skills-github-pages, wargames upstream

Rely on upstream; standardize only bamr87-added surfaces; never fan out kits without `--force-external`.

## Registry mapping (2026-09-01)

| Kind | Repos |
| --- | --- |
| site | 2005, bamr87.github.io, bashconsultants, drsai, it-journey, lifehacker.dev, wargames, zer0-mistakes, zer0-pages, zer0-pages-remote, skills-github-pages (fork), README (MkDocs), ai-seed (MkDocs) |
| app | cv-builder-pro, gitorio, aieo, edgar-data-parse (≡ fredgar-ai), law-ai, barodybroject, djangoerp, amrs-project, zer0-image-generator/web, ai-seed/src/frontend, books (studio) |
| api | aieo/backend, wtd, djangoerp, barodybroject, edgar-data-parse/backend, law-ai/backend, githubai (worker) |
| lib | zer0-mistakes (gem), zer0-image-generator (gem), README, ai-seed, githubai |
| cli | scripts, bashcrawl, books, lawmode, wtd, cv (builder) |
| ext | zpl-viewer, vs-sonic-pi, zer0-cms (≡ vscode-front-matter), csv-vscoode, lawmode/vscode-extension |
| content | 1987, 2005, books/library, cv, zer0-pages |
| fork | skills, skills-github-pages, wargames (content mirror) |
