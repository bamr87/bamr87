---
title: Repository Orientation
author: Amr Abdel-Motaleb
updated: 2026-09-03
---

# About this repository

`bamr87/bamr87` does two jobs at once, which can be confusing on first visit.

1. **It is a GitHub profile repository.** Because the repository name matches the
   account name, GitHub renders [`README.md`](../README.md) at the top of
   <https://github.com/bamr87>. That file is a bio: background, technical stack,
   professional experience, and consulting services.
2. **It is also a monorepo.** Behind the profile README sits a working codebase —
a static site, shared data and assets, submodules pointing at other projects, schema and catalog documentation, and a fair amount of tooling and automation configuration.

If you arrived expecting only a bio, this page is the map of everything else.

## Directory map

Every entry below exists at the top level of the default branch (`main`).

### Site and content

| Path | What it is |
| --- | --- |
| [`index.md`](../index.md) | Site entry page. |
| `pages/` | Additional site pages. |
| `_data/` | Structured data consumed by the site. |
| `assets/` | Images, styles, and other static assets. |
| `_config.yml` | Primary site configuration. |
| `_config_dev.yml` | Configuration overrides for local development. |
| `Gemfile` | Ruby dependencies for the site build. |
| `Rakefile` | Rake tasks for the repository. |

> The combination of `_config.yml`, `_data/`, a `Gemfile`, and YAML front matter
> in the markdown files is the conventional shape of a **Jekyll** site. Treat that
> as a strong hint rather than a confirmed fact until you have read `_config.yml`.

### Documentation

| Path | What it covers |
| --- | --- |
| [`README.md`](../README.md) | The profile README rendered on the GitHub account page. |
| [`CONTRIBUTING.md`](../CONTRIBUTING.md) | How to contribute to this repository. |
| [`SUBMODULES.md`](../SUBMODULES.md) | How the git submodules in this repo are organised and used. |
| [`SCHEMA.md`](../SCHEMA.md) | Schema documentation for the repository's structured data. |
| [`CATALOG.md`](../CATALOG.md) | Catalog of the repository's contents. |
| [`AGENTS.md`](../AGENTS.md) | Guidance for automated agents working in this repo. |
| [`CLAUDE.md`](../CLAUDE.md) | Claude-specific working notes. |
| `docs/` | Longer-form documentation, including this page. |
| `diagrams/` | Diagram sources and/or rendered diagrams. |
| `specs/` | Specifications. |
| `_reports/` | Generated reports. |

### Projects, templates, and tooling

| Path | What it is |
| --- | --- |
| `projects/` | Project directories tracked by this monorepo. |
| `templates/` | Reusable templates. |
| `tools/` | Repository tooling and scripts. |
| `.gitmodules` | Submodule definitions — see [`SUBMODULES.md`](../SUBMODULES.md). |

### Environment and automation configuration

| Path | Purpose |
| --- | --- |
| `.devcontainer/` | Dev container definition for reproducible environments. |
| `docker-compose.yml` | Container service definitions. |
| `.github/` | GitHub configuration, including any workflows. |
| `.vscode/`, `home.code-workspace` | Editor configuration and workspace file. |
| `.husky/`, `.pre-commit-config.yaml` | Git hook configuration. |
| `.prettierrc`, `.prettierignore`, `.markdownlintignore`, `.editorconfig` | Formatting and lint configuration. |
| `.env.example` | Template for local environment variables — copy, do not commit the result. |
| `.zshrc`, `.zprofile`, `.gitconfig` | Shell and git dotfiles tracked in the repo. |
| `fleet.manifest.yml`, `.mcp.json`, `.claude/` | Agent and automation configuration. |

## Getting oriented as a newcomer

A reasonable reading order:

1. **[`CONTRIBUTING.md`](../CONTRIBUTING.md)** — start here for the contribution
   workflow and any expectations about branches, commits, and review.
2. **[`SUBMODULES.md`](../SUBMODULES.md)** — this repository uses git submodules
(`.gitmodules`), so a plain `git clone` will leave those directories empty. Read this before wondering why something looks missing.
3. **[`CATALOG.md`](../CATALOG.md)** — an index of what lives where.
4. **[`SCHEMA.md`](../SCHEMA.md)** — if you are touching anything under `_data/`
   or otherwise structured, the schema is documented here.

## Building and running

This page deliberately does **not** list build, serve, or test commands, because they have not been verified against the repository's actual configuration. The authoritative sources are:

- `Gemfile` and `Rakefile` for Ruby-based tasks,
- `docker-compose.yml` and `.devcontainer/` for containerised setups,
- `.github/` for whatever CI runs on pull requests,
- `CONTRIBUTING.md` for the maintainer's own instructions.

If you work out the canonical local-development commands, adding them here is a welcome contribution.

## A note on editing the profile README

[`README.md`](../README.md) is public-facing on the GitHub account page. Changes to it are visible to anyone who visits <https://github.com/bamr87>, so treat edits there with more care than edits to files under `docs/`.
