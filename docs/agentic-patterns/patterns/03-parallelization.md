---
id: ADP-03
chapter: 3
title: Parallelization
book_pages: 50-64
status: proven
evidence_repos: [bamr87/bamr87]
last_verified: 2026-10-31
owner_bot: Tools
---
# Parallelization

## Summary
Parallelization runs independent sub-tasks (LLM calls, tool calls, whole sub-agents) at the same time instead of one after another, then merges results in a later step. Gulli frames it as the fix for latency when a workflow has steps that don't depend on each other: fan out (e.g. research several sources, evaluate several candidates), then fan in to aggregate or synthesize. It pairs with routing (pick branches) and with reflection/voting (compare parallel outputs). Frameworks express it as parallel branches in a graph or async gather; CI systems express it as matrix jobs.

## When to use / not
- Use: independent lookups, per-item processing over many repos/services, multiple drafts for A/B or voting.
- Avoid: steps with data dependencies, shared mutable state, tight rate limits, or when cost matters more than latency.

## Failure modes
One branch failing strands the rest; unbounded fan-out hits rate limits; non-deterministic merge order; aggregation step silently dropping failed branches.

## Fleet evidence
1. **Matrix fan-out of agent jobs, bounded and failure-isolated.** `.github/workflows/repo-scout.yml` L194-197: one scout agent job per repo, `fail-fast: false`, `max-parallel` from the plan job, then a fan-in summary job. Same shape in `repo-evolution.yml` L198-199. https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/.github/workflows/repo-scout.yml#L194-L197 · green run: https://github.com/bamr87/bamr87/actions/runs/41169651906
2. **Concurrent probes with fan-in.** `tools/fleet_smoke.py` L408-412: `ThreadPoolExecutor(max_workers=6)` + `as_completed` over all services. https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/tools/fleet_smoke.py#L408-L412

Reproduce:
```bash
git clone --depth 1 https://github.com/bamr87/bamr87 && cd bamr87 && git checkout 2321b3a7c1199688042339d68b628f9d08bb46eb 2>/dev/null || true
sed -n 190,200p .github/workflows/repo-scout.yml   # expect fail-fast: false / max-parallel / matrix
grep -n ThreadPoolExecutor tools/fleet_smoke.py      # expect L408
gh run view 41169651906 -R bamr87/bamr87             # expect: completed success, N parallel scout jobs
```

## Gaps
None. Future work (not a gap, no issue): an in-process LLM-call fan-out example (async gather of model calls) — bashOS hard rule 1 forbids loops in bashOS, so it would belong in the engine layer.

## Cross-links
ADP-02 Routing, ADP-04 Reflection, ADP-16 Resource-aware optimization; constitution §15 (testing evidence), #528 kill switches.
