---
id: ADP-06
chapter: 6
title: Planning
book_pages: 100-112 (PDF pages)
status: partial
evidence_repos: [bamr87/bamr87]
last_verified: 2026-10-31
owner_bot: Platform Architect
---
# Planning

## Summary

Planning is an agent's ability to turn a goal into an ordered set of steps from the current state to a goal state, and to revise that plan when reality changes. You state *what* you want and the constraints; the agent works out *how*. Gulli's key point is the trade-off: dynamic planning buys flexibility at the cost of predictability. If the procedure is already known and repeatable, a fixed workflow beats a planner. The deciding question is whether the "how" still has to be discovered. Typical forms: decompose a goal into subtasks (often hierarchical), run them, watch the results, and replan on failure or new information. Frameworks such as CrewAI and Google Deep Research run a plan, then execute and synthesize. (Paraphrased from Gulli, *Agentic Design Patterns*, Ch. 6.)

## When to use / not

- Use when the task has several steps, the path depends on intermediate results, or the work spans tools and repos.
- Avoid when a deterministic script already solves the problem. The fleet's rule, "decide in code, let the agent do only the judgment", applies this directly.

## Failure modes

- Plans that never converge.
- Replanning that burns budget.
- Plans nobody can audit.
- A planner that silently swallows constraints.

## Fleet evidence

| Sub-aspect | Rating | Evidence |
|---|---|---|
| Fixed workflow preferred over a dynamic planner when the "how" is known | proven | Issue pipeline: queue, stage, caps and dedupe are computed in Python before any model runs ([docs/ISSUE-PIPELINE.md](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/docs/ISSUE-PIPELINE.md), "What is deterministic vs what the AI decides"; [issue_pipeline.py](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/.github/scripts/dash-gen/issue_pipeline.py)) |
| Goal decomposition into staged subtasks | proven | Three tiers (intake → implement → complete), with stage derived from labels so each run reconciles state ([docs/ISSUE-PIPELINE.md](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/docs/ISSUE-PIPELINE.md)). Last scheduled runs were green: [41181601564](https://github.com/bamr87/bamr87/actions/runs/41181601564), [41021622493](https://github.com/bamr87/bamr87/actions/runs/41021622493) |
| Plan before execute (dry-run plan, then apply) | proven | JEV `number plan` / `number apply` ([tools/jev/number.py](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/tools/jev/number.py), [docs/JEV.md](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/docs/JEV.md)). The console's write-back uses a plan_id with confirm (constitution §11.4, [docs/constitution.md](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/docs/constitution.md)) |
| Replanning and escalation on failure | partial | JEV's conflict classifier picks the cheapest tier that can finish and escalates with attempts ([tools/jev/classify.py](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/tools/jev/classify.py), `classify(..., attempts, max_attempts, force_min_tier)`). It is deterministic tier escalation, not LLM replanning |
| Local plan→execute loop (`dash loop run`, dry run by default) | gap (in flight) | Evidence exists only on unmerged PRs, so it cannot count. Tracked as [#486](https://github.com/bamr87/bamr87/issues/486) ([issue](https://github.com/bamr87/bamr87/issues/486)), with open PRs #523/#524/#525 on `agent:hold` and nothing merged yet. Follow-up #488 |

### Reproduce (run 2026-10-31 at 2321b3a7c1199688042339d68b628f9d08bb46eb)

```bash
git clone https://github.com/bamr87/bamr87 && cd bamr87 && git checkout 2321b3a7c1199688042339d68b628f9d08bb46eb
python3 -m tools.jev number next
python3 -m tools.jev number plan
python3 -m pytest -q tools/test_jev_classify.py tools/test_jev_number.py tools/test_jev_ledger.py tools/test_jev_generated.py
python3 -m pytest -q tools/test_jev_conflicts.py tools/test_conformance_work.py .github/scripts/dash-gen/test_issue_pipeline.py
```

Actual output:

```
HUB: HUB-058 / FR: FR55 / NFR: NFR13 / amendment: 0014
no pending fragments
41 passed in 0.25s
61 passed in 3.15s
```

CI: python-tests was green on 8ad8cf5 (https://github.com/bamr87/bamr87/actions/runs/41256529231); the files cited are identical at 2321b3a, and the commands above were rerun locally there.

## Gaps

- An LLM planner that replans locally under a budget does not exist yet. Already tracked in #486 and PRs #523–#525, so no duplicate was filed. Promote this chapter to proven once #525 merges with a green run.

## Cross-links

ADP-07 Multi-Agent, ADP-13 HITL (apply gate), constitution §11.4 dry-run/confirm, proposed loop-switch amendment (PR #528), amendment 0002 (assign at merge).
