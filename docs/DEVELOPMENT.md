---
title: Development Guide
description: How to get this monorepo running locally, and what lives where.
status: draft
---

# Development Guide

> **Status: draft.** This guide was assembled from the repository's file listing.
> Sections marked **TODO (unverified)** still need the exact commands copied out
> of the corresponding file (`Rakefile`, `docker-compose.yml`,
> `.devcontainer/devcontainer.json`, `.github/workflows/`). Please do not treat a
> TODO section as if the command were missing — treat it as *not yet confirmed*.

## Why this file exists (and not the root README)

The `README.md` at the root of this repository is a **GitHub profile README**. It renders on <https://github.com/bamr87> and is written for that audience — it opens with `title: Amr Abdel-Motaleb - Solutions Architect & ERP Specialist`, carries badge rows and résumé sections, and says of itself:

> Yes, this is a profile README - but it is also a living map of the projects and
> systems I actively maintain.

But this repository is also a **monorepo** with a real toolchain at its root: `Gemfile`, `Rakefile`, `_config.yml`, `docker-compose.yml`, `.devcontainer/`, `.husky/`, `.pre-commit-config.yaml`, `.github/`.

Those two audiences don't mix well in one file, so:

- **`README.md`** — the public profile. Please keep it profile-shaped.
- **`docs/DEVELOPMENT.md`** (this file) — how to clone, install, run and test.
- **`CONTRIBUTING.md`** — contribution process and expectations.

## Repository map

Everything at the repository root, and what it is. Entries whose purpose is inferred from the filename rather than read from the file are marked *(inferred)* — correct them as you verify them.

### Documentation and entry points

| Path | What it is |
| --- | --- |
| `README.md` | GitHub profile README (see above). Not the contributor entry point. |
| `CONTRIBUTING.md` | Contribution guidelines. |
| `AGENTS.md` | Conventions for AI/automation agents working in this repo. *(inferred)* |
| `CLAUDE.md` | Instructions specific to Claude-based tooling. *(inferred)* |
| `SCHEMA.md` | Data/front-matter schema documentation. *(inferred)* |
| `SUBMODULES.md` | **Authoritative** guide to this repo's git submodules — read it before working with `.gitmodules`. |
| `docs/` | Longer-form documentation, including this file. |
| `index.md` | Site landing page for the generated site. *(inferred)* |

### Build, run and dependency management

| Path | What it is |
| --- | --- |
| `Gemfile` | Ruby dependency manifest. Open it for the required Ruby/gem versions. |
| `Rakefile` | The task runner. **This is where the canonical build/serve/test commands live.** |
| `_config.yml` | Primary site configuration. *(inferred: Jekyll-style)* |
| `_config_dev.yml` | Development overrides layered on top of `_config.yml`. *(inferred)* |
| `docker-compose.yml` | Containerised local environment. |
| `.devcontainer/` | VS Code / Codespaces dev container definition. |
| `.env.example` | Template for local environment variables. |
| `home.code-workspace` | VS Code multi-root workspace file. |
| `.vscode/` | Shared editor settings and tasks. |

### Content and assets

| Path | What it is |
| --- | --- |
| `_data/` | Structured data consumed by the site. *(inferred)* |
| `_reports/` | Generated or collected reports. *(inferred)* |
| `assets/` | Static assets (images, CSS, JS). *(inferred)* |
| `diagrams/` | Architecture and process diagrams. *(inferred)* |
| `pages/` | Site pages. *(inferred)* |
| `projects/` | Per-project content or subprojects. *(inferred)* |
| `templates/` | Reusable templates. *(inferred)* |
| `tools/` | Helper scripts and utilities. *(inferred)* |

### Quality gates and automation

| Path | What it is |
| --- | --- |
| `.github/` | Issue/PR templates and CI workflows. |
| `.pre-commit-config.yaml` | pre-commit hook definitions. |
| `.husky/` | Git hooks managed by Husky. |
| `.editorconfig` | Cross-editor whitespace/encoding rules. |
| `.prettierrc`, `.prettierignore` | Prettier formatting configuration. |
| `.markdownlintignore` | Paths excluded from markdown linting. |
| `.gitignore`, `.gitmodules`, `.gitconfig` | Git configuration; `.gitmodules` means this repo has submodules. |
| `.zshrc`, `.zprofile` | Shell configuration tracked in the repo (dotfiles). *(inferred)* |
| `.mcp.json` | Model Context Protocol server configuration. *(inferred)* |
| `.claude/` | Claude tooling configuration. *(inferred)* |
| `fleet.manifest.yml` | Manifest for automated agent runs against this repo. *(inferred)* |

## Getting the source

This repository contains a `.gitmodules` file, so a plain `git clone` will leave submodule directories empty. The standard git incantation is:

```bash
git clone --recurse-submodules https://github.com/bamr87/bamr87.git
cd bamr87
```

If you already cloned without `--recurse-submodules`:

```bash
git submodule update --init --recursive
```

> **See [`SUBMODULES.md`](../SUBMODULES.md) for this repository's actual submodule
> policy** — which submodules exist, whether they're required for a normal build,
> and how they're updated. The two commands above are generic git usage, not
> repo-specific instructions.

## Setting up an environment

There appear to be three supported paths. Pick one.

### 1. Dev container (VS Code / GitHub Codespaces)

A `.devcontainer/` directory is present, so opening the repository in VS Code with the Dev Containers extension (or in a Codespace) should offer to build and reopen in the container.

