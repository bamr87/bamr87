# Expedite sprints — accelerated, monitored pilots run by agentic loops

> The fleet's standard for one top-priority, time-boxed sprint at a time (constitution § 27, amendment `expedite-sprints`), driven end to end by the existing loops with three gates only Amr passes.

> **Status:** proposed. The lane rule and process are this standard; the sprint ceiling (#689), DORA projection (#690) and live record (#691) are follow-ups under epic #687. Research write-up: https://cursor.com/canvas/store-ecae274f-8a58-44f1-9d6f-1810735ef947/c859cd74-6625-43b3-a8fe-c4588a912dcd

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

## Worked example — bash-365.com consultation inquiry

Target `bash-365/bash-365.com` (BASH Consulting). A consultation inquiry form on `contact.md` backed by a new Azure Function behind the existing Static Web App, staged in the SWA PR preview (`azure-swa.yml`). Ties to the leaf PRD metric "Inbound consultation inquiries". **Needs a privacy review** (personal data: retention, storage, consent copy, spam protection, no PII in logs). Prerequisites: bash-365/bash-365.com#26 (site-health) fixed and the leaf `AGENTS.md` changed to PR-only publishing. Tracked as #692.

## Design for Failure

See the amendment record (`docs/amendments/proposed/expedite-sprints.md`) for the table: cap hit mid-attempt, unanswered gate, second expedite, broken deploy, kill switch, unreadable cost, quality debt.

## Related

`docs/ISSUE-PIPELINE.md` · `docs/JEV.md` · `docs/HARNESS.md` · `docs/WORK-BOARD.md` · `docs/prd/EXPEDITE-SPRINTS.md` · epic #687
