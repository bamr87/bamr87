---
title: Repository layout & local development
description: Contributor-facing map of this monorepo — where things live, which docs to read first, and how to get the site running locally.
updated: 2026-08-24
---

# Repository layout & local development

> **Status: draft.** The layout map below is derived from the repository's file
> tree and is accurate. The command sections are **placeholders awaiting
> maintainer verification** — they are marked with ⚠️ and deliberately left
> blank rather than filled with guessed commands. If you are a maintainer,
> please fill them in; if you are a newcomer, treat ⚠️ sections as "ask first".

## Who this page is for

The repository root `README.md` is a **GitHub profile README** — it renders on
<https://github.com/bamr87> and describes the author, not the codebase. That is
intentional, but it means a person who clones this repository has nowhere
obvious to start.

This page is that starting point. It answers:

- What is actually in this repository?
- Which of the many existing docs should I read, and in what order?
- How do I get it running on my machine?

## Read these first

This repository already carries a fair amount of documentation. This page is a
**map**, not a replacement — when a topic has a dedicated file, go there.

| Document | Read it when |
|---|---|
| [`CONTRIBUTING.md`](../CONTRIBUTING.md) | Before your first change — branch naming, commit conventions, review expectations. **This is the authoritative process doc; if it disagrees with this page, it wins.** |
| [`SUBMODULES.md`](../SUBMODULES.md) | You need to know which submodules exist, what they contain, and how to initialize/update them. |
| [`SCHEMA.md`](../SCHEMA.md) | You are adding or editing structured content — front matter fields, `_data/` files, or anything with a defined shape. |
| [`AGENTS.md`](../AGENTS.md) | You are an automated agent, or you are configuring one. Conventions for machine contributors. |
| [`CLAUDE.md`](../CLAUDE.md) | Claude-specific working instructions for this repository. |
| [`fleet.manifest.yml`](../fleet.manifest.yml) | You want to know how automated contributions to this repo are scoped and configured. |
| `docs/` | Longer-form documentation lives here (this file included). |

## What this repository is

