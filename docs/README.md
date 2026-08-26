---
title: Documentation Index
author: Amr Abdel-Motaleb
description: Navigation hub for the guides and reference material in this repository.
updated: 2026-08-26
---

# Documentation Index

This page exists for one reason: to make the documentation that already lives in
this repository easy to find. The root [`README.md`](../README.md) is a GitHub
profile README — it introduces the person, not the repository — so the guides
sitting next to it are easy to miss.

> **A note on accuracy.** Entries marked _(summary unverified)_ describe a file
> whose contents have not been confirmed by whoever last edited this index. The
> link is correct; the one-line description is an educated guess based on the
> filename and on repository conventions. If you open one of these files and the
> description is wrong, please fix it here — that is the whole point of the
> marker.

---

## Guides at the repository root

| Document | What it covers |
| --- | --- |
| [`README.md`](../README.md) | Profile README: introduction, philosophy, technical stack, professional experience, and consulting services. |
| [`CONTRIBUTING.md`](../CONTRIBUTING.md) | How to contribute to this repository. _(summary unverified)_ |
| [`SCHEMA.md`](../SCHEMA.md) | Schema reference for the structured content in this repository — likely the front matter and/or the data files under `_data/`. _(summary unverified)_ |
| [`SUBMODULES.md`](../SUBMODULES.md) | Working with the Git submodules this repository pulls in. The repository does track submodules — see [`.gitmodules`](../.gitmodules). _(summary unverified)_ |
| [`AGENTS.md`](../AGENTS.md) | Instructions for AI coding agents working in this repository, following the conventional `AGENTS.md` location. _(summary unverified)_ |
| [`CLAUDE.md`](../CLAUDE.md) | Instructions specific to Claude Code. Related configuration lives in [`.claude/`](../.claude) and [`.mcp.json`](../.mcp.json). _(summary unverified)_ |

---

## Repository layout

A map of the top-level directories, to orient a newcomer. Descriptions marked
_(unverified)_ are inferred from directory names and sibling files rather than
from the contents themselves.

| Path | Notes |
| --- | --- |
| [`docs/`](.) | This directory. Longer-form documentation, including this index. |
| `pages/` | Site pages. _(unverified)_ |
| `projects/` | Project content. _(unverified)_ |
| `templates/` | Reusable templates. _(unverified)_ |
| `tools/` | Scripts and tooling. The repository's primary language is Shell. _(unverified)_ |
| `assets/` | Static assets for the site. _(unverified)_ |
| `_data/` | Structured data files consumed by the site build. See [`SCHEMA.md`](../SCHEMA.md). _(unverified)_ |
| `_reports/` | Generated reports. _(unverified)_ |
| `.github/` | GitHub configuration: workflows, issue templates, and similar. _(unverified)_ |
| `.devcontainer/` | Dev Container definition for a reproducible development environment. _(unverified)_ |
| `.vscode/` | Shared editor settings. See also [`home.code-workspace`](../home.code-workspace). _(unverified)_ |
| `.husky/` | Git hook definitions. _(unverified)_ |
| `.claude/` | Claude Code configuration. See [`CLAUDE.md`](../CLAUDE.md). _(unverified)_ |

---

## Configuration files worth knowing about

These are not documentation, but they answer the "how does this thing build and
run?" question that usually comes right after "where are the docs?".

| File | Notes |
| --- | --- |
| [`_config.yml`](../_config.yml) / [`_config_dev.yml`](../_config_dev.yml) | Jekyll site configuration — a production config and a development override. _(unverified)_ |
| [`Gemfile`](../Gemfile) | Ruby dependencies for the site build. |
| [`Rakefile`](../Rakefile) | Rake tasks for this repository. _(unverified)_ |
| [`docker-compose.yml`](../docker-compose.yml) | Container setup for local development. _(unverified)_ |
| [`.env.example`](../.env.example) | Template for the environment variables the project expects. Copy it and fill it in rather than editing it directly. |
| [`.pre-commit-config.yaml`](../.pre-commit-config.yaml) | Pre-commit hook configuration. |
| [`.prettierrc`](../.prettierrc) / [`.prettierignore`](../.prettierignore) | Prettier formatting configuration. |
| [`.editorconfig`](../.editorconfig) | Editor defaults shared across contributors. |
| [`fleet.manifest.yml`](../fleet.manifest.yml) | Manifest describing automated agent work on this repository. _(unverified)_ |

> This index deliberately contains no build, test, or run commands. For those,
> follow [`CONTRIBUTING.md`](../CONTRIBUTING.md), which is the authoritative
> source; duplicating commands here would only create a second place for them to
> go stale.

---

## Keeping this index honest

When you add a guide to the repository root or to `docs/`, add a row here too.
When you open a file marked _(summary unverified)_ and find the description
inaccurate, correct it and drop the marker.
