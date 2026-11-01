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
| `proposed/` | dir | Unnumbered amendment records awaiting a number at merge (amendment 0002); see its SCHEMA | |
| `[0-9][0-9][0-9][0-9]-*.md` | pattern | One amendment record: Status, Date, Proposed by, Ratified by, Affects, Supersedes; never edit a ratified record (its Status and Ratified by lines are recorded by the post-merge ratify job, § 8.3), never reuse a number | |

## Placement

- New amendment → `proposed/<kebab-slug>.md` with `**Number:** NEW`, copied from `0000-template.md`, in the same PR as the constitution edit. `tools/jev/number.py` numbers it into this directory at merge; never hand-number a file here.
