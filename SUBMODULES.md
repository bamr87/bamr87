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
```
