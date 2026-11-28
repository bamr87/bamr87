# evals

The hub's agent eval sets (constitution § 13.1–13.2). Each directory is one agent role, and its `cases.yml` holds the role's tasks: the input, the expected output, the pass criterion and, optionally, an LLM-judge rubric. A task is a real past one wherever the role has a past; a set that had to be written before its role had any says so, case by case ([SCHEMA.md](SCHEMA.md)). `tools/evals.py` runs a set. `tools/test_evals.py` validates every set offline and is run by the `python-tests` workflow on every pull request, every push to `main` and every night, so a change to a prompt, a tool or the model list that breaks a set fails that check. No workflow runs a set against a model: a model run is local and started by hand.

| Role | Kind | Cases | Under test |
| --- | --- | ---: | --- |
| [`console-assist/`](console-assist/cases.yml) | model | 24 | the console's assistant (the `assist` op): its shipped prompt, tool allowlist and the real MCP layer, against a recorded page |
| [`jev-classify/`](jev-classify/cases.yml) | deterministic | 31 | `tools/jev/classify.py` `classify()` + `kind_of()`: JEV's conflict tier ladder |
| [`pr-ai-analysis/`](pr-ai-analysis/cases.yml) | model | 20 | the CI failure analyst of `pr-review.yml` (§ 19.11): its shipped prompt and parser, against past failed PR runs |
| [`qa-lead/`](qa-lead/cases.yml) | deterministic | 28 | QA Lead, the § 15 completeness reviewer (`.github/scripts/dash-gen/qa_lead.py` `decide()`): the gate, the four lines and the event, against real past pull requests |
| [`t1-intake/`](t1-intake/cases.yml) | model | 14 | the issue pipeline's tier-1 intake prompt: the ready / blocked exit and the type label |

```bash
python3 tools/evals.py list                              # roles with a set
python3 tools/evals.py run jev-classify                  # offline, no model
python3 tools/evals.py run qa-lead                       # offline, no model
python3 tools/evals.py run t1-intake --dry-run           # schema only, no model
python3 tools/evals.py run console-assist --dry-run      # recordings, sources and rules, no model
python3 tools/evals.py run --all --dry-run --json        # every set offline, as JSON
python3 tools/evals.py run t1-intake                     # SPENDS: asks the set's pinned model, capped by budget.local_usd
python3 tools/evals.py run console-assist --canary       # SPENDS: five capped sessions on assistant.model
```

The case format, how to add a role and how to grow a set are in [docs/EVALS.md](../docs/EVALS.md). Placement rules are in [SCHEMA.md](SCHEMA.md).
