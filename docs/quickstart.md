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
> a starting point and prefer whatever `tools/dash`, `CONTRIBUTING.md` or the CI
> workflows in `.github/` say. If you confirm or correct a step, please delete its
> warning block so the next person doesn't have to re-check it.

---

## What this repository is

`bamr87/bamr87` is a **monorepo** — a GitHub profile repository that also acts as the home for a collection of projects and site content. Signals of its shape, all visible in the repository root:

| Evidence | What it suggests |
|---|---|
| `tools/console/`, `pages/`, `_data/profile.yml` | The public site — the Harness Console's page built static ([CONSOLE-PAGES.md](CONSOLE-PAGES.md)) |
| `.gitmodules`, `SUBMODULES.md` | Content is composed from **git submodules** |
| `tools/dash` | Repository tasks are exposed through the **dash CLI** |
| `docker-compose.yml`, `.devcontainer/` | A **container-based** development path exists |
| `.pre-commit-config.yaml`, `.husky/`, `.prettierrc`, `.editorconfig` | Automated formatting and pre-commit hooks |
| `AGENTS.md`, `CLAUDE.md`, `.claude/`, `.mcp.json`, `fleet.manifest.yml` | Automation/agent tooling conventions |
| `SCHEMA.md`, `_data/`, `templates/`, `tools/` | Structured data, templates, and helper scripts |

The repository's primary language is reported as **Shell**, and the default branch is **`main`**.

---

## Prerequisites

Install whichever path you plan to use.

- **Git** — required for every path (this repo uses submodules).
- **Python 3 and Node (current LTS)** — for the local path: the Harness Console
  (`tools/console/`) and the public site build use nothing else.
- **Docker** — for the container path (`docker-compose.yml` is present).
- **VS Code + Dev Containers extension** — optional; a `.devcontainer/` directory is
  present, and `home.code-workspace` is the consolidated VS Code multi-root workspace.

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
tools/dash console    # creates .venv-console and installs the page's packages on first run
pip install pre-commit && pre-commit install
```

Every install resolves the newest published versions (no lockfiles — [DEPENDENCIES.md](DEPENDENCIES.md)).

## 5. Discover the supported tasks

Before running anything else, ask the repository what it supports:

```bash
tools/dash            # every command, with a one-line description
```

`tools/dash` is the repository's task entry point; it reuses the scripts under `tools/`.

Also worth reading:

- [`CONTRIBUTING.md`](../CONTRIBUTING.md) — contribution workflow and expectations.
- `.github/` — the CI workflow definitions are the authoritative statement of what
  must pass before a change is merged.

## 6. Serve the site locally

```bash
tools/dash serve      # the public site, built static exactly as Pages publishes it → http://127.0.0.1:4000
tools/dash console    # the same page live, with the console behind it → http://127.0.0.1:4001
```

### Container-based alternative

A `docker-compose.yml` and a `.devcontainer/` directory are both present, so a container path exists and avoids installing the toolchain locally.

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
> 1. `tools/run-all-tests.sh` and `tools/check-drift.sh` — the aggregate suite and the drift gate.
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
| `pages/` | Site content: `profile/*.md` and `posts/*.md` |
| `projects/` | Project content, likely including git submodules |
| `tools/console/` | The Harness Console — and, built static, the public site |
| `_data/` | Structured data consumed by the site; see [`SCHEMA.md`](../SCHEMA.md) |
| `templates/` | Reusable templates |
| `tools/` | Helper scripts (the repo's primary language is Shell) |
| `docs/` | Documentation, including this page |
| `_reports/` | Generated reports |
| `.devcontainer/` | VS Code Dev Container definition |
| `.github/` | GitHub configuration and CI workflows |
| `.claude/`, `.mcp.json` | Agent/automation tooling configuration; see [`AGENTS.md`](../AGENTS.md) and [`CLAUDE.md`](../CLAUDE.md) |

Key root files: `README.md` (the profile page), `CONTRIBUTING.md`, `SUBMODULES.md`, `SCHEMA.md`, `AGENTS.md`, `CLAUDE.md`, `fleet.manifest.yml`, `home.code-workspace` (the consolidated VS Code workspace).

---

## If you get stuck

1. `tools/dash` — the list of supported tasks.
2. [`CONTRIBUTING.md`](../CONTRIBUTING.md) — workflow and conventions.
3. [`SUBMODULES.md`](../SUBMODULES.md) — anything submodule-related.
4. `.github/` workflows — the exact commands CI runs, which always beat this page.
