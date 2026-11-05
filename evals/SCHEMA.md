---
schema: '0.1'
coverage: listed
---

# SCHEMA — evals

> The agent eval sets (constitution § 13.1): one directory per agent role, each holding real past tasks with their expected output, run by `tools/evals.py` and checked by `.github/workflows/evals.yml`.

## Conventions

- One directory per role, named as `tools/evals.py` `ADAPTERS` names it; the directory holds exactly one `cases.yml` (`schema: evals/v1`).
- Every case has `id`, `source` (the real task it came from), `input`, `expected` and `pass`; a set may add `rubric` for an LLM judge and `min_cases` as a floor the runner enforces.
- A model-backed set names its `model`, which must be an id in `_data/fleet.yml` `ai_models.allowed`.

## Structure

| entry | kind | purpose | rules |
| --- | --- | --- | --- |
| `README.md` | file | What an eval set is, the case format, and how to run and grow one | required |
| `jev-classify/` | dir | JEV's deterministic conflict classifier (`tools/jev/classify.py`), run fully offline | required |
| `t1-intake/` | dir | Issue-pipeline tier 1 intake: ready / blocked and the type label; schema-checked offline, model-run locally | required |

## Placement

- New agent role → `<role>/cases.yml` here, an adapter in `tools/evals.py` `ADAPTERS`, a row in this table, and the role named in `docs/EVALS.md`.
- Anything unrouted → propose an entry in this table first, then create it.

## Forbidden

- No secrets, tokens or private issue text in a case — `input` is a summary of a public issue.
- No case invented to make a set pass: every case names the real task it came from in `source`.
