---
description: Adopt the standardized release-please pipeline in a repo (scaffold + PR)
allowed-tools: Bash(tools/adopt-release.sh:*), Bash(gh:*), Bash(git:*)
---

Adopt the standardized release pipeline for: $ARGUMENTS

1. Run `tools/adopt-release.sh $ARGUMENTS --dry-run` first and show the detected
   ecosystem (`ruby`/`node`/`python`/`simple`), version, registry, and the files
   it will add.
2. If it looks right, run `tools/adopt-release.sh $ARGUMENTS` to push the branch
   and open the PR. If the repo already has a `release.yml`, stop and report it
   (the tool refuses to clobber).
3. Report the PR URL and the required secret (e.g. `RUBYGEMS_API_KEY`, `NPM_TOKEN`,
   or none for PyPI/OIDC and `simple`). Then update the project's `release:` block
   in `_data/projects.yml` (set `adopted: true`) via the `update-registry` skill.

Background: the shared logic lives in `bamr87/.github`; this only adds the per-repo
glue. See `docs/RELEASES.md`.
