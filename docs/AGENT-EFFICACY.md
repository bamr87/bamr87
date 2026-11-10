# The agent inventory and the efficacy contract

> Every AI agent the fleet runs, in one generated inventory (`_data/agents.yml`), held to the agentic efficacy contract (constitution § 29): what each agent must declare, how drift check (p) keeps the inventory complete, and how the contract's gaps move from warnings to a gate.

The contract is constitution § 29 (amendment `agentic-efficacy-contract`); why it is shaped this way, and the prior art, are in [ADR 0009](adr/0009-agentic-efficacy-model.md). The epic that builds it out is [#773](https://github.com/bamr87/bamr87/issues/773). This page is how to run it.

## What counts as an agent

An agent is anything that spends a model call, or runs a scheduled job an agent depends on, without a person at the keyboard. The inventory finds each kind in the files that define it:

| Category (§ 29) | Kind | Found in | Id |
| --- | --- | --- | --- |
| CI agent step | `ci-scheduled`, `ci-event`, `ci-mention` | the hub's `.github/workflows/` (a `claude-code-action` step, or a `uses:` of `.github/actions/claude-run`), and every fleet repo's from the committed `_data/harness_registry.yml` | `ci:<repo>:<workflow stem>` |
| Local loop step | `loop-step` | `tools/jev/steps/<loop>/<step>.yml`, read through `tools/jev/spec.py` | `loop:<loop>/<step>` |
| JEV tier | `jev-tier` | `_data/fleet.yml` `jev:` (tier 0, plus each of `jev.tiers`) | `jev:<tier>` |
| Scheduled local job | `local-job` | a `tools/install-*.sh` that installs a LaunchAgent (`LABEL="com.bamr87.<name>"`), or a `harness.agents.<id>.declare` block before its installer lands | `local:<name>` |

A git-hook installer (`install-prose-hook.sh`) is not a job and is not listed. An archived repo's workflows are listed with `status: archived` and are not graded.

On 2026-11-07 the inventory held 71 agents: 60 CI agent steps (10 scheduled, 15 event-driven, 35 mention handlers), 5 loop steps, 3 JEV tiers and 3 local jobs (`conflict-sweep`, `workspace-sync`, and `harness-review`, declared ahead of PR #772).

## Run it

```bash
tools/dash agents                    # rebuild _data/agents.yml (offline, deterministic)
tools/dash agents --verbose          # … and list every agent's contract gaps
tools/dash agents --check            # drift check (p): is the committed file current?
tools/dash agents --check --strict-fleet   # … and fail on fleet-half drift too (the daily --ci run)
python3 .github/scripts/dash-gen/test_agent_inventory.py
```

In VS Code, both are under **4-generate** (`🛠️ Agent inventory: …`), and `tools/dash agents --check --verbose` is in the gate picker. `fleet-pulse.yml` rebuilds the file daily, in the same commit as `_data/harness_registry.yml`.

## One entry

```yaml
- id: loop:fleet-pulse/doctor
  kind: loop-step
  category: local-loop-step
  repo: bamr87/bamr87
  where: tools/jev/steps/fleet-pulse/doctor.yml
  owner: bamr87                        # rule 1
  trigger: manual (tools/dash loop run fleet-pulse doctor); --scheduled reads vars.FLEET_PULSE_ENABLED
  switch: {config: remediation.enabled, variable: FLEET_PULSE_ENABLED, default: 'on'}
  budget: {per_run_usd: 40.0, call_sites: {fleet-pulse.yml:doctor: 40.0}, monthly_usd: 50.0}
  model: claude-opus-5-5
  kpis: {accepted_per_usd: 0.05, accepted_per_actions_min: null, time_to_outcome_h: 72, …}   # rule 3
  reads:                               # rule 4: source -> its writer
    actions-usage: fleet-pulse.yml (dash-gen actions)
    lake: local:harness-review
    …
  run_record: ai-ledger                # rule 2: where its records land
  feeds_reflector: true                # rule 5
  local_entry: tools/dash loop run fleet-pulse doctor   # rule 6
  counterparts: [ci:bamr87:fleet-pulse]
  first_seen: '2026-11-07'
  gaps: [R2:missing:permission_denials,tool_errors]
```

The file opens with the contract (`enforce`, `shadow_until`, `grace_until`, the six rules), `totals` (by category, by kind, `gaps_by_rule`), the KPI catalogue, each kind's thresholds, the run-record schema and its stores, and the source catalogue with each writer and SLO. `schema: agents/v1` is the compatibility marker: additive changes keep it, and a rename or removal bumps it.

## The six rules and their gap codes

| Rule (§ 29) | Gap codes | What closes it |
| --- | --- | --- |
| R1 registered with owner, trigger, kill switch, budget cap and model | `R1:owner`, `R1:trigger`, `R1:switch`, `R1:budget`, `R1:model` | the workflow's literals (`--model`, `--max-budget-usd`, a `vars.*_ENABLED` gate), a `switches:` entry, or a `harness.agents` fact |
| R2 one run record per model call, in one schema | `R2:no-record`, `R2:missing:<fields>` | a store that carries every `run_record.fields` (E1, #775) |
| R3 KPIs and thresholds declared | `R3:no-kpis` | the kind's block in `harness.efficacy.kinds` |
| R4 every source read has a writer and an SLO | `R4:no-writer:<source>`, `R4:no-slo:<source>`, `R4:writer-pending:<source>`, `R4:no-sources` | a scheduled writer, declared in `harness.sources` |
| R5 its run records reach the reflector | `R5:no-reflector` | records in one of `harness.efficacy.reflector_inputs` |
| R6 a local entry point | `R6:no-local-entry` | a step spec with a `local:` block, or a declared entry; a mention handler is exempt |

An agent with no model (`model: none`: tier 0, `workspace-sync`) has no R2 or R5 gap. A kind's exemption (`switch` or `local_entry` set to `{exempt: <reason>}`) is printed in the entry, so it is visible rather than silent.

## Drift check (p)

`tools/check-drift.sh` runs `tools/dash agents --check`:

- **Fails** when the hub's own files define an agent the committed inventory lacks (a new AI workflow, step spec or installer), when a registered hub agent is gone or its entry is stale, when `harness.efficacy`, `harness.sources` or a kind's thresholds changed without a rebuild, when the file was edited by hand, and when the contract in `_data/fleet.yml` does not validate (an unknown KPI or source id, a non-numeric threshold, an exemption with stray keys).
- **Warns** when only the fleet half differs (`harness_registry.yml` changed, which no hub PR causes; the daily `--ci` run fails on it), and on contract gaps while `enforce` is false.

The fix for a failure is always the same: `tools/dash agents`, then commit `_data/agents.yml`. Two PRs that both regenerate it conflict like any generated file; `.gitattributes` marks it `merge=jev-regen`, so the resolution is a rebuild, never a hand-merge.

## Adding an agent

1. Add the workflow, step spec or installer as usual.
2. If the code cannot show something the contract asks for (an installer's model, its cap, its switch, the sources it reads), add it under `_data/fleet.yml` `harness.agents.<id>`. Use `model_from` and `budget_from` to reference keys in `_data/fleet.yml` rather than copying numbers.
3. If it reads a source the catalogue does not have, add it to `harness.sources` with its writer and SLO. A source with no writer is allowed, as `writer: null`, and it shows as a defect.
4. Run `tools/dash agents --verbose` and commit `_data/agents.yml`. A changed threshold, source or exemption makes the PR gated (§ 12.3).

`declare` registers an agent before its installer exists. The declaration keeps winning after the installer lands, so that merge does not change the inventory under an unrelated PR. The generator then says to drop the block, and that later PR shows the diff. Nothing is declared today: `local:harness-review` was, ahead of PR #772, and its block was dropped once `tools/install-harness-review.sh` was in the tree. While it was declared, every agent reading the lake carried `R4:writer-pending:lake`.

The inventory reads the installer, not the machine. A local job is listed when its installer is in the tree, whether or not its LaunchAgent is loaded on the Mac: `launchctl list | grep com.bamr87` shows which are.

## Shadow, enforcement and grace

- `enforce: false` (now): every contract gap is a warning. This is the shadow period, which lasts at least until `shadow_until` (2026-11-21) and at least 14 days after § 29 is ratified.
- After that, a gated PR may set `harness.efficacy.enforce: true`. The check refuses `true` before `shadow_until`.
- Under enforcement, an agent first seen on or after `shadow_until` must have no gaps, and one first seen before it keeps its gaps as warnings until `grace_until` (2027-02-01). `first_seen` is carried forward from the committed file, so rebuilding never resets it.

## What reads it next

E1 (#775) closes the run-record gaps (R2) and fixes the numbers the checks read. E2 (#776) adds an agentic layer and trip wires to `harness_health`, reading this file and the sources' SLOs. E3 (#777) computes each KPI per agent against its kind's thresholds. E4 (#778) puts the reflector on a schedule and measures its verdicts. E5 (#779) gives the console one view to see, pause, budget and tune every agent, through § 11.
