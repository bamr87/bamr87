# AI models — switching a provider without regression

> Which model each kind of AI work runs on, every place that is written, and what a switch would take: how easy it is, and whether it is proven safe.

The decision record is [ADR 0019](adr/0019-ai-providers-switchable-without-regression.md). AI-agnostic means a provider can be switched easily and nothing gets worse when it is. This page covers what is built, phase P0: the classes, the reader that counts every place a model is named, the recorded eval runs, and the switch plan. How agents are authenticated, capped and costed is [AI-INTEGRATION.md](AI-INTEGRATION.md); the eval sets themselves are [EVALS.md](EVALS.md).

## The model in one paragraph

A **class** is a kind of work (`deep`, `standard`, `fast`) bound to one model in `_data/fleet.yml` `ai_models.classes`. That line is meant to be the only place the model is written, so that a switch is one edit. Every other place that names a model is a **binding** the switch must also edit, and `tools/dash ai models` counts them. A switch is **safe** for an agent when the eval set that covers it has a **recorded run** on the target model: the whole set, nothing failed, the set unchanged since. `tools/dash ai switch` puts both together and says whether a switch is ready.

```text
 _data/fleet.yml  ai_models:                    the tree and the fleet's checkouts
   allowed   provider → exact model ids           settings · workflows · actions · tools · kits
   classes   kind of work → one model             fleet repos' workflows · eval pins
   evals     eval set → the agents it covers                     │
            │                                                    │
            │      _data/agents.yml      _data/eval_runs.yml     │
            │      who runs which model  what passed on what     │
            └───────────────┬────────────────┬───────────────────┘
                            ▼                ▼
          tools/fleetcore/aimodels.py   status_doc() · switch_plan()   →   fleet-ai-models/v1
                            │
        tools/dash ai models | bindings | switch
```

## Operate — the short card

```bash
tools/dash ai models                                  # each class, its model, and every place that also names it
tools/dash ai bindings --model <id>                   # those places, with file and line
tools/dash ai bindings --class workflow               # only one kind of place
tools/dash ai switch standard --to <model>            # the plan: what it would edit, and who is proven
tools/dash ai switch --from <model> --to <model>      # the same for every place that names a model
tools/dash ai switch standard --to <model> --strict   # exit 1 when it is not ready
tools/dash ai models --instance ~/another-hub         # another control plane (or FLEET_HOME)

python3 tools/evals.py run <role> --model <id> --record   # SPENDS: runs the set on a model and keeps the result
```

Everything under `tools/dash ai models`, `bindings` and `switch` only reads files already on disk. It calls no model, opens no connection and writes nothing.

## Classes

```yaml
ai_models:
  allowed:
    <provider>: [<exact model id>, …]     # constitution § 13.3: exact versions, never aliases
  classes:
    deep: <id>        # planning, diagnosis and changes across many files
    standard: <id>    # the default: review, triage, content, the assistant
    fast: <id>        # mechanical edits and classification
```

A class is not an alias. It resolves to an exact id from `allowed:`, and changing its line is the same gated change as changing the list (§ 12.3). Its name says what the work needs and never which vendor serves it. Two classes bound to one model are reported, because a place that names that model could belong to either.

## Bindings

Every place a model is named, other than the allowlist and the class lines:

| Class of binding | Where the reader looks | A switch |
| --- | --- | --- |
| `setting` | any other key of `_data/fleet.yml` whose whole value is an allowed model | edits it |
| `workflow`, `action`, `generator`, `step`, `tool`, `kit` | `.github/workflows/`, `.github/actions/`, `.github/scripts/`, `tools/jev/steps/`, `tools/`, `templates/` | edits it |
| `fleet-workflow` | `.github/workflows/` of every owned repo checked out under the instance | edits it, in that repo |
| `pin` | the `model:` an eval set under `evals/` is held to | moves when the set is re-run |
| `table` | a file listed in `ai_models.scan.tables`: one row per model, such as a price | gains a row |

A model is matched as a whole token, a comment line is ignored, and tests, fixtures, archived kit versions and hidden directories are left out: they are not what runs. A repo that is not checked out is named under `NOT read`, never counted as having none.

The count that matters is the first three rows. It is what a switch owes beyond its one line, and the goal is zero.

## Recorded eval runs

`_data/eval_runs.yml` holds one row per model run, oldest first:

