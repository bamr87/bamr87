---
title: Local Development Guide
description: How to clone, configure and run this monorepo locally — the Harness Console, the public site build, and the containers.
---

# Local Development Guide

This guide gets a newcomer from `git clone` to a site running on their machine.

`README.md` at the root of this repository is a **profile README** — it describes the author, not the repository's build. This document covers the repository itself.

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
| **Native** | Python 3 and Node (current LTS) — the console and the site build use nothing else |
| **Dev Container** (VS Code) | VS Code + the *Dev Containers* extension + Docker |

The repository ships a `.devcontainer/` directory, so VS Code will offer to "Reopen in Container" when you open the folder. That path handles the toolchain for you.

Other tooling present at the root that you may want installed:

- `.pre-commit-config.yaml` — [pre-commit](https://pre-commit.com/) hooks
- `.editorconfig`, `.prettierrc`, `.prettierignore` — editor and formatting config

---

## 2. Clone the repository (with submodules)

This repository uses git submodules — there is a `.gitmodules` file at the root. If you clone without them, parts of the tree will be empty directories.

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

📖 See [`SUBMODULES.md`](../SUBMODULES.md) for this repository's own guidance on adding, updating and troubleshooting submodules — treat it as the authoritative source over this section.

---

## 3. Configure your environment

The repository provides `.env.example` as a template. Copy it and fill in values:

```bash
cp .env.example .env
```

To see exactly which variables are expected, read the template — it is the single source of truth:

```bash
cat .env.example
```

`.env` is intended to stay on your machine; check `.gitignore` before committing anything that looks like a secret.

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

Open the port published by the service — read it from the `ports:` mapping shown by `docker compose config`.

> **TODO (maintainer):** replace the above with the concrete service name and
> URL, e.g. `docker compose up <service>` → <http://localhost:PORT>.

### Option B — Native (Python + Node)

The site and the control plane are one app, the Harness Console (`tools/console/`). Run it live, with every operation behind it:

```bash
tools/dash console            # http://127.0.0.1:4001 — bootstraps .venv-console and builds the page
```

Or build the public site exactly as GitHub Pages publishes it, and serve it read-only:

```bash
tools/dash serve              # http://127.0.0.1:4000 — tools/console/build-pages.sh, then a static server
```

See [CONSOLE-PAGES.md](CONSOLE-PAGES.md) for how the two relate.

### Option C — Dev Container (VS Code / GitHub Codespaces)

The `.devcontainer/` directory describes the toolchain, so you don't have to install Ruby or the Compose services by hand:

- **VS Code:** install the *Dev Containers* extension, open the repository
folder, and choose **Reopen in Container** when prompted (or run *Dev Containers: Reopen in Container* from the command palette).
- **GitHub Codespaces:** create a codespace on the branch you want; the same
  definition is used automatically.

Once the container is up, continue with the commands from Option B.

> **TODO (maintainer):** state whether `.devcontainer/devcontainer.json` runs a
> `postCreateCommand` that already installs dependencies, and which preview port
> it forwards, so readers can skip straight to the server.

---

## 5. Build and automation tasks

Tasks run through the dash CLI, `tools/dash` — run it with no arguments for the full list. The ones a newcomer needs:

```bash
tools/dash status             # submodules, registry and drift at a glance
tools/run-all-tests.sh        # every checked-out project's own suite, plus the hub's
tools/check-drift.sh          # the drift gate CI runs
python3 tools/console/test_console.py && python3 tools/console/test_pages.py
```

### Pre-commit hooks

If you have `pre-commit` installed, wire up the hooks declared in `.pre-commit-config.yaml`:

```bash
pre-commit install
pre-commit run --all-files   # run every hook across the repo once
```

The repository also carries **Husky** hooks (`.husky/`, managed through the Node toolchain) and **Prettier** / **EditorConfig** settings (`.prettierrc`, `.prettierignore`, `.editorconfig`) — formatting is enforced, so let your editor pick these up rather than reformatting by hand.

---

## 6. Repository layout

The top level of the monorepo:

| Path | What it is |
| --- | --- |
| `_data/` | The registries every surface reads (`projects.yml` is the source of truth; `profile.yml` is the site's identity) |
| `_reports/` | Generated or checked-in reports |
| `docs/` | Documentation (you are here) |
| `pages/` | Site content: `profile/*.md` (About, Experience, …) and `posts/*.md` |
| `projects/` | Project directories (several are git submodules — see `.gitmodules`) |
| `templates/` | Reusable templates |
| `tools/` | Repository tooling and scripts |
| `tools/console/` | The Harness Console — the local control plane and, built static, the public site |
| `docker-compose.yml` | Container definition for local development |
| `fleet.manifest.yml` | Fleet/automation manifest |
| `home.code-workspace` | Consolidated VS Code multi-root workspace (dash plus related clones) |
| `.devcontainer/` | VS Code Dev Container definition |
| `.github/` | GitHub workflows, issue and PR templates |
| `.vscode/` | Editor settings shared with the team |
| `.claude/`, `.mcp.json` | AI agent configuration |

Shell dotfiles (`.zshrc`, `.zprofile`, `.gitconfig`) are tracked at the root — this repository doubles as a dotfiles/home directory. Read them before running anything that might symlink them over your own configuration.

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

**Empty directories under `projects/`** — submodules were not initialised. Run `git submodule update --init --recursive`.

**`console: page build FAILED`** — the page installs at the newest published versions, so a new major of a dependency can break it. Run `cd tools/console/web && npm install && npm run build` to see the error.

**Port already in use with Docker** — something else is bound to the published port. Check with `docker compose ps` and `docker compose config`, then stop the conflicting process or change the mapping.

**A deep link 404s in a local preview** — serve the build with `tools/dash serve` (it builds at the root). The default build is for the `/bamr87/` Pages subpath.

---

*Found a gap or an inaccuracy in this guide? Please open a PR — the `TODO (maintainer)` callouts above are the known unknowns and are the best place to start.*
