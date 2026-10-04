# Changelog

This changelog tracks the hub's **versioned public interface**: the reusable workflows member repos call by reference, and the checker they run. The interface, the tag scheme (`vX.Y.Z` plus a floating `vX`) and the meaning of each bump are defined in [`docs/WORKFLOW-VERSIONING.md`](docs/WORKFLOW-VERSIONING.md). Changes to the dash, the site, registries and generated data are not listed here.

The format follows [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html). Keep exactly one `## [Unreleased]` heading.

## [Unreleased]

## [1.0.0] - 2026-10-03

The first tagged baseline: the interface exactly as it stood on `main` when the tags were introduced, so existing `@main` callers can move to `@v1` with no behaviour change.

### Added

- `standard-ci.yml`: the one-job reusable CI gate, with inputs `node-version`, `python-version` and `ruby-version`, each resolved as caller input, then the calling repo's `vars.*`, then the built-in default.
- `fleet-conformance.yml`: the reusable UPS conformance gate, with inputs `kinds`, `tier`, `gate` (default `false`, advisory), `hub-ref` (default `main`) and `python-version`, and the `ups-conformance` report artifact.
- `tools/conformance.py` 0.1.0 and `_data/specs.yml` (UPS 1.0, status draft): the checker and rows `fleet-conformance.yml` runs.

[Unreleased]: https://github.com/bamr87/bamr87/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/bamr87/bamr87/releases/tag/v1.0.0
