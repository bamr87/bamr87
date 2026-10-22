# UPS-DOC — Documentation

> One documentation framework for every fleet repo: where each kind of fact lives, the shape every document takes, what is generated instead of written, and how the fleet reviews it all in one place.

Evidence base (2026-10-21 review of 24 checked-out repos): 20 had an `AGENTS.md`, but 8 of them were still titled `# CLAUDE.md` and 5 carried a "Claude Code notes — moved verbatim" block that duplicated sections above it; 6 kept a full `CLAUDE.md` beside or instead of `AGENTS.md`; the hub's own `CLAUDE.md` was 6,450 words. `docs/README.md` existed in 19 repos in five different shapes, one of them a 638-line tutorial. Settings, command and route tables were hand-copied from `package.json`, `urls.py` and CLI definitions. The always-loaded agent files ranged from 45 to 6,450 words.

This area is the repo layer of [`docs/DOCS-SYSTEM.md`](../docs/DOCS-SYSTEM.md). It needs none of that plan's open decisions (engines, handbook, versioning) and holds whichever surfaces a repo later turns on. README and agent-file rows that already exist stay in [REPOSITORY.md](REPOSITORY.md) and [AGENT-CONTEXT.md](AGENT-CONTEXT.md); the rows here say how they fit together.

## Homes: one place per fact

| id | level | applies | requirement | satisfied by | seed |
| --- | --- | --- | --- | --- | --- |
| UPS-DOC-01 | MUST | all | **Each fact has one home.** `README.md` is for visitors: what it is and why, Quick start, a layout pointer, links onward. `AGENTS.md` is for agents and contributors: exact commands, layout, conventions, invariants. `docs/` holds depth, one topic per file. `CHANGELOG.md` holds history, `SCHEMA.md` placement. A file links to another file's fact rather than restating it. The one sanctioned copy is the Quick start command block, which matches `AGENTS.md` **Stack & commands** (UPS-REPO-11). | review; the survey's repeated-paragraph check | — |
| UPS-DOC-04 | MUST | all | The root holds docs of record only (UPS-REPO-01): `README`, `AGENTS`, `CLAUDE`, `CHANGELOG`, `LICENSE`, `CONTRIBUTING`, `SECURITY`, `CODE_OF_CONDUCT`, `SCHEMA`, `PRD`, `BACKLOG` (a declared file backlog), and reports a tool writes there (`CATALOG.md`, `SITE_HEALTH.md`). Plans, proposals, guides, runbooks and quick references go in `docs/`. | survey root-docs check | — |
| UPS-DOC-06 | MUST | all | Superseded, one-off and historical documents — status reports, "summary of changes", fix write-ups, notes for a migration that finished, plans that shipped — are **deleted**, not banner-marked. Git history and `CHANGELOG.md` keep them. Records that are append-only by design stay: ADRs (UPS-WORK-04), a declared file backlog, `CHANGELOG.md`. A moved document leaves no stub unless an external URL depends on it, and then a one-line pointer. | review | — |

## Shape: every document

