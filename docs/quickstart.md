---
title: Quick start
description: Get a first clone of this monorepo running locally.
updated: 2026-08-23
---

# Quick start

This page walks a newcomer from a fresh clone to a running local copy.

> [!IMPORTANT]
> **Draft — commands below are inferred from files in the repository root, not from a
> verified run.** Each step names the file it was inferred from. Steps marked
> "needs verification" have not been executed against this repository; treat them as
> a starting point and prefer whatever `rake -T`, `CONTRIBUTING.md` or the CI
> workflows in `.github/` say. If you confirm or correct a step, please delete its
> warning block so the next person doesn't have to re-check it.

---

## What this repository is

`bamr87/bamr87` is a **monorepo** — a GitHub profile repository that also acts as the home for a collection of projects and site content. Signals of its shape, all visible in the repository root:

| Evidence | What it suggests |
|---|---|
| `_config.yml`, `_config_dev.yml`, `index.md`, `pages/`, `assets/`, `Gemfile` | A **Jekyll** static site, with a separate development config |
| `.gitmodules`, `SUBMODULES.md` | Content is composed from **git submodules** |
| `Rakefile` | Repository tasks are exposed through **Rake** |
| `docker-compose.yml`, `.devcontainer/` | A **container-based** development path exists |
| `.pre-commit-config.yaml`, `.husky/`, `.prettierrc`, `.editorconfig` | Automated formatting and pre-commit hooks |
| `AGENTS.md`, `CLAUDE.md`, `.claude/`, `.mcp.json`, `fleet.manifest.yml` | Automation/agent tooling conventions |
| `SCHEMA.md`, `_data/`, `templates/`, `tools/` | Structured data, templates, and helper scripts |

The repository's primary language is reported as **Shell**, and the default branch is **`main`**.

---

## Prerequisites

Install whichever path you plan to use.

- **Git** — required for every path (this repo uses submodules).
- **Ruby + Bundler** — for the local path. A `Gemfile` is present at the repository
  root.
  <!-- verify: check the Gemfile / .ruby-version / Gemfile.lock for the required Ruby version -->
  > [!WARNING]
  > The required Ruby version is **not documented here** because it was not verified.
  > Check the `Gemfile` (and a `.ruby-version` file, if one exists) before installing.
- **Docker** — for the container path (`docker-compose.yml` is present).
- **VS Code + Dev Containers extension** — optional; a `.devcontainer/` directory is
  present, and `home.code-workspace` suggests a prepared VS Code workspace.

---

## 1. Clone

```bash
git clone https://github.com/bamr87/bamr87.git
cd bamr87
```

## 2. Initialise submodules

A `.gitmodules` file exists at the repository root, so a plain clone will leave submodule directories empty. Either clone recursively:

```bash
git clone --recurse-submodules https://github.com/bamr87/bamr87.git
```

or, if you already cloned:

```bash
git submodule update --init --recursive
```

> [!NOTE]
> See [`SUBMODULES.md`](../SUBMODULES.md) for what the submodules are and how they are
> expected to be updated. The list of submodules is intentionally not duplicated here,
> to avoid it drifting out of date.

## 3. Create your environment file

An `.env.example` file is present at the repository root. The usual convention is:

```bash
cp .env.example .env
```

Then fill in the values.

> [!WARNING]
> **Needs verification.** `.env.example` exists, but which tooling reads `.env` — and
> which variables are actually required to serve the site locally versus optional —
> has not been confirmed. Read `.env.example`'s own comments before assuming any
> variable is mandatory. Never commit `.env`.

## 4. Install dependencies

```bash
bundle install
```

This is inferred from the presence of a root `Gemfile`.

> [!WARNING]
> **Needs verification.** There may be additional dependency steps — for example a
> Node/npm install (the repository contains `.husky/`, `.prettierrc` and
> `.prettierignore`, which are Node-ecosystem tools) or a `pre-commit install` step
> (`.pre-commit-config.yaml` is present). Check `CONTRIBUTING.md` and `rake -T`.

