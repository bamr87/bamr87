# Repository Map

A newcomer's orientation to this repository. Every path below is present at the
top level of the repo; the descriptions are short and, where noted, still need a
maintainer's confirmation.

> **Status:** this file intentionally contains **no build, run, or test
> commands** yet. See [Still to be documented](#still-to-be-documented) for what
> is missing and where the answers live.

## What this repository is

`bamr87/bamr87` is a GitHub profile repository that has grown into a monorepo.
`README.md` renders as the profile page for the `bamr87` GitHub account and
describes the author, Amr Abdel-Motaleb, a Solutions Architect and ERP
specialist. GitHub reports the primary language as HTML and the default branch
as `main`.

Alongside the profile content, the repository carries site sources, project
submodules, tooling, and agent configuration — see the map below.

## Existing documentation

Start here. These files already exist and are the authoritative sources for
their topics:

| Document | What it covers |
| --- | --- |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | How to contribute. **Read this first** — it is the most likely home of the real setup and workflow instructions. |
| [`SUBMODULES.md`](SUBMODULES.md) | Git submodule layout and handling (the repo has a `.gitmodules` file). |
| [`SCHEMA.md`](SCHEMA.md) | Data/content schema documentation. |
| [`CATALOG.md`](CATALOG.md) | Catalog of the repository's contents. |
| [`AGENTS.md`](AGENTS.md) | Instructions and conventions for automated agents working in this repo. |
| [`CLAUDE.md`](CLAUDE.md) | Claude-specific project instructions. |
| [`README.md`](README.md) | Profile / biography and project index. |

## Top-level layout

Descriptions marked *(inferred)* are based on the filename and common
convention rather than on reading the file; correct them if they are wrong.

### Site and content

| Path | Notes |
| --- | --- |
| `_config.yml` | Site configuration *(inferred: Jekyll)*. |
| `_config_dev.yml` | A second, development-oriented site configuration *(inferred)*. |
| `Gemfile` | Ruby dependency manifest, used with Bundler *(inferred)*. |
| `index.md` | Site entry page *(inferred)*. |
| `pages/` | Additional site pages. |
| `_data/` | Structured data consumed by the site *(inferred: Jekyll `_data`)*. |
| `assets/` | Static assets (images, styles, scripts). |
| `diagrams/` | Diagram sources and/or exports. |
| `docs/` | Documentation directory. |
| `templates/` | Reusable templates. |
| `specs/` | Specifications. |
| `projects/` | Project directories — note the repo has a `.gitmodules` file, so some of these may be submodules; see [`SUBMODULES.md`](SUBMODULES.md). |
| `_reports/` | Generated reports. |

### Build, tooling, and environment

| Path | Notes |
| --- | --- |
| `Rakefile` | Rake task definitions — the likely source of this project's build/serve/test tasks. |
| `docker-compose.yml` | Container-based workflow. |
| `.devcontainer/` | VS Code / Codespaces dev container definition. |
| `.env.example` | Template for local environment variables — copy and fill in before running anything that reads it. |
| `tools/` | Helper scripts and utilities. |
| `home.code-workspace` | VS Code multi-root workspace file. |
| `.vscode/` | Editor settings and recommended extensions. |

### Quality gates

| Path | Notes |
| --- | --- |
| `.pre-commit-config.yaml` | pre-commit hook configuration *(inferred)*. |
| `.husky/` | Git hooks managed by Husky *(inferred)*. |
| `.prettierrc`, `.prettierignore` | Prettier formatting configuration. |
| `.markdownlintignore` | Paths excluded from Markdown linting. |
| `.editorconfig` | Cross-editor formatting conventions. |
| `.github/` | GitHub configuration: workflows, issue templates, and similar. |

### Automation and agents

| Path | Notes |
| --- | --- |
| `fleet.manifest.yml` | Manifest for automated agent work. |
| `.mcp.json` | Model Context Protocol server configuration *(inferred)*. |
| `.claude/` | Claude configuration directory. |

### Shell and Git configuration

| Path | Notes |
| --- | --- |
| `.zshrc`, `.zprofile` | Zsh shell configuration tracked in the repo (this repo doubles as a dotfiles home). |
| `.gitconfig` | Git configuration tracked in the repo. |
| `.gitmodules` | Submodule definitions — see [`SUBMODULES.md`](SUBMODULES.md). |
| `.gitignore` | Ignored paths. |

## Still to be documented

The following are **not yet documented anywhere in this file**, because the
exact commands must be read from the files that define them rather than guessed:

- **Local setup and serving the site.** Read `Gemfile` and `_config.yml` /
  `_config_dev.yml` for the toolchain and its version constraints.
- **Build / serve / test task names.** Read `Rakefile` and record the task names
  it literally defines. Also check `.github/` workflows, which show how CI
  invokes the project — a reliable cross-check that a command actually works.
- **The container workflow.** Read `docker-compose.yml` for the real service
  name(s) before writing any `docker compose` invocation.
- **The dev container path.** Read `.devcontainer/` for the Codespaces / VS Code
  "Reopen in Container" flow.
- **Required environment variables.** Read `.env.example` and describe each key.
- **Hook installation.** Read `.pre-commit-config.yaml` and `.husky/` for how
  contributors are expected to install hooks.
- **Submodule initialisation.** [`SUBMODULES.md`](SUBMODULES.md) likely already
  covers this; link to it rather than duplicating it.

When those are confirmed, replace this section with the verified commands and
add a short pointer from `README.md` to this file.
