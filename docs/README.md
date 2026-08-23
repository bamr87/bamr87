---
title: Repository Index
description: A contributor's map of this monorepo — what each top-level file and directory is for, and where to go next.
---

# Repository Index

Welcome. The root [`README.md`](../README.md) of this repository is a **profile / portfolio page**, not a developer guide. This page is the developer guide's front door: a map of what lives where, and which document to read next.

> **How to read the tables below.** Everything listed is confirmed to exist in the repository. The *purpose* column is a different matter:
>
> | Marker | Meaning |
> | --- | --- |
> | (no marker) | Purpose is a standard, well-known convention for that filename (e.g. `.gitignore`, `.editorconfig`). |
> | `?` | **Inferred from the name only.** Treat as a hint, not a fact — and please [open a PR](../CONTRIBUTING.md) correcting it if you learn otherwise. |
>
> This page intentionally does **not** restate the contents of the documents it links to. When they disagree with this page, they win.

---

## Start here

| If you want to… | Read |
| --- | --- |
| Contribute changes (workflow, style, review) | [`CONTRIBUTING.md`](../CONTRIBUTING.md) |
| Understand how AI agents are expected to work in this repo | [`AGENTS.md`](../AGENTS.md) and [`CLAUDE.md`](../CLAUDE.md) |
| Understand the data shapes / schema used here | [`SCHEMA.md`](../SCHEMA.md) |
| Clone, initialise, or update the git submodules | [`SUBMODULES.md`](../SUBMODULES.md) |
| See the public-facing profile | [`README.md`](../README.md) |

If you are cloning this repository for the first time, read [`SUBMODULES.md`](../SUBMODULES.md) **before** anything else — the presence of a [`.gitmodules`](../.gitmodules) file means a plain `git clone` will leave you with empty submodule directories.

---

## Top-level layout

### Documentation

| Path | Purpose |
| --- | --- |
| [`README.md`](../README.md) | Profile / portfolio page rendered on the GitHub profile. Not a developer guide. |
| [`CONTRIBUTING.md`](../CONTRIBUTING.md) | Contribution workflow and expectations. **The authoritative source for how to build and change things.** |
| [`AGENTS.md`](../AGENTS.md) | Instructions and conventions for automated / AI agents operating on this repository. |
| [`CLAUDE.md`](../CLAUDE.md) | Claude-specific guidance, complementing `AGENTS.md`. |
| [`SCHEMA.md`](../SCHEMA.md) | Schema documentation for the repository's structured data. |
| [`SUBMODULES.md`](../SUBMODULES.md) | How the git submodules are organised and maintained. |
| `docs/` | Longer-form documentation. This file is its index. |

### Site content and data

| Path | Purpose |
| --- | --- |
| [`index.md`](../index.md) | Site entry page (carries Jekyll-style front matter). |
| [`_config.yml`](../_config.yml) | Primary site configuration. |
| [`_config_dev.yml`](../_config_dev.yml) | Configuration overrides for local development `?` |
| [`Gemfile`](../Gemfile) | Ruby dependencies for the site toolchain. |
| `_data/` | Structured data consumed by the site — see [`SCHEMA.md`](../SCHEMA.md) for its shape `?` |
| `pages/` | Site pages `?` |
| `assets/` | Static assets (images, styles, scripts) `?` |
| `templates/` | Reusable templates / scaffolding `?` |
| `projects/` | Per-project content or checkouts — likely related to the submodules described in [`SUBMODULES.md`](../SUBMODULES.md) `?` |
| `_reports/` | Generated reports or output `?` |

> The `_`-prefixed names (`_config.yml`, `_data/`, `_reports/`) follow Jekyll's convention for build inputs and collections. Check [`_config.yml`](../_config.yml) for which directories are published versus excluded from the built site.

### Automation and tooling

| Path | Purpose |
| --- | --- |
| [`Rakefile`](../Rakefile) | Rake task definitions. Worth inspecting first — repository-specific automation usually lives here `?` |
| `tools/` | Helper scripts and utilities `?` |
| [`fleet.manifest.yml`](../fleet.manifest.yml) | Manifest describing the "fleet" of automated agents/tasks that operate on this repository `?` |
| [`.mcp.json`](../.mcp.json) | Model Context Protocol server configuration for AI tooling `?` |
| `.claude/` | Claude tooling configuration — see [`CLAUDE.md`](../CLAUDE.md) `?` |
| `.github/` | GitHub configuration: workflows, issue templates, and similar. |
| [`.husky/`](../.husky) | Git hooks managed by Husky. |
| [`.pre-commit-config.yaml`](../.pre-commit-config.yaml) | pre-commit hook definitions. |

