# tools/

Development environment setup and maintenance utilities for the **bamr87 monorepo**.

## Overview

This directory contains cross-platform scripts for bootstrapping, configuring, and maintaining the development environment. The primary entrypoint is `setup.sh`, which reads package definitions from the central manifest `devtools.conf` and installs them using the platform-native package manager.

## Files

| File | Purpose |
| --- | --- |
| `devtools.conf` | **Central manifest** — declares all tools, packages, and env vars by platform |
| `devtools-env.sh` | Shell environment loader — exports vars, PATH, and aliases from the manifest |
| `Brewfile` | macOS Homebrew bundle — native `brew bundle` format (derived from manifest) |
| `setup.sh` | **Primary entrypoint** — cross-platform dev environment setup |
| `setup-terminal.sh` | macOS terminal CHUI — clones `bamr87/chui`, installs Oh My Zsh / Powerlevel10k / Meslo, registers the Nerd Font with CoreText, wires bamr87 env into `~/.config/chui/local.zsh` |
| `macos-register-nerd-fonts.swift` | Registers `MesloLGS Nerd Font` with CoreText so Apple Terminal does not render `eza`/`ls` icons as `?` |
| `update-submodules.sh` | Refresh `projects/` — bring each submodule onto its declared branch at the remote tip (safe by default) and record moved pointers |
| `install-workspace-sync.sh` | Installs the `com.bamr87.workspace-sync` LaunchAgent (macOS) that runs `update-submodules.sh --no-commit --no-push` daily and at login, keeping the local clone on `main` everywhere — pointer recording stays with the `update-submodules.yml` PR (`--uninstall` removes it) |
| `install-prose-hook.sh` | Installs a **global** git `pre-commit` hook (`~/.git-hooks`, `core.hooksPath`) that runs `unwrap-prose.py` over the staged markdown and restages it, so a commit is born passing the `markdown-oneline` gate and the CI run it would have cost never happens; other hook names forward to each repo's own `.git/hooks`/`.husky` hooks. `PROSE_HOOK_SKIP=1` skips once, `--uninstall` removes it |
| `audit-git-hooks.sh` | Read-only diagnostic for the "Husky vs. pre-commit" question — reports which hook manager is actually live in a clone. Husky sets `core.hooksPath` to `.husky`, which makes git ignore the `.git/hooks` shim `pre-commit install` writes, so only one can be in effect and whichever installer ran last wins. Never installs or rewrites config, and always exits 0 |
| `fleet-dev.sh` | **The fleet dev stack's entry point** (`dash dev`) — launch, debug and work on any submodule from the hub. Drives each project as its OWN compose project joined by the external `fleet-net`, layering the hub's generated port override over the submodule's untouched compose file; `--debug` adds the repo's own debugpy layer. `up|down|ps|logs|exec|build|config|ports|list`, `--all` for everything. See [docs/FLEET-COMPOSE.md](../docs/FLEET-COMPOSE.md) |
| `fleet-compose.py` | Projects [`_data/ports.yml`](../_data/ports.yml) onto that stack — generates `.env.fleet`, `compose/overrides/*.yml` and `compose.fleet.yml`, and gates the allocation (bands, collisions, staleness) as drift check (m). `check --audit` also reports which submodules still hardcode a published port |
| `fleet_smoke.py` | **The monorepo smoke test** (`dash dev smoke`) — connects to every running fleet container and exercises it for real (HTTP GET, TCP connect, a `select` through the container's own `psql`, `redis-cli PING`, and an `exec` that records which user the process runs as), writes the whole observation to `_data/smoke.yml`, and `check` re-probes and fails on any move away from that baseline. Topology comes from `_data/ports.yml`, so a new service is probed automatically |
| `docker_harmonize.py` | The **fleet Docker standard** (`dash docker`) — brings a repo's Dockerfiles and compose files to it from ONE version registry (`_data/fleet.yml` `images:`): variant kept, never lowered, deliberate pins respected, Postgres 18 mount, loopback env-overridable ports, no `container_name`, `127.0.0.1` healthchecks. Line edits that preserve comments; idempotent. `tools/fanout.sh --kit docker` delivers it as PRs. See [docs/DOCKER.md](../docs/DOCKER.md) |
| `docker_view.py` | The **consolidated Docker view** (`dash docker view --write`) — joins the port registry, the image contract, the smoke recording, the launch/attach configurations and the read-only harmonizer audit into `_data/docker.yml`, rendered at `/docker/`: what to open, what is running, which image each service is on, and where that drifts from the contract (a deliberate pin, an `image_overrides:` ceiling and a floating tag are counted apart from real drift). Local-first — two of its inputs only exist where the containers and submodules are. |
| `test_docker_view.py` | Tests for `docker_view.py` — each one a mistake it actually made before it shipped: comparing majors instead of the contract's precision (which reported five repos on Python 3.11/3.12 as conforming to 3.14), counting a deliberate pin or an `image_overrides:` ceiling as drift, taking a multi-stage `FROM base` for an image, and reporting a repo with no checkout as clean. Run by drift check (n). |
| `pg-major-upgrade.sh` | Upgrade a compose service's Postgres across a MAJOR without losing data (`dash dev db-upgrade`): backs up the raw volume, dumps, verifies, recreates on the new layout, restores. Dry run without `--yes` |
| `dash` | Unified dash CLI (`status`, `monitor`, `dev`, `serve`, `sync`, `ai`, `gen`, `harnesses`, `console`, `lake`, …) — see [docs/DASH.md](../docs/DASH.md); `dash lake sync|status|export` is the local data lake + Phoenix trace export of the local stack ([docs/HARNESS-OPS.md](../docs/HARNESS-OPS.md)) |
| `console/` | The **Harness Console** — the local control plane's front end: a FastAPI service (`tools/dash console`, or `docker compose up -d console` → http://127.0.0.1:4001) that renders every committed fleet signal (harness inventory, schedules, throughput, cost trends, triage, credentials by age), runs the **allowlisted** `dash` operations as jobs with live logs (dry-run by default; GitHub-writing operations confirm-gated and serialized), dispatches control-plane workflows, and edits the `harnesses:` contract in `fleet.yml` with comments preserved — never commits, never merges. Its **Traces** tab is the window onto the rest of the local stack: the data lake (`dash lake`, `.dash-lake/`) and the Phoenix trace store (compose service `phoenix`, :6006). See [docs/HARNESS-OPS.md](../docs/HARNESS-OPS.md) |
| `dash-gen` | Wrapper for the registry generator (`health`, `readme`, `ai`, `ai-usage`, `actions`, `daily`, `triage`, `remediate`, `reconcile`, `vendor`, `estimate`, `ledger`, `all`) in [.github/scripts/dash-gen/](../.github/scripts/dash-gen/) |
| `fleet-config.py` | Reads [`_data/fleet.yml`](../_data/fleet.yml), the fleet's central config. `audit` (= `dash secrets`) prints the per-repo matrix of declared secrets/variables vs what GitHub actually has; `sync --apply` (= `dash config sync`) projects the canonical repo **variables** onto every fleet repo; `show [dotted.key]` reads a value; `rotate` (= `dash secrets rotate`) runs the weekly credential loop — audit each repo's secret AGE from GitHub's `updated_at`, re-mint via the optional OAuth refresh grant, propagate hub-first to missing/stale copies — and `rotation-plan` (= `dash secrets plan`) is its read-only half. Secret *values* are never read or stored: `gh` returns names only, and a value to be written comes from the environment and goes straight to `gh secret set`'s stdin. See [`docs/TOKEN-ROTATION.md`](../docs/TOKEN-ROTATION.md). |
| `check-drift.sh` | **Hard drift gate** — registry/`.gitmodules` parity, README freshness, schema pyramid, and advisory GitHub-reality checks (CI + `dash status`) |
| `audit-standards.sh` | Standardization conformance matrix across the submodule fleet (wrapped by `dash audit`) |
| `run-all-tests.sh` | Aggregate verification — root lint, **the control plane's own `dash-gen` tests**, and each project's own checks (wrapped by `dash test`) |
| `adopt-release.sh` | Scaffolds the release-please pipeline into a repo and opens a PR (wrapped by `dash adopt-release`) |
| `protect-branch.sh` | Requires the CI gate on a repo's default branch (wrapped by `dash protect`) |
| `fanout.sh` | Shared fan-out engine — clone→branch→seed→commit→PR loop with dry-run and external-upstream guard, called by `standardize-fanout.yml`, `schema-fanout.yml`, and `deps-fanout.yml`. Targets resolve through `.gitmodules` **or**, for a registered repo that is not mounted as a submodule, through `_data/projects.yml` — the engine clones the target either way, so a mount was never what made a repo reachable |
| `issue-evidence.sh` | Builds one issue's **evidence bundle** in an isolated virtual environment — fresh clone, own toolchain (`venv`/`node_modules`/`vendor/bundle`), the project's own lint/test/build, screenshots, and issue-term-ranked candidate files. Tier 1 of the [issue pipeline](../docs/ISSUE-PIPELINE.md); `dash evidence <owner/repo> <n>`. Never executes commands found in an issue body, and scrubs credentials from every log it writes |
| `unpin-deps.sh` | Converts one repo to the fleet's **always-latest** dependency policy — strips exact pins, deletes + gitignores lockfiles, adapts CI installs (idempotent; the `deps-latest` fan-out kit runs it per clone) — see [docs/DEPENDENCIES.md](../docs/DEPENDENCIES.md) |
| `schema_lint.py` | Vendored Pyramid Schema linter (`check` + `init`) — provenance in [templates/schema/VERSION](../templates/schema/VERSION) |
| `gen-projects-schema.py` | Regenerates `projects/SCHEMA.md` from `.gitmodules` + the registry (`--check` gates staleness) |
| `render-diagrams.sh` | Validates every `diagrams/*.json` archify IR file and delivers the standalone HTML beside it |
| `unwrap-prose.py` | Liquid-safe one-paragraph-per-line unwrapper for markdown prose (`--check`/`--diff`/`--write`); vendored into the fleet by the prose kit |
| `conformance.py` | **Executable Universal Project Standard checker** (`dash spec`): `check [path]` runs the machine-checkable rows of `_data/specs.yml` against one repo (kinds detected from the tree or `--kinds`; `--gate` fails on MUST); `fleet --write` snapshots every submodule → `_data/conformance.yml` (the repo-evolution brief's adoption lane); the reusable `fleet-conformance.yml` runs the same checker in each repo's CI |
| `gen-catalog.py` | Regenerates the root `CATALOG.md` — the master index of specs, kits, references, registries, tools, workflows, AI layer, docs, dash surfaces, diagrams — from disk + each directory's README/SCHEMA tables (`--check` gates staleness) |
| `gen-specs-data.py` | Regenerates `_data/specs.yml` (the machine-readable Universal Project Standard) from the requirement tables in `specs/*.md` (`--check` gates staleness) |
| `seed-schema.sh` | Seeds the schema kit into one repo (dry-run default) — see [docs/SCHEMA-FRAMEWORK.md](../docs/SCHEMA-FRAMEWORK.md) |

## Architecture

```
bamr87/
├── .devcontainer/             # VS Code dev container config + image
├── .env.example               # Environment variable template
├── .zprofile                  # Sources tools/devtools-env.sh
├── docker-compose.yml         # All services (dev, wiki, db, etc.)
└── tools/                     # This directory — the Files table above is authoritative
    ├── environment setup      #   devtools.conf, devtools-env.sh, Brewfile, setup.sh
    ├── dash CLI + gates       #   dash, dash-gen, check-drift.sh, audit-standards.sh, run-all-tests.sh
    ├── fleet operations       #   update-submodules.sh, adopt-release.sh, protect-branch.sh, fanout.sh
    └── schema tooling         #   schema_lint.py, gen-projects-schema.py, seed-schema.sh
```

## Central Tool Manifest — `devtools.conf`

All tools and packages are defined in a single file instead of being hardcoded in scripts. To add or remove a tool, edit `devtools.conf`:

```conf
# Sections group related packages
[core]
git                             # Available on all platforms
jq                              # JSON processor

[languages]
@brew    node                   # macOS only (via Homebrew)
@apt     python3                # Linux only (via apt)
@winget  OpenJS.NodeJS.LTS      # Windows only (via winget)
@custom  node-linux             # Requires special install logic

[devtools]
@pip     pre-commit             # Installed via pip on all platforms
@cask    visual-studio-code     # Homebrew cask (macOS GUI app)

[env]
BAMR87_HOME=~/bamr87            # Exported to shell environment
```

**Prefix reference:**

| Prefix    | Package Manager           | Platform          |
| --------- | ------------------------- | ----------------- |
| _(none)_  | Generic (brew/apt/winget) | All               |
| `@brew`   | Homebrew formula          | macOS             |
| `@cask`   | Homebrew cask             | macOS             |
| `@apt`    | apt-get                   | Ubuntu/Debian/WSL |
| `@winget` | winget                    | Windows           |
| `@pip`    | pip3                      | All (Python)      |
| `@npm`    | npm                       | All (Node.js)     |
| `@custom` | Custom install logic      | Platform-specific |

After editing `devtools.conf`, also update `Brewfile` to stay in sync for macOS users who prefer native `brew bundle`.

## Quick Start

### First-time Setup

```bash
# Clone the repo
git clone --recurse-submodules https://github.com/bamr87/bamr87.git
cd bamr87

# Run the setup script (auto-detects your OS)
./tools/setup.sh
```

### Setup Modes

```bash
# Full setup (local + Docker)
./tools/setup.sh

# Docker/dev container only
./tools/setup.sh --docker

# Local development only (no Docker)
./tools/setup.sh --local

# Specific components only
./tools/setup.sh --local cv docs

# Preview without making changes
./tools/setup.sh --dry-run --verbose

# Skip OS package installation (if you already have deps)
./tools/setup.sh --skip-deps
```

### macOS terminal (CHUI)

On Darwin, `setup.sh` also runs `setup-terminal.sh` unless you pass `--skip-terminal`. That clone-and-install path is [bamr87/chui](https://github.com/bamr87/chui):

```bash
./tools/setup-terminal.sh            # clone ~/github/chui, install, register Meslo
./tools/setup.sh --skip-terminal     # hub tools only
```

Copying a Nerd Font into `~/Library/Fonts` is not enough — Apple Terminal keeps SF Mono until CoreText has registered the family. `macos-register-nerd-fonts.swift` does that, then CHUI's `macos-font.sh` sets profile **Clear Dark** to **MesloLGS Nerd Font**. If `ls` still prints `?`, run `ls` again in that window (or quit Terminal.app once).

bamr87 PATH/aliases live in `~/.config/chui/local.zsh` so they survive CHUI's `~/.zshrc` symlink. Do not append to that symlink from `setup.sh`.

### Shell Environment

The `.zprofile` (and CHUI `local.zsh`) source `tools/devtools-env.sh`, which:

- Reads the `[env]` section from `devtools.conf` and exports variables
- Adds `tools/` and `projects/scripts/` to `PATH`
- Registers convenience aliases

```bash
# Available after sourcing (or opening a new terminal):
bamr87-setup           # Run tools/setup.sh
bamr87-update          # Run tools/update-submodules.sh
bamr87-cv              # cd projects/cv-builder-pro && npm run dev
bamr87-dash            # Run tools/dash (unified dash CLI)
bamr87-docs            # tools/dash serve — Jekyll dash via docker (:4000)
bamr87-dc              # docker compose (from project root)
```

To load manually in any shell:

```bash
source ~/bamr87/tools/devtools-env.sh
```

### macOS — Brewfile

macOS users can also install tools directly with Homebrew's native bundle:

```bash
brew bundle --file=tools/Brewfile
brew bundle check --file=tools/Brewfile   # Check what's missing
```

### Dev Container (VS Code)

1. Open the repo in VS Code
2. When prompted, click **"Reopen in Container"**
3. VS Code builds the dev container with all tools pre-installed
4. The `postCreateCommand` runs `setup.sh` automatically

### Docker Compose

```bash
cp .env.example .env                       # Configure
docker compose up -d                       # Start all services
docker compose exec devenv bash            # Dev shell
docker compose --profile admin up -d       # Include pgAdmin
docker compose logs -f                     # View logs
docker compose down                        # Stop
```

## Platform Support

| Platform           | Package Manager   | Status        |
| ------------------ | ----------------- | ------------- |
| macOS              | Homebrew (`brew`) | Full support  |
| Ubuntu/Debian      | APT (`apt-get`)   | Full support  |
| WSL (Windows)      | APT + winget      | Full support  |
| Windows (Git Bash) | winget            | Basic support |

## Adding a New Tool

1. Edit [tools/devtools.conf](devtools.conf) — add the package to the appropriate section
2. If macOS: also add to [tools/Brewfile](Brewfile)
3. If custom install logic is needed: add a case to `install_custom()` in [tools/setup.sh](setup.sh)
4. Test: `./tools/setup.sh --dry-run --verbose`

## Submodule Management

`update-submodules.sh` refreshes the `projects/` folder so every submodule sits **on its declared branch** (from `.gitmodules`) at the latest remote commit, then records the moved pointers in the root repo. It is safe by default: a submodule with uncommitted changes, unpushed commits, or a diverged history is skipped with a warning instead of being reset — pass `--force` to re-align those, or `--detach` for the legacy detached-HEAD behaviour.

```bash
./tools/update-submodules.sh --status      # Show declared vs. checked-out branch
./tools/update-submodules.sh --check       # List available updates (no changes)
./tools/update-submodules.sh               # Refresh all onto their declared branch
./tools/update-submodules.sh cv            # Refresh one (path, short name, or .gitmodules name)
./tools/update-submodules.sh --no-commit   # Refresh but leave pointer changes staged
./tools/update-submodules.sh --force       # Also re-align dirty/diverged submodules
```

Wrapped by `tools/dash sync` (which also regenerates dash data) and the `bamr87-update` alias.

## Troubleshooting

**Docker not starting:**

- macOS: Ensure Docker Desktop is running
- Linux: `sudo systemctl start docker`

**Port conflicts:** Edit `.env` to change ports, check with `lsof -i :5000`

**Submodule issues:** `git submodule sync --recursive && git submodule update --init --recursive --force`

**Permission denied on scripts:** `chmod +x tools/*.sh projects/scripts/*.sh`

**Python venv errors:** `rm -rf .venv-docs projects/README/.venv && ./tools/setup.sh --local docs`

**Terminal icons are `?`:** `./tools/setup-terminal.sh` (registers MesloLGS with CoreText). Then `ls` again.

**`pip3 install --user` fails (PEP 668):** expected on Homebrew Python. `setup.sh` uses `pipx` (`brew install pipx`).

---

**Version:** 2.3.0 | **Last Modified:** 2026-09-20