```yaml
schema: eval-runs/v1
runs:
  - role: <eval role>
    model: <id>
    provider: <provider>
    date: 'YYYY-MM-DD'
    scope: all                  # or "5 of 24 cases" when the run took a sample
    passed: 24
    failed: 0
    set: sha256:…               # the cases file that ran
    cost_usd: 1.2345
    cost_label: API-equivalent (estimate)
```

The eval runner is its only writer: `python3 tools/evals.py run <role> --model <id> --record`. Never edit a row by hand. A dry run, a deterministic role and a run that stopped on an error leave no row, and `--record` refuses `--dry-run` and `--cases`.

The latest row for a role and a model decides how the set stands on that model:

| State | Means |
| --- | --- |
| `proven` | the whole set ran, nothing failed, and the set in the tree is the one that ran |
| `partial` | the run took a sample of the set |
| `stale` | the set changed after the run |
| `failed` | a case failed |
| `unproven` | no run on this model is recorded |

An **agent** is proven only when every model-backed set that covers it is proven. `ai_models.evals` says which agents a set covers, and `covers:` says when it tests only part of one: such an agent reads `partial`, never proven. An agent no set covers reads `no-evals`.

## The switch plan

`tools/dash ai switch <class> --to <model>` prints three lines and a verdict:

- **TARGET** — whether the model is in `ai_models.allowed`, and whether its provider differs from the current one.
- **EASY** — the class line, plus the settings and literals that would have to be edited by hand.
- **SAFE** — every agent that runs on the current model, by state on the target.

It says `READY` only when the target is allowed, nothing but the class line names the current model, and every agent the switch moves is proven. Otherwise it lists why. A change of provider is always a reason until the runner that reaches the new provider has passed the conformance suite (ADR 0019, P2). The plan is advice: it exits 0 unless `--strict`.

A pull request that changes a class line should carry the plan's output and the rows it relies on.

## What the reader does not see

- **A prompt that changed.** A run goes stale when its set changes. A changed prompt with the same set still reads `proven` until ADR 0019's P4 puts the prompt in the hash.
- **A model that is not in the allowlist.** It finds the ids `ai_models.allowed` lists. A workflow that passes `--model` with any other id is reported as `unlisted-model`, a note: an agent's model belongs in the list, a product's own model does not.
- **More than the workflows of a fleet repo.** In another repo it reads `.github/workflows/` only; that repo's own tools are its own to count.
- **How an agent is started.** Which program reaches a provider, and whether it caps, sandboxes and records as today's does, is the runner seam of P2.

## The document

`status_doc()` returns `fleet-ai-models/v1`. Adding a field is free; renaming one changes the marker.

| Key | Holds |
| --- | --- |
| `providers` | each provider in the allowlist, its models, and how many bindings name them |
| `classes` | each class: its model and provider, its settings, hub literals, fleet literals and eval pins, the agents on it, and how many are proven or have no evals |
| `bindings` | every place: `class`, `repo`, `file`, `line` or `key`, `model`, `provider` |
| `evals` | each eval set: mode, pin, hash, case count, the agents it covers, and its state on every allowed model |
| `agents` | how many agents the inventory holds, how many run a model, how many an eval set covers, and the count per model |
| `findings` | `unlisted-model`, `classless-model` (a model named somewhere that no class is bound to), `shared-model`, `uncovered-set` (an eval set mapped to no agent) |
| `read` | the checkouts read, the repos that were not, and why |
| `summary` | totals: the edits every switch together would owe, by kind, and the recorded runs |

## Files

| File | Role |
| --- | --- |
| `_data/fleet.yml` `ai_models:` | The allowlist, the classes, which agents each eval set covers, and the files that are tables |
| `_data/eval_runs.yml` | The recorded model runs; written only by `tools/evals.py --record` |
| `tools/fleetcore/aimodels.py` | The reader, `status_doc()` and `switch_plan()`; `python3 -m fleetcore.aimodels` is `tools/dash ai models`, `bindings` and `switch` |
| `tools/evals.py` | The eval runner, and the writer of a recorded run |
| `tools/test_fleetcore_aimodels.py` | Fixture tests with made-up providers and models, the committed settings, the recorded row, and the rule that the reader names no provider and no model |
| [ADR 0019](adr/0019-ai-providers-switchable-without-regression.md) | The decision, the prior art and the phases |
