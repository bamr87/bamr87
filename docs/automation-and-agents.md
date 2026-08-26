---
title: Agent & Automation Configuration
description: An index of the agent, AI-assistant and automation configuration files in this repository, and where to look for each.
updated: 2026-08-25
---

# Agent & Automation Configuration

This repository keeps several agent/automation configuration artifacts at the top level, next to the usual Jekyll files (`_config.yml`, `Gemfile`, `index.md`, `pages/`, `assets/`). If you are new here, that can be confusing: there is more than one file that *looks* like it might be "the instructions for the AI".

This page is the map. It tells you **which files exist and where**, so you know what to open. It does **not** yet summarise what each one says — see [Status of this page](#status-of-this-page) below.

> [!IMPORTANT]
> This page was drafted from the repository's file listing alone. Sections marked
> **⚠️ Unverified** are hypotheses based on ecosystem naming conventions, **not** on
> the contents of the files in this repo. Please confirm against the actual files
> before relying on them, and replace the `TODO` markers as you do.

---

## The artifacts at a glance

| Path | Type | Verified from listing | What it is |
| --- | --- | --- | --- |
| [`AGENTS.md`](../AGENTS.md) | file | ✅ exists at repo root | ⚠️ Unverified — `TODO` |
| [`CLAUDE.md`](../CLAUDE.md) | file | ✅ exists at repo root | ⚠️ Unverified — `TODO` |
| [`.claude/`](../.claude) | directory | ✅ exists at repo root | ⚠️ Unverified — `TODO` |
| [`.mcp.json`](../.mcp.json) | file | ✅ exists at repo root | ⚠️ Unverified — `TODO` |
| [`fleet.manifest.yml`](../fleet.manifest.yml) | file | ✅ exists at repo root | ⚠️ Unverified — `TODO` |

The only thing confirmed above is that each path exists at the repository root and whether it is a file or a directory. Everything else needs a maintainer pass.

---

## `AGENTS.md`

**Path:** `AGENTS.md` (repository root)

**⚠️ Unverified — convention only.** `AGENTS.md` is a cross-vendor convention for a plain-Markdown file of instructions aimed at coding agents: build/test commands, project conventions, things to avoid. See <https://agents.md/> for the general idea. Whether this repository's file follows that convention, and what it actually asks agents to do, has not been checked.

`TODO(maintainer)`: replace this paragraph with a 2–3 sentence summary of what `AGENTS.md` actually covers here, and note which tools read it.

## `CLAUDE.md`

**Path:** `CLAUDE.md` (repository root)

**⚠️ Unverified — convention only.** `CLAUDE.md` is the filename Claude Code reads automatically as project context/instructions (see Anthropic's Claude Code documentation at <https://docs.claude.com/en/docs/claude-code>). The contents of *this* repository's `CLAUDE.md` have not been reviewed.

`TODO(maintainer)`: summarise what it contains, and — importantly — say how it relates to `AGENTS.md`. Common patterns are (a) `CLAUDE.md` is a thin pointer to `AGENTS.md`, (b) they are maintained separately for different tools, or (c) one is a symlink to the other. Please state which applies.

## `.claude/`

**Path:** `.claude/` (directory, repository root)

**⚠️ Unverified.** Only the directory's existence is confirmed; its contents are unknown. In Claude Code projects this directory commonly holds tool-specific assets such as slash commands, subagent definitions, settings and hooks.

`TODO(maintainer)`: list the notable entries inside `.claude/` and what each is for. Also note which of them are committed intentionally versus machine-local (check `.gitignore`).

## `.mcp.json`

**Path:** `.mcp.json` (repository root)

**⚠️ Unverified — convention only.** `.mcp.json` is the conventional filename for project-scoped Model Context Protocol server configuration — the servers an agent is allowed to connect to for extra tools and data. Background:
<https://modelcontextprotocol.io/>.

`TODO(maintainer)`: list the MCP servers configured here and what each provides. Call out any that require credentials — see `.env.example` in the repo root — and say which environment variables are needed.

## `fleet.manifest.yml`

**Path:** `fleet.manifest.yml` (repository root)

**⚠️ Unverified.** This filename does not map to a convention I can point a newcomer at, so it is presumably specific to this repository or to a private automation system.

`TODO(maintainer)`: this one needs the most attention. Explain what a "fleet" manifest is in this context, what consumes the file, what the schema is (or link to `SCHEMA.md` if it is described there), and whether editing it has effects outside this repository.

---

## Which file wins?

The main reason this page exists is that a newcomer cannot tell which document is authoritative when they overlap.

`TODO(maintainer)`: complete the table below. It is left blank on purpose — guessing a precedence order would be worse than leaving it empty.

| Situation | Authoritative source | Notes |
| --- | --- | --- |
| General contribution rules for humans | | |
| Instructions for AI coding agents | | |
| Claude Code specific behaviour | | |
| Tool/MCP server availability | | |
| Fleet / cross-repo automation | | |

---

## Related automation surfaces

These also live at the repository root and are part of the wider automation story, even though they are not agent configuration. Existence is confirmed from the file listing; contents have not been reviewed.

- `.github/` — GitHub configuration; typically Actions workflows and issue/PR templates.
- `.devcontainer/` — Dev Container definition for reproducible development environments.
- `.husky/` — Git hooks.
- `.pre-commit-config.yaml` — pre-commit hook definitions.
- `.editorconfig`, `.prettierrc`, `.prettierignore` — formatting configuration.
- `tools/` — repository tooling (contents unreviewed).
- `Rakefile`, `Gemfile`, `docker-compose.yml`, `_config_dev.yml` — build and local
  development plumbing for the Jekyll site.
- `.env.example` — template for local environment variables.

## Other documentation in this repository

- [`README.md`](../README.md) — project overview and profile page.
- [`CONTRIBUTING.md`](../CONTRIBUTING.md) — contribution guidance.
- [`SCHEMA.md`](../SCHEMA.md) — data/schema documentation.
- [`SUBMODULES.md`](../SUBMODULES.md) — this repository uses Git submodules
  (a `.gitmodules` file is present at the root).

---

## Status of this page

This is a **draft index**, not a finished reference. It was written from the repository's file listing without access to the file contents, so it deliberately stops short of describing behaviour it cannot confirm.

To finish it, open each of the five artifacts above and replace the `TODO` markers and **⚠️ Unverified** notes with what the files actually say. If any of them turn out to be stale or redundant, deleting an entry here is a perfectly good outcome too.
