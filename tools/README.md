# tools/

Development environment setup and maintenance utilities for the **bamr87 monorepo**.

## Overview

This directory contains cross-platform scripts for bootstrapping, configuring, and maintaining the development environment. The primary entrypoint is `setup.sh`, which reads package definitions from the central manifest `devtools.conf` and installs them using the platform-native package manager.

## Files

| File | Purpose |
|---|---|
| `devtools.conf` | **Central manifest** — declares all tools, packages, and env vars by platform |
| `devtools-env.sh` | Shell environment loader — exports vars, PATH, and aliases from the manifest |
| `Brewfile` | macOS Homebrew bundle — native `brew bundle` format (derived from manifest) |
| `setup.sh` | **Primary entrypoint** — cross-platform dev environment setup |
| `setup-dev.sh` | Legacy wrapper — delegates to `setup.sh --local` |
| `update-submodules.sh` | Git submodule update with status checking and selective updates |

## Architecture

```
bamr87/
├── .devcontainer/
│   ├── devcontainer.json      # VS Code dev container config
│   └── Dockerfile             # Dev container image
├── .env.example               # Environment variable template
├── .zprofile                   # Sources tools/devtools-env.sh
├── docker-compose.yml         # All services (dev, wiki, db, etc.)
└── tools/
    ├── devtools.conf          # ← Central tool manifest (edit this)
    ├── devtools-env.sh        # Shell env loader (sourced by .zprofile)
    ├── Brewfile               # macOS Homebrew bundle
    ├── setup.sh               # Main setup entrypoint
    ├── setup-dev.sh           # Legacy wrapper
    └── update-submodules.sh   # Submodule management
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

| Prefix | Package Manager | Platform |
|---|---|---|
| *(none)* | Generic (brew/apt/winget) | All |
| `@brew` | Homebrew formula | macOS |
| `@cask` | Homebrew cask | macOS |
| `@apt` | apt-get | Ubuntu/Debian/WSL |
| `@winget` | winget | Windows |
| `@pip` | pip3 | All (Python) |
| `@npm` | npm | All (Node.js) |
| `@custom` | Custom install logic | Platform-specific |

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

### Shell Environment

The `.zprofile` sources `tools/devtools-env.sh`, which:
- Reads the `[env]` section from `devtools.conf` and exports variables
- Adds `tools/` and `scripts/` to `PATH`
- Registers convenience aliases

```bash
# Available after sourcing (or opening a new terminal):
bamr87-setup           # Run tools/setup.sh
bamr87-update          # Run tools/update-submodules.sh
bamr87-cv              # cd cv && npm run dev
bamr87-docs            # mkdocs serve
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

| Platform | Package Manager | Status |
|---|---|---|
| macOS | Homebrew (`brew`) | Full support |
| Ubuntu/Debian | APT (`apt-get`) | Full support |
| WSL (Windows) | APT + winget | Full support |
| Windows (Git Bash) | winget | Basic support |

## Adding a New Tool

1. Edit [tools/devtools.conf](devtools.conf) — add the package to the appropriate section
2. If macOS: also add to [tools/Brewfile](Brewfile)
3. If custom install logic is needed: add a case to `install_custom()` in [tools/setup.sh](setup.sh)
4. Test: `./tools/setup.sh --dry-run --verbose`

## Submodule Management

```bash
./tools/update-submodules.sh --status      # Check status
./tools/update-submodules.sh --check       # Check for updates
./tools/update-submodules.sh               # Update all
./tools/update-submodules.sh cv            # Update one
```

## Troubleshooting

**Docker not starting:**
- macOS: Ensure Docker Desktop is running
- Linux: `sudo systemctl start docker`

**Port conflicts:** Edit `.env` to change ports, check with `lsof -i :5000`

**Submodule issues:** `git submodule sync --recursive && git submodule update --init --recursive --force`

**Permission denied on scripts:** `chmod +x tools/*.sh scripts/*.sh`

**Python venv errors:** `rm -rf .venv-docs README/.venv && ./tools/setup.sh --local docs`

---

**Version:** 2.0.0 | **Last Modified:** 2026-02-10
