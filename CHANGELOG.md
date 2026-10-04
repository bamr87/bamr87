# Changelog

This changelog tracks the hub's **versioned public interface**: the reusable workflows member repos call by reference, and the checker they run. The interface, the tag scheme (`vX.Y.Z` plus a floating `vX`) and the meaning of each bump are defined in [`docs/WORKFLOW-VERSIONING.md`](docs/WORKFLOW-VERSIONING.md). Changes to the dash, the site, registries and generated data are not listed here.

The format follows [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html). Keep exactly one `## [Unreleased]` heading.

## [Unreleased]

### Added

- `site-quality.yml`: a reusable site quality scan (Lighthouse CI, axe-core at 390 px and 1366 px, pa11y contrast) with `mode: build` (build the Jekyll site against a fresh theme resolved to a commit SHA, recorded in the job summary and report) and `mode: url` (scan live URLs). New interface, additive: inputs `mode`, `config`, `base-url`, `source`, `build-command`, `theme-cache` (default `false`), `expired-allowlist-level`, `gate`, `artifact-name`, `retention-days`, `hub-ref`, `node-version`, `ruby-version`; outputs `status`, `errors`, `warnings`, `theme-repo`, `theme-sha`, `report-artifact`. Every threshold comes from the caller's config (`templates/site-quality/site-quality.schema.json`, `version: 1`); the defaults only report. Runtime pinned exactly in `.github/site-quality/` with a committed lockfile, kept current by a Dependabot npm entry.
- The `site-quality` kit (`templates/site-quality/`, `tools/fanout.sh --kit site-quality`): a caller pinned `@v1`, a report-only config template, the JSON Schema, pass/fail fixture sites, and draft rows UPS-QA-60..63 (`rollout: warn`, contract `specs/QUALITY.contract.yml`).

## [1.0.0] - 2026-10-03

The first tagged baseline: the interface exactly as it stood on `main` when the tags were introduced, so existing `@main` callers can move to `@v1` with no behaviour change.

### Added

- `standard-ci.yml`: the one-job reusable CI gate, with inputs `node-version`, `python-version` and `ruby-version`, each resolved as caller input, then the calling repo's `vars.*`, then the built-in default.
- `fleet-conformance.yml`: the reusable UPS conformance gate, with inputs `kinds`, `tier`, `gate` (default `false`, advisory), `hub-ref` (default `main`) and `python-version`, and the `ups-conformance` report artifact.
- `tools/conformance.py` 0.1.0 and `_data/specs.yml` (UPS 1.0, status draft): the checker and rows `fleet-conformance.yml` runs.

[Unreleased]: https://github.com/bamr87/bamr87/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/bamr87/bamr87/releases/tag/v1.0.0
