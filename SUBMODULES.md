# Submodules

This repository uses the following submodules:

- `README`: https://github.com/bamr87/README.git
- `scripts`: https://github.com/bamr87/scripts.git
- `cv`: https://github.com/bamr87/cv-builder-pro.git
- `skills`: https://github.com/microsoft/skills.git (tracks `main` branch)

If you clone this repository, fetch the submodules as well:

```bash
git clone --recurse-submodules <parent-repo-url>
```

Or, if you already cloned the repo:

```bash
git submodule update --init --recursive
```

Automated updates
-----------------
This repository contains one GitHub Actions workflow for submodule pointer updates:

- `.github/workflows/update-submodules.yml` runs weekly or on demand and opens a reviewable pull request for a selected submodule or all submodules.

The workflow updates submodule pointers in the parent repository only. Changes inside a submodule should be committed to the submodule repository before updating the parent pointer.

Local update script
-------------------
You can force an update locally using the included script:

```bash
./tools/update-submodules.sh
```

PR-based submodule updates
--------------------------
The PR workflow is `.github/workflows/update-submodules.yml`.

Usage:
- Schedule: Runs weekly, or you can trigger manually from GitHub Actions using `workflow_dispatch`.
- Inputs:
  - `submodule` - optional. Path to the submodule to update (e.g., `cv`, `scripts`, `README`). Leave blank to update all.
  - `base_branch` - optional. Base branch to open a PR against (default: `main`).

The workflow updates the designated submodule(s) and opens a PR if pointer changes are detected. This is safer than pushing changes directly since it allows review and CI to run against the updated pointers.
