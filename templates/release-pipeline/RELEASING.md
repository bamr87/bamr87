# Releasing

This repo uses the standardized [bamr87 release pipeline](https://github.com/bamr87/.github#readme).
You don't bump versions or edit the changelog by hand — [release-please](https://github.com/googleapis/release-please) does.

## How a release happens

1. Land changes via PRs with **[Conventional Commit](https://www.conventionalcommits.org/)** titles
   (`fix:` → patch, `feat:` → minor, `feat!:`/`BREAKING CHANGE:` → major).
2. On merge to the default branch, **release-please opens/updates a "release PR"** that bumps the
   version and rewrites `CHANGELOG.md`.
3. **Merge the release PR** when you're ready to ship. That tags `vX.Y.Z`, creates the GitHub Release,
   and `publish.yml` publishes the package (`__REGISTRY__`).

## What's tracked

- Version source: `__VERSION_SOURCE__`
- Manifest: `.release-please-manifest.json` · Config: `release-please-config.json`

## Required setup

- `__SECRET__`
- Optional `RELEASE_PLEASE_TOKEN` PAT so the release PR triggers CI.

To cut a release manually (rare), merge any pending release PR, or push an empty
`chore: release` commit to re-trigger release-please.
