---
schema: '0.1'
coverage: listed
---

# SCHEMA — t1-intake

> The seed eval set for issue-pipeline tier 1 (intake): the ready / blocked exit and type label for past issues, schema-checked offline by `python3 tools/evals.py run t1-intake --dry-run`.

## Conventions

- Each case is one past intake decision that stood after review; `source` is the issue reference.

## Structure

| entry | kind | purpose | rules |
| --- | --- | --- | --- |
| `cases.yml` | file | The cases (`schema: evals/v1`, `mode: model`, `min_cases: 10`) and the pinned `model` | required |

## Placement

- A new intake decision → a case in `cases.yml` with its issue in `source`.
- Anything unrouted → propose an entry in this table first, then create it.

## Forbidden

- No private repository content, secrets or credential-shaped strings in a summary.
