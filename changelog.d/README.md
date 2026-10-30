# changelog.d/ — pending changelog entries

One file per change worth announcing, written by the pull request that makes the change; folded into the `## [Unreleased]` section of [`../CHANGELOG.md`](../CHANGELOG.md) by `python3 -m tools.jev number apply` when the pull request lands on `main` ([amendment 0002](../docs/amendments/0002-conflict-free-numbering.md)).

Every pull request that touches the changelog touches the same handful of lines at the top of the same file, so the changelog is the single most reliable source of merge conflicts in a repository — and the conflict is always spurious, because two entries never actually disagree. A fragment per entry removes the shared line.

```markdown
<!-- changelog.d/my-change.md -->
### Added

- `thing.yml`: what it is and what a consumer gets. One paragraph per line.
```

Use the [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) headings — `Added`, `Changed`, `Deprecated`, `Removed`, `Fixed`, `Security`. The compiler groups fragments by heading and emits them in that order, so one `### Added` section comes out of five fragments that each wrote one.

This repository's changelog tracks the hub's **versioned public interface** only (`docs/WORKFLOW-VERSIONING.md`); a change to the dash, the site or generated data needs no fragment. In a fleet repo where release-please owns `CHANGELOG.md`, release-please stays in charge and this directory is not used.
