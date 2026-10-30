# Releasing

This repo uses the standardized [bamr87 release pipeline](https://github.com/bamr87/.github#readme). You don't bump versions or edit the changelog by hand — [release-please](https://github.com/googleapis/release-please) does.

## How a release happens

1. Land changes via PRs with **[Conventional Commit](https://www.conventionalcommits.org/)** titles (`fix:` → patch, `feat:` → minor, `feat!:`/`BREAKING CHANGE:` → major).
2. On merge to the default branch, **release-please opens/updates a "release PR"** that bumps the version and rewrites `CHANGELOG.md`.
3. **Merge the release PR** when you're ready to ship. That tags `vX.Y.Z`, creates the GitHub Release, and `publish.yml` publishes the package (`__REGISTRY__`).

## What's tracked

- Version source: `__VERSION_SOURCE__`
- Manifest: `.release-please-manifest.json` · Config: `release-please-config.json`

## Required setup

- `__SECRET__`
- `RELEASE_PLEASE_TOKEN` PAT (`contents` + `pull requests` write) so the release PR triggers CI. **Mandatory** unless Settings > Actions > General > Workflow permissions has "Allow GitHub Actions to create and approve pull requests" on: without either, GitHub refuses to open the release PR and no release is ever cut ([bamr87/bamr87#406](https://github.com/bamr87/bamr87/issues/406)).

To cut a release manually (rare), merge any pending release PR, or push an empty `chore: release` commit to re-trigger release-please.
