---
title: Prerequisites
description: What a newcomer (and CI) must have installed before running the quick start.
---

# Prerequisites

This page exists so that a human laptop and a CI runner can follow the *same* quick start and end up with the *same* toolchain. If you only read one thing: **every version below has exactly one authoritative source file in this repository, and this page mirrors it.** When you bump a version, bump it in the source file first, then update the table here in the same commit.

> [!IMPORTANT]
> Some cells in the table below are marked `TODO (unverified)`. They were not
> filled in automatically because the exact pin lives inside a file that must be
> read to be quoted accurately. Please replace each `TODO` with the value from
> the listed source file — do not guess.

## Toolchains used by this repository

The repository root shows which toolchains are in play:

| Toolchain | Evidence in the repo root | Required version | Authoritative source |
| --- | --- | --- | --- |
| Node.js | `tools/console/web/package.json`, `.prettierrc`, `.husky/` | current LTS (the page's React Router requires ≥ 22) | `.github/workflows/console-web.yml` |
| Python | `tools/console/requirements.txt`, `.pre-commit-config.yaml` | 3.12+ | `_data/fleet.yml` `toolchain:` |
| Docker / Compose | `docker-compose.yml`, `.devcontainer/` | `TODO (unverified)` | `docker-compose.yml` and `.devcontainer/` |
| Git | `.gitmodules`, `SUBMODULES.md` | any recent 2.x | — |

Not every task needs every toolchain. Pick the row(s) that match what you are about to do:

- **Editing site content, building the site or running the console** → Python + Node.js.
- **Running the formatter or the git hooks** → Node.js (Prettier is configured
  via `.prettierrc`; hooks live in `.husky/`).
- **Running `pre-commit`** → Python, per `.pre-commit-config.yaml`.
- **Using the container-based setup** → Docker only; the container image is
responsible for the Ruby/Node versions, see `.devcontainer/` and `docker-compose.yml`.

## Verify what you already have

Run these before filing a "it doesn't build" issue. Each command prints the version of a tool referenced above:

```bash
ruby -v
bundler -v          # or: bundle -v
node -v
npm -v
python3 --version
pre-commit --version
docker --version
docker compose version
git --version
```

If a command is missing, install that tool with your usual package manager (Homebrew, apt, asdf, rbenv, nvm, mise, …). This repository does not prescribe a version manager, so use whichever one already installs the pinned versions from the table above.

## Submodules

This repository uses git submodules (`.gitmodules` is present at the root, and `SUBMODULES.md` documents them). A fresh clone is not complete until the submodules are initialised:

```bash
git clone --recurse-submodules <repo-url>
# or, in an existing clone:
git submodule update --init --recursive
```

See [`SUBMODULES.md`](../SUBMODULES.md) for the details of which submodules exist and what they are for.

## Environment variables

The root contains `.env.example`. Copy it before running anything that reads configuration from the environment:

```bash
cp .env.example .env
```

Then fill in the values documented in that file.

## Keeping this page honest

CI and this page drift apart the moment one of them changes alone. To prevent that:

1. Pin versions in machine-readable files (`Gemfile` / `.ruby-version` /
   `.nvmrc` / `package.json` `engines` / `.pre-commit-config.yaml`).
2. Have the CI workflow's setup step read those files (for example
`ruby-version: .ruby-version` or `node-version-file: .nvmrc`) rather than hard-coding a version inline.
3. Update the table above in the same pull request that changes any pin.

A reviewer checklist for version bumps:

- [ ] Source file (lockfile / `.ruby-version` / `.nvmrc` / …) updated
- [ ] CI setup step still resolves to the same version
- [ ] Table in `docs/prerequisites.md` updated
- [ ] Devcontainer image (`.devcontainer/`) still matches

## Related documents

- [`README.md`](../README.md) — project overview and quick start
- [`CONTRIBUTING.md`](../CONTRIBUTING.md) — contribution workflow
- [`SUBMODULES.md`](../SUBMODULES.md) — submodule layout
- [`SCHEMA.md`](../SCHEMA.md) — data/schema conventions
- [`AGENTS.md`](../AGENTS.md) / [`CLAUDE.md`](../CLAUDE.md) — agent-facing conventions
