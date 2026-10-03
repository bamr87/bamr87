# Docs System — one source, four renderers

> **Status: PLAN (2026-10-03).** Nothing below is built yet. This document proposes how every fleet repo gets a Jekyll, MkDocs, Sphinx and Wiki.js variant of its documentation. Each variant is chosen for what it does best, and none becomes a second copy of the content to keep in sync by hand. Once adopted, its requirement rows move into `specs/DOCS.md` (area `DOC`) and this file becomes the operator doc for the machinery.

## The decision in one paragraph

Four hand-maintained doc sites per repo across ~40 repos would be ~160 sites, and they would drift apart in a week. So **a "variant" is a build target, not a content tree.** Each repo writes its docs once, as portable Markdown under `docs/`, with a front-matter contract and one nav manifest (`docs/docs.yml`). A vendored engine (`docs_engine.py`) renders that source four ways: Jekyll, an `mkdocs.yml` site (built by Zensical or MkDocs-Material), Sphinx via MyST, and a Wiki.js export. Each repo declares one **primary** engine, chosen by stack kind. The primary is the one deployed to the repo's single Pages surface, which UPS-OPS-40 requires. The other engines are **secondaries**. CI builds them to prove the source stays portable, the fleet aggregators consume them, and they can be previewed locally on demand. Wiki.js is not a static site generator, so it is never per-repo. There is one central instance, and each repo is a read-only namespace inside it.

## What exists today (survey, 2026-10-03)

The survey used blob-less clones of every `.gitmodules` entry: 26 public repos were read and 13 private repos could not be reached from the survey session. Engine detection used `_config.yml`, `mkdocs.yml`, `docs/**/conf.py`, Wiki.js compose wiring, and `docs/**/*.md` counts.

| Engine | Where it runs now | Notes |
| --- | --- | --- |
| **Jekyll** (zer0-mistakes theme) | 2005, bamr87.github.io, bashconsultants, irony-works, it-journey, lifehacker.dev, wargames, zer0-mistakes, zer0-pages (+ private: zer0-pages-remote, drsai) and the hub | The design-system reference. Authored product docs live in `pages/_docs/` (zer0-mistakes 95, zer0-pages 104, lifehacker.dev 65, bamr87.github.io 23). |
| **MkDocs** (Material) | README (the fleet aggregator, ~3.2k aggregated pages), ai-seed | zer0-CMS ships MkDocs *fixtures*: the CMS already understands Jekyll and MkDocs sites. The hub's own `mkdocs.yml` was deleted as a stale fork. |
| **Sphinx** | barodybroject only (`src/parodynews/docs/source/`, 57 `.rst`, autodoc against Django settings) | It is the fleet's only reStructuredText. |
| **Wiki.js** | Hub `wiki` service (`requarks/wiki:2`, `docs` profile, port 3000) and README's own compose + `scripts/wiki-manage.sh` | The hub mounts `projects/README/docs` at `/wiki/content:ro`. Wiki.js 2 does not read pages from a mounted directory; content enters through a storage module. The mount is probably inert, which needs verifying in Phase 1. |
| **Bespoke Pages builds** | bashcrawl (`make web` → `web/`), csv-vscoode (Node `site/` + its own link checker), fredgar-ai (Python → `_site`) | Each is a fourth way to publish docs, with no shared theme, feedback widget or gate. |
| **`docs/` but no engine** | aieo 16, bashcrawl 18, bashos 12, csv-vscoode 11, fredgar-ai 15, vs-sonic-pi 11, githubai 7, bashconsultants 7, wtd 2, djangoerp 1 | Markdown that is only readable on GitHub. UPS-REPO-03 already warns when a bare `docs/` has no index. |
| **Nothing** | 1987, lawmode, scripts (docs aggregated into README), skills (fork, own Pages) | — |

What already exists to build on: UPS-REPO-03 (docs layout), UPS-FE-01 (`--fleet-*` tokens), UPS-FB-32 (the feedback snippet in MkDocs base templates), UPS-QA-15 (Jekyll strict build + htmlproofer), UPS-OPS-40 (one Pages surface), the README aggregator (`aggregate-docs.yaml`, weekly), the content atlas (`dash content`), and the drift gate's vendored-payload parity check (i).

