# Docs System — one content contract, one front door, specialist backends

> **Status: PLAN, revision 2 (2026-10-03).** Nothing below is built yet. The plan harmonizes, standardizes and modernizes documentation across the fleet using Jekyll, MkDocs, Sphinx and Wiki.js, each **by role**. Revision 1 rendered every page four ways; [Design history](#design-history) records why that was dropped. Once adopted, the requirement rows move into `specs/DOCS.md` (area `DOC`) and this file becomes the operator doc for the machinery.

## The decision in one paragraph

Jekyll, MkDocs, Sphinx and Wiki.js do different jobs. Fragmentation comes from using all four for the *same* pages, each with its own voice, metadata and navigation. So **every page has exactly one home**, chosen by the page's type, and every system speaks one **content contract**: Diátaxis types, one front-matter schema, one Markdown dialect, one link and ownership rule, and one style rule set. Each repo can use any of four **surfaces**:

- a **front door** (Jekyll), for repos that need one
- **guides** (MkDocs)
- **API reference** (Sphinx)
- a space in the fleet's **one private handbook** (Wiki.js)

A repo turns a surface on only when it has content of that role, so a two-page `docs/` never becomes four sites. The contract lives once in the hub (`templates/docs/`), is vendored into each repo, and the drift gate holds it byte-identical. Git is the source of truth for anything a user or agent is expected to cite. The wiki may be fast and wrong, and is never cited.

## What exists today (survey, 2026-10-03)

The survey used blob-less clones of every `.gitmodules` entry: 26 public repos were read and 13 private repos could not be reached from the survey session. Engine detection used `_config.yml`, `mkdocs.yml`, `docs/**/conf.py`, Wiki.js compose wiring, and `docs/**/*.md` counts.

| Engine | Where it runs now | Notes |
| --- | --- | --- |
| **Jekyll** (zer0-mistakes theme) | 2005, bamr87.github.io, bashconsultants, irony-works, it-journey, lifehacker.dev, wargames, zer0-mistakes, zer0-pages (+ private: zer0-pages-remote, drsai) and the hub | The design-system reference. Authored docs live in `pages/_docs/` (zer0-mistakes 95, zer0-pages 104, lifehacker.dev 65, bamr87.github.io 23). |
| **MkDocs** (Material) | README (the fleet aggregator), ai-seed | zer0-CMS ships MkDocs fixtures: the CMS already edits Jekyll and MkDocs sites. The hub's own `mkdocs.yml` was deleted as a stale fork. |
| **Sphinx** | barodybroject only (`src/parodynews/docs/source/`, 57 `.rst`, autodoc against Django settings) | The fleet's only reStructuredText. The repo also carries a `jekyll-gh-pages.yml` workflow, giving it two Pages builds. |
| **Wiki.js** | Hub `wiki` service (`requarks/wiki:2`, `docs` profile, port 3000) and README's own compose + `scripts/wiki-manage.sh` | The hub mounts `projects/README/docs` at `/wiki/content:ro`. Wiki.js 2 loads content through storage modules, not mounted folders, so the mount is probably inert. To be verified in Phase 1. |
| **Bespoke Pages builds** | bashcrawl (`make web` → `web/`), csv-vscoode (Node `site/` + its own link checker), fredgar-ai (Python → `_site`) | Each is another publishing path, with no shared theme, feedback widget or gate. |
| **`docs/` but no site** | aieo 16, bashcrawl 18, bashos 12, csv-vscoode 11, fredgar-ai 15, vs-sonic-pi 11, githubai 7, bashconsultants 7, wtd 2, djangoerp 1 | Markdown that is only readable on GitHub, which is often the right answer (see the surface thresholds below). |
| **Nothing** | 1987, lawmode, scripts (docs copied into README), skills (fork, own Pages) | — |

### Duplicate clusters already visible

These are the Phase 3 backlog seed: each is one page or tree living in two systems.

| Cluster | Copies | Notes |
| --- | --- | --- |
| **README aggregator** | ~3.2k pages copied from it-journey (1,167), zer0-mistakes (727), skills (712), barodybroject (310), OverTheWire (232), and others | Republished at `bamr87.github.io/README/` with no `canonical` override or `noindex` in `mkdocs.yml`. Each copy is a second, drifting citation target for the original. |
| **zer0-mistakes** | `docs/` (75, e.g. `docs/installation/*`) vs `pages/_docs/` (95, e.g. `installation.md`) | Same topics in two trees in one repo. |
| **lifehacker.dev** | `docs/` (13) vs `pages/_docs/` (65) | To be checked for overlap. |
| **barodybroject** | Sphinx tree + a Jekyll Pages workflow | Two publishing paths in one repo. |
| **Hub ↔ README docs copies** | `projects/README/docs/{scripts,skills}/` mirror the submodules | Already flagged in CLAUDE.md "Docs aggregation gotcha". |

### Two external facts that shape the plan

- **Material for MkDocs is in maintenance mode.** 9.7.0 (Nov 2025) was its last feature release, and critical and security fixes end in **November 2026**. Its authors' successor, **Zensical**, reads existing `mkdocs.yml`. Material already constrains `mkdocs<2`, because MkDocs 2.0 breaks the plugin API.
- **Wiki.js 3.0 is still alpha.** The plan targets **2.5**, the image the hub already runs.

## Each system's job

| System | Keep it for | Never use it for |
| --- | --- | --- |
| **Jekyll** (zer0-mistakes theme) | The public **front door**: product or landing pages, blog, changelog, author / E-E-A-T pages, anything that needs Liquid, structured data or JSON-LD; whole sites for `site` and `content` repos | Deep reference trees; anything that needs versioned docs nav |
| **MkDocs** (Material) | Product and developer **guides**: tutorials, how-tos, CLI docs, conceptual handbooks, and an HTTP API rendered from committed OpenAPI. Markdown-native, fast preview, strong nav and search | Autodoc-heavy library manuals; authenticated or internal notes |
| **Sphinx** (MyST + autodoc, Furo) | **Library reference** generated from docstrings, intersphinx cross-project links, PDF / ePub output | Marketing pages, guides, runbooks, anything non-developers edit in a browser |
| **Wiki.js** (one central instance) | **Living internal knowledge**: runbooks, decisions, onboarding, ops notes. Web editor, permissions, GitHub sign-in, comments | Canonical product or API docs; anything public or citable. The database is its working source of truth and its Git sync is partial. |
| *(GitHub itself)* | **Repo docs**: `README.md`, `docs/*.md` (UPS-REPO-03) for contributors | Users who aren't contributors; once a repo has those, it needs a site |

Two sharpenings for this fleet:

- **Sphinx will be rare.** For a web service, the API users need is HTTP, and the committed OpenAPI (BACKEND rows) already describes it. That is rendered in the MkDocs guides (a Redoc/Scalar page), not by autodoc of internals. Sphinx is for importable Python libraries whose docstrings *are* the API, and it stays in barodybroject, where it already works.
- **CLI man pages come from the CLI** (`click-man`, `argparse-manpage`, `help2man`), not from a Sphinx tree kept only for the man builder. A second system just for one output format is the fragmentation this plan exists to stop.

## Surfaces per repo

### Activation thresholds: no empty sites

| Surface | Turn it on when | Until then |
| --- | --- | --- |
| Repo docs (GitHub) | Always (UPS-REPO-03) | — |
| Guides (MkDocs) | The repo has users beyond its contributors **and** ≥5 user-facing pages, **or** a published package / extension / CLI | `docs/` stays GitHub-rendered |
| API reference (Sphinx) | A Python package with a public import API documented in docstrings | Docstrings + OpenAPI page in guides |
| Front door (Jekyll) | `site` / `content` kind, or a product needs marketing layout, authorship or JSON-LD beyond what the guides' home page gives | The guides' `index.md` is the front door |
| Handbook space (Wiki.js) | The repo has runbooks, decisions or onboarding notes worth keeping | — (the space is cheap; it's one namespace in one instance) |

### Default surfaces by stack kind

| Kind | Front door | Guides | API reference | Handbook |
| --- | --- | --- | --- | --- |
| `site` | **Jekyll** (the whole site) | only for product docs beyond site content | — | space |
| `content` | **Jekyll** | — | — (Sphinx only if PDF/ePub is a real requirement, e.g. `books`) | — |
| `app` | guides home (Jekyll if marketing) | **MkDocs** | — | space |
| `api` | guides home | **MkDocs** + OpenAPI page | — | space |
| `lib` (Python) | guides home | **MkDocs** | **Sphinx** when the threshold is met | space |
| `lib` (Ruby gem) | **Jekyll** | — | — (YARD out of scope) | space |
| `cli` | guides home | **MkDocs** (+ man pages generated from the CLI) | — | space |
| `ext` | Marketplace README | **MkDocs** | — | space |
| `fork` | — | — | — | — |

### Proposed assignment (public repos; private repos resolved from registry `kinds` at fan-out)

| Repo | Today | Target surfaces | Note |
| --- | --- | --- | --- |
| zer0-mistakes | Jekyll `_docs` 95 + `docs/` 75 | Jekyll only | **Deliberate exception**: the theme documents itself with live Liquid demos, so its guides stay in Jekyll. Dedupe `docs/` against `pages/_docs/`. |
| it-journey, lifehacker.dev, bamr87.github.io, zer0-pages, bashconsultants, wargames, irony-works, 2005 | Jekyll | Jekyll + handbook space | Contract + JSON-LD; lifehacker.dev dedupe check |
| README | MkDocs aggregator | **Index, not copies** (see Aggregation) + owns the Wiki.js setup | Stops republishing other repos' pages |
| ai-seed | MkDocs | MkDocs | Reference repo for the guides kit |
| barodybroject | Sphinx (reST) + Jekyll workflow | MkDocs guides + Sphinx `/api/` in one Pages artifact | Reference repo for the API kit; narrative `.rst` → MkDocs, autodoc stubs stay, prose in MyST |
| aieo, fredgar-ai, djangoerp, wtd | `docs/`, bespoke, or near-empty | MkDocs + OpenAPI page when thresholds are met | fredgar-ai's bespoke build retires; djangoerp (1 page) and wtd (2) stay GitHub-rendered for now |
| bashcrawl, bashos, githubai, lawmode, scripts | `docs/` or none | MkDocs (+ CLI man pages) when thresholds are met | bashcrawl's `web/` game stays the app; docs move under `/guides/` |
| csv-vscoode, vs-sonic-pi, zer0-cms | `docs/`, bespoke Node site | MkDocs | csv-vscoode's custom site and link checker retire into the shared gate |
| 1987 | none | Jekyll (`content`) | Seed only |
| skills | fork | — | Untouched |

## The shared contract (`docs/v1`)

### Information architecture: Diátaxis, one type per page

`tutorial`, `how-to`, `reference` and `explanation` apply in every public system; `runbook` and `decision` exist only in the handbook. The routing rules:

- API signatures live only in Sphinx (Python libraries) or the OpenAPI page (services).
- Procedures that must survive a release live only in guides.
- Unreviewed decisions and runbooks live only in the handbook until promoted.

Existing files are **not moved** to create Diátaxis folders. A page's type comes from its front matter; new material may use `tutorials/ how-to/ reference/ explanation/` folders. UPPERCASE operator docs (UPS-REPO-03) keep their names and declare a type.

### Front matter, the same fields everywhere

| Field | Values | Jekyll | MkDocs | Sphinx (MyST) | Wiki.js |
| --- | --- | --- | --- | --- | --- |
| `title` | text; also the page's only H1 | native | native | MyST front matter | page title |
| `description` | one sentence, 50–160 chars; used as the meta description **and** the AI excerpt | `jekyll-seo-tag` | `meta` | `html_meta` | description |
| `type` | `tutorial` \| `how-to` \| `reference` \| `explanation` \| `runbook` \| `decision` | key | key | key | tag `type:*` |
| `audience` | `user` \| `developer` \| `operator` \| `internal` | key | key | key | tag `audience:*` |
| `owner` | GitHub handle or team | key | key | key | tag `owner:*` |
| `last_reviewed` | ISO date, set by a person, distinct from last modified | key | key | key | tag + weekly report |
| `product`, `version` | product slug; semver or `unversioned` | key | key | key | tags |
| `status` | `draft` \| `stable` \| `deprecated` | `published: false` when draft | excluded from build when draft | excluded when draft | page published flag |
| `tags` | free | native | `tags` plugin | key | tags |

The fields that existing content sites already require through `_data/fleet.yml` `content.quality` (`date`, `author`, `categories`, …) stay. The contract adds fields and never removes them, so the content atlas and the docs system share one vocabulary. `dateModified` comes from git or `last_modified_at`. A modified date is never presented as a review date.

### Authoring dialect

CommonMark plus a short allow-list: fenced code with a language, admonitions in GitHub alert form (`> [!NOTE]`), GFM tables, fenced `mermaid`, and relative links. Nothing tool-specific (shortcodes, Liquid, Jinja, raw directives) goes in shared pages. Jekyll-only pages that need Liquid are front-door pages by definition.

- reStructuredText stays inside existing Sphinx API pages only.
- New Sphinx prose uses MyST, so the dialect matches MkDocs.
- Each engine renders GitHub alerts through its own extension, a callouts extension in MkDocs and a small MyST/Sphinx shim.

### Links

- **Within a repo's public site:** stable paths under one Pages host (`/`, `/guides/…`, `/api/…`), never tool internals such as `_build/` or `objects.inv` paths in prose.
- **Across repos:** absolute URLs taken from the registry's `docs_url`.
- **intersphinx:** library-to-library only.
- **The handbook:** linked *out to* from operator pages, never linked *into* from public pages.

### Ownership and review

One owner per section. A public page without `owner` and `last_reviewed` fails CI on changed files (warning mode first). The handbook is checked weekly by `dash docs wiki-report`, which reads Wiki.js's GraphQL API and writes a values-free report of stale and ownerless pages.

### Style

One Vale style set (fleet vocabulary, terms to avoid, heading case, link text) vendored with the kit. It runs on Markdown, MyST and the remaining reST alike.

## Target architecture

```text
per repo — ONE GitHub Pages artifact (UPS-OPS-40 unchanged: one Pages surface)
  /            front door      Jekyll   (site/content kinds, or marketing need)  — else the guides' home
  /guides/     guides          MkDocs   (versioned with mike where the repo releases)
  /api/        API reference   Sphinx   (Python libraries)  |  OpenAPI page inside /guides/ (services)
  /llms.txt    generated from the front door's index + the guides/API nav

fleet-wide — private, never cited
  handbook (Wiki.js, forge host)   handbook/fleet/…  +  handbook/<repo>/…
                                   GitHub sign-in, private by default, noindex
```

GitHub Pages deploys **one artifact per repo**. So the path split is built as separate jobs whose outputs are assembled into one `upload-pages-artifact`, not as three Pages sites. The front door does not mirror the other trees; it links to them, and owns only pages that need its layout. Search stays per system at first (Jekyll theme search, Material search, Sphinx search). A federated index is a later phase, not a prerequisite. A candidate is Pagefind's multisite index merging, since it works over any static output.

### The handbook and its promotion path

- **One instance** in the fleet stack, local-first, with a shared copy on the forge host ([FORGE-HOST.md](FORGE-HOST.md)). Never 40 instances.
- **Private by default:** GitHub OAuth sign-in, `noindex`, and excluded from every `llms.txt` and sitemap.
- **Git storage in push mode** (wiki → Git) to a **private** repository. This gives backup, history and diffs, and makes promotion a copy rather than a retype. It is not a sync source, so the database stays the working copy and Git stays the record. The repository must be private, which rules out a branch of the public bamr87/README.
- **Promotion:** a runbook or decision becomes canonical only through a PR that moves it into the owning repo's guides (or API reference). The wiki page is then replaced by a stub linking to the published page. A quarterly sweep archives promoted pages.
- The dead `/wiki/content:ro` mount leaves the hub compose when the storage module is wired.

## The machinery

### `templates/docs/`: the contract kit (vendored, parity-checked)

```text
templates/docs/
  README.md, VERSION, archive/
  docs.template.yml        which surfaces this repo has, their roots, owners, versioning — schema docs/v1
  frontmatter.schema.json  the contract above (JSON Schema; one validator for every engine's files)
  docs_check.py            contract + routing + dialect + draft/internal leak + single-H1 checks
  vale/                    .vale.ini + the fleet style set and vocabulary
  lychee.toml              link-check config (anchors fail the build)
  configs/
    mkdocs.yml             Material config the README/ai-seed configs already converge on (+ callouts, redirects, llmstxt)
    sphinx/conf.py         myst_parser, autodoc, intersphinx, sphinx-reredirects, Furo
    jekyll/_config.docs.yml   collection + front-matter defaults for consumer sites (no theme edits)
  chrome/
    tokens.css + per-engine adapters   shared color, type, link treatment and admonition meaning
    header/footer/edit-link/feedback   same header, footer, "edit this page" and feedback widget (FB-32) everywhere
    jsonld/                Material `main.html` override emitting TechArticle (the theme handles Jekyll)
  docs.yml                 thin caller of the reusable fleet-docs.yml
```

Engine configs are **committed, hand-owned files** seeded from `configs/`. Each system keeps its own native nav, because no page renders in two systems and a meta-manifest would add a layer without buying anything. What drift check (i) holds byte-identical is the *contract*: `frontmatter.schema.json`, `docs_check.py`, the Vale styles, and the chrome. Design is shared tokens only; Sphinx is not skinned to look like Material pixel for pixel. A consistent header, footer, edit link and feedback widget is enough.

### `fleet-docs.yml`: one workflow shape (in `bamr87/.github`, beside `fleet-conformance.yml` / `fleet-verify.yml`)

| Step | Every active static surface |
| --- | --- |
| install | Latest tools (fleet always-latest policy; see the note below) |
| check | `docs_check.py` on changed pages: front matter, one H1, Diátaxis routing (no signatures outside API reference, no `runbook`/`decision` on public hosts), no `audience: internal`, drafts excluded |
| build | Strict mode: `jekyll build --strict_front_matter` (QA-15), `mkdocs build --strict`, `sphinx-build -W --keep-going -n`. MkDocs and Sphinx build in parallel jobs. |
| lint | Vale (shared styles) + lychee (broken links **and anchors** fail) + htmlproofer on Jekyll |
| assemble | Front door at `/`, guides at `/guides/`, API at `/api/`, `llms.txt` at root → one Pages artifact |
| publish | `actions/deploy-pages` on `main` (OPS-40). Never a bare `git push` to a protected branch. |

- **Gating:** the gate is advisory (`DOCS_GATE_ENABLED`, default-on kill switch per the hub rule) until Phase 2, which turns errors on for new and changed pages only.
- **Versions:** the always-latest policy holds. Tool versions float, and breakage surfaces in CI for the daily doctor. The one deliberate choice is the **builder** for `mkdocs.yml` (Material today), recorded in `_data/fleet.yml` `docs.builder`. It is a decision, not a version pin.
- **Versioning:** `mike` publishes `latest` plus supported releases, **only for repos with release-please and a published artifact**. mike stores versions on a `gh-pages` branch, so the workflow checks that branch out and folds it into the assembled artifact rather than letting Pages serve the branch. The Sphinx API tree publishes the same version set beside it, with an intersphinx inventory per version. Sites, front doors and the handbook are unversioned on purpose; the front door's changelog links into the versioned trees.

### Registry, config, spec, surfaces

- `_data/fleet.yml` gets a **`docs:` block** holding the builder choice, the surface defaults by kind, activation thresholds, the Vale rule-severity map, the handbook URL and storage repo, the fan-out caps and the weekly cron (off the hour).
- `_data/projects.yml` gets a per-repo **`docs:` adoption key**, shaped like `schema:` / `release:`: `{ surfaces: [front, guides, api], status: none|pending|adopted, pr }`. `docs_url` stays and points at the front door.
- `specs/DOCS.md` (new area `DOC`) holds the rows: one home per page, contract fields, dialect, routing, strict builds, one Pages artifact, no internal or draft content on public hosts, `llms.txt`, JSON-LD, shared chrome, handbook privacy. They are statically checked by `tools/conformance.py` and regenerated into `_data/specs.yml`. They start as SHOULD and become MUST in Phase 5.
- `dash docs inventory --write` → `_data/docs_index.yml` → a `/docs-index/` dash page. It records surfaces, generators, page counts, last commit, owner and review coverage, the Diátaxis mix and duplicate clusters, graded from files on disk the way `_data/features_index.yml` is. The content atlas adds docs as a site class, so stale and thin pages get the same suggestions content sites do.
- `dash docs serve <project> [--surface front|guides|api]` previews from one shared per-engine container (ports from the `docs` band in `_data/ports.yml`; `mkdocs` keeps 8001, the wiki keeps 3000).

## AI citability (do it once, not four times)

- **`llms.txt` / `llms-full.txt` per repo**, emitted by whichever system is the front door: the theme for Jekyll, the `llmstxt` plugin for MkDocs. Each points into guides and API. The hub's fleet-level `llms.txt` (`dash-gen machine-api`) links each repo's. The handbook is never listed.
- **JSON-LD:** `TechArticle` (or `SoftwareApplication` on a product front door), plus `FAQPage` only where a real FAQ exists. `author`, `dateModified` and `version` come from the contract. The Jekyll half is **one change in zer0-mistakes** that reaches every `remote_theme` consumer; the MkDocs half is the kit's `main.html` override.
- **Every canonical page:** one H1, a stable `description` (what answer engines extract), and `last_reviewed` on the pages an agent is most likely to cite.
- **Machine companions** where they exist: committed OpenAPI beside the rendered API page, Sphinx `objects.inv` beside the HTML.
- **No duplicate citation targets.** Aggregators link and summarize; they do not republish (see below). The wiki is excluded entirely.

### Aggregation: an index, not a mirror

The README aggregator's job changes from copying pages to **indexing** them. It keeps its context pyramid (facts → cards → apex) and its fleet-wide catalog. Each entry is a summary card that links to the page's one home. Until the copies are retired, the pages it still renders carry `rel=canonical` to the original plus `noindex`. The weekly aggregation stays; the ~3.2k republished pages go.

## Phased plan

Fan-outs use `tools/fanout.sh` (dry-run default, PRs only, additive-only) in waves of ≤5 repos, one submodule per PR, committed upstream first. Weeks are relative to approval.

| Phase | Weeks | Deliverable | Exit evidence |
| --- | --- | --- | --- |
| **0 — Inventory** | 1–2 | `dash docs inventory --write`: every surface's URL, generator, page count, last commit, owner and type; duplicates marked (seeded by the survey and clusters above). Verify the Wiki.js mount. | `_data/docs_index.yml` committed; this is the migration backlog |
| **1 — Contract** | 2–4 | `specs/DOCS.md` (SHOULD), `templates/docs/`, `fleet-docs.yml` in **warning mode**, fanned out to every repo with a site. **No pages move.** References: ai-seed (guides), barodybroject (guides + API), it-journey (front door + JSON-LD via the theme). | Warnings visible fleet-wide; references green |
| **2 — Freeze boundaries** | 4–8 | New API reference goes to Sphinx/OpenAPI only, new guides to MkDocs only, new internal notes to the handbook only, and Jekyll accepts only front-door pages. CI errors on **new and changed** pages. Handbook stood up private (GitHub sign-in, Git push storage, spaces). | Routing violations on new pages = 0 |
| **3 — Dedupe** | 6–12 | Per cluster: pick the winner by the job table, redirect the loser (`jekyll-redirect-from` / `aliases:`, `mkdocs-redirects`, `sphinx-reredirects`), delete the copy. Order by traffic where analytics exist, otherwise by drift. Retire the README mirror, the bespoke Pages builds and barodybroject's second workflow. Wiki pages that are really product docs are promoted by PR. | No page in two systems except redirects |
| **4 — Publish surface** | 10–14 | Path split in one artifact per repo; Jekyll nav points at `/guides/` and `/api/`; `llms.txt` + JSON-LD shipped; `last_reviewed` on the most-cited public pages | `/docs-index/` shows every active repo with a front door, `llms.txt`, and JSON-LD |
| **5 — Operate** | ongoing | **Monthly:** owners review anything older than 90 days in the public trees (`dash docs stale` files `docs:review` issues into the issue pipeline). **Quarterly:** archive promoted wiki pages. DOC rows → MUST. **Builder gate:** decide Zensical vs Material once the contract is in (target Q1 2027). Federated search. | Review coverage ≥90% on cited pages |

**On Zensical timing:** Material's fix window closes during Phase 2. Changing builders in the middle of harmonizing would mix two migrations, so the plan holds Material through Phase 4. The cost of waiting is small: the builder runs only at build time, its output is static HTML, and Material's own `mkdocs<2` constraint keeps latest-resolving installs working. The trigger to move earlier is a security advisory against the build chain, or a dependency break that the doctor cannot fix.

## Rules that keep it from re-fragmenting

- No page exists in two systems unless one is a redirect. Aggregators index; they do not mirror.
- No reStructuredText outside existing Sphinx reference pages.
- No `audience: internal`, `runbook`, `decision` or draft content on a Jekyll or MkDocs host. The handbook is never in `llms.txt`, a sitemap or a citation.
- A repo turns a surface on only when it has content of that role. No empty sites.
- A new tool needs a job the four do not already cover. "Nicer theme" is not a job. Nor is "one output format": CLI man pages come from the CLI.
- Style, metadata and link rules live in the hub's `templates/docs/` and are vendored and parity-checked. A repo never forks them, and improvements go to the hub first.

## Risks

| Risk | Mitigation |
| --- | --- |
| Material/MkDocs 1.x without fixes after Nov 2026 | Static output, build-time only; the builder gate is in Phase 5 with an early trigger; `mkdocs.yml` is what Zensical reads |
| The contract feels like overhead on small repos | Activation thresholds keep them GitHub-rendered; CI checks changed files only; warning mode before errors |
| Backfilling `last_reviewed` with fake dates | Forbidden. Missing stays missing (a warning) until a person reviews the page. |
| Wiki knowledge never gets promoted | The weekly report surfaces old `runbook`/`decision` pages; the quarterly sweep; promotion is a copy because Git storage holds the Markdown |
| Wiki.js 2 ages out; 3.0 changes storage | The handbook is a private, non-canonical layer; its Git-stored Markdown makes moving it a bounded job |
| mike's `gh-pages` branch fights the deploy-pages model | Folded into the assembled artifact; only releasing repos use it |
| Removing the README mirror loses fleet-wide search | Interim canonical + noindex; index cards keep discovery; federated search in Phase 5 |

## Open questions (need an owner decision before Phase 1)

1. **Handbook storage repo:** a new private `bamr87/handbook` (proposed), or another private repo you already have? It cannot be a branch of the public bamr87/README.
2. **Handbook hosting:** forge host on the LAN only, or reachable from the internet behind GitHub sign-in? The second needs a backup and restore drill under UPS-OPS-34.
3. **Versioned docs:** confirm the rule "release-please + a published package". Candidates are the gems, the VS Code extensions, and the Python packages on PyPI.
4. **Vale severity:** which rules error and which warn at Phase 2. Proposed: vocabulary and banned terms error; style suggestions warn.
5. **README aggregator:** retire the mirror in Phase 3 (proposed), or keep it as an explicit noindex archive?

## Design history

**Revision 1** (same day) had every repo write portable Markdown once, and a vendored engine render it four ways: Jekyll, MkDocs, Sphinx, and a read-only export into the wiki. Each repo deployed one primary, and CI built the rest to prove portability. Review rejected it for three reasons:

- **It put the same page in up to four systems.** Even unpublished secondaries and a wiki mirror create competing copies. The README aggregator already shows the cost: 3.2k republished pages and no canonical link.
- **The render layer solved the wrong problem.** Fragmentation comes from content in the wrong place with inconsistent metadata, not from rendering. A shared contract fixes that, while a cross-engine transpiler adds a dialect to maintain.
- **It used the wiki as a mirror.** That wastes the wiki's one real strength, fast private editing, and risks agents citing it.

Carried over from revision 1: the survey, the stack-kind defaults (now *surfaces*), GitHub-alert source syntax, `llms.txt`, the shared tokens and feedback chrome, the vendored-and-parity-checked kit, and the Material/Zensical watch.

## Related

[`specs/REPOSITORY.md`](../specs/REPOSITORY.md) (UPS-REPO-03) · [`specs/FRONTEND.md`](../specs/FRONTEND.md) (tokens, FE-42) · [`specs/FEEDBACK.md`](../specs/FEEDBACK.md) (FB-32) · [`specs/OPERATIONS.md`](../specs/OPERATIONS.md) (OPS-34, OPS-40) · [`specs/STACKS.md`](../specs/STACKS.md) · [`CONTENT-ATLAS.md`](CONTENT-ATLAS.md) · [`VERIFICATION.md`](VERIFICATION.md) (the shape `/docs-index/` copies) · [`ISSUE-PIPELINE.md`](ISSUE-PIPELINE.md) (`docs:review` issues) · [`FORGE-HOST.md`](FORGE-HOST.md)
