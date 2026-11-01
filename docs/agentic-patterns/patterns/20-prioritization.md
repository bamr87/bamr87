---
id: ADP-20
chapter: 20
title: Prioritization
book_pages: "Ch. 20 (10 pp.)"
status: partial
evidence_repos: [bamr87/bamr87]
last_verified: 2026-10-31
owner_bot: executor (Grok Bot)
---
# Prioritization

## Summary

Agents usually face more candidate work than they have time, budget or attention for. Prioritization gives them an explicit way to choose. You define the criteria, score each candidate against them, pick the next item or ordering with a selection rule, and re-rank as conditions change. The book lists urgency, importance, dependencies, resource availability, cost/benefit and user preference as typical criteria. It applies them at three levels: picking a goal, ordering sub-tasks, and choosing the next action. Its example is a project-manager agent that creates tasks, assigns P0-P2 priorities and hands them out. The point of the pattern is to spend effort on what matters most so an agent doesn't stall or chase low-value work. The book's rule of thumb is to use it whenever an agent must juggle competing tasks or goals under limited resources.

## When to use / not

- Use: shared work queues, triage, loops that run unattended over many items, alert floods.
- Avoid: a single-item flow, or a strict FIFO that the business requires.

## Failure modes

- An opaque score nobody can override.
- Age-only ranking that starves urgent work (or the reverse).
- Ignoring dependencies.
- Priorities that are never re-evaluated.

## Fleet evidence (`bamr87/bamr87@2321b3a`)

| Behavior | Permalink |
|---|---|
| Criteria and scoring: type base, severity, red CI on the repo, repo status, engagement, bounded age bump, clamped 0-100 | [issue_pipeline.py L377-L400](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/.github/scripts/dash-gen/issue_pipeline.py#L377-L400) |
| Score → label thresholds (80/55/30 → P0/P1/P2, else P3) | [issue_pipeline.py L403-L408](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/.github/scripts/dash-gen/issue_pipeline.py#L403-L408) |
| Selection logic: human rank first, then priority, readiness (above age, by design), then age | [issue_pipeline.py L748-L762](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/.github/scripts/dash-gen/issue_pipeline.py#L748-L762) |
| Human override layer: `_data/work_queue.yml` manual order and priority overrides, applied in every loop's lane | [work_queue.py L1-L30, L168-L177](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/.github/scripts/dash-gen/work_queue.py#L168-L177) |
| Taxonomy: P0-P3 labels map to the Fleet Project `Priority` field; `agent:queued` → Ready | [framework.yml L29, L47-L58](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/templates/projects/framework.yml#L47-L58), [_data/fleet.yml L344-L354](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/_data/fleet.yml#L344-L354) |
| Priority-driven policy hook: `assisted_priorities` forces human review for chosen priorities | [_data/fleet.yml L330](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/_data/fleet.yml#L330) |
| Re-prioritization signal: idle P0/P1 issues are flagged | [specs/WORK.contract.yml L268-L277](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/specs/WORK.contract.yml#L268-L277) |

### Reproduce

```bash
gh repo clone bamr87/bamr87 /tmp/hub && cd /tmp/hub && git checkout 2321b3a7c1199688042339d68b628f9d08bb46eb
python3 -m pytest -q .github/scripts/dash-gen/test_issue_pipeline.py .github/scripts/dash-gen/test_work_board.py
# queue ordering: test_queues / test_tier3_queue in test_issue_pipeline.py (L288, L344); override file: test_work_queue_file (test_work_board.py L255)
```

Expected: all pass (run 2026-10-31, together with the ADP-11 suite: 56 passed). Live intake and ranking: [issue-pipeline run 41181601564](https://github.com/bamr87/bamr87/actions/runs/41181601564) (success).

## Gaps

1. **Dependencies aren't a criterion.** The queue never reads blocked-by or prerequisite links, so blocked items can be picked and prerequisites get no boost. → [#538](https://github.com/bamr87/bamr87/issues/538) (`agent:queued`).
Scope note (not a gap): ordering in submodules (bashcrawl, rewind-arcade, godotgo) was not checked for this chapter.

## Cross-links

ADP-11 (goals feed the queue), ADP-16 (resource limits), ADP-15/ADP-07 (multi-agent handoff); constitution §9 (work tracking), §15 (evidence).