### Two external facts that shape the plan

- **Material for MkDocs is in maintenance mode.** 9.7.0 (Nov 2025) was its last feature release. Critical and security fixes end in **November 2026**, which is one month from now. Its authors' successor, **Zensical**, reads existing `mkdocs.yml`. Material already constrains `mkdocs<2`, because MkDocs 2.0 breaks the plugin API. The plan therefore treats `mkdocs.yml` as the *config contract* and keeps the builder swappable. The fleet does not need a ceiling of its own, so the always-latest policy is untouched.
- **Wiki.js 3.0 is still alpha.** It promises bi-directional GitHub sync with PRs reflected in the wiki. The plan targets **2.5** (the image the hub already runs) through its Git storage module, and lists 3.0 as a watch item.

## Engine roles — what each one is for

| Engine | Strength | Weakness | Role in the fleet |
| --- | --- | --- | --- |
| **Jekyll** + zer0-mistakes | Narrative and marketing content, blogs, GitHub Pages native, the fleet design system, the feedback widget and SEO stack (FE-42) for free | `github-pages` caps Jekyll at 3.x and Ruby `< 4.0`; weak API reference; Liquid ties content to the engine | Primary for `site` and `content` kinds. The hub dash stays Jekyll. |
| **MkDocs-family** (`mkdocs.yml` → Zensical / Material 9.7) | Fastest path from `docs/*.md` to good product docs, excellent search, Mermaid, tabs, versioning (`mike`), mkdocstrings | Builder in transition (above); plugin ecosystem at risk under 2.0 | Primary for `app`, `cli`, `ext`, and non-API-heavy Python `lib`. This is the default renderer. |
| **Sphinx** + MyST | Real API reference (autodoc, Django/DRF models, intersphinx cross-links to Python/Django), `objects.inv`, **PDF / ePub / man pages** from one source, `-W -n` nitpicky builds | Heavier config; reST culture (avoided by MyST) | Primary for Python `api` and API-heavy `lib`. Secondary wherever a man page (`cli`) or PDF/ePub (`books`, `content`) is wanted. |
| **Wiki.js** (central instance) | Runtime: browse, search and edit across the *whole fleet* in one place; access control; human-authored runbooks and team knowledge beside generated repo docs | Not static, so it can't live on Pages; needs Postgres; one Git storage target per instance; 2.x is aging | One instance, fed by every repo's export (namespace `fleet/<repo>/…`, read-only) plus a human-editable `kb/` namespace. Runs local-first in the fleet stack, and on the forge host for a shared copy. |
| *(implicit)* **GitHub** + **llms.txt** | Source renders on github.com; agents read `llms.txt` | — | Every source must render correctly on GitHub as is. The engine also emits `llms.txt` / `llms-full.txt` from the same manifest: an AI variant that costs nothing extra. |

## Primary / secondary matrix by stack kind

Defaults live in `_data/fleet.yml` `docs.matrix`; a repo overrides them in its own `docs/docs.yml`. `P` = primary (deployed), `S` = secondary (built in CI and consumed by aggregators), `W` = wiki export, `—` = off.

| Kind | Jekyll | MkDocs | Sphinx | Wiki | Why |
| --- | --- | --- | --- | --- | --- |
| `site` | **P** | S | — | W | The site *is* the docs; MkDocs proves `docs/` stays portable |
| `content` | **P** | — | S (PDF/ePub when `books`-like) | W | Reading and knowledge; Sphinx only for print formats |
| `app` | — | **P** | — | W | User and developer guide beside a non-Pages app |
| `api` (Python) | — | S | **P** | W | autodoc + OpenAPI; MkDocs for the narrative guide |
| `api` (other) | — | **P** | — | W | Embed the committed OpenAPI (BE rows) via a Redoc/Scalar page |
| `lib` (Python) | — | **P** | S | W | mkdocstrings for the guide; Sphinx for `objects.inv` and intersphinx consumers |
| `lib` (Ruby gem) | **P** | — | — | W | The zer0-mistakes precedent; YARD stays out of scope |
| `cli` | — | **P** | S (man pages) | W | `sphinx -b man` turns the same pages into `man <tool>` |
| `ext` | — | **P** | — | W | The Marketplace README stays the storefront; the docs site goes deeper |
| `fork` | — | — | — | — | Upstream owns docs (skills keeps its own Pages) |

