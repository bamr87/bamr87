---
title: Repository Toolchain Map
status: draft
---

# Repository Toolchain Map

> **Status: draft.** This document was assembled from the repository's root file
> listing only. The configuration files themselves had not been read when it was
> written, so it deliberately contains **no install, serve, build or test
> commands** — those would have been guesses. Sections marked `TODO` are genuine
> unknowns; see [Unverified — needs confirmation](#unverified--needs-confirmation).

## What this repository is

`bamr87/bamr87` is a monorepo that doubles as the owner's GitHub profile repository. The root `README.md` renders as the profile page; the rest of the tree (`pages/`, `projects/`, `docs/`, `templates/`, `tools/`, `_data/`, `assets/`) holds the monorepo's actual content and automation.

The root configuration files imply a stack with four distinct layers:

1. a **Ruby / Jekyll** static site,
2. a **containerised** development environment (Docker Compose + Dev Containers),
3. **git hooks** for pre-commit quality gates, from two independent hook managers,
4. **shell / editor** environment configuration checked into the repo itself.

Each layer is inventoried below.

---

## Layer 1 — Ruby and the static site

| File | Tool it belongs to | What it means here |
| --- | --- | --- |
| `Gemfile` | [Bundler](https://bundler.io/) | Declares the Ruby gem dependencies. A `Gemfile.lock` is not present in the root listing, which usually means it is either gitignored or generated in the container. |
| `Rakefile` | [Rake](https://ruby.github.io/rake/) | Defines the repository's task entry points. This is the most likely home for the project's build/serve/test commands. |
| `_config.yml` | [Jekyll](https://jekyllrb.com/) | Jekyll's primary site configuration. Its presence alongside `index.md`, `_data/`, `assets/` and underscore-prefixed directories is the main evidence that the site is built with Jekyll. |
| `_config_dev.yml` | Jekyll | A second configuration profile, conventionally layered *on top of* `_config.yml` for local development. |

Jekyll supports being given more than one config file, with later files overriding earlier ones — which is the usual reason a `_config_dev.yml` exists alongside `_config.yml`. **How this repository actually combines the two is not yet documented here** (`TODO`).

---

## Layer 2 — Containerised development

| File / directory | Tool it belongs to | What it means here |
| --- | --- | --- |
| `docker-compose.yml` | [Docker Compose](https://docs.docker.com/compose/) | Defines the service(s) used to run the project without installing Ruby locally. |
| `.devcontainer/` | [Dev Containers](https://containers.dev/) | Lets VS Code (or GitHub Codespaces) open the repository directly inside a container. |
| `.env.example` | environment variables | A template for a local, untracked `.env`. Copy it and fill it in before starting the containers. The variables it declares are not documented here (`TODO`). |
| `home.code-workspace` | VS Code | A multi-root workspace file — consistent with a monorepo that also uses git submodules. |

Because both a Compose file and a Dev Container definition exist, there are probably **two supported ways to get a working environment** (open in a dev container, or bring up Compose by hand), plus a third native path via Bundler. Which one the maintainer considers canonical is not yet recorded (`TODO`).

---

## Layer 3 — Git hooks and formatting

This repository carries **two** hook managers, which is unusual and worth understanding before you commit:

| File / directory | Tool it belongs to | What it means here |
| --- | --- | --- |
| `.pre-commit-config.yaml` | [pre-commit](https://pre-commit.com/) (Python) | Declares hooks that run before each commit. Requires a one-time install step to activate the git hook. |
| `.husky/` | [Husky](https://typicode.github.io/husky/) (Node.js) | A second, Node-based git hook manager. Its hook scripts live as files inside this directory. |
| `.prettierrc` | [Prettier](https://prettier.io/) | Formatting rules. |
| `.prettierignore` | Prettier | Paths excluded from formatting. |
| `.editorconfig` | [EditorConfig](https://editorconfig.org/) | Editor-level whitespace/charset settings, applied automatically by most editors. |

The presence of `.prettierrc` implies a Node.js toolchain, but **no `package.json` appears in the root listing.** That is worth resolving — Husky normally expects one — and is recorded as an open question below.

---

## Layer 4 — Shell, submodules and agent configuration

| File / directory | What it is |
| --- | --- |
| `.gitmodules` | Git submodule definitions. The repository is a monorepo of linked repositories; see `SUBMODULES.md` for the maintainer's own notes. |
| `tools/` | The repository's scripts. The manifest reports Shell as the primary language, which is consistent with this directory, though its contents are not described here (`TODO`). |
| `.zshrc`, `.zprofile`, `.gitconfig` | Dotfiles tracked in-repo — this repository doubles as a dotfiles source. |
| `.github/` | GitHub configuration: workflows, issue templates, and similar. |
| `.vscode/` | Shared editor settings. |
| `.claude/`, `.mcp.json`, `AGENTS.md`, `CLAUDE.md` | AI-agent configuration and instructions for tooling that operates on this repository. |
| `fleet.manifest.yml` | Manifest describing the repository to automation. |
| `SCHEMA.md`, `SUBMODULES.md`, `CONTRIBUTING.md` | Existing maintainer documentation. Read `CONTRIBUTING.md` first if you intend to open a PR. |
| `_reports/` | Generated or collected reports. |

---

## Unverified — needs confirmation

Everything below is an open question. Answering these turns this map into a usable getting-started guide. Each item names the exact file to read.

### Commands

- [ ] **`Rakefile`** — list the defined tasks. Which one serves the site
      locally, which builds it, which runs tests or linting? Record the exact
      `rake` invocations.
- [ ] **`Gemfile`** — confirm that `jekyll` is actually a declared dependency,
      note the required Ruby version, and list any gem groups (e.g. a
      development-only group) that change the install step.
- [ ] **`docker-compose.yml`** — record the service names, the published port(s)
      for the local site, and the exact command used to bring the stack up.
- [ ] **`.devcontainer/`** — record the base image and any post-create command,
      so newcomers know what is already installed for them.

### Configuration profiles

- [ ] **`_config_dev.yml` vs `_config.yml`** — document precisely what the dev
      profile overrides (baseurl? url? host? plugins? `future`/`drafts`
      settings?) and how the two are combined at build time.

### Hooks

- [ ] **`.pre-commit-config.yaml`** — list each hook, what it checks, and the
      one-time command required to install the git hook.
- [ ] **`.husky/`** — list the hook scripts present and what each one runs.
- [ ] **Why both managers?** Determine whether pre-commit and Husky cover
      different file types, or whether one supersedes the other. Newcomers need
      to know which to install.
- [ ] **Missing `package.json`** — Husky and Prettier normally require a Node
      project manifest. Confirm whether one lives elsewhere in the tree, whether
      it is generated, or whether these tools are invoked another way.

### Environment

- [ ] **`.env.example`** — document each variable, whether it is required, and
      what a safe local value looks like.
- [ ] **`tools/`** — summarise what the scripts do and which are entry points
      intended for humans.

### Contribution flow

- [ ] **`CONTRIBUTING.md`** — cross-check this document against it and remove
      any duplication, or fold this file into it entirely.
- [ ] **`.github/`** — record which CI workflows run on a pull request, so
      contributors know what must pass.
