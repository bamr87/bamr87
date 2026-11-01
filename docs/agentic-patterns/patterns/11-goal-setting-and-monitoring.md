---
id: ADP-11
chapter: 11
title: Goal Setting and Monitoring
book_pages: "Ch. 11 (12 pp.)"
status: partial
evidence_repos: [bamr87/bamr87]
last_verified: 2026-10-31
owner_bot: executor (Grok Bot)
---
# Goal Setting and Monitoring

## Summary
An agent needs a defined end state and a way to tell whether it has reached it. In this pattern you state the objective in measurable terms, break it into steps, and keep checking progress against the objective while the agent works. If the agent drifts, it corrects course or replans, and it escalates when it can't succeed. The chapter's example is a coding agent that writes code, judges it against a list of goals, and revises, capped at a fixed number of iterations. The book is candid about the weak spots. An LLM can misread a goal or wrongly decide it has succeeded. A model that judges its own work struggles to see when it has gone wrong. A naive loop can run forever. So the book recommends a separate reviewer role, real tests, and hard stop conditions (ch. 11, "Caveats and Considerations"). In the book's words, the pattern turns reactive agents into "proactive, goal-oriented systems" by closing a feedback loop.

## When to use / not
- Use: multi-step, unattended work where "done" can be stated and checked, such as issue → PR, a release, or a budgeted loop.
- Avoid: one-shot Q&A, or goals that can't be measured, where a judge loop only adds cost.
- Failure modes: the same model acts as author and judge; the goal is vague, so success is self-declared; there is no iteration or budget cap (a runaway loop); something is monitored but nothing acts on it.

## Fleet evidence (hub commit 2321b3a7c1199688042339d68b628f9d08bb46eb unless noted)
| Behaviour | Permalink |
|---|---|
| Goal must be stated before work: readiness gaps for missing acceptance criteria, scope or evidence, scored 0-100 | [issue_pipeline.py L200-L202, L311-L374](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/.github/scripts/dash-gen/issue_pipeline.py#L311-L374) |
| Readiness threshold: below 70, intake must not pass an item on | [_data/fleet.yml L319-L320](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/_data/fleet.yml#L319-L320) |
| Explicit definition of done (every check green, every acceptance criterion verified, tests fail without the change); iterate until green or genuinely stuck | [issue-pipeline.yml L915-L926](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/.github/workflows/issue-pipeline.yml#L915-L926) |
| Escalation instead of self-approval: `human-review` keeps the PR a draft; `never_merge: true` | [issue-pipeline.yml L928-L935](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/.github/workflows/issue-pipeline.yml#L928-L935), [_data/fleet.yml L327](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/_data/fleet.yml#L327) |
| Goal state on the board: `agent:queued` → Ready … `agent:done` → Done, with a fixed lifecycle | [templates/projects/framework.yml L37-L63](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/templates/projects/framework.yml#L37-L63) |
| Staleness monitor: in-progress spec with no commit for 30+ days, or a P0/P1 issue idle for 30+ days | [specs/WORK.contract.yml L268-L277](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/specs/WORK.contract.yml#L268-L277) |
| Stop conditions for loops: `budget.loops` monthly ceiling ($25) with a scheduled stop at 80%, checked before each model call (open PR [#525](https://github.com/bamr87/bamr87/pull/525), head 80c6ceec91fc925b3bb31c6bce0540e5d19d7a52) | [fleet.yml L580-L582](https://github.com/bamr87/bamr87/blob/80c6ceec91fc925b3bb31c6bce0540e5d19d7a52/_data/fleet.yml#L580-L582), [tools/jev/loop.py L1020-L1040](https://github.com/bamr87/bamr87/blob/80c6ceec91fc925b3bb31c6bce0540e5d19d7a52/tools/jev/loop.py#L1020-L1040) |

### Reproduce
```bash
gh repo clone bamr87/bamr87 /tmp/hub && cd /tmp/hub && git checkout 2321b3a7c1199688042339d68b628f9d08bb46eb
python3 -m pytest -q .github/scripts/dash-gen/test_issue_pipeline.py .github/scripts/dash-gen/test_work_board.py tools/test_conformance_work.py tools/test_governance_lint.py
# loop budget stop (unmerged PR #525):
git fetch origin pull/525/head:pr525 && git checkout pr525
python3 -m pytest -q tools/test_jev_loop.py .github/scripts/dash-gen/test_ai_budget.py
```
Expected (run 2026-10-31): `56 passed`, then `84 passed`. Live runs: [issue-pipeline run 41181601564](https://github.com/bamr87/bamr87/actions/runs/41181601564) (success, 2026-10-31 01:41 MDT); [Python tests run 41256758330](https://github.com/bamr87/bamr87/actions/runs/41256758330) (success, main).

## Gaps
1. **The goal check is the agent's own prose.** Tier 3 judges whether the acceptance criteria are met, but nothing machine-checks that judgment before `agent:done`. This is the book's author-as-judge caveat. → [#537](https://github.com/bamr87/bamr87/issues/537) (`agent:queued`). Related: an independent reviewer bot, [#492](https://github.com/bamr87/bamr87/issues/492).
2. `budget.loops` stop conditions exist only on unmerged PRs [#523](https://github.com/bamr87/bamr87/pull/523)–[#525](https://github.com/bamr87/bamr87/pull/525). The status stays `partial` until they merge.

## Cross-links
ADP-19 (evaluation and monitoring), ADP-12 (exception handling), ADP-16 (resource-aware: budget stops), ADP-20 (prioritization); constitution §15 (testing evidence), #528 (kill switches).