A multi-kind repo (e.g. djangoerp `app`+`api`) takes the **first** primary in the order `api` > `site` > `app` > `lib` > `cli` > `ext` > `content`. The tie-break favors the engine whose unique strength is otherwise lost.

### Proposed assignment (public repos; private repos resolved from registry `kinds` at fan-out)

| Repo | Today | Primary → | Migration note |
| --- | --- | --- | --- |
| zer0-mistakes | Jekyll `_docs` 95 + `docs/` 75 | Jekyll | Reference for the Jekyll adapter; `docs/` gains `docs.yml` |
| it-journey, lifehacker.dev, bamr87.github.io, zer0-pages, bashconsultants, wargames, irony-works, 2005 | Jekyll | Jekyll | Add `docs.yml`; wiki export is the new surface |
| README | MkDocs (aggregator) | MkDocs | Becomes the **fleet aggregator v2** (Phase 4) and owner of the wiki content branch |
| ai-seed | MkDocs | MkDocs | Reference for the MkDocs adapter (+ first Zensical trial) |
| barodybroject | Sphinx (reST) | Sphinx | Reference for the Sphinx adapter; convert prose `.rst` → MyST `.md`, keep autodoc stubs |
| djangoerp, fredgar-ai, aieo, wtd | `docs/` or bespoke | Sphinx (backend API) | fredgar-ai's bespoke Pages build is replaced; frontends document under the same site |
| bashcrawl, bashos, githubai, lawmode, scripts | `docs/` or none | MkDocs (+ Sphinx man pages for CLIs) | bashcrawl keeps its `web/` game as the app and moves docs under `/docs/` |
| csv-vscoode, vs-sonic-pi, zer0-cms | `docs/`, bespoke Node site | MkDocs | csv-vscoode's custom site + link checker retire in favor of the shared gate |
| 1987 | none | Jekyll (`content`) | Seed only |
| skills | fork | — | Untouched |

## The canonical source contract (`docs/v1`)

### Layout

```text
docs/
  docs.yml            manifest: engines, primary, nav, api sources, wiki namespace (schema docs/v1)
  index.md            landing page (required)
  tutorials/          Diátaxis: learning-oriented
  how-to/             task-oriented
  reference/          information-oriented (generated API pages land here at build time, never committed)
  explanation/        understanding-oriented
  UPPERCASE-TOPIC.md  operator docs stay where UPS-REPO-03 put them; docs.yml files them under a Diátaxis section
  assets/             images/diagrams referenced by relative path
```

Existing files are **not moved**. The manifest assigns each one to a section, so no inbound link breaks. Diátaxis directories are for new material, and the engine's `check` proposes a placement for unfiled pages.

### `docs/docs.yml`

```yaml
schema: docs/v1
title: barodybroject
primary: sphinx                 # jekyll | mkdocs | sphinx  (overrides fleet.yml docs.matrix)
variants: [mkdocs, wiki, llms]  # secondaries to build; omit to take the kind default
audiences: [user, developer, operator]
nav:                            # ONE nav, rendered into every engine's own format
  - index.md
  - Tutorials: [tutorials/first-parody.md]
  - How-to: [how-to/deploy.md, DEPLOYMENT.md]
  - Reference:
      - api: { engine: sphinx, autodoc: src/parodynews, openapi: openapi.yaml }
      - reference/settings.md
  - Explanation: [explanation/architecture.md]
wiki: { namespace: fleet/barodybroject }
exclude: [archive/**]
```

### Portable Markdown dialect

The source is CommonMark + GFM, plus a short list of constructs that every engine can render after the engine's own translation pass. The source never contains engine syntax.

