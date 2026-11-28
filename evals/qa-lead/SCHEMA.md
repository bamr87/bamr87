---
schema: '0.1'
coverage: listed
---

# SCHEMA — qa-lead

> The eval set for QA Lead, the § 15 completeness reviewer (`.github/scripts/dash-gen/qa_lead.py`), run offline by `python3 tools/evals.py run qa-lead`.

## Conventions

- Each case is one pull request's recorded facts (files, labels, size, author, body, linked CI runs) and the gate, event and four lines QA Lead must return.

## Structure

| entry | kind | purpose | rules |
| --- | --- | --- | --- |
| `cases.yml` | file | The cases (`schema: evals/v1`, `min_cases: 20`) | required |

## Placement

- A new case → recorded with `qa_lead.py facts --repo OWNER/NAME --pr N`, its `source` naming the pull request.
- Anything unrouted → propose an entry in this table first, then create it.

## Forbidden

- No private repository's pull request: QA Lead skips private repositories, and a case body is public text.
