# Repository layout

A newcomer's map of what lives at the root of this repository and why.

> **Status of this document.** It was assembled from the repository's top-level
> file listing. Rows marked **(verified)** are things the listing itself proves
> (the file or directory exists, with that name). Rows marked **(inferred)** are
> educated guesses from conventional naming that **have not been confirmed by
> reading the file**. If you have the repo checked out and a row is wrong, please
> fix it — that is the fastest way to make this page trustworthy.

---

## The short version

This repository wears two hats at once, which is the main thing that confuses
first-time readers:

1. **A Jekyll site.** `_config.yml`, `Gemfile`, `index.md`, `_data/`, `pages/`
   and `assets/` are the ingredients of a static site. Even `README.md` opens
   with YAML front matter (`title:`, `author:`, `class:`, `updated:`), so it is
   both the GitHub profile README *and* site content.
2. **A monorepo with automation around it.** `projects/`, `templates/`,
   `tools/`, `_reports/`, `fleet.manifest.yml`, `.mcp.json`, `AGENTS.md` and
   `CLAUDE.md` are about building, orchestrating and agent-driven workflows —
   not about the site's HTML.

Everything else at the root is developer-environment plumbing: linting,
formatting, hooks, containers, editor settings.

**`README.md` is a personal profile page, not a build guide.** Don't look there
for setup instructions.

---

## Where to start reading

| If you want to… | Open |
| --- | --- |
| Know who maintains this and what they do | `README.md` |
| Contribute a change | `CONTRIBUTING.md` |
| Understand the data shapes / schemas used here | `SCHEMA.md` |
| Understand the git submodules and how to initialise them | `SUBMODULES.md` |
| Understand how AI agents are expected to work in this repo | `AGENTS.md`, `CLAUDE.md` |

(These files exist at the root — **verified** from the listing. Their contents
are summarised here only by what their names claim; open them for the detail.)

---

## Top-level map

### Jekyll site sources

| Entry | Role | Confidence |
| --- | --- | --- |
| `_config.yml` | Jekyll site configuration. | verified (file exists; Jekyll's conventional config name) |
| `_config_dev.yml` | A second Jekyll config, presumably layered over `_config.yml` for local development. | inferred — confirm how it's meant to be combined |
| `Gemfile` | Ruby dependencies (Jekyll and plugins). Bundler reads this. | verified |
| `index.md` | The site's home page source. | inferred |
| `_data/` | Jekyll data files consumed by templates. | inferred (leading `_` + Jekyll's `_data` convention) |
| `pages/` | Additional site pages. | inferred |
| `assets/` | Static assets — CSS, JS, images — served by the site. | inferred |
| `README.md` | Profile README; also carries Jekyll front matter, so it is site content too. | verified (front matter is visible in the file) |

### Monorepo content and tooling

| Entry | Role | Confidence |
| --- | --- | --- |
| `projects/` | Project directories. Given `.gitmodules` is present, some or all of these are likely git submodules. | inferred — cross-check against `.gitmodules` and `SUBMODULES.md` |
| `templates/` | Reusable templates (scaffolding for new projects, pages, or documents). | inferred — purpose and consumer unconfirmed |
| `tools/` | Scripts and utilities. The repository's primary language is reported as Shell, so this is a likely home for those scripts. | inferred |
| `_reports/` | Generated reports/output. The leading underscore suggests generated-not-hand-written. | inferred — confirm what writes here and whether it's committed |
| `Rakefile` | Rake tasks — the repository's task runner entry point. Run `rake -T` locally to list the real tasks. | verified that the file exists; task names unconfirmed |
| `.gitmodules` | Git submodule definitions. See `SUBMODULES.md`. | verified |

### Agent and automation configuration

| Entry | Role | Confidence |
| --- | --- | --- |
| `AGENTS.md` | Instructions for AI coding agents working in this repo. | verified (file exists) |
| `CLAUDE.md` | Claude-specific project instructions. | verified (file exists) |
| `.claude/` | Claude configuration directory (e.g. commands, settings). | inferred |
| `.mcp.json` | Model Context Protocol server configuration. | inferred |
| `fleet.manifest.yml` | Manifest describing the automation "fleet" that operates on this repo. | inferred — see the file for the authoritative schema |
| `.github/` | GitHub configuration: workflows, issue/PR templates. | inferred |

### Development environment and code quality

| Entry | Role | Confidence |
| --- | --- | --- |
| `.devcontainer/` | VS Code / Codespaces dev container definition — likely the quickest path to a working environment. | inferred |
| `docker-compose.yml` | Container services for local development. | inferred — read the file for the actual service names |
| `.vscode/` | Shared VS Code settings for this workspace. | inferred |
| `home.code-workspace` | A VS Code multi-root workspace file. | inferred |
| `.editorconfig` | Cross-editor whitespace/encoding rules. | verified (standard format) |
| `.prettierrc`, `.prettierignore` | Prettier formatting config and exclusions. | verified (standard names) |
| `.pre-commit-config.yaml` | `pre-commit` framework hook definitions. | verified (standard name) |
| `.husky/` | Husky git hooks. | verified (standard name) |
| `.env.example` | Template for a local `.env`; copy it and fill in your own values. Never commit the real `.env`. | verified (standard convention) |
| `.gitignore` | Ignored paths. | verified |

### Dotfiles at the root

| Entry | Role | Confidence |
| --- | --- | --- |
| `.zshrc`, `.zprofile`, `.gitconfig` | Shell and git dotfiles. These may be *managed by* this repository (i.e. content it distributes to a machine) rather than configuration *of* the repository. | inferred — needs confirmation, this distinction matters |

### Documentation

| Entry | Role | Confidence |
| --- | --- | --- |
| `docs/` | Long-form documentation — including this page. | verified |
| `SCHEMA.md` | Schema documentation. | verified (file exists) |
| `SUBMODULES.md` | Submodule documentation. | verified (file exists) |
| `CONTRIBUTING.md` | Contribution guide. | verified (file exists) |

---

## Getting set up — **not yet documented here**

This page deliberately contains **no install, build, serve or test commands**.
The author of this page could not read `Gemfile`, `Rakefile`, `_config.yml`,
`docker-compose.yml` or `.devcontainer/`, and writing commands that were never
verified is worse than writing none.

Until this section is filled in, the authoritative sources are, in rough order
of usefulness:

1. `.devcontainer/` — if a dev container is defined, opening the repo in it is
   usually the shortest path to a working environment.
2. `Rakefile` — run `rake -T` in a checkout to list the available tasks.
3. `Gemfile` — the Ruby/Jekyll dependency set; installed with Bundler.
4. `docker-compose.yml` — the local service definitions.
5. `.github/` — CI workflows show the exact commands that must pass, which is
   the most reliable description of "how this project is built and tested".

### TODO for a maintainer

Replace this section with the real commands, copied verbatim from the files
above:

- [ ] Prerequisites (Ruby version, Node version, Docker — whatever is actually required)
- [ ] First-time setup, including submodule initialisation (see `SUBMODULES.md`) and `.env` creation from `.env.example`
- [ ] How to serve the site locally, and how `_config_dev.yml` participates
- [ ] How to run linters/formatters (`pre-commit`, Prettier, Husky hooks)
- [ ] How to run tests, if any
