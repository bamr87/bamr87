---
title: Repository Map
description: Orientation guide to the top-level directories of the bamr87/bamr87 monorepo.
updated: 2026-08-26
---

# Repository Map

This repository is a **monorepo**. The root `README.md` is a GitHub *profile* README — it
introduces the author, not the codebase — so this page exists to answer a different question:

> "I want to change something. Which directory do I open?"

## How to read this page

Each entry below is present in the repository root. The **Status** column tells you how much
trust to place in the description:

| Marker | Meaning |
| --- | --- |
| ✅ **Confirmed** | The entry exists and its role is unambiguous from the filename (a standard, well-known config file). |
| 🔍 **Inferred** | The entry exists; the description follows from naming convention and from other files in this repo, but the contents were not read. |
| ⚠️ **Unverified** | The entry exists, but its purpose is a placeholder awaiting a maintainer. **Do not rely on this row.** |

If you correct a row, please also drop its marker down to ✅ — that is the whole maintenance
burden of this page.

---

## Content and source directories

These are the directories you are most likely to be looking for.

| Path | What it is | Status |
| --- | --- | --- |
| `pages/` | ⚠️ Purpose not verified. The name, alongside `index.md` and `_config.yml`, suggests standalone site pages (as opposed to dated posts). A maintainer should confirm whether these are Jekyll pages, and what the naming/front-matter convention is. | ⚠️ Unverified |
| `projects/` | ⚠️ Purpose not verified. Likely per-project content or subdirectories — note that `.gitmodules` exists, so some of these may be **git submodules** rather than files tracked here. See `SUBMODULES.md` before editing anything under this path. | ⚠️ Unverified |
| `templates/` | ⚠️ Purpose not verified. The name suggests reusable scaffolding — either page/layout templates for the site, or file templates used when generating new content. Which one is unknown. | ⚠️ Unverified |
| `tools/` | ⚠️ Purpose not verified. The repository's primary language is reported as **Shell**, so this is a plausible home for the scripts that make up that share of the codebase. Contents not inspected. | ⚠️ Unverified |
| `docs/` | Documentation — this file lives here. Other contents were not inspected. | 🔍 Inferred |
| `assets/` | Static assets (images, CSS, JS) for the site. Standard Jekyll convention. | 🔍 Inferred |
| `index.md` | The site's landing page. | 🔍 Inferred |

## Data and generated output

| Path | What it is | Status |
| --- | --- | --- |
| `_data/` | Structured data files consumed by the site. In Jekyll, files here are exposed to templates via `site.data`. See `SCHEMA.md`, which likely documents their shape. | 🔍 Inferred |
| `_reports/` | ⚠️ Purpose not verified. The name suggests **generated output** rather than hand-edited source. Confirm before editing by hand — if it is generated, edits here will be overwritten. | ⚠️ Unverified |

## Site configuration and build

| Path | What it is | Status |
| --- | --- | --- |
| `_config.yml` | Primary site configuration. | 🔍 Inferred |
| `_config_dev.yml` | A development-time configuration overlay. Jekyll supports layering configs, so this is likely applied *on top of* `_config.yml` for local work. The exact invocation is not documented here — see "Open questions". | 🔍 Inferred |
| `Gemfile` | Ruby dependencies. Confirms this project has a Ruby/Bundler toolchain. | ✅ Confirmed |
| `Rakefile` | Rake task definitions. This is where repo automation tasks are likely defined; run `rake -T` locally to list them. | ✅ Confirmed |
| `docker-compose.yml` | Container service definitions for local development. Services not inspected. | ✅ Confirmed |

## Documentation at the root

The root holds several Markdown files that are worth knowing about before you contribute:

| File | What it covers |
| --- | --- |
| `README.md` | Profile README — author background, skills, experience. Not a build guide. |
| `CONTRIBUTING.md` | **Read this first** if you intend to open a PR. |
| `AGENTS.md` | Guidance for AI/automated agents working in this repository. |
| `CLAUDE.md` | Instructions specific to Claude Code, alongside the `.claude/` directory. |
| `SCHEMA.md` | Schema documentation — most likely describes the structure of files under `_data/`. |
| `SUBMODULES.md` | Git submodule documentation. Pairs with `.gitmodules`. |

## Tooling, environment, and hooks

These exist to keep contributions consistent. You rarely need to edit them, but it helps to
know why a commit was rejected.

| Path | What it is | Status |
| --- | --- | --- |
| `.pre-commit-config.yaml` | pre-commit framework hook definitions. | ✅ Confirmed |
| `.husky/` | Husky git hooks. Note that both Husky *and* pre-commit are configured — check which one is authoritative before adding a new hook. | ✅ Confirmed |
| `.prettierrc` / `.prettierignore` | Prettier formatting rules and exclusions. | ✅ Confirmed |
| `.editorconfig` | Cross-editor whitespace and encoding settings. | ✅ Confirmed |
| `.github/` | GitHub configuration: workflows, issue templates, and similar. Contents not inspected. | 🔍 Inferred |
| `.devcontainer/` | Dev Container definition for VS Code / Codespaces. | 🔍 Inferred |
| `.vscode/` | Workspace-local VS Code settings. | 🔍 Inferred |
| `home.code-workspace` | A VS Code multi-root workspace file — useful given the submodule setup. | 🔍 Inferred |
| `.claude/` | Claude Code configuration. Pairs with `CLAUDE.md`. | 🔍 Inferred |
| `.mcp.json` | Model Context Protocol server configuration. | 🔍 Inferred |
| `fleet.manifest.yml` | ⚠️ Manifest for the automated agent fleet operating on this repository. Contents not inspected. | ⚠️ Unverified |
| `.env.example` | Template for local environment variables. Copy it, fill it in, and keep the real file untracked. | ✅ Confirmed |
| `.gitignore` | Ignore rules. | ✅ Confirmed |
| `.gitmodules` | Submodule definitions — see `SUBMODULES.md`. | ✅ Confirmed |

## Tracked dotfiles

| Path | What it is |
| --- | --- |
| `.zshrc`, `.zprofile` | Zsh shell configuration, tracked in the repository. |
| `.gitconfig` | Git configuration, tracked in the repository. |

These are unusual to find in a project repository and are a strong hint that this monorepo
doubles as a **dotfiles / home-environment repository** (the `home.code-workspace` filename
points the same way). ⚠️ This reading is an inference and should be confirmed by a maintainer.

---

## Working with submodules

`.gitmodules` is present, which means a plain `git clone` will leave some directories empty.
Refer to **`SUBMODULES.md`** for the project's own instructions — this page intentionally does
not restate clone or update commands, because those were not verified against that file.

## Open questions for maintainers

The following could not be determined from the repository listing alone. Answering them here
would make this page complete:

1. What is the actual purpose and content convention of `pages/`, `projects/`, `templates/`,
   `tools/`, and `_reports/`?
2. Which of those directories, if any, are git submodules?
3. Is `_reports/` generated output? If so, by what — a Rake task, a workflow in `.github/`, or
   the agent fleet?
4. How is `_config_dev.yml` applied relative to `_config.yml`?
5. What are the canonical commands to install dependencies, serve the site locally, and run
   checks? (Candidates live in `Gemfile`, `Rakefile`, and `docker-compose.yml`, but were not
   verified — no commands are asserted here rather than risk publishing one that fails.)
6. Are Husky and pre-commit both active, or is one superseded?

## Contributing to this page

This map is only useful if it stays true. If you add or rename a top-level directory, please
add or update its row in the same change.
