# Expedite sprints — accelerated, monitored pilots run by agentic loops

> The fleet's standard for one top-priority, time-boxed sprint at a time (constitution § 27, amendment `expedite-sprints`), driven end to end by the existing loops with three gates only Amr passes.

> **Status:** proposed. The lane rule and process are this standard; the sprint ceiling and circuit breaker are built ([below](#the-sprint-ceiling-and-circuit-breaker), #689); the DORA projection (#690) and live record (#691) are follow-ups under epic #687. Research write-up: https://cursor.com/canvas/store-ecae274f-8a58-44f1-9d6f-1810735ef947/c859cd74-6625-43b3-a8fe-c4588a912dcd

## What an expedite sprint is

The Kanban expedite class of service (WIP 1, preempts other work), run with incident-command roles (one commander, one writer per repo, a live state document), under a Shape Up appetite (fixed time, variable scope, a circuit breaker instead of an extension), scored by DORA's delivery metrics and stopped by the same budgets, kill switches and review gate as every other loop.

## Phases and who does what

| Phase | Loop / agent | Reuses | Output | Watched |
| --- | --- | --- | --- | --- |
| 0. Intake | Issue pipeline T1 | `issue-pipeline.yml`, readiness score | Epic + one sub-issue per phase on the Fleet project, P0 | readiness |
| **Gate A — declaration** | Amr | `_data/work_queue.yml` `order:` (committing it is the approval) | Item first in its lane; appetite recorded | — |
| 1. Scope | T1 + spec agent | `templates/spec-driven/`, § 10.8 prior art | Spec with user stories, DFF table, acceptance; FEAT/PRD fragments | scope cut vs kept |
| **Gate B — spec approval** | Amr | § 12.3 review gate | Approved spec; amendments left for his merge | — |
| 2. Build | Issue pipeline T2 | hardened clone, read-only allowlist, `--max-budget-usd` | One draft PR per repo | change lead time, API-equivalent cost (estimate) |
| 3. Test | T3, CI, UX gate, evals | leaf CI, preview environments, `templates/ux-audit/`, § 13 | Green required checks, evidence | CI pass rate |
| 3b. Conflicts | JEV | tier 0 → 1 → 2 → 3 (`docs/JEV.md`) | Merge-commit resolution or `jev:needs-human` | tier reached |
| **Gate C — merge** | Amr | `needs-amr` + Fleet status *Needs Amr* | Merge commit | review wait |
| 4. Deploy | Existing CI | Pages / SWA / § 21 promote by digest | Live change | deployment frequency |
| 5. Monitor | fleet-pulse doctor, site-health | trip wires in `docs/HARNESS.md` | Attention items | change fail rate, recovery time, rework rate |
| 6. Retro | harness refinement | ratchet, `_data/harness_library` | Lessons, debt issues | lessons promoted to sensors |

## Rules

1. One active expedite sprint fleet-wide; a second request is refused until the first ends or is demoted.
2. No gate is skipped, relaxed or self-approved; agents never merge a gated PR (§ 12).
3. The appetite is a ceiling. At the cap the sprint stops and files a draft; extension needs a new declaration.
4. Sprint spend sits inside `budget.call_sites`, `budget.loops`, `budget.jev` and the fleet monthly ceiling; JEV starts at tier 0.
5. Every loop honours its kill switch (§ 17); the sprint-scope switch stops all of them.
6. Outgoing messages (posts, emails) are drafts until Amr merges or sends.
7. Hands off Amr's Mac until an approved deploy step (§ 10.5).
8. DORA metrics are a guide per app, never a target.

## The sprint ceiling and circuit breaker

Declared in [`_data/fleet.yml`](../_data/fleet.yml) `budget.sprints` (the shape is documented there) and checked by [`tools/jev/sprints.py`](../tools/jev/sprints.py) in every loop a sprint drives (#689).

- **Declaration (Gate A).** Amr pins the item in `_data/work_queue.yml` `order:` and commits its entry: `item` (the work-queue key), `repos` (optional when the item names its repository), `usd` (the ceiling, API-equivalent (estimate)), `hours` (the appetite), `declared`, and an optional `ends` (the earlier of `ends` and `declared + hours` wins, so neither extends the other).
- **Refused at load.** A ceiling or appetite that is `.inf`, `.nan`, 0 or negative; a ceiling above `harnesses.budget.monthly_ai_usd` (a sprint sits inside the caps, § 27.4); an unknown key; an end that is not after the declaration; two sprints whose time boxes overlap (WIP 1). A refused declaration stops every loop that checks sprints until it is fixed, and `test_ai_budget.py` and `tools/test_jev_sprints.py` keep one off `main`.
- **Scope.** Inside its time box, every loop attempt on one of the sprint's repositories is sprint work.
- **The ceiling.** Before it spends on a sprint item, each loop asks whether the sprint's spend plus the attempt's **full** call-site cap fits under `usd`. The loop runner (`tools/dash loop run`) asks after the monthly `budget.loops` check, under the same budget lock. JEV runs tier 0 always and tiers 1 and 2 only inside the ceiling; past it the conflict goes to `jev:needs-human`. The issue pipeline's scan reserves for its whole run, in tier order, the full cap of each tier job that can run a sprint item (T1 $40, T2 $60, T3 $60); a tier that does not fit holds its sprint items. Tier 2 re-scans after tier 1 has marked issues `agent:ready`, so the scan reserves tier 2's cap whenever it is queuing a sprint issue for tier 1 or has one ready, and the re-scan runs sprint items only inside the room the scan reserved for it: an item that reached `agent:ready` some other way waits for the next run. A tier the run does not start (a dry run, or a dispatch of other tiers) reserves nothing. A sprint whose `usd` is below a step's call-site cap never runs that step.
- **Spend.** Summed inside the time box from the ledgers that already exist: the AI ledger's local loop rows (and the runner's unledgered charges) on a sprint repository, JEV's ledger rows on one, `_data/ai_usage.yml` `ci_ledger` runs of a sprint repository's own workflows, and the issue pipeline's reservations. The hub's CI runs are never attributed, because its workflows run fleet-wide loops. A ledger that records only a day counts every row of a day the time box touches. A figure that cannot be read stops the attempt rather than reading as $0.
- **The issue pipeline's reservations.** Its tier jobs run in the hub and batch several issues in one session, so no ledger attributes their cost to a sprint item. Instead each run that reserved anything adds a row to `_data/issue_pipeline.yml` `sprint.reservations` (the run and attempt, the time, the sprint and its declaration, and the cap of each tier it reserved), and the next run, the loop runner and JEV count every row inside the time box as estimated spend: the full cap, so the estimate errs high. The scan reads the rows from its checkout, from the hub's default branch as it is now (a queued run's checkout can predate the run before it) and from the publish fallback branch `chore/issue-pipeline` (where a refused push leaves them); one it cannot read stops the scan. The loop runner and JEV read them from their own checkout of the hub, as they read `_data/ai_usage.yml` and JEV's ledger, so a row still on the fallback branch reaches them once that pull request merges. A run spends on sprint items only once its record has landed: the tier jobs that hold one run only in the attempt whose snapshot was published, so a re-run of a failed tier job does not spend a second time under the same reservation, and a run whose snapshot did not publish runs none.
- **Circuit breaker.** At the cap the attempt is skipped (`budget-skip`), nothing extends the sprint, and the stop is recorded: an event (`sprint-stop`, with the spend against the cap) in the loop runner's `run.json` `events`, a JEV ledger row and the `jev:needs-human` comment, and `sprint.held` / `sprint.events` in `_data/issue_pipeline.yml`. What the sprint already produced stays as it was filed: T2's pull requests are drafts, and the loop runner's previews are dry runs until `--apply`. When the time box closes the sprint is over: its repositories go back to their lanes, and the declared item stays held (`budget-skip`) until a new declaration.
- **Kill switch.** `vars.EXPEDITE_SPRINT_ENABLED` (opt-out; § 17 entry `hub/expedite-sprint` in `_data/fleet.yml` `switches:`). On a scheduled run, `'false'` stops the active sprint's items in every loop, before tier 0, so not even a $0 merge commit is pushed (`sprint-off`). The issue pipeline's queue steps and `jev-conflicts.yml` are handed the variable; `tools/dash loop run --scheduled` and a scheduled local conflict sweep read it with `gh variable get` and refuse when they cannot. A manual run bypasses it, as a `workflow_dispatch` bypasses every § 17 switch.
- **Reading it.** `tools/dash loop budget` prints the active sprint against its ceiling (`--json` carries its spend by source; exit 1 when it cannot be judged); the issue pipeline snapshot's `sprint:` block shows its spend, this run's reservation by tier, every run's reservation row and what was held.

## Worked example — bash-365.com consultation inquiry

Target `bash-365/bash-365.com` (BASH Consulting). A consultation inquiry form on `contact.md` backed by a new Azure Function behind the existing Static Web App, staged in the SWA PR preview (`azure-swa.yml`). Ties to the leaf PRD metric "Inbound consultation inquiries". **Needs a privacy review** (personal data: retention, storage, consent copy, spam protection, no PII in logs). Prerequisites: bash-365/bash-365.com#26 (site-health) fixed and the leaf `AGENTS.md` changed to PR-only publishing. Tracked as #692.

## Design for Failure

See the amendment record (`docs/amendments/0026-expedite-sprints.md`) for the table: cap hit mid-attempt, unanswered gate, second expedite, broken deploy, kill switch, unreadable cost, quality debt.

## Related

`docs/ISSUE-PIPELINE.md` · `docs/JEV.md` · `docs/HARNESS.md` · `docs/WORK-BOARD.md` · `docs/prd/EXPEDITE-SPRINTS.md` · epic #687
