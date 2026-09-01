---
title: Git Hooks & Local Checks
description: How to install and run this repository's pre-commit, husky, Prettier, and markdownlint checks.
---

# Git Hooks & Local Checks

This repository ships configuration for several automated checks that run against your changes. They are **configured** when you clone, but most of them are not **installed** until you run a setup command — so a fresh clone will happily let you commit code that the tooling would otherwise flag.

This page covers the one-time setup and the manual commands you can run any time.

## What ships in this repository

| File / directory | Tool it belongs to | What it controls |
| --- | --- | --- |
| `.pre-commit-config.yaml` | [pre-commit](https://pre-commit.com/) | The set of hooks pre-commit runs before each commit |
| `.husky/` | [husky](https://typicode.github.io/husky/) | Git hook scripts managed via Git's `core.hooksPath` |
| `.prettierrc` | [Prettier](https://prettier.io/) | Formatting rules |
| `.prettierignore` | Prettier | Paths Prettier should not format |
| `.markdownlintignore` | [markdownlint-cli](https://github.com/igorshubovych/markdownlint-cli) | Paths excluded from Markdown linting |
| `.editorconfig` | [EditorConfig](https://editorconfig.org/) | Editor-level whitespace/charset defaults (applied by your editor, no install step) |

Open `.pre-commit-config.yaml` and the scripts in `.husky/` for the authoritative, up-to-date list of what actually runs — the configs are the source of truth, and they change more often than this page does.

## One-time setup

### 1. Install the pre-commit hooks

`pre-commit` is a standalone tool; installing this repository's dependencies does not install it for you. Pick whichever channel suits your machine:

```bash
# any one of these
pip install pre-commit
pipx install pre-commit
brew install pre-commit
```

Then, from the repository root, wire it into your local `.git/hooks`:

```bash
pre-commit install
```

From this point on, the hooks declared in `.pre-commit-config.yaml` run automatically against your **staged** files each time you `git commit`.

> The first run downloads and caches each hook's environment, so expect it to be
> noticeably slower than subsequent runs.

### 2. Enable the husky hooks

The `.husky/` directory holds Git hook scripts. Husky works by pointing Git's `core.hooksPath` setting at that directory — until that setting exists in your local clone, the scripts in `.husky/` are inert.

If the project exposes an npm `prepare` script that runs husky, installing the Node dependencies is enough:

```bash
npm install
```

Otherwise you can point Git at the directory yourself:

```bash
git config core.hooksPath .husky
```

Verify which one applies with:

```bash
git config --get core.hooksPath   # should print: .husky
```

> **Verify:** there is no `package.json` at the repository root, so the `npm install`
> route may not apply here (or may need to be run from a subdirectory). Confirm the
> intended bootstrap path with a maintainer and prune whichever option is wrong.

> **Note:** `pre-commit install` and husky both want to own your Git hooks. If both
> are in use, check whether one already invokes the other before enabling both, so
> you don't end up running the same checks twice — or, worse, silently replacing one
> set of hooks with the other.

## Running the checks manually

You do not need to make a commit to exercise the checks. This is the fastest way to reproduce a CI failure locally.

### pre-commit

```bash
# run every hook against every file in the repo
pre-commit run --all-files

# run every hook against only your staged changes
pre-commit run

# run a single hook by its id (ids are listed in .pre-commit-config.yaml)
pre-commit run <hook-id> --all-files
```

To pull newer versions of the pinned hook repositories:

```bash
pre-commit autoupdate
```

### Prettier

`.prettierrc` and `.prettierignore` are picked up automatically when you run Prettier from the repository root. Prettier requires Node.js.

```bash
# report files that are not formatted (non-zero exit if any are found)
npx prettier --check .

# rewrite them in place
npx prettier --write .
```

### markdownlint

`.markdownlintignore` is the ignore file read by `markdownlint-cli`:

```bash
npx markdownlint-cli '**/*.md'
```

> **Verify:** `markdownlint-cli` and `markdownlint-cli2` are different packages with
> different ignore-file conventions. Confirm which one this repository uses (check
> `.pre-commit-config.yaml` and CI workflow files) and delete the other from this
> section.

## Skipping hooks

Sometimes you need to land a commit without running the hooks — a work-in-progress commit on a scratch branch, or an emergency fix. Use this sparingly: whatever the hooks catch locally will usually be caught again in review or CI.

```bash
# skip all Git hooks for a single commit (works for both pre-commit and husky)
git commit --no-verify -m "wip"

# skip specific pre-commit hooks by id
SKIP=<hook-id>,<other-hook-id> git commit -m "..."
```

## Troubleshooting

**`pre-commit: command not found` on commit.** The hook script was installed but the executable is not on your `PATH` — common with `pip install --user`. Reinstall via `pipx` or `brew`, or add the user script directory to your `PATH`.

**Hooks don't run at all.** Confirm the installation actually happened:

```bash
ls .git/hooks/pre-commit          # pre-commit writes a shim here
git config --get core.hooksPath   # husky sets this to .husky
```

Note that if `core.hooksPath` is set, Git ignores `.git/hooks/` entirely — that is the usual reason a `pre-commit install` appears to have no effect.

**A hook fails on files you didn't touch.** Formatters run over whatever they are given; if a hook was recently added, pre-existing files may fail on their first run. Raise it with a maintainer rather than reformatting unrelated files inside a feature branch.

**Hook environments look stale after a config change.** Clear the cached environments and let pre-commit rebuild them:

```bash
pre-commit clean
pre-commit run --all-files
```
