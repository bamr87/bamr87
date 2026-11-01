---
id: ADP-07
chapter: 7
title: Multi-Agent Collaboration
book_pages: 113-131 (PDF pages)
status: partial
evidence_repos: [bamr87/bamr87]
last_verified: 2026-10-31
owner_bot: Platform Architect
---
# Multi-Agent Collaboration

## Summary

Some problems are too broad for one monolithic agent. Multi-agent collaboration splits the work across specialized agents, each with its own role, tools and context, and coordinates them through a defined protocol. Gulli lists several topologies: sequential handoffs, parallel workers, debate and consensus, hierarchical supervisor/worker, critic/reviewer pairs, and agents exposed as tools to other agents. The gains are modularity, specialization and robustness. The costs are coordination overhead, error propagation between agents, and harder debugging, so communication contracts and observability are essential. (Paraphrased from Gulli, Ch. 7.)

## When to use / not

Terms: `§` numbers refer to sections of the fleet's constitution (`docs/constitution.md`), its written governance rules. JEV is the fleet's agent logic engine (`tools/jev`). QA Lead is a planned reviewer bot that checks major PRs for completeness (#492). A2A (agent-to-agent) is an open protocol for agents to discover and call each other; an Agent Card is its published description of one agent. AIEO is the planned AI-readiness validator (#495). HITL means human-in-the-loop (ADP-13).


- Use when the subtasks need different expertise, tools or permissions, or can run in parallel.
- Avoid when a single agent with a few tools is enough. Every handoff is a new place to fail.

## Failure modes

- Agents racing on shared state.
- Unclear ownership.
- Cascading hallucinations.
- Runaway cost.

## Fleet evidence (`bamr87/bamr87@2321b3a`)

| Sub-aspect | Rating | Evidence |
|---|---|---|
| Specialized roles with a sequential handoff | proven | Issue pipeline tier 1 (T1) intake → tier 2 (T2) implement → tier 3 (T3) complete, where each tier hands a structured evidence bundle to the next ([docs/ISSUE-PIPELINE.md](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/docs/ISSUE-PIPELINE.md)). Green runs: [41181601564](https://github.com/bamr87/bamr87/actions/runs/41181601564) |
| Shared coordination state via labels (a "blackboard" every agent reads and writes) | proven | The label state machine (`agent:queued`, `agent:ready`, `agent:in-pr`, `agent:hold` …) is defined in [issue_pipeline.py](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/.github/scripts/dash-gen/issue_pipeline.py) (label map around L83–L129). Tests: test_issue_pipeline.py |
| Producer agents feeding the queue (scout, deep-dive, fleet-pulse) | proven | Repo scout files proposals into intake ([docs/SCOUT.md](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/docs/SCOUT.md)). The deep-dive rotation picks one repo per day ([tools/deep_dive.py](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/tools/deep_dive.py)): `today` printed `cycle 1 day 2/42 scheduled: bamr87` |
| Concurrency control between agents | proven | `concurrency: claude-<thread>` in [claude.yml](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/.github/workflows/claude.yml) serializes runs per thread. `concurrency: jev-number` serializes id assignment ([docs/JEV.md](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/docs/JEV.md)) |
| Critic/reviewer agent | partial | §15.5 requires completeness review by JEV and QA Lead, where the author never reviews its own work. QA Lead isn't built yet (#492), so the review is warn-only with Amr as fallback ([constitution §15](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/docs/constitution.md)) |
| Cost-tiered delegation (try the cheapest model first) | proven | JEV conflict tiers 0–3 with a cheap-model envelope ([tools/jev/classify.py](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/tools/jev/classify.py)) |
| Interop protocol (A2A agent card) and per-role evals | gap | §16.4 requires an A2A Agent Card, tracked under AIEO #495. §13.1 role eval sets don't exist yet, filed as [#530](https://github.com/bamr87/bamr87/issues/530) |

### Reproduce

```bash
python3 tools/deep_dive.py today --date 2026-10-31
python3 -m pytest -q tools/test_deep_dive.py tools/test_governance_lint.py tools/test_pin_policy.py tools/test_fleet_ci_gate.py .github/scripts/dash-gen/test_scout.py .github/scripts/dash-gen/test_work_board.py
```

Actual output:

```
2026-10-31  cycle 1 day 2/42  scheduled: bamr87
45 passed in 0.87s
```

CI: python-tests was green on 8ad8cf5 (https://github.com/bamr87/bamr87/actions/runs/41256529231); the cited files are identical at 2321b3a and the commands were rerun locally there.

## Gaps

- [#530](https://github.com/bamr87/bamr87/issues/530): eval sets per agent role, plus an eval-regression check (shared with Fleet Ops ADP-19 G19-1).
- #492 (existing): build the QA Lead critic agent.
- #495 (existing): AIEO / A2A agent card.

## Cross-links

ADP-06 Planning, ADP-13 HITL, ADP-18 Guardrails, constitution §12, §13, §15, §16.
