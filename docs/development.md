---
title: Development Guide
description: Contributor-facing entry point for the bamr87/bamr87 monorepo.
---

# Development Guide

> **Draft.** This page was assembled from the repository's file listing. Sections
> marked **TODO** need a maintainer to fill in exact commands from the config
> files they reference. Nothing here is guessed: where a command was not
> verifiable, it is left blank rather than invented.

## Start here (and not in the root README)

The `README.md` at the root of this repository is a **GitHub profile README**.
Its front matter reads `title: Amr Abdel-Motaleb - Solutions Architect & ERP
Specialist`, and its audience is people visiting the `bamr87` GitHub profile —
not people cloning the repository.

This page is the counterpart: the entry point for anyone who wants to run,
build, or change the code.

## Repository map

The repository is described in its own metadata as a **monorepo**, primary
language **Shell**, default branch **`main`**. Here is what lives at the top
level.

### Documentation

| Path | What it is |
| --- | --- |
| `README.md` | GitHub profile README (visitor-facing, not a build guide) |
| `CONTRIBUTING.md` | Contribution guidelines — **read this first before opening a PR** |
| `AGENTS.md` | Conventions for AI coding agents working in this repository |
| `CLAUDE.md` | Claude-specific project instructions |
| `SCHEMA.md` | Data/content schema documentation (relates to `_data/`) |
| `SUBMODULES.md` | How the git submodules declared in `.gitmodules` are organised |
| `docs/` | Longer-form documentation, including this page |
| `fleet.manifest.yml` | Manifest describing automated agent work on this repository |

### Site content

| Path | What it is |
| --- | --- |
| `index.md` | Site landing page |
| `pages/` | Additional content pages |
| `_data/` | Structured data consumed by the site (see `SCHEMA.md`) |
| `assets/` | Static assets (images, styles, scripts) |
| `templates/` | Reusable templates — *purpose inferred from the directory name* |
| `projects/` | Project entries — *purpose inferred from the directory name* |
| `_reports/` | Generated reports — *purpose inferred from the directory name* |

### Build and tooling

| Path | Tool it configures | Where to look for details |
| --- | --- | --- |
| `Gemfile` | Ruby / Bundler dependencies | `Gemfile` (and `Gemfile.lock` if committed) |
| `Rakefile` | Rake tasks — the repository's task runner | `Rakefile` for the full task list |
| `_config.yml` | Site configuration (production) | `_config.yml` |
| `_config_dev.yml` | Site configuration (development overrides) | `_config_dev.yml` |
| `docker-compose.yml` | Containerised local environment | `docker-compose.yml` for service and port names |
| `.devcontainer/` | VS Code / Codespaces Dev Container | `.devcontainer/devcontainer.json` |
| `.pre-commit-config.yaml` | `pre-commit` hook definitions | `.pre-commit-config.yaml` |
| `.husky/` | Git hooks | scripts inside `.husky/` |
| `.prettierrc`, `.prettierignore` | Prettier formatting rules | the files themselves |
| `.editorconfig` | Editor defaults (indentation, line endings) | `.editorconfig` |
| `.env.example` | Template for local environment variables | copy and fill in as needed |
| `.gitmodules` | Git submodule declarations | `SUBMODULES.md` |
| `.github/` | CI workflows and repository templates | `.github/workflows/` |
| `tools/` | Repository scripts — *purpose inferred from the directory name* |
| `home.code-workspace` | VS Code multi-root workspace file | open in VS Code |
| `.vscode/` | Shared editor settings and tasks | `.vscode/` |
| `.zshrc`, `.zprofile`, `.gitconfig` | Dotfiles managed in this monorepo | the files themselves |
| `.mcp.json` | Model Context Protocol server configuration | `.mcp.json` |
| `.claude/` | Claude agent configuration | `.claude/` |

The combination of `Gemfile`, `_config.yml`, `_config_dev.yml`, `_data/`,
`index.md` and `assets/` is the conventional layout of a **Jekyll** site. Treat
that as a strong inference rather than a confirmed fact until `_config.yml` is
checked.

## Getting a local checkout

1. Clone the repository.
2. **Submodules.** `.gitmodules` is present, so a plain clone will not fetch
   everything. See [`SUBMODULES.md`](../SUBMODULES.md) for the procedure this
   repository expects.
3. **Environment variables.** `.env.example` exists; copy it to the filename
   your tooling expects and fill in the values. **TODO:** document which
   variables are required and what they do.

### Three ways to get an environment

This repository ships configuration for all three, so pick whichever suits you:

- **Dev Container** — open the repository in VS Code or GitHub Codespaces and
  reopen in the container defined by `.devcontainer/`. This is usually the
  lowest-friction option because the toolchain is pinned for you.
- **Docker Compose** — `docker-compose.yml` defines a containerised stack.
  **TODO:** name the services and the port the site is served on.
- **Native** — install Ruby and run Bundler against the `Gemfile`.
  **TODO:** record the Ruby version this repository targets.

## Common tasks

**TODO — fill in from `Rakefile`, `docker-compose.yml` and `.pre-commit-config.yaml`.**
These are intentionally left blank so that nobody copies a command that was
never run against this repository.

| Task | Command |
| --- | --- |
| Install dependencies | _TODO_ |
| Serve the site locally | _TODO_ |
| Build the site for production | _TODO_ |
| List available Rake tasks | _TODO_ |
| Run the linters / formatters | _TODO_ |
| Run the test suite | _TODO_ |

Until the table is filled in, `Rakefile` is the best single place to discover
what automation already exists.

## Checks that run before your commit lands

Two hook systems are configured at the root:

- **`pre-commit`** (`.pre-commit-config.yaml`) — Python-ecosystem hook manager.
  Hooks defined here run against staged files. Install the hooks locally so you
  find failures before CI does.
- **Husky** (`.husky/`) — git hooks driven by the JavaScript ecosystem, likely
  paired with the Prettier configuration (`.prettierrc`, `.prettierignore`).

**TODO:** confirm how the two are meant to coexist, and which one owns
formatting. Note that `.husky/` and `.prettierrc` normally accompany a
`package.json`, which is not present at the repository root — worth clarifying.

CI workflows live in `.github/workflows/`; those are the authoritative checks
for a pull request.

## Where to go next

- Opening a pull request → [`CONTRIBUTING.md`](../CONTRIBUTING.md)
- Editing structured content in `_data/` → [`SCHEMA.md`](../SCHEMA.md)
- Working with submodules → [`SUBMODULES.md`](../SUBMODULES.md)
- Working in this repository with an AI agent → [`AGENTS.md`](../AGENTS.md)
  and [`CLAUDE.md`](../CLAUDE.md)

## Improving this page

If you fill in one of the TODOs above, please do it by reading the config file
named alongside it and pasting the command you actually ran. A guide that is
blank in places is more useful than one that is confidently wrong.