A **monorepo** built around a [Jekyll](https://jekyllrb.com/) static site, with
Git submodules pulling in related projects, plus the author's shell/dotfile and
tooling configuration.

The evidence for "Jekyll site" is in the root: a `Gemfile`, `_config.yml`,
`_config_dev.yml`, `_data/`, `assets/`, `pages/`, and an `index.md` entry page —
the standard Jekyll shape.

## Layout

### Site content and configuration

| Path | What it is |
|---|---|
| `_config.yml` | Primary Jekyll configuration. |
| `_config_dev.yml` | A second, development-oriented Jekyll config. ⚠️ *Verify:* whether this replaces `_config.yml` or is layered on top of it (Jekyll supports `--config a.yml,b.yml`), and which one local serving uses. |
| `index.md` | Site entry page. |
| `pages/` | Site pages. |
| `_data/` | Structured data consumed by Jekyll templates. See [`SCHEMA.md`](../SCHEMA.md) for the expected shape of these files before editing them. |
| `assets/` | Static assets (styles, scripts, images) served by the site. |
| `templates/` | ⚠️ *Verify:* content scaffolds/boilerplate for new pages, as opposed to Jekyll layouts. |
| `projects/` | Project content and/or submodule mount points. Cross-check against [`SUBMODULES.md`](../SUBMODULES.md). |
| `docs/` | Long-form documentation, including this page. |
| `_reports/` | ⚠️ *Verify:* generated output (reports/audits). Confirm whether this is committed deliberately or generated locally. |

### Build, run, and automation

| Path | What it is |
|---|---|
| `Gemfile` | Ruby dependencies. Its `Gemfile.lock` is not committed at root level in the listing — ⚠️ *verify whether that is intentional.* |
| `Rakefile` | Rake task definitions — likely the intended task entry point. ⚠️ *Verify:* run your Rake binary's task-listing flag to enumerate available tasks. |
| `docker-compose.yml` | Containerized local environment. ⚠️ *Verify:* service names and published ports. |
| `.devcontainer/` | VS Code / GitHub Codespaces dev container definition — the lowest-friction path if you use either. |
| `tools/` | Repository tooling and scripts. The repository's primary language is reported as **Shell**, so expect executable scripts here. ⚠️ *Verify:* whether these are meant to be run directly or only via `Rakefile` tasks. |
| `.github/` | GitHub Actions workflows, issue/PR templates. **The workflows here are the ground truth for what CI actually runs** — if you want to know how the project is built and checked, read them.  |

### Code quality and environment

| Path | What it is |
|---|---|
| `.editorconfig` | Editor defaults (indentation, line endings). Most editors apply this automatically. |
| `.prettierrc`, `.prettierignore` | Prettier formatting configuration and exclusions. |
| `.pre-commit-config.yaml` | [pre-commit](https://pre-commit.com/) hook definitions. |
| `.husky/` | Husky Git hooks. ⚠️ *Verify:* how these coexist with `pre-commit` — running both is possible but worth documenting so contributors know which hook fired. |
| `.env.example` | Template for local environment variables. Copy it to `.env` (which is git-ignored) and fill in real values. ⚠️ *Verify:* which keys are required vs. optional. |
| `.gitmodules` | Submodule definitions — see [`SUBMODULES.md`](../SUBMODULES.md). |
| `.gitconfig`, `.zshrc`, `.zprofile` | The author's shell and Git configuration, versioned as dotfiles. **These are not needed to build the site** — do not source them expecting the project to require it. |
| `.vscode/`, `home.code-workspace` | VS Code workspace settings and multi-root workspace file. Open the `.code-workspace` file rather than the plain folder to pick up the intended workspace layout. |
| `.mcp.json`, `.claude/` | Model Context Protocol / Claude tooling configuration for agent-assisted work. See [`AGENTS.md`](../AGENTS.md) and [`CLAUDE.md`](../CLAUDE.md). |

## Getting the site running locally

There appear to be **three** supported paths. Pick one.

### 1. Dev container (recommended if you use VS Code or Codespaces)

The repository ships a `.devcontainer/` definition, which means the toolchain is
already pinned for you: open the folder in VS Code and choose *Reopen in
Container*, or start a Codespace from the GitHub UI.

> ⚠️ **Needs verification:** base image, forwarded ports, and whether a
> post-create step already runs dependency installation and submodule
> initialization. Fill in below.
>
> - Base image / features:
> - Forwarded port(s):
> - Runs automatically on create:

### 2. Docker Compose

A `docker-compose.yml` exists at the root.

> ⚠️ **Needs verification:** exact invocation, service name(s), and the URL the
> site is served on.
>
> ```sh
> # fill in from docker-compose.yml
> ```

### 3. Native Ruby toolchain

With a `Gemfile` and a `Rakefile` present, dependencies are managed by Bundler
and tasks are likely exposed through Rake.

> ⚠️ **Needs verification:** required Ruby version (check for a `.ruby-version`
> or the `ruby` directive in `Gemfile`), the install command, and the
> serve/build tasks defined in `Rakefile`. Fill in below.
>
> - Ruby version:
> - Install dependencies:
> - Serve locally (and how `_config_dev.yml` is applied):
> - Build for production:
> - Local URL:

### Submodules

This repository uses Git submodules (`.gitmodules`). A plain `git clone` will
leave submodule directories empty, and a site build may then fail or silently
omit content.

[`SUBMODULES.md`](../SUBMODULES.md) is the authoritative reference for which
submodules exist and how to work with them — read it before your first clone,
and consult it again when a submodule directory looks unexpectedly empty or a
diff shows a bare pointer change.

## Tests and checks

> ⚠️ **Needs verification.** No dedicated test directory appears in the
> repository root listing, so it is likely that verification here means
> "the site builds cleanly" plus the configured lint/format hooks, rather than
> a unit test suite. The workflows in `.github/` are the authoritative answer
> to *what CI actually enforces* — read them and record the result here.
>
> - Test command (if any):
> - Lint / format command:
> - Link or build validation:

In the meantime, before opening a pull request:

1. Make sure the site builds locally by whichever path you used above.
2. Let the configured hooks run — `.pre-commit-config.yaml` and `.husky/` are
   both present, so formatting and lint checks are expected to fire on commit.
   Do not bypass them without saying so in your PR description.
3. Follow the process in [`CONTRIBUTING.md`](../CONTRIBUTING.md).

## Where to put a change

| You want to… | Go to |
|---|---|
| Edit the profile page that shows on github.com/bamr87 | `README.md` (root) — note this is the *profile* README, not project docs |
| Add or edit a site page | `pages/`, or `index.md` for the landing page |
| Change structured data behind the site | `_data/` — check [`SCHEMA.md`](../SCHEMA.md) first |
| Change styling or static assets | `assets/` |
| Add or change a build/automation task | `Rakefile` and/or `tools/` |
| Change CI | `.github/` |
| Add contributor documentation | `docs/` (this directory) |
| Change something inside a submodule | The submodule's own upstream repository — see [`SUBMODULES.md`](../SUBMODULES.md) |

## Improving this page

Every ⚠️ marker above is an open question. If you resolve one — by reading the
file, or by running the command successfully — please replace the marker with
the verified answer in the same pull request as your other work. The goal is for
this page to have zero ⚠️ markers.