| Construct | Source form (renders on GitHub) | Jekyll | MkDocs | Sphinx (MyST) | Wiki.js |
| --- | --- | --- | --- | --- | --- |
| Callout | `> [!NOTE]` / `[!TIP]` / `[!WARNING]` (GitHub alerts) | theme callout include | `!!! note` (or a callouts extension) | `:::{note}` | `> … {.is-info}` |
| Diagram | fenced `mermaid` | theme Mermaid | `pymdownx.superfences` | `sphinxcontrib-mermaid` | native |
| Tabs | `<!-- tabs -->` fenced group | theme tabs | `pymdownx.tabbed` | `sphinx-design` | flattened to headings |
| Cross-link | relative `.md` paths | rewritten to permalinks | native | MyST native | rewritten to `/fleet/<repo>/…` |
| Code include | `<!-- include: path#L1-L20 -->` | expanded at stage | `snippets` | `literalinclude` | expanded at stage |

Forbidden in portable `docs/`: Liquid (`{% %}`, `{{ }}`), Jinja, reST directives, raw engine shortcodes. Jekyll-only authored content (`pages/_docs/`, `_posts/`) stays Jekyll-only. It is exported to the wiki only when it is Liquid-free, and `check` reports which pages qualify.

### Front matter

```yaml
title: Deploying to Azure          # all engines
description: 50–160 chars          # SEO (FE-42), MkDocs meta, Sphinx html_meta, Wiki.js description
type: how-to                       # tutorial | how-to | reference | explanation (Diátaxis)
audience: [operator]
tags: [deploy, azure]
updated: 2026-10-03                # falls back to git log when absent
owner: '@bamr87'
```

Each adapter maps these fields to its engine's native keys. For Wiki.js 2 that means the HTML-comment header block its Git storage expects (`title`, `description`, `published`, `tags`, `editor: markdown`, `dateCreated`). The engine checks the same fields that `_data/fleet.yml` `content.quality` already checks for the content sites, so the content atlas and the docs system share one front-matter vocabulary.

## The machinery

### 1. `templates/docs/`: the kit (vendored, parity-checked)

```text
templates/docs/
  README.md, VERSION, archive/
  docs_engine.py            stage | render <engine> | build <engine> | check | export wiki | llms
  docs.template.yml         the manifest scaffold
  adapters/
    jekyll/                 _config.docs.yml fragment + collection mapping (consumer sites: zero theme edits)
    mkdocs/                 mkdocs.yml template (Material features the README/ai-seed configs already converge on)
    sphinx/                 conf.py template: myst_parser, sphinx-design, sphinxcontrib-mermaid, autodoc/autodoc2, furo
    wiki/                   exporter mapping + page-rule recipe for the read-only namespace
  theme/
    fleet-docs.css          --fleet-* tokens → --md-* (Material/Zensical), furo CSS vars, Wiki.js injected CSS
    feedback-head.html      the FB snippet for the MkDocs/Sphinx base templates and Wiki.js head injection
  docs.yml                  thin caller of the reusable fleet-docs.yml
```

The engine **stages** `docs/` into a gitignored `.docs-build/<engine>/`, then translates the dialect, expands includes, generates API stubs, and writes that engine's config from `docs.yml`. The rendered `mkdocs.yml` / `conf.py` are **generated, never committed**, except where a repo opts to commit them for editor tooling. Even then, `check` fails if the committed copy differs from what the generator would produce. This is the projects/SCHEMA.md pattern applied to docs. `docs_engine.py` joins drift check (i)'s vendored-payload parity list, so every repo builds with the same engine.

### 2. `fleet-docs.yml`: one reusable gate (in `bamr87/.github`, shaped like `fleet-conformance.yml` / `fleet-verify.yml`)

| Trigger | Does |
| --- | --- |
| PR touching `docs/**`, `docs.yml`, API sources | `check` (contract, nav covers every page, no orphans, no engine syntax, front matter) → build **primary** strictly → build each secondary as a matrix → link-check the source (lychee) → upload each variant as an artifact |
| push to `main` | build primary → `actions/deploy-pages` (OPS-40) → `llms.txt` into the Pages root |
| schedule (weekly, off the hour per the hub cron rule) | wiki export → push to the wiki content branch (Phase 4) |

Strict builds per engine: `jekyll build --strict_front_matter` + htmlproofer (QA-15, unchanged); `mkdocs build --strict` / `zensical build`; `sphinx-build -W --keep-going -n`; and the wiki export validated against its header schema. Cost control: secondaries run only when docs paths change, `variants_on_pr: primary|all` is a caller input, and the gate stays **advisory** (`gate: false`) until Phase 5. This follows the existing kill-switch convention: a repo variable `DOCS_GATE_ENABLED`.

