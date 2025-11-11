# Submodules

This repository uses the following submodules:

- `README`: https://github.com/bamr87/README.git
- `scripts`: https://github.com/bamr87/scripts.git
 - `cv`: https://github.com/bamr87/cv-builder-pro.git

If you clone this repository, fetch the submodules as well:

```
git clone --recurse-submodules <parent-repo-url>
```

Or, if you already cloned the repo:

```
git submodule update --init --recursive
```

Automated updates
-----------------
This repository contains a GitHub Actions workflow (`.github/workflows/update-submodules.yml`) that runs on a schedule and can be triggered manually. It attempts to update the submodules to the latest remote commits and commits the parent repo to bump the submodule pointers if changes were detected.

Local update script
-------------------
You can force an update locally using the included script:

```
./tools/update-submodules.sh

PR-based submodule updates
--------------------------
There's also an automated workflow to open a pull request when submodule pointer(s) change: `.github/workflows/update-submodule.yml`.

Usage:
- Schedule: Runs daily, or you can trigger manually from GitHub Actions using 'workflow_dispatch'.
- Inputs:
	- `submodule` - optional. Path to the submodule to update (e.g., `cv`, `scripts`, `README`). Leave blank to update all.
	- `base_branch` - optional. Base branch to open a PR against (default: `main`).

The workflow updates the designated submodule(s) and opens a PR if pointer changes are detected. This is safer than pushing changes directly since it allows review and CI to run against the updated pointers.
```
