# Outcome learning

> What happened to each loop's output, one estimate per loop and per repo of how likely the next output is to land, and where the next slots would pay. Shadow only: it prints a plan, steers no loop and changes no cap.

Every loop that files work chooses it with a fixed rule. The scout rotates through the repos by date, evolution takes every opted-in repo, the pipeline scores an issue from its labels. None of them reads what became of the last thing it filed. This module reads it, from the local lake, and keeps the count ([ADR 0010](adr/0010-fleet-graph-and-outcome-learning.md)).

| | |
| --- | --- |
| **Module** | [`tools/fleetcore/learn.py`](../tools/fleetcore/learn.py) (`learning/v1`) |
| **Config** | `_data/fleet.yml` `learning:` |
| **CLI** | `tools/dash learn [status \| plan \| replay] [--loop L] [--slots N] [--json]` |
| **MCP** | `fleet_learning` (`loop`, `slots`, `limit`); no console needed |
| **API** | `GET /api/learn?loop=…&slots=…` · operations `learn-status`, `learn-plan` |
| **Page** | none yet: the operations' logs on the console's Operations page; a Learning page is the next phase |
| **Reads** | the lake's `issues`, `runs` and `agent_runs` tables, opened read-only; `_data/projects.yml` for the arms |
| **Tests** | `python3 tools/test_fleetcore_learn.py` · `python3 .github/scripts/dash-gen/test_fleet_lake.py` (the two outcome columns) |

## Run it

```bash
tools/dash lake sync --days 90 --jobs none --logs none --max-issues 2000   # once: fill the two outcome columns for the window
tools/dash learn                      # one row per loop: outcomes, the landing estimate, the backlog, one word of advice
tools/dash learn plan --loop repo-evolution --slots 5
tools/dash learn replay               # does knowing the repo predict the outcome better than the loop's average?
```

`tools/dash learn` costs nothing, calls no model, reads GitHub nowhere and writes no file. The one-off sync above is the only GitHub read: it lists each repo's issues once (the two flags skip jobs and logs). After it, the harness-review job's daily `lake sync --days 2` keeps the numbers current on a machine where that job is installed.

## Outcomes

`learning.loops` attributes an issue or pull request to a loop by the labels that loop puts on what it files. One item can belong to two loops: an issue the scout proposed and the pipeline then implemented is an outcome of both.

| Outcome | Means | Counts as |
| --- | --- | --- |
| **landed** | a pull request merged, or an issue closed as completed | a success |
| **rejected** | a pull request closed unmerged, or an issue closed as not planned or duplicate | a failure |
| **stale** | still open after `horizon_days`, with no label that says a later stage took it | a failure |
| **working** | open, carrying one of `working_labels` | nothing yet |
| **young** | open and younger than the horizon | nothing yet |
| **unread** | closed, and the lake holds no reason for it | nothing: never guessed |

Stale is a failure here on purpose. For deciding where the next slot goes, an output nobody acted on in two weeks is the signal, whether the proposal was good or not. ADR 0009's KPI counts an open scout issue as accepted; that measures the proposals' quality, and this measures whether anything takes them up.

A lake synced before the outcome columns existed reads every closed item as unread. `tools/dash learn` says so in a note and gives the advice `unread` instead of a rate.

## The estimate

An arm is the repo a loop acted on. For each loop and each arm:

- **Evidence:** landed against rejected plus stale, each outcome weighted by its age. An outcome `half_life_days` old counts half as much as one from today, so a repo that changed is not judged on last quarter.
- **Prior:** the loop's own rate, worth `prior_strength` observations. An arm with no history starts at the loop's average.
- **Estimate:** the mean of Beta(prior + successes, prior + failures) and its 90% range. A wide range means little evidence.

`tools/dash learn` also prints the **pressure** on each loop: its open output divided by what landed per week over the last four weeks, and one word.

| Advice | When |
| --- | --- |
| `file` | nothing open, or under `backlog_weeks.slow` weeks of backlog |
| `slow` | between `slow` and `hold` weeks |
| `hold` | `hold` weeks or more, or output open and nothing landed in four weeks |
| `unread` | closed output whose outcome the lake has not stored |

Where the lake has read an agent run's cost, the loop's row adds dollars per landed output. The figure is API-equivalent (estimate) and a floor: it says how many of the workflow's runs it covers.

## The plan

`tools/dash learn plan` shares the next `--slots` between a loop's arms by Thompson sampling. It draws a landing rate for every arm from its estimate, notes which arm drew highest, and repeats 4,000 times. An arm's share is how often it won.

- An arm with a good record takes most of the slots.
- An arm with no record still wins sometimes, because its range is wide. That is the exploration: a repo is not written off for never having been tried.
- An arm with a bad record wins almost never.
- The seed is the date and the loop, so one day gives one plan on every surface.

Beside each arm's share the plan prints what the loop actually filed there in the last horizon. The gap between the two columns is what the plan would change. For a loop with `arms: registry`, every active registry repo is an arm.

## The replay

Before an estimate may steer anything it has to show it knows something. `tools/dash learn replay` walks a loop's resolved outputs in the order they were filed. For each one it predicts the outcome twice from what was known that day: once from the arm's estimate, once from the loop's plain average. It scores both (Brier score) and reports the skill: above zero, knowing the arm helped.

Below `min_resolved` scored outputs the verdict is "not enough evidence". A loop with one arm has nothing to choose between and says so.

## Shadow, and what comes after

`learning.mode` accepts `shadow` and nothing else; any other value is refused when the config loads. Three steps can follow, each for one loop and each its own gated pull request (ADR 0010 decision 6):

1. **Advise:** the loop prints the plan in its run summary beside what it took.
2. **Steer:** the loop's queue builder orders its candidates by the plan, inside its existing caps.
3. **Propose:** the engine drafts a cap or share change as a pull request a person merges.

A loop may take a step only after its replay shows skill above zero. No step raises a cap, edits a step spec, or changes this module's own thresholds. A pin in `_data/work_queue.yml` always wins.

## Configuration

| Key | Default | Means |
| --- | --- | --- |
| `mode` | `shadow` | the only value accepted |
| `window_days` | 90 | output filed before this is not read |
| `horizon_days` | 14 | open this long with nobody working it is stale |
| `half_life_days` | 30 | an outcome this old weighs half |
| `prior_strength` | 4 | observations the loop's own rate is worth in each arm |
| `min_resolved` | 8 | below this a loop's plan and replay say "not enough evidence" |
| `backlog_weeks` | `{slow: 4, hold: 12}` | the advice thresholds |
| `working_labels` | `[agent:ready, agent:in-pr]` | an open item a later stage took |
| `loops.<name>` | | `kind` (`issue` or `pr`), `labels` (all of them) or `any_labels` (one of them), `workflow` (joins the loop to its runs' cost), `arms: registry` |

To add a loop, give it a rule here. The loop has to label what it files; an output with no label of its own cannot be attributed.

## Limits

- **Attribution is by label.** The pipeline is measured through the issues it took (`agent:in-pr`, `agent:done`), not through its pull requests' branches, which the lake does not store.
- **The doctor has one arm.** Its issues are all filed in the hub, so it has a loop-level estimate and no plan to share out.
- **Cost is a floor.** Only runs whose logs the lake has read carry a cost.
- **One maintainer.** A stale output may be a good proposal nobody has read. The advice names the backlog, not the agent.
- **Small numbers.** With a few resolved outputs per repo the plan is close to an even split. That is the right answer to little evidence, and the replay says when it stops being true.

Last modified: 2026-11-10
