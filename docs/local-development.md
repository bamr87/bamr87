---
title: Running the site locally
description: How to install dependencies, build, and serve this repository on your own machine.
---

# Running the site locally

This page is a starting point for anyone who has just cloned the repository and
wants to build and preview the site.

> **About the `TODO` markers below.** This guide was written from the repository
> layout. A few details — exact task names, container service names, ports —
> depend on file contents that should be read straight from the source rather
> than guessed. Where that is the case, the guide shows you the command that
> *lists* the real answer, and leaves a `TODO` for a maintainer to fill in the
> short version. Please replace them as you confirm each one.

---

## 1. What's in the repository

This is a monorepo. The files that matter for local development are all at the
repository root:

| File / directory | Role |
| --- | --- |
| `Gemfile` | Ruby dependencies, installed with [Bundler](https://bundler.io/). |
| `Rakefile` | Task runner — the entry point for build/serve/clean tasks. |
| `_config.yml` | Site configuration. |
| `_config_dev.yml` | Development overrides layered on top of `_config.yml`. |
| `docker-compose.yml` | Container-based workflow, if you'd rather not install Ruby locally. |
| `.devcontainer/` | Dev container definition for VS Code and GitHub Codespaces. |
| `.env.example` | Template for local environment variables. |
| `.gitmodules`, `SUBMODULES.md` | Git submodules — see [`SUBMODULES.md`](../SUBMODULES.md). |
| `.pre-commit-config.yaml`, `.husky/` | Commit-time hooks and checks. |
| `.prettierrc`, `.prettierignore`, `.editorconfig` | Formatting rules. |
| `_data/`, `assets/`, `pages/`, `projects/`, `templates/`, `docs/`, `index.md` | Site content and layout sources. |
| `tools/` | Repository tooling and scripts. |

There are three reasonable ways to get running. Pick **one**.

---

## 2. Option A — Dev container (least setup)

The repository ships a `.devcontainer/` directory, so the toolchain is already
described for you.

- **VS Code:** install the *Dev Containers* extension, open the repository
  folder, and choose **Reopen in Container** when prompted (or run
  *Dev Containers: Reopen in Container* from the command palette).
- **GitHub Codespaces:** create a codespace on the branch you want; the same
  definition is used automatically.

Once the container is up, continue from [step 5, *Build and serve*](#5-build-and-serve).

> **TODO (verify):** does `.devcontainer/devcontainer.json` run a
> `postCreateCommand` that already installs dependencies, and does it forward a
> preview port? If so, say so here so readers can skip ahead.

---

## 3. Option B — Docker Compose

The repository includes a `docker-compose.yml`. First, see which services it
defines:

```bash
docker compose config --services
```

Then start the one you need:

```bash
docker compose up <service>
```

To stop and clean up:

```bash
docker compose down
```

> **TODO (verify):** replace `<service>` with the real service name, note the
> port the site is published on, and mention any volumes or environment
> variables the service expects.

---

## 4. Option C — Native Ruby toolchain

### Prerequisites

- **Ruby** with **Bundler** available (`gem install bundler` if `bundle` is
  missing). The presence of a `Gemfile` is what makes Bundler the install path.
- **Git**, for the repository and its submodules.

> **TODO (verify):** if `Gemfile` (or a `.ruby-version` / `Gemfile.lock`) pins a
> Ruby version, state it explicitly here.

### Clone with submodules

This repository uses git submodules (`.gitmodules`), so a plain clone will leave
some directories empty:

```bash
git clone --recurse-submodules https://github.com/bamr87/bamr87.git
cd bamr87
```

Already cloned without them?

```bash
git submodule update --init --recursive
```

See [`SUBMODULES.md`](../SUBMODULES.md) for the full story on how submodules are
organised and updated in this repository.

### Install dependencies

```bash
bundle install
```

### Environment variables

Copy the example file and fill in any values you need:

```bash
cp .env.example .env
```

`.env` is not committed — check `.env.example` for the list of keys and what
each one is for.

---

## 5. Build and serve

The repository drives its build through a `Rakefile`. List the available tasks
first — this is always the authoritative answer, and it never goes stale:

```bash
bundle exec rake -T
```

That prints every task with its description. Pick the one that builds or serves
the site and run it:

```bash
bundle exec rake <task>
```

> **TODO (verify):** replace this with the two or three tasks a newcomer
> actually needs — for example the build task, the local serve task, and a clean
> task — plus the URL the local server listens on.

### Development configuration

There are two config files: `_config.yml` and `_config_dev.yml`. The `_dev`
variant exists to override settings for local work (things like the site URL or
base path typically differ between local and published builds).

> **TODO (verify):** document how `_config_dev.yml` gets applied — whether a
> rake task passes it automatically, or whether you need to supply both config
> files on the command line. Getting this wrong is the most common reason local
> links and asset paths break, so it's worth spelling out.

---

## 6. Checks before you commit

The repository configures automated checks:

- **pre-commit** (`.pre-commit-config.yaml`). Install the hooks once with:

  ```bash
  pre-commit install
  ```

  and run them against everything with:

  ```bash
  pre-commit run --all-files
  ```

- **Husky** (`.husky/`) — git hooks managed through the Node toolchain.
- **Prettier** (`.prettierrc`, `.prettierignore`) and **EditorConfig**
  (`.editorconfig`) — formatting is enforced, so let your editor pick these up.

> **TODO (verify):** if there is a test task, add it here (`bundle exec rake -T`
> will reveal it) along with anything CI in `.github/workflows/` runs that
> contributors should reproduce locally.

---

## 7. Troubleshooting

**A directory is empty or a build fails on a missing include.**
Submodules probably aren't checked out. Run
`git submodule update --init --recursive` and see [`SUBMODULES.md`](../SUBMODULES.md).

**`bundle: command not found`.**
Bundler isn't installed for your Ruby: `gem install bundler`.

**Native gem fails to build during `bundle install`.**
Use the dev container (Option A) or Docker Compose (Option B) instead — both
exist precisely so you don't have to fight a local Ruby toolchain.

**Links or assets resolve incorrectly in the local preview.**
The development config (`_config_dev.yml`) is likely not being applied — see
[Development configuration](#development-configuration).

---

## See also

- [`CONTRIBUTING.md`](../CONTRIBUTING.md) — contribution workflow.
- [`SUBMODULES.md`](../SUBMODULES.md) — how submodules are structured.
- [`SCHEMA.md`](../SCHEMA.md) — content/data schema.
- [`AGENTS.md`](../AGENTS.md) / [`CLAUDE.md`](../CLAUDE.md) — conventions for
  automated contributors working in this repository.
