---
title: Repository Layout
description: A map of every top-level file and directory in this repository and what it is for.
---

# Repository Layout

This repository is a **monorepo**: the root holds a Jekyll-style site, agent and
automation configuration, shell/dotfile artifacts, and several content
directories side by side. That mix is useful once you know it, but it is
disorienting on a first visit.

This page exists to answer one question: *what is that thing in the root, and
why is it there?* Every top-level entry is listed below.

> **How to read this page.** Entries marked ⚠️ are **inferred from the file or
> directory name and common convention**, not confirmed by reading the file. If
> you are the maintainer, please correct anything wrong — and if you are a
> newcomer, treat ⚠️ lines as "probably, but check" rather than as fact.
>
> This page intentionally contains **no install, build, or test commands**. For
> those, see the local development guide elsewhere in `docs/` and the project
> `README.md`; commands are only trustworthy when they are kept next to the
> tooling that defines them.

---

## At a glance

The root splits into four themes:

| Theme | Entries |
| --- | --- |
| **Site** — the published Jekyll site | `_config.yml`, `_config_dev.yml`, `_data/`, `assets/`, `pages/`, `index.md`, `Gemfile`, `Rakefile` |
| **Agents & automation** — how AI agents and CI act on this repo | `.claude/`, `.mcp.json`, `AGENTS.md`, `CLAUDE.md`, `fleet.manifest.yml`, `.github/` |
| **Content & knowledge** — the material the site and the author work from | `projects/`, `templates/`, `diagrams/`, `docs/`, `_reports/` |
| **Environment & tooling** — how a machine is set up to work here | `.devcontainer/`, `docker-compose.yml`, `.zshrc`, `.zprofile`, `.gitconfig`, `.husky/`, `.pre-commit-config.yaml`, `.editorconfig`, `.prettierrc`, `.prettierignore`, `.markdownlintignore`, `.vscode/`, `home.code-workspace`, `tools/`, `.gitmodules`, `.env.example`, `.gitignore` |

---

## 1. The site

The root looks like a **Jekyll** static site: a `_config.yml`, a `_data/`
directory, an `index.md` entry page, and a `Gemfile` for Ruby dependencies are
the canonical Jekyll signature, and the author's `README.md` lists Jekyll among
the tools they work with. ⚠️ *This has not been confirmed by reading `Gemfile`;
check that the `jekyll` gem is declared there before relying on it.*

| Entry | Type | Purpose |
| --- | --- | --- |
| `_config.yml` | file | Primary site configuration. ⚠️ Assumed to be the Jekyll site config (title, base URL, plugins, collections). |
| `_config_dev.yml` | file | A development-time configuration overlay. ⚠️ Jekyll conventionally layers a second config over the first for local runs (e.g. a different host or base URL); the exact overrides here have not been read. |
| `_data/` | directory | Structured data consumed by the site's templates. ⚠️ In Jekyll, files here (YAML/JSON/CSV) are exposed to templates as `site.data`. See [`SCHEMA.md`](../SCHEMA.md) in the repository root, which appears to describe the shape of this data. |
| `assets/` | directory | Static assets served with the site — ⚠️ typically stylesheets, scripts, images, and fonts. |
| `pages/` | directory | Site pages. ⚠️ A non-default location for Jekyll pages, which usually implies `_config.yml` includes it explicitly or the files carry their own `permalink` front matter. |
| `index.md` | file | The site's landing page (Markdown with front matter). |
| `Gemfile` | file | Ruby gem dependencies for building the site. ⚠️ Contents not inspected. |
| `Rakefile` | file | Ruby `rake` task definitions — the repository's task runner. ⚠️ The available tasks have not been enumerated; run your local `rake` task-listing command to see them. |

> **Note on the root `README.md`.** It is a GitHub **profile README** (an
> author bio, tech stack, and experience) rather than a description of this
> codebase. That is deliberate — `bamr87/bamr87` is a profile repository — and
> it is why this layout page exists separately.

---

## 2. Agents and automation

This repository is set up to be worked on by AI agents as well as humans, and
several root entries exist purely to tell those agents how to behave.

| Entry | Type | Purpose |
| --- | --- | --- |
| `AGENTS.md` | file | Instructions for AI coding agents operating in this repository — the tool-agnostic convention. **Read this before making automated changes.** |
| `CLAUDE.md` | file | Claude-specific project instructions and context. |
| `.claude/` | directory | Claude configuration. ⚠️ Typically holds settings, custom commands, and/or agent definitions. |
| `.mcp.json` | file | Model Context Protocol server configuration — declares the MCP servers/tools available to agents in this workspace. ⚠️ The specific servers configured have not been inspected. |
| `fleet.manifest.yml` | file | Manifest describing the agent "fleet" that operates on this repository. ⚠️ Contents not inspected. |
| `.github/` | directory | GitHub platform configuration. ⚠️ Conventionally CI/CD workflows under `.github/workflows/`, plus issue/PR templates. |
| `CONTRIBUTING.md` | file | How to contribute — start here before opening a PR. |