> Two hook systems are configured (`.husky/` and `.pre-commit-config.yaml`). Confirm with [`CONTRIBUTING.md`](../CONTRIBUTING.md) which one you are expected to install locally, and whether both run in CI.

### Environment and editor setup

| Path | Purpose |
| --- | --- |
| `.devcontainer/` | Dev Container definition — a reproducible containerised environment for VS Code / Codespaces. |
| [`docker-compose.yml`](../docker-compose.yml) | Docker Compose service definitions for running the stack locally. |
| [`.env.example`](../.env.example) | Template for the local environment file. Copy it, fill it in, and never commit the result. |
| [`home.code-workspace`](../home.code-workspace) | VS Code multi-root workspace file — likely the intended way to open this repository together with its submodules `?` |
| `.vscode/` | Shared VS Code settings and recommendations. |
| [`.editorconfig`](../.editorconfig) | Cross-editor formatting rules (indentation, line endings). |
| [`.prettierrc`](../.prettierrc) / [`.prettierignore`](../.prettierignore) | Prettier formatting configuration and exclusions. |
| [`.gitconfig`](../.gitconfig) | Repository-scoped or shareable git configuration `?` |
| [`.zshrc`](../.zshrc) / [`.zprofile`](../.zprofile) | Shell configuration — this repository doubles as a dotfiles/home directory `?` |
| [`.gitmodules`](../.gitmodules) | Submodule definitions. See [`SUBMODULES.md`](../SUBMODULES.md). |
| [`.gitignore`](../.gitignore) | Ignored paths. |

---

## Running the site locally

There appear to be **three** supported paths into a working environment. They are listed here so you know they exist; the canonical, up-to-date commands belong in [`CONTRIBUTING.md`](../CONTRIBUTING.md) and this page deliberately does not duplicate (or guess at) them.

1. **Dev Container** — `.devcontainer/` exists, so opening the repository in VS Code or GitHub Codespaces and reopening in the container should give you a preconfigured environment with no local installation. This is usually the lowest-friction option.
2. **Docker Compose** — [`docker-compose.yml`](../docker-compose.yml) defines the services; read it to see what it starts and on which ports.
3. **Native Ruby toolchain** — [`Gemfile`](../Gemfile), [`_config.yml`](../_config.yml) and [`_config_dev.yml`](../_config_dev.yml) indicate a Ruby/Jekyll-based site you can build directly on your machine, with the `_dev` config presumably layered on for local runs.

Before any of these, copy [`.env.example`](../.env.example) to your local env file and populate it, and initialise the submodules as described in [`SUBMODULES.md`](../SUBMODULES.md).

> **Maintainers:** if `CONTRIBUTING.md` already documents the one blessed command, replace this section with a one-line pointer to it.

---

## Conventions worth knowing

- **Formatting is enforced, not suggested.** `.editorconfig`, `.prettierrc`, `.pre-commit-config.yaml` and `.husky/` all exist; expect hooks to reformat or reject commits. Install them before your first commit.
- **Structured data has a schema.** If you are editing anything under `_data/`, read [`SCHEMA.md`](../SCHEMA.md) first.
- **Parts of this repository are edited by automated agents.** [`AGENTS.md`](../AGENTS.md), [`CLAUDE.md`](../CLAUDE.md), [`fleet.manifest.yml`](../fleet.manifest.yml) and [`.mcp.json`](../.mcp.json) exist for that reason. If a change of yours affects agent behaviour, update those files in the same PR.
- **Submodules mean history lives elsewhere.** Changes inside a submodule belong to that submodule's repository; this repository only records which commit it points at.

---

## Improving this page

Entries marked `?` above are inferences drawn from file and directory names, not from reading the files. If you know better, correcting one is a genuinely useful first contribution — see [`CONTRIBUTING.md`](../CONTRIBUTING.md).
