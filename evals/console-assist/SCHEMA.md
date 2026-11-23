---
schema: '0.1'
coverage: listed
---

# SCHEMA — console-assist

> The eval set for the console's assistant (the `assist` operation, `tools/console/core.py`): a question, a recorded page and what must hold, validated offline by `python3 tools/evals.py run console-assist --dry-run` and run against the pinned model only when started by hand (`--canary`, `--all-cases`).

## Conventions

- Each case names its `source` as a list of entries, each `rule:`, `evidence:` or `conversation:`. A `rule:` entry quotes the rule of the shipped prompt the case was written for (`rule: <file> "<quote>"`), and the runner checks the quote is still in that file. An `evidence:` entry names the file that records a real run of the scenario. A `conversation:` entry names a real assistant conversation; the set has none yet.
- A recorded page (`input.page`) is named states, each with the `outline` a snapshot returns in the page's own format (`tools/console/web/src/assist/pageBridge.ts`) and the `rules` that say what a command answers there. A refusal is the page's own sentence, verbatim: the runner holds each one to the page's source.
- `expected` holds deterministic rules only: `calls_all`, `calls_any`, `calls_none`, `commands_all`, `commands_none`, `after_refusal: stop`, `max_page_commands`, `answer_all`, `answer_any`, `answer_none` ([docs/EVALS.md](../../docs/EVALS.md#the-console-assist-role)).
- About five cases carry `canary: true`: the subset a hand-started model run takes first.
- The model is `_data/fleet.yml` `assistant.model` (`model_from: assistant.model`); the set names no model of its own.

## Structure

| entry | kind | purpose | rules |
| --- | --- | --- | --- |
| `cases.yml` | file | The cases (`schema: evals/v1`, `mode: model`, `min_cases: 20`), the block every recorded page shares (`page:`), the page's refusals and the documents the cases reuse | required |

## Placement

- A real assistant conversation worth keeping → a case in `cases.yml` with a `conversation:` source, replacing a rule-written case that covers the same behaviour.
- A regression in real use → a case that reproduces it, in the same change as the fix.
- A new rule in `tools/console/assist.prompt.txt` or `assist.page.txt` → a case with that rule quoted in `source`.
- Anything unrouted → propose an entry in this table first, then create it.

## Forbidden

- No secret, token or credential-shaped string in a question, an outline or a document: a case about a secret field names the field, never a value.
- No refusal text written from memory: take it from the page's code or from a recorded run.
- No rule that needs a judge: a check that cannot be made from the log and the answer's text belongs in a rubric, not in `expected`.
