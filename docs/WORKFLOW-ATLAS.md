# The workflow atlas

> The hub's own GitHub Actions read as one model: what each workflow and composite action does, the standards they are held to, why their runs fail, what can be retired, and a designer that writes a new workflow already inside the standards.

The 2026-10-27 overhaul ([#422](https://github.com/bamr87/bamr87/pull/422), [WORKFLOW-OPTIMIZATION.md](WORKFLOW-OPTIMIZATION.md)) kept finding the same three problems. First, facts about the workflows were copied by hand into five places, and the copies drifted: the console's dispatch allowlist refused every input of four workflows, and the workflows README had lost nine files. Second, the standards existed only as prose in [`.github/workflows/README.md`](../.github/workflows/README.md#standards) and AGENTS.md, so two defects sat on `main` undetected (a cron gate that could never be true, and agent loops that turned a spent Claude window into a red run). Third, most red runs were not defects, but nothing told a spent usage window or a repo setting apart from a bug. The atlas is the one reading of `.github/` that the console, the CLI and the `fleet` MCP server share, so none of them keeps its own copy.

| | |
| --- | --- |
| **Page** | Harness Console → Harnesses → **Workflows** (`/workflows`, `/workflows/<id>`, `/workflows/actions/<id>`); read-only on the [public site](CONSOLE-PAGES.md), which has no run health and no designer |
| **Module** | [`.github/scripts/dash-gen/workflow_atlas.py`](../.github/scripts/dash-gen/workflow_atlas.py) |
| **CLI** | `tools/dash workflows [list \| show <id> \| lint \| health \| new]` |
| **MCP** | `fleet_workflows` (the catalog, one workflow, or run health) and `workflow_lint` (check a draft) |
| **API** | `GET /api/workflows` · `GET /api/workflows/health?days=N` · `POST /api/workflows/lint` · `POST /api/workflows/scaffold` · operations `workflows-lint`, `workflow-new` |
| **Tests** | `python3 .github/scripts/dash-gen/test_workflow_atlas.py` (holds the live tree to zero errors) · `python3 tools/console/test_console.py` · `python3 tools/test_fleetcore_mcp.py` |

## The model

`scan()` parses every `.github/workflows/*.yml` and `.github/actions/**/action.yml`, offline. For each workflow it records:

- the triggers, their paths, branches and types, and each cron with its human form, its fires per day, and its `_data/fleet.yml` `schedule:` key;
- its dispatch inputs and call inputs, with type, default and options;
- its top-level and per-job permissions, its concurrency group, and each job's timeout, needs, condition and runner;
- every action and reusable workflow it uses, whether local, from the `.fleet-hub` checkout, remote `bamr87/bamr87/...@vN` or external;
- the secrets and variables it reads, and its `vars.*_ENABLED` kill switch;
- each Claude call site, with its model, turns, dollar cap, the cap `budget.call_sites` declares, `continue-on-error` and the paired `claude-cost` step's `usage-limit` mode;
- the paths it publishes through `utilities/publish-data`.

Each composite action carries its inputs, outputs and callers. The README's tables give each workflow its group and purpose, and its `## Retired` table becomes the graveyard.

The console adds two joins only it knows: which loop a workflow is, and whether it is on the dispatch allowlist. That allowlist, `DISPATCH_WORKFLOWS` in [`tools/console/core.py`](../tools/console/core.py), is a list of names, a deliberate choice. Each workflow's inputs and their types are read from its file as the default branch holds it, because that is the file `gh workflow run` runs (the working tree is the fallback when git cannot say). The dispatch form and its validation follow that file: a boolean is a checkbox, a choice is a select, and a value outside the options is refused.

Workflows are read as YAML 1.2, as GitHub reads them: only `true`/`false` are booleans, so a choice option `yes` stays `"yes"`. A document that expands past 50,000 nodes through YAML aliases is refused before anything walks it. A file that cannot be read is a `parse-error` finding, never a crash.

## The rules

Each rule names the incident behind it. Where another gate already enforces a rule, the rule says so, and that gate stays the authority. Every other rule is enforced at error level by `test_workflow_atlas.py`, which fails if the live tree carries an error.

| Rule | Severity | Checks | Gate |
| --- | --- | --- | --- |
| `parse-error` | error | the file parses | actionlint |
| `permissions` | warn | a top-level `permissions:` block, or one on every job (a called workflow is exempt: it inherits) | atlas |
| `timeout` | warn | every job with steps sets `timeout-minutes` | atlas |
| `concurrency` | warn | a workflow that writes on a schedule or dispatch has a `concurrency:` group, on the workflow or on every writing job | atlas |
| `sha-pin` | error | actions ride major tags | check-drift (j) |
| `cron-declared` | error | each cron is `schedule.<stem_with_underscores>` in fleet.yml (one override: `token-rotation` → `rotate_tokens`) | `test_schedule.py` |
| `cron-on-hour` | error | no hub cron fires at minute 0 | `test_schedule.py` |
| `kill-switch` | error | a scheduled Claude loop reads a `vars.*_ENABLED` switch | atlas |
| `ai-budget` | error | each Claude site passes `--max-budget-usd` equal to its `budget.call_sites` entry (a cap taken from an input with no default is left to the gate) | `test_ai_budget.py` |
| `usage-limit` | error | a scheduled site pairs `continue-on-error: true` with `usage-limit: skip` (a `continue-on-error` decided by an expression is not checked) | `test_ai_budget.py` |
| `null-input` | error | for a dispatch input that defaults to `true`, no `inputs.x == false`, `!= false` or `!inputs.x` in a workflow with other triggers, unless the expression guards on `github.event_name` against `workflow_dispatch` or `schedule`: on a cron run the input is null, which reads as false, so the cron and a default dispatch disagree | atlas |
| `workflow-run` | warn | no `workflow_run` trigger (prefer `needs:`) | atlas |
| `pr-token` | warn | `gh pr create` (through `GH_TOKEN` or `GITHUB_TOKEN`) or `peter-evans/create-pull-request` does not run with the job token alone (its CI would never fire; a probed token with the job token as fallback passes) | atlas |
| `bare-push` | warn | no `git push` whose refspec names `main` or `master`, and none that names no branch or only `HEAD` (on a run that checked out the default branch, both land on it); called workflows are exempt | atlas |
| `undocumented` | warn | every workflow and action has a README row, and every README row has a file | atlas |
| `action-description-expr` | error | no `${{` in an action's description, or in any input's or output's | check-drift (l) |
| `action-unused` | warn | every composite action has a caller | atlas |

Run against `main` before #422, the rules report what that pass found by hand: `null-input` on `schema-vendor.yml`, `usage-limit` on all five scheduled agent sites, `pr-token` on the retired `unified-evolution.yml`, and nine workflows missing from the README.

**Known limits.** `kill-switch` checks that a scheduled Claude loop reads a `vars.*_ENABLED` variable somewhere, not that the variable gates every agent job. A scheduled workflow that reaches Claude only through a called workflow (a job with `uses: …/ai-lane.yml`) is not followed into it, so neither `kill-switch` nor `ai-budget` sees that call. The lane carries its own switch and cap inputs. `test_schedule.py` and `test_ai_budget.py` remain the authority for what they cover.

## Run health

`lake_health()` reads the hub's runs from the [local lake](HARNESS-OPS.md) (`tools/dash lake sync`), and `classify_failure()` sorts each failed run into a cause and a class. It reads three pools in order:

1. the run's error annotations;
2. the error-looking lines at the end of each job's log, each job read on its own so a later job cannot push the failing one out;
3. the warning annotations, last, so a cache warning or another job's usage-limit skip never explains a failure.

The echo GitHub prints before each step (the script, its `with:` and `env:`) is skipped, so a step or prompt that only mentions "usage limit hit" does not count as a run that hit it, and a line about a retry is a symptom, not the cause. Causes are tried in a fixed order: a 429 run that also reports `is_error:true` is capacity, not an agent error, and a push a ruleset rejected says "failed" but is config, not a test. A 429 counts as capacity only when the line names Claude. When nothing matches, the evidence is the first specific error line, never "Process completed with exit code 1." if anything better exists.

The patterns were checked against every failed run in the lake (87 across 23 repos), not only the hub's.

| Class | Causes | What it means |
| --- | --- | --- |
| **capacity** | `usage-limit`, `budget-cap`, `turn-limit` | A shared limit was spent. It clears by itself; scheduled sites should be in skip mode |
| **config** | `actions-permission`, `push-rejected`, `auth`, `missing-ref`, `startup` | A setting or a credential, not the code |
| **transient** | `api-rate-limit`, `infra`, `timeout` | Re-run it; if it repeats, it is not transient |
| **dependency** | `dependabot`, `deps-install` | Upstream: override, pin a range, or wait |
| **defect** | `agent-error`, `code`, `test`, `gate`, `exit-code` | The workflow or the code it checks is wrong |

Each workflow also shows:

- **429s absorbed**: green runs whose annotations record a usage-limit skip, so capacity stays visible after skip mode turns those runs green;
- **ghosts**: runs whose workflow file is gone (GitHub keeps listing a workflow while it has runs);
- **skipping**: a workflow whose every run was skipped, which is normal for a mention handler and a dead loop for a schedule.

## Retire

The Retire tab gathers four kinds of candidate: ghost workflows, scheduled workflows with no run in the window or only skipped runs, actions with no caller, and README rows for files that no longer exist. Below them is the README's retirement record. Nothing is deleted from the page: deleting runs and files stays a human decision.

## Design

`scaffold(kind, id)` writes a workflow that passes every rule. It is linted against fleet.yml as it will be once the companion edits are made.

| Kind | Shape |
| --- | --- |
| `loop` | schedule (first free `:07` slot) + dispatch, read-only token with a write job, concurrency, timeout, `publish-data` with `[skip ci]` |
| `agent-loop` | schedule (first free `:37` slot from 11:00) + dispatch, default-off `vars.<ID>_ENABLED` switch that a dispatch bypasses, `claude-auth`, `claude-code-action` with `--max-budget-usd` = `budget.default_usd`, `continue-on-error`, `claude-cost` with `usage-limit: skip` |
| `gate` | `pull_request` + push `main` with path filters, cancel-in-progress concurrency, timeout |
| `reusable` | `workflow_call` with no permissions (inherited), timeout |
| `dispatch` | `workflow_dispatch` with a `dry_run` input defaulting to true |

Names are written as quoted YAML strings, so `Audit: nightly` or `[wip] audit` stays a name. An id whose `schedule:` key or `budget.call_sites` entry is already taken is refused, because its companion edit would overwrite another workflow's. The companion edits are printed, never applied: the `schedule:` key, the `budget.call_sites` entry, the kill-switch variable, the README row and, for a loop, the AGENTS.md loop table. The console's Config page does not invent keys `fleet.yml` does not already carry, and neither does the scaffold. `tools/dash workflows new --write` (or **Write** on the Design tab, the `workflow-new` operation) creates the file. It creates the file only if nothing is at that path (a symlink included), refuses a scaffold that does not parse, and commits nothing.

The Design tab also lints any draft you paste or edit against the same rules, and agents can do the same with the `workflow_lint` MCP tool.

## Changing a rule

Add or change the rule in `RULES` and in `lint_workflow()` / `lint_action()`, add a fixture to `test_workflow_atlas.py` that shows it both firing and passing, and update the table above and the `## Standards` list in the workflows README. A new rule must pass on the live tree before it lands, or land with the fix that makes it pass.