---

## 3. Content and knowledge

| Entry | Type | Purpose |
| --- | --- | --- |
| `projects/` | directory | Project material. ⚠️ Purpose not confirmed; may hold per-project pages, notes, or submodule mount points (see `.gitmodules`). |
| `templates/` | directory | Reusable templates. ⚠️ Could be content scaffolds, document templates, or generator inputs — not confirmed. |
| `diagrams/` | directory | Diagram sources and/or exports (architecture, process, data-flow). ⚠️ Format not confirmed. |
| `docs/` | directory | Long-form documentation, including this page and the local development guide. |
| `_reports/` | directory | Generated reports. ⚠️ The leading underscore suggests a Jekyll collection or an excluded-from-build output directory; which of the two has not been confirmed. Check whether it is generated (and therefore should not be hand-edited) before modifying anything inside. |
| `SCHEMA.md` | file | Documents the data schema used by the repository — ⚠️ most plausibly the structure of `_data/`. |
| `SUBMODULES.md` | file | Documents the Git submodules used here and how to work with them. Pair it with `.gitmodules`. |

---

## 4. Environment, dotfiles, and tooling

### Development environment

| Entry | Type | Purpose |
| --- | --- | --- |
| `.devcontainer/` | directory | Dev Container definition — a reproducible containerised environment for VS Code / GitHub Codespaces. |
| `docker-compose.yml` | file | Container service definitions for local development. ⚠️ The services defined have not been inspected. |
| `.vscode/` | directory | Workspace-scoped VS Code settings, tasks, and recommended extensions. |
| `home.code-workspace` | file | A VS Code multi-root workspace file. ⚠️ The name suggests it opens this repo together with related folders (likely the submodules); open it to see the actual roots. |
| `.env.example` | file | Template for environment variables. Copy it to `.env` and fill in real values; `.env` itself should never be committed. |

### Shell and Git dotfiles

| Entry | Type | Purpose |
| --- | --- | --- |
| `.zshrc` | file | Zsh interactive shell configuration. |
| `.zprofile` | file | Zsh login shell configuration (environment/PATH setup). |
| `.gitconfig` | file | Git configuration (aliases, user settings, tooling). |

> ⚠️ **Open question worth confirming.** These three are *home-directory*
> dotfiles living inside a repository. They are most likely tracked here so the
> author's shell environment is version-controlled and portable — but whether
> they are meant to be **symlinked or copied into `$HOME`** by a bootstrap step,
> or kept purely as reference, is not documented anywhere I could see. Do not
> assume they are applied automatically. `tools/` and `Rakefile` are the places
> to look for a bootstrap routine.

### Code quality and formatting

| Entry | Type | Purpose |
| --- | --- | --- |
| `.pre-commit-config.yaml` | file | [pre-commit](https://pre-commit.com) hook definitions — the checks that run before a commit is created. |
| `.husky/` | directory | Husky Git hooks (Node-based). ⚠️ Note that this coexists with `pre-commit`; check both to understand what actually runs on commit. |
| `.editorconfig` | file | Editor-agnostic formatting baseline (indentation, line endings, final newline). |
| `.prettierrc` | file | Prettier formatting rules. |
| `.prettierignore` | file | Paths Prettier must not reformat. |
| `.markdownlintignore` | file | Paths excluded from Markdown linting. ⚠️ Implies markdownlint runs somewhere — most likely via `.pre-commit-config.yaml`, `.husky/`, or a `.github/` workflow. |

### Miscellaneous

| Entry | Type | Purpose |
| --- | --- | --- |
| `tools/` | directory | Supporting scripts and utilities for the repository. ⚠️ Contents not inspected. |
| `.gitmodules` | file | Git submodule registry — maps submodule paths to their upstream repositories. See [`SUBMODULES.md`](../SUBMODULES.md). |
| `.gitignore` | file | Paths excluded from version control. |

---

## Orientation tips for a newcomer

1. **Read [`CONTRIBUTING.md`](../CONTRIBUTING.md) first** for the contribution
   workflow, and [`AGENTS.md`](../AGENTS.md) if you are (or are directing) an
   automated agent.
2. **Clone with submodules.** `.gitmodules` is present, so a plain clone will
   leave some directories empty. [`SUBMODULES.md`](../SUBMODULES.md) is the
   authority on how to initialise them.
3. **Check `_reports/` before editing it.** Generated output should be
   regenerated, not hand-edited.
4. **Get build and run commands from the tooling, not from memory.** `Rakefile`,
   `docker-compose.yml`, `.devcontainer/`, and the workflows in `.github/` are
   the sources of truth for how this project is built and checked.

## Keeping this page honest

When you add a new top-level file or directory, add a row here too. A layout map
that has silently drifted out of date is more harmful than no map at all — and
if you confirm one of the ⚠️ entries above, please remove the marker and state
the fact plainly.
