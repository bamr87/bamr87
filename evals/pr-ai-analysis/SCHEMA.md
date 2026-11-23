---
schema: '0.1'
coverage: listed
---

# SCHEMA — pr-ai-analysis

> The eval set for the CI failure analyst of `pr-review.yml` (constitution § 19.11): past failed runs on pull requests, each with the verdict on whether the PR caused it and the phrases a correct root cause names; validated offline, and the composed prompt held to the workflow's byte budget, by `python3 tools/evals.py run pr-ai-analysis --dry-run`.

## Conventions

- Each case is one past failed run on a pull request in this repository; `source` names the run and the pull request.
- `input.runs[].jobs[].log` is the failed step's log as recorded, timestamps stripped and anything token-shaped redacted.

## Structure

| entry | kind | purpose | rules |
| --- | --- | --- | --- |
| `cases.yml` | file | The cases (`schema: evals/v1`, `mode: model`, `min_cases: 10`) and the pinned `model`, which is the shipped analyst's | required |

## Placement

- A new failed run worth holding the analyst to → a case in `cases.yml` with its run and pull request in `source`.
- Anything unrouted → propose an entry in this table first, then create it.

## Forbidden

- No secrets or credential-shaped strings in a log, and no private repository content.
- No case tuned to what a model happened to answer: `expected` comes from what fixed the run.
