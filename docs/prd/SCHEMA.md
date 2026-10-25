---
schema: '0.1'
coverage: listed
---

# SCHEMA — docs/prd

> Sub-PRDs: detailed product requirements for one feature area. The root `PRD.md` owns every requirement id (`FRn`/`NFRn`); a sub-PRD expands them and is linked from it and from the feature's `docs:` in `features/features.yml`.

## Structure

| entry | kind | purpose | rules |
| --- | --- | --- | --- |
| `[A-Z]*.md` | pattern | One sub-PRD per feature area (`TOPIC.md`), with a Status line (Draft / proposed / accepted) | |

## Placement

- New sub-PRD → `docs/prd/TOPIC.md`; add its requirement ids to the root `PRD.md` and the feature to `features/features.yml` in the same PR.