**TODO (unverified):** record the base image, the installed features, and any `postCreateCommand` from `.devcontainer/devcontainer.json`, so contributors know what the container gives them for free.

### 2. Docker Compose

A `docker-compose.yml` is present at the root. `devenv` is the primary workspace container (the repo is mounted at `/workspace`); the rest are optional.

```bash
docker compose up -d devenv
docker compose exec devenv bash
docker compose up -d console           # the Harness Console — http://127.0.0.1:4001 (or: tools/dash console)
docker compose up -d phoenix           # Phoenix traces — http://127.0.0.1:6006 (tools/dash lake export ships traces to it)
docker compose --profile admin up -d   # adds pgAdmin
docker compose down -v                 # stop and wipe volumes
```

The `console` service is the local control plane's **front end**: it renders every committed fleet signal, runs the allowlisted `tools/dash` operations as jobs with live logs, dispatches the control-plane workflows, and edits the `harnesses:` contract — dry-run by default, confirm-gated for anything that writes to GitHub, never a commit. Its credentials come from `.env` (`FLEET_TOKEN` / `GH_TOKEN` / the Claude tokens, by name). See [HARNESS-OPS.md](HARNESS-OPS.md) and [`tools/console/README.md`](../tools/console/README.md).

The `phoenix` service is the local stack's trace store ([Arize Phoenix](https://github.com/Arize-ai/phoenix)): `tools/dash lake sync` extracts the fleet's GitHub records (runs, jobs, steps, run logs, issues, workflow files, `.factory/` blueprints) into the gitignored `.dash-lake/fleet.sqlite`, and `tools/dash lake export [--local]` turns the agent runs — and, optionally, this machine's Claude Code sessions — into OpenInference traces you browse at :6006. The console's **Traces** tab drives both.

Ports and services are tabulated in [DASH.md](DASH.md) — that table is maintained in exactly one place.

### 3. Local Ruby toolchain

The root has a `Gemfile` and a `Rakefile`.

**TODO (unverified):** record the required Ruby version (check `Gemfile` and any `.ruby-version`), the bundler install step, and any system prerequisites.

### Environment variables

Copy `.env.example` to `.env` and fill in the values before running anything that needs credentials:

```bash
cp .env.example .env
```

**TODO (unverified):** list which variables in `.env.example` are required versus optional, and what each one is for. `.env` must stay untracked — confirm it is covered by `.gitignore`.

## Building, serving and testing

**TODO (unverified) — this is the most important gap in this guide.**

The `Rakefile` is the task runner for this repository, and `.github/` should contain the workflows that run in CI. Between them they define the real, authoritative commands. Please fill in this section by:

1. Running `rake -T` (or reading the `Rakefile`) and listing the tasks a
   contributor actually needs: build, serve locally, test, lint, clean.
2. Reading `.github/workflows/*` and documenting exactly what CI runs, so a
   contributor can reproduce a CI failure locally.
3. Explaining when `_config_dev.yml` is used instead of (or in addition to)
   `_config.yml`.

Do not guess these commands from the presence of a `Gemfile` — copy them from the files.

## Code quality and git hooks

Several quality gates are configured at the root:

- **`.pre-commit-config.yaml`** — pre-commit framework hooks. Install them once
  per clone so they run automatically on `git commit`.
- **`.husky/`** — Husky-managed git hooks.
- **`.prettierrc` / `.prettierignore`** — Prettier formatting rules and exclusions.
- **`.markdownlintignore`** — files excluded from markdown linting.
- **`.editorconfig`** — baseline whitespace and encoding rules; most editors apply
  this automatically.

**TODO (unverified):** document the one-time hook installation step, list which hooks run at which stage, and state how to run the linters manually (e.g. across all files) so a contributor can fix issues before committing.

**Open inconsistency:** `.husky/` and `.prettierrc` normally accompany a Node.js project with a `package.json`, but no `package.json` appears at the repository root. Either it lives in a subdirectory, or the Node tooling is installed some other way. Please clarify — a newcomer will hit this immediately.

## Automation and agent configuration

This repository carries configuration for AI/automation tooling: `AGENTS.md`, `CLAUDE.md`, `.claude/`, `.mcp.json` and `fleet.manifest.yml`.

If you are contributing by hand, you can ignore these. If you are configuring or debugging automation, start with `AGENTS.md`.

**TODO (unverified):** summarise what `fleet.manifest.yml` controls and who consumes it.

## Open questions for maintainers

Collected here so they're easy to close out. Each one is a gap that a newcomer will hit:

1. What are the tasks in the `Rakefile`? (blocks the entire build/test section)
2. What does CI run — which workflows exist under `.github/workflows/`?
3. Which Ruby version is required, and are there system-level prerequisites?
4. What services does `docker-compose.yml` define, and on which ports?
5. What does `.devcontainer/devcontainer.json` set up, and does it run a
   post-create command?
6. Where is the `package.json` that `.husky/` and Prettier imply?
7. Which variables in `.env.example` are required for a local run?
8. Which submodules are required for a normal build, per `SUBMODULES.md`?
9. When is `_config_dev.yml` used instead of `_config.yml`?
10. Does `docs/` already contain a development guide that overlaps with this one?

## See also

- [`CONTRIBUTING.md`](../CONTRIBUTING.md) — contribution process
- [`SUBMODULES.md`](../SUBMODULES.md) — submodule workflow
- [`SCHEMA.md`](../SCHEMA.md) — data/front-matter schema
- [`AGENTS.md`](../AGENTS.md) — conventions for automation agents
