---
schema: '0.1'
coverage: listed
---

# SCHEMA — evals

> The agent eval sets (constitution § 13.1): one directory per agent role, each holding the role's tasks with their expected output, run by `tools/evals.py` and checked offline by `tools/test_evals.py` in the `python-tests` workflow.

## Conventions

- One directory per role, named as `tools/evals.py` `ADAPTERS` names it; the directory holds exactly one `cases.yml` (`schema: evals/v1`).
- Every case has `id`, `source`, `input`, `expected` and `pass`; a set may add `rubric` for an LLM judge and `min_cases` as a floor the runner enforces.
- `source` is the real task a case came from: an issue, a pull request, a ledger row, a conversation. A role with no history yet may hold a case written for one stated rule of its prompt instead, on three conditions: `source` says so and quotes the rule, the set's header says that its cases were written this way and are to be replaced (the runner reports how many there are), and a real task replaces the case once one exists. `console-assist` is the first such role: it was written when its model had answered two messages, neither on a page that was recorded.
- A model-backed set names its `model`, an id in `_data/fleet.yml` `ai_models.allowed`, or, where the role's own configuration pins one, `model_from` naming that key.

## Structure

| entry | kind | purpose | rules |
| --- | --- | --- | --- |
| `README.md` | file | What an eval set is, the case format, and how to run and grow one | required |
| `console-assist/` | dir | The console's assistant (`assist` op): a question, a recorded page and deterministic rules; validated offline, model-run by hand on a canary subset | required |
| `jev-classify/` | dir | JEV's deterministic conflict classifier (`tools/jev/classify.py`), run fully offline | required |
| `pr-ai-analysis/` | dir | The CI failure analyst of `pr-review.yml` (§ 19.11): past failed PR runs, the caused-by-PR verdict and the root cause; schema-checked offline, model-run locally | required |
| `qa-lead/` | dir | QA Lead, the § 15 completeness reviewer (`.github/scripts/dash-gen/qa_lead.py`): real past pull requests and the gate, event and lines each must get; run fully offline | required |
| `t1-intake/` | dir | Issue-pipeline tier 1 intake: ready / blocked and the type label; schema-checked offline, model-run locally | required |

## Placement

- New agent role → `<role>/cases.yml` here, an adapter in `tools/evals.py` `ADAPTERS`, a row in this table, and the role named in `docs/EVALS.md`.
- Anything unrouted → propose an entry in this table first, then create it.

## Forbidden

- No secrets, tokens or private issue text in a case — `input` is a summary of a public issue.
- No case invented to make a set pass. A case written for a rule is held to the convention above: it names the rule it tests, and it is never tuned to what a model happened to answer.
