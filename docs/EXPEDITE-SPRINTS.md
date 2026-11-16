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
- **The ceiling.** Before it spends on a sprint item, each loop asks whether the sprint's spend plus the attempt's **full** call-site cap fits under `usd`. The loop runner (`tools/dash loop run`) asks after the monthly `budget.loops` check, under the same budget lock. JEV runs tier 0 always and tiers 1 and 2 only inside the ceiling; past it the conflict goes to `jev:needs-human`. The issue pipeline reserves, per run and in tier order, the full cap of each tier job that would run a sprint item (T1 $40, T2 $60, T3 $60); a tier that does not fit holds its sprint items. A sprint whose `usd` is below a step's call-site cap never runs that step.
- **Spend.** Summed inside the time box from the ledgers that already exist: the AI ledger's local loop rows (and the runner's unledgered charges) on a sprint repository, JEV's ledger rows on one, and `_data/ai_usage.yml` `ci_ledger` runs of a sprint repository's own workflows. The hub's CI runs are never attributed, because its workflows run fleet-wide loops. A ledger that records only a day counts every row of a day the time box touches. A figure that cannot be read stops the attempt rather than reading as $0.
- **Not yet counted.** The issue pipeline's tier jobs run in the hub and batch several issues in one session, so no ledger attributes their cost to a sprint item. Each run's dispatches must still fit under the ceiling, and the live sprint record (#691) will carry their cost.
- **Circuit breaker.** At the cap the attempt is skipped (`budget-skip`), nothing extends the sprint, and the stop is recorded: an event (`sprint-stop`, with the spend against the cap) in the loop runner's `run.json` `events`, a JEV ledger row and the `jev:needs-human` comment, and `sprint.held` / `sprint.events` in `_data/issue_pipeline.yml`. What the sprint already produced stays as it was filed: T2's pull requests are drafts, and the loop runner's previews are dry runs until `--apply`. When the time box closes the sprint is over: its repositories go back to their lanes, and the declared item stays held (`budget-skip`) until a new declaration.
- **Kill switch.** `vars.EXPEDITE_SPRINT_ENABLED` (opt-out; § 17 entry `hub/expedite-sprint` in `_data/fleet.yml` `switches:`). On a scheduled run, `'false'` stops the active sprint's items in every loop, before tier 0, so not even a $0 merge commit is pushed (`sprint-off`). The issue pipeline's queue steps and `jev-conflicts.yml` are handed the variable; `tools/dash loop run --scheduled` and a scheduled local conflict sweep read it with `gh variable get` and refuse when they cannot. A manual run bypasses it, as a `workflow_dispatch` bypasses every § 17 switch.
- **Reading it.** `tools/dash loop budget` prints the active sprint against its ceiling; the issue pipeline snapshot's `sprint:` block shows its spend, the run's reservations and what was held.

## Worked example — bash-365.com consultation inquiry

Target `bash-365/bash-365.com` (BASH Consulting). A consultation inquiry form on `contact.md` backed by a new Azure Function behind the existing Static Web App, staged in the SWA PR preview (`azure-swa.yml`). Ties to the leaf PRD metric "Inbound consultation inquiries". **Needs a privacy review** (personal data: retention, storage, consent copy, spam protection, no PII in logs). Prerequisites: bash-365/bash-365.com#26 (site-health) fixed and the leaf `AGENTS.md` changed to PR-only publishing. Tracked as #692.

## Design for Failure

See the amendment record (`docs/amendments/0026-expedite-sprints.md`) for the table: cap hit mid-attempt, unanswered gate, second expedite, broken deploy, kill switch, unreadable cost, quality debt.

## Related

`docs/ISSUE-PIPELINE.md` · `docs/JEV.md` · `docs/HARNESS.md` · `docs/WORK-BOARD.md` · `docs/prd/EXPEDITE-SPRINTS.md` · epic #687
