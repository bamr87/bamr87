---
title: Documentation Index
description: A map of the documentation in this repository and when to read each piece.
---

# Documentation Index

This page lists the documentation that lives in this repository and suggests
which file to open for a given task.

> **Note on accuracy:** the entries below were compiled from the repository's
> file listing. The one-line descriptions are inferred from each file's name and
> conventional usage — the contents of the individual documents were not
> reviewed when this index was written. If a description does not match what a
> document actually covers, please correct it here.

## Start here

| Document | Read it when you want to… |
| --- | --- |
| [`../README.md`](../README.md) | Get an overview of the repository and its author. This is the project's front page and the GitHub profile README. |
| [`../index.md`](../index.md) | See the landing page used by the site build (the repository contains Jekyll configuration — see *Site & build configuration* below). |

## Working on the repository

| Document | Read it when you want to… |
| --- | --- |
| [`../CONTRIBUTING.md`](../CONTRIBUTING.md) | Contribute a change — how to propose work and what is expected of a contribution. |
| [`../SUBMODULES.md`](../SUBMODULES.md) | Understand the Git submodules this repository pulls in. The repository is a monorepo and carries a [`.gitmodules`](../.gitmodules) file, so a checkout is not complete without them. |
| [`../SCHEMA.md`](../SCHEMA.md) | Understand the data schema(s) used by the repository. Related directory: [`_data/`](../_data). |

## Working with AI agents

| Document | Read it when you want to… |
| --- | --- |
| [`../AGENTS.md`](../AGENTS.md) | Understand the conventions agents are expected to follow in this repository. |
| [`../CLAUDE.md`](../CLAUDE.md) | Find Claude-specific instructions and context for this repository. |
| [`../fleet.manifest.yml`](../fleet.manifest.yml) | See the manifest describing automated/agent work against this repository. |
| [`../.mcp.json`](../.mcp.json) | See the Model Context Protocol server configuration. |
| [`../.claude/`](../.claude) | Browse additional Claude configuration checked into the repository. |

## Site & build configuration

These are configuration files rather than prose documentation, but they are the
authoritative source for how the project is built and run. Read them directly —
this index intentionally does not paraphrase their commands.

| File | What it governs |
| --- | --- |
| [`../_config.yml`](../_config.yml) / [`../_config_dev.yml`](../_config_dev.yml) | Jekyll site configuration (production and development). |
| [`../Gemfile`](../Gemfile) | Ruby dependencies. |
| [`../Rakefile`](../Rakefile) | Rake tasks defined for the repository. |
| [`../docker-compose.yml`](../docker-compose.yml) | Container-based local setup. |
| [`../.devcontainer/`](../.devcontainer) | Dev Container definition for editors that support it. |
| [`../.pre-commit-config.yaml`](../.pre-commit-config.yaml), [`../.husky/`](../.husky), [`../.prettierrc`](../.prettierrc), [`../.editorconfig`](../.editorconfig) | Formatting and pre-commit hooks. |
| [`../.github/`](../.github) | GitHub workflows, issue templates and other GitHub metadata. |
| [`../.env.example`](../.env.example) | Template for the environment variables the project expects. |

## Other content directories

| Directory | Contents |
| --- | --- |
| [`../pages/`](../pages) | Site pages. |
| [`../projects/`](../projects) | Project content. |
| [`../templates/`](../templates) | Templates used across the repository. |
| [`../tools/`](../tools) | Tooling and scripts. |
| [`../assets/`](../assets) | Static assets for the site. |
| [`../_data/`](../_data) | Structured data consumed by the site (see [`../SCHEMA.md`](../SCHEMA.md)). |
| [`../_reports/`](../_reports) | Generated reports. |

## Inside this directory

<!-- TODO: enumerate the files in docs/ here.
     This section was left as a placeholder because the contents of docs/ were
     not available when this index was drafted. Please list each file with a
     one-line description of what it covers. -->

The contents of `docs/` are not yet listed on this page. If you add a document
here, please add a row for it above so the index stays complete.

## Keeping this page current

When you add, rename or remove a documentation file, update the corresponding
entry on this page in the same change.
