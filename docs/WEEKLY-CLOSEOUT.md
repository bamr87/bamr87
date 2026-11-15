# Weekly close-out

> Three scheduled console loops that close out the week's open work on Friday, draft next week's plan on Saturday and write the week-ahead brief on Sunday.

Amr's week ends with open PRs, failing checks, conflicting branches, leftover clones and worktrees. These loops round that up, clean it up and hand the next week a clean slate, and the console schedules, dispatches and maintains them like every other control-plane loop. All three are **off** until the repository variable below is `true`; a manual dispatch always runs.

| Loop | Workflow | When (America/Denver, MST = UTC-7) | Cron (UTC) | Switch | Agent |
| --- | --- | --- | --- | --- | --- |
| `weekly_closeout` | [`weekly-closeout.yml`](../.github/workflows/weekly-closeout.yml) | Friday 13:17 | `17 20 * * 5` | `WEEKLY_CLOSEOUT_ENABLED` | Opus, 120 turns, $20, [`closeout.md`](../.github/weekly/closeout.md) |
| `weekly_gather` | [`weekly-gather.yml`](../.github/workflows/weekly-gather.yml) | Saturday 10:17 | `17 17 * * 6` | `WEEKLY_GATHER_ENABLED` | Sonnet, 60 turns, $10, [`gather.md`](../.github/weekly/gather.md) |
| `weekly_finalize` | [`weekly-finalize.yml`](../.github/workflows/weekly-finalize.yml) | Sunday 16:17 | `17 23 * * 0` | `WEEKLY_FINALIZE_ENABLED` | Sonnet, 60 turns, $10, [`finalize.md`](../.github/weekly/finalize.md) |

The crons live in [`_data/fleet.yml`](../_data/fleet.yml) `schedule:` (`weekly_closeout`, `weekly_gather`, `weekly_finalize`), where the console's schedule config reads them; the workflow's own `on: schedule:` is what GitHub obeys, and [`tools/test_weekly_closeout.py`](../tools/test_weekly_closeout.py) holds the two equal. UTC hours 17, 20 and 23 carry no other AI cron, so the three-per-hour throughput cap is not touched. Denver moves to UTC-6 in daylight time (March to November), so the wall clock shifts an hour at each change; retune the crons then.

## How it is built

Each loop is a caller of the fleet's reusable [`ai-lane.yml`](../.github/workflows/ai-lane.yml) (kit `ai-runner`, [`templates/ai-runner/`](../templates/ai-runner/README.md)): the lane supplies the kill switch, the bot guard, the credential order, named concurrency that never cancels a writer, the capped model step and the "did the agent produce something" assertion. The caller supplies least-privilege `permissions:`, the exact model, the two circuit breakers (`max-turns` and `max-budget-usd` change together; the dollar cap must clear `budget.usd_per_turn` × turns) and the prompt, which names the brief under `.github/weekly/`. A turn-cap or dollar-cap stop fails the step and must not fall through to the API fallback ([#840](https://github.com/bamr87/bamr87/pull/840) carries that rule in `claude-run`; these callers get it when it merges).

The week's state is one issue in this repo, `Week <ISO year>-W<week> — close-out and plan` (label `weekly-closeout`), that each lane comments on: Friday's `## Friday close-out`, Saturday's `## Saturday gather (draft)`, Sunday's `## Week-ahead brief`. Each lane also uploads its artifact (`.closeout/`, `.weekly/`) for 30 days.

### Friday: what the agent may and may not do

It consumes a manifest (a path or URL given at dispatch, or the one it builds with `gh`): open PRs classified green, failing, conflicting, draft, stale or superseded, plus leftover `/tmp` clones and worktrees. It may fix failing CI with a commit on the PR's own branch (one PR per repo, never a second fix PR), merge the base into a conflicting or behind branch, repair catalog, story or PRD links when that is the actual cause, delete the remote head branch of Amr's own PR only after confirming it is merged, and prune finished clones and worktrees only after `git status` and an unpushed-commit check (when unsure it lists them). It caps at the most valuable dozen fixes and lists the rest as carry-over, and writes `.closeout/summary.md`: Fixed, Ready for Amr to merge, Proposed to close, Needs Amr, Carry-over.

It never merges, closes or approves a PR, never releases, never force-pushes, never changes settings, branch protection, variables or secrets, never prints a secret, and never touches `~/bamr87`, running containers, monitoring or existing Claude sessions. The ~55 harness-rollout PRs of 2026-11-13 depend on #840: it fixes CI on one only when that PR is failing for its own reasons. Saturday and Sunday are read-only apart from one issue comment, and Sunday does not wake other Grok bots; its brief only recommends assignments.

