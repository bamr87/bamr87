# Evals

> The agent eval sets, the runner and the eval-regression check (constitution § 13.1–13.2): what each role is held to, how to run it, and how to grow a set.

Constitution § 13 says every agent role keeps an eval set of about 20 real past tasks. The set reruns on every prompt, tool or model change, and a regression fails a CI check. A step may move to a cheaper model only if its evals still pass on it. This page covers the hub's machinery for that: the sets in [`evals/`](../evals/README.md), the runner [`tools/evals.py`](../tools/evals.py), and the check [`.github/workflows/evals.yml`](../.github/workflows/evals.yml).

## Roles covered

| Role | Kind | What it checks |
| --- | --- | --- |
| `jev-classify` | deterministic | JEV's conflict classifier ([JEV.md](JEV.md)): the tier (0–3) and file kinds for a given conflict shape. The adapter imports `tools/jev/classify.py` directly, with no network and no `claude`. |
| `t1-intake` | model | Issue-pipeline tier 1 ([ISSUE-PIPELINE.md](ISSUE-PIPELINE.md#tier-1--intake)): given an issue and its gaps, the ready / blocked exit and the type label. `--dry-run` validates the set offline. A model run asks the set's pinned `model`. |

Still to come, in later issues: issue-pipeline T2/T3, repo-scout, the fleet-pulse doctor, JEV's model tiers and deep-dive.

## Reproduce

```console
$ python3 tools/evals.py run jev-classify
jev-classify (deterministic): 31 passed, 0 failed
$ python3 tools/evals.py run t1-intake --dry-run
t1-intake (model, dry run): 14 passed, 0 failed
$ python3 tools/evals.py run --all --dry-run
jev-classify (deterministic): 31 passed, 0 failed
t1-intake (model, dry run): 14 passed, 0 failed
$ python3 tools/test_evals.py
...............
Ran 15 tests in 1.6s

OK
```

`--json` prints one object per role (an array with `--all`):

```json
{
  "role": "jev-classify",
  "mode": "deterministic",
  "dry_run": false,
  "model": null,
  "cost_usd": 0.0,
  "passed": 31,
  "failed": 0,
  "errors": [],
  "cases": [
    {
      "id": "empty-trial-merge",
      "passed": true,
      "expected": {"tier": "tier0", "reason_contains": "no conflicted files"},
      "actual": {"tier": "tier0", "kinds": {}, "reason": "no conflicted files in the trial merge"},
      "detail": ""
    }
  ]
}
```

A failing case prints `FAIL <id>: <detail>`, for example `FAIL console-lockfile: tier3 != expected tier0`, and the run exits 1. `tools/test_evals.py` `test_wrong_expectation_fails_the_run` injects exactly that wrong expectation and asserts the non-zero exit. The CI job runs this self-test before the sets, so it proves on every run that the check can fail.

Exit codes: `0` means every case passed (or validated, under `--dry-run`); `1` means a case failed or the set is malformed (bad schema, duplicate id, fewer than `min_cases`, unknown role, unpinned model); `2` is a usage error.

## The case format

`evals/<role>/cases.yml`, `schema: evals/v1`:

```yaml
schema: evals/v1
role: jev-classify          # must match the directory and an adapter in tools/evals.py
mode: deterministic         # or: model
target: tools/jev/classify.py
model: claude-sonnet-5-5    # model sets only; must be in _data/fleet.yml ai_models.allowed
min_cases: 20               # the runner fails the set below this
rubric: …                   # optional LLM-judge rubric
cases:
  - id: console-lockfile    # unique within the set
    source: …               # the real past task this came from (an issue, a PR, a conflict shape)
    input: {…}              # what the role is given
    expected: {…}           # what it must produce
    pass: …                 # the criterion, in words; the adapter enforces it
```

`jev-classify` input is `files[]` (`path`, `hunks`, `lines`, and optionally `kind` or `binary`), optional `globs` (`generated`, `fragments`, `union`, `append`), and any `classify()` option (`attempts`, `id_collision`, `squash_only`, `budget_exhausted`, `force_min_tier`, the envelopes). Its `expected` is `tier`, plus optional `kinds` (path to kind) and `reason_contains`.

`t1-intake` input is `repo`, `title`, `summary` and `gaps[]` (`gap`, `by: agent|human`). Its `expected` is `exit` (`ready` or `blocked`) and `type` (from `_data/fleet.yml` `issue_pipeline.labels.types`).

## Model runs and spend

A model-backed run (`python3 tools/evals.py run t1-intake`) is local and manual. It:

- uses the set's `model`, or `--model`, and refuses any id that is not in `_data/fleet.yml` `ai_models.allowed` before calling anything (§ 13.3);
- caps the whole run at `budget.local_usd`, passing what is left of the cap to every `claude -p` call as `--max-budget-usd`, and stops once it is spent;
- reports `cost_usd`, which is API-equivalent (estimate) under OAuth ([AI-INTEGRATION.md](AI-INTEGRATION.md#spend-guardrails)).

The CI check calls no model, so it needs no AI credential, no `claude-cost` step and no `budget.call_sites` entry. If CI ever runs a model-backed set, that job becomes an AI call site and the rules in [AI-INTEGRATION.md](AI-INTEGRATION.md) apply: a `call_sites` entry, `continue-on-error`, and `claude-cost` with `usage-limit: skip` (all checked by `test_ai_budget.py`).

## The check

`.github/workflows/evals.yml` runs on pull requests and pushes to `main` that touch `evals/**`, `tools/evals.py`, `tools/jev/**`, the issue-pipeline workflow, `.github/prompts/**` or `_data/fleet.yml`, and on dispatch. It runs `tools/test_evals.py`, then `python3 tools/evals.py run --all --dry-run`, and writes the summary to the job page.

- **Kill switch (§ 17):** `vars.EVALS_ENABLED`. The check is on unless the variable is set to `false`, and a dispatch bypasses it. When the central `switches:` map lands (bamr87/bamr87#526), the variable becomes a projection of it.
- **Required check:** the maintainer decides whether to make it required in branch protection (§ 12.4). Nothing here makes it required.

## Adding a role or growing a set

1. Write `evals/<role>/cases.yml` and add a row to [`evals/SCHEMA.md`](../evals/SCHEMA.md) and [`evals/README.md`](../evals/README.md).
2. Add an adapter to `ADAPTERS` in `tools/evals.py`. A deterministic adapter imports the code under test. A model adapter validates offline under `--dry-run` and reads its model and cap from `_data/fleet.yml`.
3. Add the role's prompt or tool paths to `evals.yml` `paths:` so a change to them reruns the set.
4. Grow toward about 20 cases from real history: a JEV row in `_data/jev_resolutions.yml`, or an intake decision that stood after review. Name the source in `source:`. When a role regresses, its fix lands with a case that reproduces the regression.
