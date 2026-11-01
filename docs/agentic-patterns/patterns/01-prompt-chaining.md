---
id: ADP-01
chapter: 1
title: Prompt Chaining
book_pages: "Ch. 1 (12 pp.)"
status: partial
evidence_repos: [bamr87/bamr87]
last_verified: 2026-10-31
owner_bot: Content & Comms
---
# Prompt Chaining (Pipeline)

## Summary

Don't ask a model to do a big, many-part job in one prompt. Split it into a short line of focused steps, and pass each step's output into the next one. Each step does one thing, so it is easier to write, test and debug. Between steps you can run normal code: check the output, reshape it, or call a tool. Gulli calls it a "divide-and-conquer strategy" that improves "the reliability and control of the output" (book ch. 1, Conclusion). One big prompt tends to fail in known ways: it skips instructions, loses track of the context, carries early mistakes forward, and makes things up when it is overloaded. A chain fixes these by keeping each step small and by putting a check point between steps. You can also give each step its own role, such as analyst, then writer.

## When to use / not

- Use it when the job has clear stages, needs tool or data calls between stages, or needs a check before the next stage starts.
- Skip it when one short prompt does the job well. Every extra step adds delay, cost and one more place to fail. Also skip it when the steps don't depend on each other. Run those in parallel instead (ADP-03).

## Failure modes

- A step's output is free text with no fixed format, so the next step misreads it.
- Errors carry through the chain because nothing checks them between steps.
- Context grows at every step until the "focused" prompts aren't focused anymore.
- No stop condition: a step runs even after the step before it was refused or ran out of budget.

## Fleet evidence (commit 2321b3a7c1199688042339d68b628f9d08bb46eb)

The hub's **Issue Pipeline** is a working four-step chain that turns an open issue into a merge-ready PR. Steps: scan (no AI), then tier 1 intake, then tier 2 implement, then tier 3 complete.

| Behavior | Permalink |
|---|---|
| Chain design: each step's job and the deterministic first step | [issue-pipeline.yml L1-32](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/.github/workflows/issue-pipeline.yml#L1-L32) |
| Steps are linked with `needs:` (tier2 needs scan and tier1; tier3 needs all three) | [L545](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/.github/workflows/issue-pipeline.yml#L545), [L784](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/.github/workflows/issue-pipeline.yml#L784) |
| Handoff between steps: a label (`agent:ready` / `agent:blocked`) plus a work order and evidence bundle | [L11-20](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/.github/workflows/issue-pipeline.yml#L11-L20), [L276-319](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/.github/workflows/issue-pipeline.yml#L276-L319) |
| Gate: tier 2 stops when tier 1 hit the usage limit | [L249-253](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/.github/workflows/issue-pipeline.yml#L249-L253), [L546-549](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/.github/workflows/issue-pipeline.yml#L546-L549) |
| Each step gets its own narrow tool list and a turn cap | [L371-373](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/.github/workflows/issue-pipeline.yml#L371-L373), [L647](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/.github/workflows/issue-pipeline.yml#L647), [L858](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/.github/workflows/issue-pipeline.yml#L858) |
| Each step can run as a named role (`.claude/agents/<name>.md`) | [claude-run/action.yml L38-43](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/.github/actions/claude-run/action.yml#L38-L43) |

### Reproduce

```bash
git clone --depth 1 https://github.com/bamr87/bamr87 /tmp/hub && cd /tmp/hub   # HEAD was 2321b3a7c1 on 2026-10-31
grep -n "needs:" .github/workflows/issue-pipeline.yml      # scan -> tier1 -> tier2 -> tier3
python3 -m pytest -q tools/test_pipeline_map.py tools/test_work_contract.py
gh run view 41181601564 -R bamr87/bamr87 --json jobs -q '.jobs[]|"\(.name) \(.conclusion)"'
```

Verified 2026-10-31 (MDT):

- pytest: **7 passed**.
- Run [41181601564](https://github.com/bamr87/bamr87/actions/runs/41181601564) (2026-10-31 01:41 MDT): all four steps **success**. Scan, Tier 1 intake & evidence, Tier 2 implement & open draft PR, and Tier 3 complete & ready for review.
- The five daily runs before it (Oct 26-30) were also green.

## Gaps

- The handoff between steps is a label plus free-text prose. Nothing machine-checks tier 1's output against a schema before tier 2 starts. The book's advice to use structured output between steps isn't applied. Filed as [#534](https://github.com/bamr87/bamr87/issues/534) (agent:queued).
- Related open issue: [#348](https://github.com/bamr87/bamr87/issues/348) (a 429 error kills tiers 2-3). This is a reliability issue in the chain, not a missing contract.

## Cross-links

- ADP-02 Routing: scan sorts issues into steps.
- ADP-03 Parallelization: the fan-out workflow.
- ADP-12 Exception Handling: the claude-run fallbacks.
- ADP-16 Resource-Aware: turn and dollar caps.
- ADP-19 Evaluation.
- Constitution §15 (testing evidence), #528 (kill switches), [#526](https://github.com/bamr87/bamr87/issues/526).
