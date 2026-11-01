---
id: ADP-19
chapter: 19
title: Evaluation and Monitoring
book_pages: "Ch. 19 (18 pp.)"
status: partial
evidence_repos: [bamr87/bamr87]
last_verified: 2026-10-31
owner_bot: executor (Grok Bot)
---
# Evaluation and Monitoring

## Summary

An agent is only as trustworthy as the evidence that it still works. This pattern pairs **offline evaluation** (fixed test sets, trajectory checks, LLM-as-judge, regression gates on every prompt/model change) with **online monitoring** (latency, cost, error rates, drift, alerting) so degradation is caught rather than discovered. The book stresses tracking performance, cost and compliance continuously and evaluating the agent's trajectory, not only its final answer (ch. 19). Results should feed back into gates that block bad changes.

## When to use / not

- Use: any agent that changes over time (prompts, models, tools) or runs unattended.
- Avoid: vanity dashboards with no gate or owner.

## Failure modes

- Monitors that crash silently.
- Evals defined in policy but never built.
- Cost metrics presented as invoices.

## Fleet evidence (commit 2321b3a7c1199688042339d68b628f9d08bb46eb)

| Behavior | Permalink / workflow |
|---|---|
| Drift gate (runs budget + python tests) | [drift-check.yml](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/.github/workflows/drift-check.yml); green run [41256758338](https://github.com/bamr87/bamr87/actions/runs/41256758338) |
| Fleet conformance scoring | [conformance.yml](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/.github/workflows/conformance.yml), [tools/conformance.py](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/tools/conformance.py); green run [41080860256](https://github.com/bamr87/bamr87/actions/runs/41080860256) |
| Spec gate (backlog/spec consistency, stale report) | [spec-gate.yml L29-62](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/.github/workflows/spec-gate.yml#L29-L62) (reusable; no hub run listed) |
| Daily key health monitor + single open alert issue | [api-keys.yml L1-30](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/.github/workflows/api-keys.yml#L1-L30) |
| Fleet doctor / pulse with spend + budget_hit outputs | [fleet-pulse.yml L490-493](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/.github/workflows/fleet-pulse.yml#L490-L493); green run [41173476332](https://github.com/bamr87/bamr87/actions/runs/41173476332) |
| Structured activity events (start/finish/retry/declined) | [fleet_activity.py L22-60](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/tools/fleet_activity.py#L22-L60) |
| Eval policy (rerun on change, required check) | [constitution §13 L137-142](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/docs/constitution.md#L137-L142), [amendment 0011](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/docs/amendments/0011-eval-baseline-risk-tiers.md) |

### Reproduce

```bash
cd /tmp/hub && git checkout 2321b3a7c1199688042339d68b628f9d08bb46eb
python3 -m pytest -q tools/test_conformance_work.py
gh run list -R bamr87/bamr87 -w drift-check.yml -L 1
```

Expected: tests pass (verified 2026-10-31); latest drift-check `success`.

## Gaps

1. **§13 eval sets don't exist**: no eval directory or eval CI check for any AI call site (searched repo, 2026-10-31). → Already tracked: [#530](https://github.com/bamr87/bamr87/issues/530) (found on pre-filing dedupe; not refiled). Related: #492, #495.
2. Monitor health: API Key Watch red — [#522](https://github.com/bamr87/bamr87/issues/522). Telemetry pipeline in progress — #446-#451.

## Cross-links

ADP-12, ADP-16; constitution §13, §15 testing evidence.
