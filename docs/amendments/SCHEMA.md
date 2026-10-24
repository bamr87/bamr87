---
schema: '0.1'
coverage: listed
---

# SCHEMA — docs/amendments

> The hub constitution's amendment log: one numbered record per change to `docs/constitution.md`, ratified by the maintainer merging the PR (UPS-WORK-16, templates/governance/).

## Structure

| entry | kind | purpose | rules |
| --- | --- | --- | --- |
| `README.md` | file | Index of amendments and the process summary | required |
| `0000-template.md` | file | Template to copy for a new amendment | required |
| `[0-9][0-9][0-9][0-9]-*.md` | pattern | One amendment record: Status, Date, Proposed by, Ratified by, Affects, Supersedes; never edit a ratified record, never reuse a number | |

## Placement

- New amendment → next free `NNNN-kebab-slug.md`, copied from `0000-template.md`, in the same PR as the constitution edit.
