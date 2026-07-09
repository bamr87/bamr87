# Submodules

This repository is a **dash** (control plane) whose projects live as ~40 Git
submodules under [`projects/`](projects/). Each submodule is a separate
repository with its own stack, branch, and release cycle.

## Where the list lives (do not hardcode it here)

The authoritative list is the registry, cross-checked against `.gitmodules`:

- **[`_data/projects.yml`](_data/projects.yml)** — the single source of truth
  (name, `submodule_path`, `branch`, stack, category, status, standards tier).
- **[`.gitmodules`](.gitmodules)** — the Git-level definitions.

`tools/check-drift.sh` fails CI if these two disagree, so this document
intentionally does **not** repeat the list — read the registry or run:

```bash
git submodule status              # checked-out SHAs + branches
tools/dash status                 # registry + drift summary
./tools/update-submodules.sh --status   # declared vs. checked-out branch
```

### Branch conventions

Most submodules track `main`. Exceptions: `scripts`, `edgar-data-parse`, and
`jekyll` track `master`; `sonic-pi` tracks `dev`; `skills` is an external
`microsoft/skills` mirror (`update = merge`). Always read the branch from
`.gitmodules` — never assume `main`.

## Cloning and updating

```bash
git clone --recurse-submodules https://github.com/bamr87/bamr87.git
# already cloned:
git submodule update --init --recursive
```

## Working inside a submodule

A change inside a submodule is committed **in its own repo first**, then the
pointer is recorded in root (see [`CLAUDE.md`](CLAUDE.md) for the full flow):

```bash
cd projects/<name>
git checkout <branch>                 # submodules often land in detached HEAD
# ...edit...
git add . && git commit -m "feat: ..."
git push origin <branch>              # pushes to bamr87/<name>, NOT this repo
cd ../..
git add projects/<name> && git commit -m "chore: bump <name> submodule"
```

Don't bundle changes across multiple submodules into one PR.

## Automated pointer updates

`.github/workflows/update-submodules.yml` runs weekly (or on demand) and opens a
reviewable PR bumping submodule pointers **up** into root. It never pushes
directly and never modifies submodule contents — content changes belong to the
submodule's own repo. The complementary **downward** flow
(`.github/workflows/standardize-fanout.yml`) opens standardization PRs *into*
submodules; see [`docs/STANDARDS.md`](docs/STANDARDS.md).

Local refresh (safe by default — skips submodules with uncommitted/diverged work):

```bash
./tools/update-submodules.sh            # refresh all onto declared branch
./tools/update-submodules.sh <name>     # refresh one
```

## Adding or onboarding a project

```bash
git submodule add <url> projects/<name>
# add a matching entry to _data/projects.yml (or use /register-project)
tools/dash-gen readme        # refresh the profile README list
tools/check-drift.sh         # verify .gitmodules <-> registry parity
tools/dash audit <name>      # check it against the standardization baseline
```

If a project directory already exists on disk but is in neither `.gitmodules`
nor the registry, the drift gate now flags it; use the `/onboard-dir` skill to
adopt it (or remove it).
