---
schema: "0.1"
coverage: listed
---

# SCHEMA — changelog.d

> Pending changelog entries: one Keep a Changelog fragment per file, folded into `CHANGELOG.md`'s `## [Unreleased]` section on `main` by `tools/jev/number.py` (amendment 0002). The directory exists so two pull requests never edit the same changelog line.

## Conventions

- A fragment is a `### <Heading>` line followed by one or more `- ` bullets; headings come from Keep a Changelog 1.1.0 (`Added`, `Changed`, `Deprecated`, `Removed`, `Fixed`, `Security`).
- One paragraph per line, like every other Markdown file here.

## Structure

| entry | kind | purpose | rules |
| --- | --- | --- | --- |
| `README.md` | file | The fragment format and what belongs in this repo's changelog | required |
| `*.md` | pattern | One pending changelog entry, named `<kebab-slug>.md`; consumed (deleted) when compiled | |

## Placement

- New public-interface change → `<kebab-slug>.md` here, never a new bullet in `../CHANGELOG.md`.

## Forbidden

- No version headings (`## [1.2.3]`) — a release cuts those, a fragment never does.
- Nothing here for a change outside the hub's versioned public interface (docs/WORKFLOW-VERSIONING.md).