| id | level | applies | requirement | satisfied by | seed |
| --- | --- | --- | --- | --- | --- |
| UPS-DOC-02 | MUST | all | Every Markdown document has **one H1** (a Jekyll page may use front-matter `title:` instead) and a **one-sentence summary**: front-matter `description:` in a file that has front matter, otherwise a `>` blockquote directly under the H1. The summary is what the docs index, the README survey and answer engines show for the page. | `python3 tools/docs_index.py --lint` | `tools/docs_index.py` |
| UPS-DOC-07 | MUST | all | Hygiene: one paragraph per line (`tools/unwrap-prose.py --check`), every relative link resolves, no `TODO:` scaffold lines in docs of record, and file names follow UPS-REPO-03 (`UPPERCASE-TOPIC.md` operator docs, lowercase guides). | prose gate; survey D8 | `tools/fanout.sh --kit prose` |
| UPS-DOC-08 | SHOULD | all | Budgets keep the files every session loads effective: `CLAUDE.md` at most 20 non-blank lines (UPS-AGENT-08), `AGENTS.md` at most 2,000 words, `README.md` at most 2,000 words outside generated spans. Over budget means a section belongs in `docs/` behind a link. A justified overage is a **Standard deviations** line. | survey budget check | — |
| UPS-DOC-09 | MUST | all except fork | `AGENTS.md` opens with `# <repo name>` (never `# CLAUDE.md`), carries the six UPS-AGENT-07 headings, and keeps no migration leftovers: the D4 "Claude Code notes — moved verbatim" blocks are folded into those headings with the duplicates dropped. | survey agent-file check; `tools/conformance.py` UPS-AGENT-07/08 | `templates/sdlc/AGENTS.template.md` |
| UPS-DOC-10 | MUST | all except fork | `README.md` follows the portfolio skeleton ([`docs/PORTFOLIO.md`](../docs/PORTFOLIO.md) §4): `# <name>`, a `>` tagline, badges, then **Overview · Features · Quick start/Usage** · deep-dive sections · **Project structure · Development · Contributing · Changelog · License**, then the portfolio footer. Content repos may fold Usage and Development into one **Working with this repo** section. When `docs/` exists, the README links `docs/README.md`. Replaces UPS-REPO-10, whose order predated the skeleton. | `tools/conformance.py` UPS-DOC-10; survey G2 | `.github/templates/README.template.md` |

## Generated, not written

| id | level | applies | requirement | satisfied by | seed |
| --- | --- | --- | --- | --- | --- |
| UPS-DOC-03 | MUST | all with `docs/` | `docs/README.md` is the **docs index**: one row per document — the root docs of record, then every file under the doc roots (a subdirectory with its own `README.md` is one row) — inside an `<!-- AUTO:docs-index:start -->` span generated from the UPS-DOC-02 summaries. Hand prose may sit above the span. Extra roots and exclusions ride on the start marker (`roots=docs,specs exclude=docs/media/`). | `python3 tools/docs_index.py --check` | `python3 tools/docs_index.py --write` |
| UPS-DOC-05 | MUST | all | Reference that can be derived from source is **generated**: CLI help, VS Code `contributes` (commands, settings, keybindings), Make/npm/rake targets, HTTP routes, management commands, configuration keys and defaults, workflow inventories, registries. It lives in `docs/reference/` (or an `<!-- AUTO:<name> -->` span), opens with a `GENERATED` comment that names the command that rebuilds it, and a test or `--check` mode fails when it is stale. Hand-written prose explains; it does not re-list. | the repo's own check; survey generated-marker check | per repo |

## Fleet review

| id | level | applies | requirement | satisfied by | seed |
| --- | --- | --- | --- | --- | --- |
| UPS-DOC-20 | SHOULD | all | The README repo's survey is the fleet's consolidated documentation review. `python3 -m scripts.context_engine survey --workspace <dir>` reads every checkout under `<dir>`, applies these rows, and writes `context/reports/docs_review.{json,md}`: each repository's document inventory (path, words, summary) and its findings, ranked. The weekly survey reads the same checks from shallow clones. | the committed report | bamr87/README `scripts/context_engine/` |

## Applying it to a repo

1. `AGENTS.md`: retitle to `# <repo>`; fold any moved-verbatim block into the six headings, keeping one copy of each rule; move long explanations into `docs/` behind a link (DOC-08, DOC-09). `CLAUDE.md` becomes the kit pointer (UPS-AGENT-08).
2. `README.md`: the portfolio skeleton; deep dives over budget move to `docs/` (DOC-10, DOC-08).
3. Root: move non-record documents into `docs/` and fix their inbound links (DOC-04). Delete the superseded ones (DOC-06).
4. Every document gets its summary line (DOC-02). `python3 tools/docs_index.py --lint` lists the ones missing.
5. Replace hand-copied reference with a generator and its check (DOC-05).
6. Vendor `tools/docs_index.py` from the hub and run `python3 tools/docs_index.py --write`, then `python3 tools/unwrap-prose.py --write` (DOC-03, DOC-07).
7. From a bamr87/README checkout: `python3 -m scripts.context_engine survey --local <repo>` shows what is left.
