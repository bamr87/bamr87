---
schema: '0.1'
coverage: listed
---

# SCHEMA — docs/adr

> Architecture Decision Records for the hub: decisions that are hard to reverse, one numbered file each, with an index (UPS-WORK-04, decision D2).

## Conventions

- `NNNN-short-kebab-title.md`, four-digit sequence, never renumbered; a superseded ADR is never deleted, it links forward.
- Every ADR carries Status, Context, Decision, Consequences, Alternatives considered, Supersedes / Superseded by.

## Structure

| entry | kind | purpose | rules |
| --- | --- | --- | --- |
| `README.md` | file | The ADR index and the format rules | required |
| `0000-template.md` | file | Blank ADR to copy from | required |
| `[0-9][0-9][0-9][0-9]-*.md` | pattern | One decision each, numbered in sequence | |

## Placement

- New decision → copy `0000-template.md` to the next `NNNN-slug.md`, add a row to `README.md`, in the same PR as the change it justifies.
- Anything unrouted → propose an entry in this table first, then create it.

## Forbidden

- No renumbering, no deleting a superseded ADR, no decisions recorded only in a PR comment.
