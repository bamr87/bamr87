---
schema: '0.1'
coverage: listed
---

# SCHEMA — jev-classify

> The eval set for JEV's deterministic conflict classifier (`tools/jev/classify.py`), run offline by `python3 tools/evals.py run jev-classify`.

## Conventions

- Each case is one conflict shape: real hub paths, the hunks and lines of each, and the tier and kinds the ladder must return.

## Structure

| entry | kind | purpose | rules |
| --- | --- | --- | --- |
| `cases.yml` | file | The cases (`schema: evals/v1`, `min_cases: 20`) | required |

## Placement

- A new conflict shape → a case in `cases.yml`, its `source` naming the PR or ledger row it came from.
- Anything unrouted → propose an entry in this table first, then create it.

## Forbidden

- No conflict contents or diffs — only paths, counts and kinds.
