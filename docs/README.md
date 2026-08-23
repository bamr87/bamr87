---
title: Documentation Index
description: Entry point for people working on this repository, as opposed to reading the profile README.
---

# Documentation

Welcome. The [root `README.md`](../README.md) of this repository doubles as a GitHub **profile** page, so it is written for visitors rather than contributors. This page is the entry point for anyone who wants to work *on* the repository.

> **Note on this index:** it is built from the repository's top-level file listing. Each entry below names a file that exists and describes what it is *expected* to cover based on its name and conventional usage. Where a document's contents have not been summarised here, open the file itself — it is the authoritative source.

## Start here

| Document | What it is for |
| --- | --- |
| [`CONTRIBUTING.md`](../CONTRIBUTING.md) | Contribution guidelines — read this before opening a pull request. Treat it as the authoritative source for setup, workflow and review expectations. |
| [`SUBMODULES.md`](../SUBMODULES.md) | Guidance for the Git submodules used by this repository. A `.gitmodules` file is present at the root, so a fresh clone is likely to need submodule initialisation before it is complete. |
| [`SCHEMA.md`](../SCHEMA.md) | The content/front-matter schema used across the repository. |

## Working with automation and agents

This repository carries several files that describe how automated tooling and AI assistants are expected to behave in it:

| File | What it is for |
| --- | --- |
| [`AGENTS.md`](../AGENTS.md) | Conventions and instructions for agents operating on this repository. |
| [`CLAUDE.md`](../CLAUDE.md) | Project-specific guidance for Claude / Claude Code sessions. |
| [`fleet.manifest.yml`](../fleet.manifest.yml) | Manifest describing the automation fleet configured for this repository. |
| `.claude/`, `.mcp.json` | Assistant and Model Context Protocol configuration. |

## Build, tooling and environment

These exist at the repository root. **Do not assume the commands** — check `CONTRIBUTING.md` and the files themselves for the invocations this project actually supports.

| File or directory | What it is |
| --- | --- |
| `Gemfile` | Ruby dependencies. Together with `_config.yml` / `_config_dev.yml` this indicates a Jekyll-based site. |
| `_config.yml`, `_config_dev.yml` | Jekyll site configuration (production and development variants). |
| `Rakefile` | Rake tasks for the repository. Run `rake -T` to list what is available. |
| `docker-compose.yml` | Container definitions for local development. |
| `.devcontainer/` | VS Code Dev Container definition. |
| `.github/` | GitHub Actions workflows and repository metadata. |
| `.pre-commit-config.yaml`, `.husky/` | Pre-commit and Git hook configuration. |
| `.editorconfig`, `.prettierrc`, `.prettierignore` | Formatting configuration. Please keep these settings rather than reformatting to personal preference. |
| `.env.example` | Template for local environment variables. Copy it, fill it in, and never commit the result — see `.gitignore`. |
| `home.code-workspace`, `.vscode/` | VS Code workspace and editor settings. |

## Repository layout

Top-level directories, with the role suggested by their name and by the Jekyll configuration at the root:

- `docs/` — this documentation set.
- `pages/` — site pages.
- `projects/` — project entries.
- `templates/` — reusable templates.
- `tools/` — scripts and utilities.
- `assets/` — static assets (images, styles, scripts).
- `_data/` — Jekyll data files.
- `_reports/` — generated reports.

The repository is also home to shell environment files (`.zshrc`, `.zprofile`, `.gitconfig`), which is consistent with it being described as a monorepo with Shell as its primary language.

## Contributing to these docs

Documentation changes are welcome and follow the same process as code changes — see [`CONTRIBUTING.md`](../CONTRIBUTING.md). If you add a document under `docs/`, please link it from this index so it stays discoverable.
