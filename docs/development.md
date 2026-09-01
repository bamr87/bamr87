# Development Guide

This repository serves two purposes at once:

1. It is **`bamr87/bamr87`**, the GitHub *profile* repository — so `README.md` at the
root renders on the owner's profile page and reads as a personal/professional introduction rather than as project documentation.
2. It is also a **working project**: the root of the repository contains a `Gemfile`,
a `Rakefile`, a `docker-compose.yml`, a `.devcontainer/` directory, site configuration (`_config.yml`, `_config_dev.yml`), content (`index.md`, `pages/`, `_data/`) and assets (`assets/`).

Because the top-level `README.md` is dedicated to purpose (1), this page is the entry point for purpose (2).

> **Status of this page.** It was written from the repository's file listing. It tells
> you *where to look* for each concern and is deliberately conservative about exact
> commands: sections marked **⚠️ Unverified** still need a maintainer to fill in the
> real invocation. Please do that rather than deleting the marker.

---

## Repository map

Everything below is present at the repository root.

### Build and run

| Path | What it is |
| --- | --- |
| `Gemfile` | Ruby dependency manifest. Its presence means the project's build tooling is Ruby/Bundler based. |
| `Rakefile` | Rake task definitions — the likely home of this repo's build, generate and maintenance tasks. Read it to discover the available task names. |
| `docker-compose.yml` | Containerised setup for running the project locally without installing the toolchain on the host. |
| `.devcontainer/` | VS Code / GitHub Codespaces dev container definition — the lowest-friction way to get a working environment. |
| `_config.yml` | Primary site configuration. |
| `_config_dev.yml` | Development overrides, layered on top of `_config.yml`. |
| `.env.example` | Template for environment variables. Copy it to `.env` and fill in local values; `.env` itself is expected to stay untracked. |

The combination of `Gemfile` + `_config.yml` + `_config_dev.yml` + `index.md` + `pages/` + `assets/` is the conventional layout of a **Jekyll** static site, and the profile README lists Jekyll among the owner's tools. Treat this as a strong inference rather than a confirmed fact until `_config.yml` is checked.

**⚠️ Unverified — commands.** The exact commands for installing dependencies, serving the site locally, and building for production have not been confirmed against the `Rakefile`, `Gemfile` or `docker-compose.yml`. Please add them here, for example the real `rake` task names, the Compose service name and the port it publishes.

### Content

| Path | What it is |
| --- | --- |
| `index.md` | Site entry page. |
| `pages/` | Site pages. |
| `_data/` | Structured data consumed by the site. See [SCHEMA.md](../SCHEMA.md) for the expected shape. |
| `assets/` | Static assets (styles, images, scripts). |
| `diagrams/` | Diagram sources. |
| `templates/` | Reusable templates. |
| `docs/` | Project documentation — including this file. |
| `projects/` | Project content/collections. |
| `_reports/` | Generated or collected reports. |

### Tooling and quality gates

| Path | What it is |
| --- | --- |
| `.pre-commit-config.yaml` | pre-commit hook configuration. Install the hooks once after cloning so checks run before each commit. |
| `.husky/` | Husky git hooks (Node-side hook management). |
| `.prettierrc`, `.prettierignore` | Prettier formatting configuration and exclusions. |
| `.markdownlintignore` | Paths excluded from Markdown linting. |
| `.editorconfig` | Editor defaults (indentation, line endings) shared across editors. |
| `.github/` | GitHub configuration, including any CI workflows. Check here for the checks a pull request must pass. |
| `tools/` | Repository scripts and utilities. |

If a change is rejected by a hook or by CI, the configuration file above is where the rule lives.

### Submodules

This repository uses git submodules — `.gitmodules` is present at the root. A plain `git clone` will leave submodule directories empty.

See **[SUBMODULES.md](../SUBMODULES.md)** for how they are wired up and how to update them.

**⚠️ Unverified — which submodules are required for a local build**, and whether the clone must be recursive, has not been confirmed. `SUBMODULES.md` is the authority.

### Agent and workspace configuration

| Path | What it is |
| --- | --- |
| `AGENTS.md`, `CLAUDE.md` | Instructions for AI coding agents operating on this repository. Read these before letting an agent make changes. |
| `.claude/`, `.mcp.json` | Agent tooling configuration. |
| `fleet.manifest.yml` | Manifest describing automated fleet work against this repository. |
| `home.code-workspace` | VS Code multi-root workspace file. |
| `.vscode/` | Shared VS Code settings. |
| `.zshrc`, `.zprofile`, `.gitconfig` | Dotfiles tracked in this repository. |

---

## Getting started

1. **Set up your environment** — see [first-time-setup.md](first-time-setup.md).
*(⚠️ Unverified: confirm this path exists; if the setup guide lives elsewhere in `docs/`, fix this link.)*
2. **Clone with submodules**, per [SUBMODULES.md](../SUBMODULES.md).
3. **Copy `.env.example` to `.env`** and fill in any local values.
4. **Choose a runtime**: the `.devcontainer/` definition or `docker-compose.yml` avoid
   installing Ruby locally; otherwise install dependencies from the `Gemfile`.
5. **Install the git hooks** described by `.pre-commit-config.yaml` and `.husky/` so
   your commits are checked the same way CI checks them.
6. **Read [CONTRIBUTING.md](../CONTRIBUTING.md)** before opening a pull request.

---

## Related documentation

- [CONTRIBUTING.md](../CONTRIBUTING.md) — contribution process
- [SUBMODULES.md](../SUBMODULES.md) — submodule layout and updates
- [SCHEMA.md](../SCHEMA.md) — content and data schema
- [AGENTS.md](../AGENTS.md) / [CLAUDE.md](../CLAUDE.md) — rules for AI agents working here
- [README.md](../README.md) — the profile README