### 3. Registry, config, spec

- `_data/fleet.yml` gets a **`docs:` block** holding engine images and versions, the `matrix` above, the dialect version, wiki instance settings (URL, namespace root, content branch), fan-out caps, and the cron. Bumping an engine here reaches every repo, like `toolchain:`.
- `_data/projects.yml` gets a per-repo **`docs:` adoption key**, the same shape as `schema:` / `release:`: `{ primary, status: none|pending|adopted, pr }`. `docs_url` stays and is derived from the primary's Pages URL.
- `specs/DOCS.md` (new area `DOC`) holds the rows, with `UPS-DOC-01..` covering manifest present, primary declared, portable dialect, front matter, strict primary build, secondaries build, one Pages surface, wiki export, `llms.txt`, theme tokens, and the feedback snippet. They go into `tools/conformance.py` (static checks: file presence, manifest schema, generated-config parity) and are regenerated into `_data/specs.yml`. They start as SHOULD and are promoted to MUST in Phase 5.

### 4. Local preview: the fleet stack

`tools/dash docs serve <project> [--engine jekyll|mkdocs|sphinx|wiki]` stages the project and serves the chosen variant from one shared per-engine container. That means one container per engine, not one per repo, which keeps the fleet within the 7.7 GiB Docker VM budget the containers block documents. The ports come from the existing `docs` band in `_data/ports.yml`: the `mkdocs` service keeps 8001, Sphinx (`sphinx-autobuild`) and Jekyll-docs previews are allocated there, and the wiki keeps 3000. `tools/dash docs build|check` runs the same engine CI runs.

### 5. Fleet aggregation

- **README aggregator v2** replaces `repos.txt` scraping and `aggregate.sh`. It reads each repo's `docs.yml` plus its built MkDocs-variant artifact, and nests each repo as a top-level section of one fleet MkDocs/Zensical site with unified search. The context-pyramid build keeps running on top of it.
- **Wiki.js** uses Git storage in a **bidirectional** mode against a content branch (proposed: `wiki-content` in bamr87/README, which already owns the Wiki.js setup). Path layout:
  - `fleet/<repo>/…` is written only by the weekly export and made read-only for every group by Wiki.js page rules. "Edit this page" links to the source file on GitHub (`edit_uri`). The feedback widget files issues into the owning repo, which feeds the existing issue pipeline.
  - `kb/…` is human-authored runbooks and team knowledge, editable in the wiki and committed to the branch by Wiki.js itself.
  - The dead `/wiki/content:ro` mount is removed from the hub compose once the storage module is wired.
- **`/docs-index/` dash surface.** `dash docs fleet --write` writes `_data/docs_index.yml` (primary, variants, build status, page counts, front-matter hygiene, Diátaxis coverage, last export), graded from files on disk the way `_data/features_index.yml` is. The content atlas adds `docs` as a site class, so stale and thin docs get the same suggestions content sites do.

## Rollout

Each phase is one PR series and lands behind the previous one's evidence. Fan-outs use `tools/fanout.sh` (dry-run default, PRs only, additive-only) and follow the submodule rule: one submodule per PR, committed upstream first.

