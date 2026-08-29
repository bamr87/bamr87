---
title: First-Time Setup
description: How to clone this repository correctly, including git submodule initialization.
---

# First-Time Setup

This page covers the first thing you should do with this repository: get a **complete** working copy onto your machine. Everything else — installing dependencies, building the site, running checks — assumes you have completed this step.

## Start here: this repository uses git submodules

There is a [`.gitmodules`](../.gitmodules) file at the repository root, which means part of this project's content lives in **separate repositories that are linked in as git submodules**.

This matters because of a git default that surprises almost everyone the first time:

> A plain `git clone` creates the submodule directories but leaves them **empty**. Git does
> not fetch submodule contents unless you explicitly ask it to.

If you clone without initializing submodules, you will end up with a tree that looks superficially correct but has empty directories where content should be. Any build or preview you run against that tree may be incomplete, and the failure mode is usually a confusing "file not found" or a page that renders with missing sections — not a clear "you forgot the submodules" error.

So: initialize the submodules first, then move on.

## Option A — Clone with submodules in one step (recommended)

If you have not cloned the repository yet, use `--recurse-submodules`. This clones the superproject and checks out every submodule at the recorded commit in a single command:

```bash
git clone --recurse-submodules https://github.com/bamr87/bamr87.git
cd bamr87
```

If you prefer SSH:

```bash
git clone --recurse-submodules git@github.com:bamr87/bamr87.git
cd bamr87
```

## Option B — You already cloned without submodules

This is the common case: you ran a normal `git clone`, noticed empty directories, and found this page. You do **not** need to delete anything and start over. From inside the repository root, run:

```bash
git submodule update --init --recursive
```

What the flags do:

| Flag | Effect |
| --- | --- |
| `--init` | Registers submodules from `.gitmodules` into your local `.git/config` so git knows to track them. Without this, `git submodule update` silently does nothing for uninitialized submodules. |
| `--recursive` | Also initializes any submodules **nested inside** a submodule. Harmless if there are none, essential if there are. |

## Verify it worked

Check the state of every submodule:

```bash
git submodule status
```

Read the first character of each output line:

- **no prefix** (a space) — the submodule is initialized and checked out at the commit the
  superproject expects. This is what you want for every line.
- **`-` prefix** — the submodule is **not initialized**. Go back and run the `Option B`
  command above.
- **`+` prefix** — the submodule is checked out at a *different* commit than the
superproject records. That is not necessarily broken (you may be intentionally working inside a submodule), but on a fresh clone it is unexpected.

Then confirm your working tree is clean:

```bash
git status
```

A fresh, correctly initialized clone should report nothing to commit. If `git status` shows submodule paths as modified immediately after cloning, see the troubleshooting notes below.

## Which submodules are there, and what are they for?

This repository maintains a dedicated document for that: [`SUBMODULES.md`](../SUBMODULES.md) at the repository root.

Treat `SUBMODULES.md` as the **source of truth** for the submodule inventory, what each one contains, and any project-specific conventions for updating them. It is intentionally not duplicated here so the two documents cannot drift apart. If `SUBMODULES.md` documents a project-specific setup command or helper script, prefer that over the generic `git` commands above.

The machine-readable definition — submodule paths and their upstream URLs — lives in [`.gitmodules`](../.gitmodules).

## Keeping submodules up to date later

Submodules are pinned to a specific commit, so they do **not** advance automatically when you pull the superproject. After pulling changes that touch a submodule pointer, run:

```bash
git pull
git submodule update --init --recursive
```

Or do both in one step:

```bash
git pull --recurse-submodules
```

If you want git to check out the right submodule commits automatically whenever you switch branches or check out a different revision, enable this once for your local clone:

```bash
git config submodule.recurse true
```

This makes `git checkout`, `git pull`, and friends recurse into submodules by default. It is a per-clone convenience setting; it does not change anything for other contributors.

## Troubleshooting

**`git submodule status` shows a `-` prefix after cloning.** The submodule was never initialized. Run `git submodule update --init --recursive` from the repository root.

**Cloning or updating a submodule fails with a permission or authentication error.** The submodule's upstream URL may point at a repository you do not have access to, or it may use a protocol (SSH vs. HTTPS) you are not set up for. Check the URL for that path in [`.gitmodules`](../.gitmodules) and confirm with a maintainer whether the submodule is public. If the only difference is the protocol, you can override the URL locally with `git config submodule.<path>.url <alternate-url>` followed by `git submodule sync --recursive` and `git submodule update --init --recursive`.

**A submodule directory shows as modified right after a clean clone.** Most often this is a detached-HEAD or line-ending artifact rather than real local edits. Inspect what changed with:

```bash
git diff --submodule
```

To discard local changes inside submodules and force them back to the recorded commits:

```bash
git submodule update --init --recursive --force
```

> ⚠️ `--force` discards uncommitted work inside submodule directories. Only use it if you
> are sure you have nothing to keep there.

**Directories are still empty after `git submodule update --init`.** Make sure you are running the command from the **repository root** (the directory containing `.gitmodules`), not from inside a subdirectory.

## What comes next

Once `git submodule status` is clean for every entry, you have a complete working copy and can move on to installing dependencies and running the project locally. The relevant configuration lives in these root-level files:

- [`CONTRIBUTING.md`](../CONTRIBUTING.md) — contribution workflow and expectations.
- [`Gemfile`](../Gemfile) — Ruby dependencies for the site.
- [`_config.yml`](../_config.yml) and [`_config_dev.yml`](../_config_dev.yml) — site
  configuration, with a separate development variant.
- [`Rakefile`](../Rakefile) — project task definitions.
- [`docker-compose.yml`](../docker-compose.yml) — containerized local environment.
- [`.devcontainer/`](../.devcontainer) — VS Code / Codespaces dev container definition, an
  alternative to setting up a local toolchain by hand.
- [`.env.example`](../.env.example) — template for local environment variables; copy it to
  `.env` and fill in values as needed.
- [`.pre-commit-config.yaml`](../.pre-commit-config.yaml) and [`.husky/`](../.husky) — the
  pre-commit hooks this project runs.

Refer to those files (and `CONTRIBUTING.md` in particular) for the exact commands used to install dependencies, build, and serve the site.
