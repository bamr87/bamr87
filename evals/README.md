# evals

The hub's agent eval sets (constitution § 13.1–13.2). Each directory is one agent role, and its `cases.yml` holds real past tasks for that role: the input, the expected output, the pass criterion and, optionally, an LLM-judge rubric. `tools/evals.py` runs a set. `.github/workflows/evals.yml` reruns every set on any change to a prompt, a tool or the model list, and any failed case fails that check.

| Role | Kind | Cases | Under test |
| --- | --- | ---: | --- |
| [`jev-classify/`](jev-classify/cases.yml) | deterministic | 31 | `tools/jev/classify.py` `classify()` + `kind_of()`: JEV's conflict tier ladder |
| [`t1-intake/`](t1-intake/cases.yml) | model | 14 | the issue pipeline's tier-1 intake prompt: the ready / blocked exit and the type label |

```bash
python3 tools/evals.py list                          # roles with a set
python3 tools/evals.py run jev-classify              # offline, no model
python3 tools/evals.py run t1-intake --dry-run       # schema only, no model
python3 tools/evals.py run t1-intake                 # asks the set's pinned model, capped by budget.local_usd
python3 tools/evals.py run --all --dry-run --json    # what CI runs, as JSON
```

The case format, how to add a role and how to grow a set are in [docs/EVALS.md](../docs/EVALS.md). Placement rules are in [SCHEMA.md](SCHEMA.md).
