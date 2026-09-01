---
title: Development Environment Setup
description: How to clone, initialise and run this repository locally, including the git submodule workflow.
---

# Development Environment Setup

This guide takes you from nothing to a working local checkout of this repository.

> **Read this first:** the repository root contains a [`.gitmodules`](../.gitmodules) file,
> which means parts of this project live in **separate repositories** that are mounted into
> this one as git submodules. A plain `git clone` will leave those directories **empty**,
> and later steps (dependency install, build, site serve) will fail in confusing ways.
> Initialising submodules is step 1 below, not a footnote.
>
> For details about the individual submodules — what each one is, where it points, and
> any per-submodule rules — see [`SUBMODULES.md`](../SUBMODULES.md), which is the
> authoritative reference. This page covers the *workflow*.

---

## Prerequisites

| Tool | Why it is needed |
| --- | --- |
| `git` (2.13 or newer) | Required for the `--recurse-submodules` and `submodule update --recursive` behaviour used below. |
| Ruby + [Bundler](https://bundler.io/) | The repository contains a [`Gemfile`](../Gemfile), so Ruby dependencies are managed with Bundler. |
| Docker *(optional)* | There is a [`docker-compose.yml`](../docker-compose.yml) and a [`.devcontainer/`](../.devcontainer) directory if you prefer a containerised environment. |

Check your git version — older versions do not support recursive submodule flags:

```bash
git --version
```

---

## First-time setup

### 1. Clone the repository **with its submodules**

```bash
git clone --recurse-submodules https://github.com/bamr87/bamr87.git
cd bamr87
```

**Already cloned without the flag?** You do not need to start over. From inside the repository run:

```bash
git submodule update --init --recursive
```

Verify it worked before continuing. Every line of the following output should begin with a commit SHA; a leading `-` means that submodule is still uninitialised:

```bash
git submodule status
```

```text
 3f0a1b2c...  some/path (v1.2.0)     # ✅ initialised
-3f0a1b2c...  some/path              # ❌ not initialised — rerun the update command
```

Do not proceed until there are no `-` prefixes.

### 2. Configure your environment

The repository ships an [`.env.example`](../.env.example) template. Copy it and fill in any values you need:

```bash
cp .env.example .env
```

`.env` is intended to stay local — check [`.gitignore`](../.gitignore) before committing anything that looks like a secret.

### 3. Install dependencies

```bash
bundle install
```

If this step fails with "file not found" errors pointing at a submodule directory, go back to step 1 — an incomplete submodule checkout is the most common cause.

### 4. Run the site locally

The repository is a static site: it has [`_config.yml`](../_config.yml), a development override at [`_config_dev.yml`](../_config_dev.yml), an [`index.md`](../index.md), and `pages/` and `assets/` directories.

There is also a [`Rakefile`](../Rakefile). List the available tasks — the local serve command is most likely one of them:

```bash
bundle exec rake -T
```

> **TODO (maintainers):** replace this note with the canonical local-serve command,
> including how `_config.yml` and `_config_dev.yml` are meant to be combined.

Alternatively, use the containerised path via [`docker-compose.yml`](../docker-compose.yml) or open the project in the [`.devcontainer/`](../.devcontainer) configuration from VS Code.

### 5. Enable the repository's hooks and linters

This repository configures pre-commit tooling ([`.pre-commit-config.yaml`](../.pre-commit-config.yaml), [`.husky/`](../.husky)) and formatting/linting rules ([`.prettierrc`](../.prettierrc), [`.markdownlintignore`](../.markdownlintignore), [`.editorconfig`](../.editorconfig)). See [`CONTRIBUTING.md`](../CONTRIBUTING.md) for the project's contribution rules before opening a pull request.

---

## The everyday submodule workflow

Submodules are the part of this repository most likely to surprise you. The mental model:

> The parent repository does **not** store the submodule's files. It stores a **pointer** —
> one specific commit SHA — for each submodule. Updating a submodule is therefore always
> two commits: one *inside* the submodule repository, and one *in this repository* to move
> the pointer.

### Pulling changes from teammates

A `git pull` updates the pointers but does **not** update the submodule working trees. After every pull:

```bash
git pull
git submodule update --init --recursive
```

To make git do this automatically for the rest of time, set this once per clone:

```bash
git config submodule.recurse true
```

With `submodule.recurse` enabled, `git pull`, `git checkout` and `git switch` will update submodules for you.

### Seeing what state you are in

```bash
git submodule status               # SHA + path for each submodule
git submodule foreach 'git status --short'   # working-tree status inside each one
git diff --submodule                          # what pointer changes are staged/unstaged
```

In `git status`, a submodule listed as `modified: some/path (new commits)` means the pointer has moved. `(modified content)` means there are uncommitted edits *inside* the submodule.

### Making a change inside a submodule

By default a freshly-initialised submodule is in **detached HEAD** state. Commits made there are not on any branch and are easy to lose. Always check out a branch first:

```bash
cd path/to/submodule
git checkout main            # or the submodule's default branch
git pull

# ...make your edits...

git add .
git commit -m "Describe the change"
git push                     # ← push the submodule FIRST
```

Then return to the parent repository and record the new pointer:

```bash
cd -                         # back to the repository root
git add path/to/submodule
git commit -m "Bump path/to/submodule to latest main"
git push
```

**Order matters.** If you push the parent repository's pointer before pushing the submodule's commit, everyone else — and CI — will try to check out a commit that does not exist on the remote and the build will break. To have git guard against this for you:

```bash
git push --recurse-submodules=check
```

### Pulling the latest upstream commits into a submodule

To fast-forward a submodule to the tip of its tracked remote branch:

```bash
git submodule update --remote path/to/submodule
git add path/to/submodule
git commit -m "Update path/to/submodule"
```

Omit the path to do this for every submodule at once. Note that `--remote` follows the branch recorded in `.gitmodules` (defaulting to the remote's default branch), which is different from plain `git submodule update`, which restores the pointer already recorded in the parent repository.

### Adding a new submodule

```bash
git submodule add <repository-url> path/to/submodule
git commit -m "Add path/to/submodule"
```

This writes a new entry into [`.gitmodules`](../.gitmodules). Please also add the new submodule to [`SUBMODULES.md`](../SUBMODULES.md) so the reference stays complete.

### Removing a submodule

```bash
git submodule deinit -f path/to/submodule
git rm path/to/submodule
rm -rf .git/modules/path/to/submodule
git commit -m "Remove path/to/submodule"
```

### Continuous integration

If a workflow in [`.github/`](../.github) builds anything that lives inside a submodule, its checkout step must opt in — GitHub's `actions/checkout` does **not** fetch submodules by default:

```yaml
- uses: actions/checkout@v4
  with:
    submodules: recursive
```

A build that works locally but fails in CI with missing files is very often this setting.

---

## Troubleshooting

| Symptom | Likely cause and fix |
| --- | --- |
| A submodule directory exists but is empty. | Submodules were never initialised. Run `git submodule update --init --recursive`. |
| `git submodule status` shows a `-` prefix. | Same as above — that submodule is uninitialised. |
| `fatal: not a git repository` when running git inside a submodule directory. | The submodule was not initialised, so there is no `.git` file linking it to `.git/modules/`. |
| `git status` shows a submodule as modified but you changed nothing. | The submodule's HEAD moved (often by an earlier `--remote` update). Run `git submodule update` to restore the recorded pointer, or `git add` the path to accept the new one. |
| CI cannot find a commit that exists on your machine. | You pushed the parent pointer without pushing the submodule commit. Push from inside the submodule, then re-run CI. |
| Dependency install or build fails with missing files under a submodule path. | Incomplete checkout — go back to step 1 of first-time setup. |

---

## Unverified — maintainers, please confirm

This guide was drafted from the repository's file listing. The following points were inferred from the presence of a file rather than from reading it, and should be corrected or confirmed:

- That `bundle install` is the correct dependency-install command (inferred from `Gemfile`).
- The correct local-serve command and how `_config.yml` and `_config_dev.yml` combine
  (see the TODO in step 4).
- That `cp .env.example .env` is the expected environment-configuration step.
- Which `rake` task, if any, is the canonical entry point.
- Whether the existing workflows under `.github/` already set `submodules: recursive`.
- Whether the submodule workflow above matches what [`SUBMODULES.md`](../SUBMODULES.md)
already documents; if the two disagree, `SUBMODULES.md` wins and this page should be corrected.

## Related documents

- [`SUBMODULES.md`](../SUBMODULES.md) — authoritative submodule reference
- [`CONTRIBUTING.md`](../CONTRIBUTING.md) — contribution rules
- [`SCHEMA.md`](../SCHEMA.md) — data/content schema
- [`AGENTS.md`](../AGENTS.md) / [`CLAUDE.md`](../CLAUDE.md) — automation and agent conventions
