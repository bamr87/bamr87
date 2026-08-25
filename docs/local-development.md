---
title: Local Development Guide
description: How to clone, configure and run this monorepo locally with Docker or Bundler + Jekyll.
---

# Local Development Guide

This guide gets a newcomer from `git clone` to a site running on their machine.

`README.md` at the root of this repository is a **profile README** — it describes the
author, not the repository's build. This document covers the repository itself.

> **Note on accuracy:** every command below is either a standard tool command or a
> *discovery* command that prints the repository's real configuration. Where a value
> is specific to this repo and needs a maintainer to confirm it, you'll see a
> `TODO (maintainer)` callout. Please replace those with concrete values rather than
> guessing.

---

## 1. Prerequisites

Pick **one** of the two paths below. You do not need both.

| Path | You need |
| --- | --- |
| **Docker** (recommended for a first run) | Docker Desktop / Docker Engine with the `docker compose` plugin |
| **Native Ruby** | Ruby + Bundler (`gem install bundler`) |
| **Dev Container** (VS Code) | VS Code + the *Dev Containers* extension + Docker |

The repository ships a `.devcontainer/` directory, so VS Code will offer to
"Reopen in Container" when you open the folder. That path handles the toolchain
for you.

Other tooling present at the root that you may want installed:

- `.pre-commit-config.yaml` — [pre-commit](https://pre-commit.com/) hooks
- `.editorconfig`, `.prettierrc`, `.prettierignore` — editor and formatting config

---

## 2. Clone the repository (with submodules)

This repository uses git submodules — there is a `.gitmodules` file at the root.
If you clone without them, parts of the tree will be empty directories.

```bash
git clone --recurse-submodules https://github.com/bamr87/bamr87.git
cd bamr87
```

Already cloned without `--recurse-submodules`? Fix it in place:

```bash
git submodule update --init --recursive
```

To see which submodules are configured and where they point:

```bash
cat .gitmodules
git submodule status
```

📖 See [`SUBMODULES.md`](../SUBMODULES.md) for this repository's own guidance on
adding, updating and troubleshooting submodules — treat it as the authoritative
source over this section.

---

## 3. Configure your environment

The repository provides `.env.example` as a template. Copy it and fill in values:

```bash
cp .env.example .env
```

To see exactly which variables are expected, read the template — it is the single
source of truth:

```bash
cat .env.example
```

`.env` is intended to stay on your machine; check `.gitignore` before committing
anything that looks like a secret.

> **TODO (maintainer):** state whether `.env` is *required* for a plain local
> build, or only for optional integrations, and which variables are mandatory.

---

## 4. Run the site

### Option A — Docker Compose

`docker-compose.yml` lives at the repository root. First, see what it defines:

```bash
docker compose config --services   # list the service names
docker compose config              # the fully-resolved configuration, incl. ports
```

Then start everything in the foreground (Ctrl-C to stop):

```bash
docker compose up
```

Or in the background, with logs followed separately:

```bash
docker compose up -d
docker compose logs -f
docker compose down          # stop and remove the containers
```

Open the port published by the service — read it from the `ports:` mapping shown
by `docker compose config`.

> **TODO (maintainer):** replace the above with the concrete service name and
> URL, e.g. `docker compose up <service>` → <http://localhost:PORT>.

### Option B — Native Ruby / Bundler

The root `Gemfile` declares the Ruby dependencies:

```bash
bundle install
```

Then run the Jekyll development server:

```bash
bundle exec jekyll serve
```

By default Jekyll reads `_config.yml`. This repository *also* contains
`_config_dev.yml`, which suggests a development override is layered on top —
Jekyll supports this with a comma-separated list:

```bash
bundle exec jekyll serve --config _config.yml,_config_dev.yml
```

> **TODO (maintainer):** confirm which invocation is correct here — whether
> `_config_dev.yml` is layered as above, whether `docker-compose.yml` already
> applies it, and what the local URL/port is.

### Option C — Dev Container (VS Code / GitHub Codespaces)

The `.devcontainer/` directory describes the toolchain, so you don't have to
install Ruby or the Compose services by hand:

- **VS Code:** install the *Dev Containers* extension, open the repository
  folder, and choose **Reopen in Container** when prompted (or run
  *Dev Containers: Reopen in Container* from the command palette).
- **GitHub Codespaces:** create a codespace on the branch you want; the same
  definition is used automatically.

Once the container is up, continue with the Bundler commands from Option B.

> **TODO (maintainer):** state whether `.devcontainer/devcontainer.json` runs a
> `postCreateCommand` that already installs dependencies, and which preview port
> it forwards, so readers can skip straight to the server.

---

## 5. Build and automation tasks

A `Rakefile` sits at the repository root. Rather than memorising task names, ask
Rake what it offers:

```bash
bundle exec rake -T          # list all documented tasks with descriptions
bundle exec rake -T build    # filter to tasks matching "build"
```

Run a task with:

```bash
bundle exec rake <task_name>
```

> **TODO (maintainer):** call out the two or three tasks a newcomer actually
> needs (build, test, lint, deploy) so they don't have to guess from `rake -T`.

### Pre-commit hooks

If you have `pre-commit` installed, wire up the hooks declared in
`.pre-commit-config.yaml`:

```bash
pre-commit install
pre-commit run --all-files   # run every hook across the repo once
```

The repository also carries **Husky** hooks (`.husky/`, managed through the Node
toolchain) and **Prettier** / **EditorConfig** settings (`.prettierrc`,
`.prettierignore`, `.editorconfig`) — formatting is enforced, so let your editor
pick these up rather than reformatting by hand.

---

## 6. Repository layout

The top level of the monorepo:

| Path | What it is |
| --- | --- |
| `_config.yml`, `_config_dev.yml` | Jekyll site configuration (production and development) |
| `_data/` | Jekyll data files |
| `_reports/` | Generated or checked-in reports |
| `assets/` | Static assets for the site |
| `docs/` | Documentation (you are here) |
| `index.md`, `pages/` | Site content |
| `projects/` | Project directories (several are git submodules — see `.gitmodules`) |
| `templates/` | Reusable templates |
| `tools/` | Repository tooling and scripts |
| `Gemfile` | Ruby dependencies |
| `Rakefile` | Automation tasks |
| `docker-compose.yml` | Container definition for local development |
| `fleet.manifest.yml` | Fleet/automation manifest |
| `home.code-workspace` | VS Code multi-root workspace file |
| `.devcontainer/` | VS Code Dev Container definition |
| `.github/` | GitHub workflows, issue and PR templates |
| `.vscode/` | Editor settings shared with the team |
| `.claude/`, `.mcp.json` | AI agent configuration |

Shell dotfiles (`.zshrc`, `.zprofile`, `.gitconfig`) are tracked at the root —
this repository doubles as a dotfiles/home directory. Read them before running
anything that might symlink them over your own configuration.

---

## 7. Related documentation

| Document | Purpose |
| --- | --- |
| [`CONTRIBUTING.md`](../CONTRIBUTING.md) | Contribution workflow, branch and commit conventions |
| [`SUBMODULES.md`](../SUBMODULES.md) | Working with the git submodules in `projects/` |
| [`SCHEMA.md`](../SCHEMA.md) | Data/content schema reference |
| [`AGENTS.md`](../AGENTS.md), [`CLAUDE.md`](../CLAUDE.md) | Conventions for AI agents operating on this repository |
| [`fleet.manifest.yml`](../fleet.manifest.yml) | Automation manifest |

---

## 8. Troubleshooting

**Empty directories under `projects/`** — submodules were not initialised. Run
`git submodule update --init --recursive`.

**`bundler: command not found: jekyll`** — dependencies are not installed for the
current Ruby. Re-run `bundle install`, and make sure you are prefixing commands
with `bundle exec`.

**`bundle: command not found`** — Bundler isn't installed for your Ruby:
`gem install bundler`.

**A native gem fails to build during `bundle install`** — use the Dev Container
(Option C) or Docker Compose (Option A) instead; both exist precisely so you
don't have to fight a local Ruby toolchain.

**Port already in use with Docker** — something else is bound to the published
port. Check with `docker compose ps` and `docker compose config`, then stop the
conflicting process or change the mapping.

**Changes not appearing in the browser** — Jekyll's watcher can miss files inside
bind-mounted volumes on some platforms. Restart the server, or check whether the
path is excluded in `_config.yml`.

**Links or assets resolve incorrectly in the local preview** — the development
config (`_config_dev.yml`) is probably not being applied; see the Bundler
invocation under Option B.

---

*Found a gap or an inaccuracy in this guide? Please open a PR — the `TODO
(maintainer)` callouts above are the known unknowns and are the best place to
start.*