### Operating it from the console

The Loops page and the MCP `loops` tool list all three (the `LOOPS` entries in [`tools/console/core.py`](../tools/console/core.py)), with the cron from `fleet.yml`. `dispatch` runs one now (all three are in `DISPATCH_WORKFLOWS`, so `manifest` and `focus` are accepted from the workflow's own `workflow_dispatch.inputs`); the read-only `triage` and `decisions-refresh` ops refresh the inputs the Friday agent reads. To arm a lane, Amr runs `gh variable set WEEKLY_CLOSEOUT_ENABLED -R bamr87/bamr87 --body true` (the same for the other two) and records the flip in `fleet.yml` `switches:` in the same PR. This PR sets no variable.

**Not built here: a local `loop-run`.** `loop-run` runs a JEV step spec, and a spec must be held equal to a `claude-code-action` step in its workflow (`tools.jev.spec.parity_errors`), which an `ai-lane` caller does not contain. A local adapter, planner and filer for these loops is the follow-up; until then `tools/dash agents` lists each loop with the honest gap `R6:no-local-entry`, and the console runs them through `dispatch`.

## Console vs Grok routines

| | Today | After this PR merges and Amr arms the switches |
| --- | --- | --- |
| Schedule, dispatch, repo work (rebases, CI fixes, branch and clone cleanup), the summary | three Grok Bot routines in Grok Bot chat | **the console** (these loops, their crons, `dispatch`) |
| The inventory report and the message to Amr | Grok Bot routines | **still Grok routines**: the chat is where Amr reads and answers, and nothing here can message him |
| Changing a Grok routine's config | Grok Bot chat | not from this repo; unchanged |

To move the Grok *triggering* into the console, four things are needed, none done by this PR: (1) Amr sets the three kill-switch variables; (2) the console's `dispatch` and `loop-run` ops are confirm-gated and `mcp_writes_enabled` is currently false on the tunnel, while `job_dispatch` allows only a small report-op allowlist that excludes `loop-run` and `dispatch`; (3) the Cursor `harness-console-http` connector is `failed_to_load` even though the raw tunnel at the saved trycloudflare URL answers with a valid token, so the connector needs repair or re-registration; (4) a console→Grok wake, or a console-native inventory report that can be delivered to Amr, would replace the routine trigger.

## User stories

- As Amr, on Friday afternoon I want open PRs that are only failing or conflicting to be repaired, so Monday's merge queue is clean, without anything being merged for me.
- As Amr, I want finished clones and worktrees pruned only when nothing would be lost, so cleanup is safe to leave unattended.
- As Amr, on Saturday I want a draft plan from the carry-over and upcoming routines, and no ping unless something needs me before Monday.
- As Amr, on Sunday I want a two-minute brief that splits the week between the Grok loops and the Claude job queue.
- As the operator, I want each loop to be a switch I flip once, visible and dispatchable in the console like every other loop.

## Failure modes, detection, recovery (DFF)

| Failure mode | Detection | Recovery |
| --- | --- | --- |
| A lane runs before it is wanted | cannot happen on a schedule: the gate idles until its variable is `true` | leave the variable unset; dispatch to exercise it |
| The agent hits its turn or dollar cap | the agent step fails (red), no API fallback; the summary file is empty so the result check fails too | read the artifact and the issue comment so far, re-dispatch with a narrower `manifest` or `focus`; raise `max-turns` and `max-budget-usd` together only if work was real |
| Usage window spent or no credential | the gate or the model step reports it; a spent window is capacity, not a defect | next scheduled run, or dispatch later |
| A token is expired | `GH_PAT` is probed with `gh api user` and the lane warns it fell back to the job token; cross-repo pushes then fail visibly in the log | rotate through `token-rotation.yml` |
| The agent fixes the wrong thing or leaves a bad commit | every change is a commit on an existing PR branch, reviewed in that PR; nothing is merged or force-pushed | revert the commit in the PR; a bad branch deletion is limited to merged PRs' heads, restorable from the PR page |
| Cleanup removes work | pruning requires a clean `git status` and no unpushed commit, and lists when unsure | the pushed branch or the listed clone is the copy |
| Saturday or Sunday finds no tracking issue | the draft says so | Friday's lane creates it; dispatch Friday first |
| Two lanes in one UTC weekday-hour | `tools/test_weekly_closeout.py` and the `/schedules` page | move a minute or an hour in `fleet.yml` and the workflow together |
| Daylight saving shifts the wall clock | the crons are fixed UTC | retune in March and November |