## 5. Discover the supported tasks

Before running anything else, ask the repository what it supports:

```bash
rake -T
```

`rake -T` lists every documented Rake task with its description. Because a `Rakefile` exists at the repository root, **this is the most reliable way to find the real, current commands for this project** — more reliable than this page. No specific task name is claimed in this document, precisely because none has been verified.

Also worth reading:

- [`CONTRIBUTING.md`](../CONTRIBUTING.md) — contribution workflow and expectations.
- `.github/` — the CI workflow definitions are the authoritative statement of what
  must pass before a change is merged.

## 6. Serve the site locally

The repository contains both `_config.yml` and `_config_dev.yml`, which is the standard Jekyll pattern of layering a development override on top of the production configuration:

```bash
bundle exec jekyll serve --config _config.yml,_config_dev.yml
```

> [!WARNING]
> **Needs verification.** This command is the conventional Jekyll invocation for a
> layered config, not a confirmed command for this repository. In particular it is
> unconfirmed that (a) `jekyll` is a dependency in the `Gemfile`, (b) `_config_dev.yml`
> is meant to be layered rather than passed alone, and (c) there is not already a Rake
> task that wraps this. **Run `rake -T` first** — if a serve task exists, prefer it.

### Container-based alternative

A `docker-compose.yml` and a `.devcontainer/` directory are both present, so a container path exists and avoids installing Ruby locally.

- **Dev Container:** open the folder in VS Code and choose *Reopen in Container*.
- **Docker Compose:** the entry point is likely `docker compose up`.

> [!WARNING]
> **Needs verification.** Service names, exposed ports, and the intended compose
> command have not been confirmed. Read `docker-compose.yml` — the `services:` keys and
> `ports:` entries tell you what to run and which URL to open.

## 7. Run the checks

> [!WARNING]
> **Not yet documented.** No test command has been verified for this repository. Rather
> than guess, use these two sources of truth:
>
> 1. `rake -T` — look for tasks named `test`, `check`, `lint`, `validate` or similar.
> 2. `.github/` — the CI workflow files define exactly what runs on a pull request.
>    Whatever CI runs is what your change must pass.
>
> Note also that `.pre-commit-config.yaml` and `.husky/` exist, so some checks are
> likely wired to run automatically on commit once hooks are installed.

---

## Repository layout

Top-level directories and what the surrounding files suggest they hold:

| Path | Purpose (inferred) |
|---|---|
| `pages/` | Site pages |
| `projects/` | Project content, likely including git submodules |
| `assets/` | Static assets for the site |
| `_data/` | Structured data consumed by the site; see [`SCHEMA.md`](../SCHEMA.md) |
| `templates/` | Reusable templates |
| `tools/` | Helper scripts (the repo's primary language is Shell) |
| `docs/` | Documentation, including this page |
| `_reports/` | Generated reports |
| `.devcontainer/` | VS Code Dev Container definition |
| `.github/` | GitHub configuration and CI workflows |
| `.claude/`, `.mcp.json` | Agent/automation tooling configuration; see [`AGENTS.md`](../AGENTS.md) and [`CLAUDE.md`](../CLAUDE.md) |

Key root files: `README.md` (the profile page), `CONTRIBUTING.md`, `SUBMODULES.md`, `SCHEMA.md`, `AGENTS.md`, `CLAUDE.md`, `Rakefile`, `Gemfile`, `fleet.manifest.yml`, `home.code-workspace`.

---

## If you get stuck

1. `rake -T` — the definitive list of supported tasks.
2. [`CONTRIBUTING.md`](../CONTRIBUTING.md) — workflow and conventions.
3. [`SUBMODULES.md`](../SUBMODULES.md) — anything submodule-related.
4. `.github/` workflows — the exact commands CI runs, which always beat this page.