| Phase | Deliverable | Exit evidence |
| --- | --- | --- |
| **0 — Decide** *(this doc)* | Plan reviewed; open questions answered; `specs/DOCS.md` drafted as SHOULD rows | Plan merged |
| **1 — Engine** | `templates/docs/` + `docs_engine.py` with unit tests per adapter (golden-file render of a fixture tree into all four targets); verify Wiki.js 2 Git storage and the current inert mount; Zensical vs Material build of the fixture | Fixture renders strictly in all four engines in hub CI |
| **2 — References** | One reference repo per engine: **zer0-mistakes** (Jekyll), **ai-seed** (MkDocs → Zensical trial), **barodybroject** (Sphinx, reST → MyST), **README** (wiki export + aggregator v2 prototype). The hub dogfoods it: hub `docs/` gets `docs.yml` and builds MkDocs + wiki as secondaries while the dash stays primary (so the deleted stale `mkdocs.yml` doesn't come back) | Each reference passes `fleet-docs.yml` with all its variants green; screenshots of each variant via `verify` scenarios |
| **3 — Fan-out** | `fanout.sh --kit docs` + `docs-fanout.yml`, in waves of ≤5 repos (cap in `fleet.yml docs.fanout`): **wave A** repos with real `docs/` and no engine (aieo, bashos, fredgar-ai, csv-vscoode, vs-sonic-pi); **B** the Jekyll sites; **C** CLIs/libs; **D** private repos and the rest | Each wave's PRs merged; registry `docs.status: adopted` |
| **4 — Aggregate** | README aggregator v2; central Wiki.js on Git storage with namespaces and page rules; `/docs-index/` surface; `dash docs serve`; wiki on the forge host | One search across the fleet in both the aggregated site and the wiki; index page live |
| **5 — Enforce** | DOC rows promoted to MUST; `DOCS_GATE_ENABLED` defaults on; docs drift becomes a lane in the evolution brief and a doctor signal; the MkDocs builder switches fleet-wide to Zensical where its feature check passes (before Material's fix window closes) | Conformance shows DOC rows passing on ≥90% of non-fork repos |

Phases 1–2 are the urgent part. The Zensical decision is due before November 2026, and two of the three existing MkDocs consumers are the references.

## Risks and how the design absorbs them

| Risk | Mitigation |
| --- | --- |
| Material/MkDocs 1.x stops receiving fixes; Zensical lacks a plugin some repo uses (mkdocstrings especially) | `mkdocs.yml` is generated, so switching the builder is a `fleet.yml` change. Python API reference is Sphinx's job anyway, which leaves MkDocs repos with few plugins to miss. |
| Four builds per PR burn Actions minutes | Secondaries are path-filtered; `variants_on_pr: primary` exists; cost is read from the billing meter per the standing rule and visible on `/actions/` |
| The translation layer becomes its own dialect nobody understands | The source form is GitHub-native everywhere (alerts, Mermaid, relative links), so a page that renders on GitHub is valid; the translation table above is the whole dialect, versioned in `docs/v1` |
| Wiki edits diverge from repo docs | Generated namespaces are read-only by page rule; the only editable wiki area (`kb/`) has no repo twin |
| Wiki.js 2 ages out; 3.0 changes storage | The export is plain Markdown with a header block, so re-targeting it (3.0, or another wiki) touches one adapter |
| Jekyll sites' Liquid-heavy `_docs` can't go portable | They stay Jekyll-only by design. Only `docs/` makes the four-variant promise, and `check` reports which `_docs` pages are portable. |
| Generated config committed by hand drifts | `check` fails on a committed `mkdocs.yml` / `conf.py` that differs from its render |

## Open questions (need an owner decision before Phase 1)

1. **Wiki content home:** a `wiki-content` branch in bamr87/README (proposed: no new repo, and README already owns Wiki.js), or a dedicated `bamr87/wiki` repo?
2. **Shared wiki hosting:** forge host (LAN, see [FORGE-HOST.md](FORGE-HOST.md)) only, or a public instance too? A public instance needs auth and a backup policy under UPS-OPS-34.
3. **Sphinx theme:** `furo` (proposed: minimal, CSS-variable driven, so it maps to `--fleet-*` cleanly) or `pydata-sphinx-theme` / `shibuya`?
4. **Committed generated configs:** allow (with the parity check) or forbid outright?
5. **Strict secondaries:** should a secondary's failure block a PR in Phase 5, or stay advisory forever, with only the primary gating?

## Related

[`specs/REPOSITORY.md`](../specs/REPOSITORY.md) (UPS-REPO-03) · [`specs/FRONTEND.md`](../specs/FRONTEND.md) (tokens, FE-42) · [`specs/FEEDBACK.md`](../specs/FEEDBACK.md) (FB-32) · [`specs/STACKS.md`](../specs/STACKS.md) · [`CONTENT-ATLAS.md`](CONTENT-ATLAS.md) · [`VERIFICATION.md`](VERIFICATION.md) (the shape the coverage index copies) · [`CONTAINERS.md`](CONTAINERS.md) / [`FLEET-COMPOSE.md`](FLEET-COMPOSE.md) (preview services, ports)
