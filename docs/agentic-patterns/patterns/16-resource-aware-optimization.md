---
id: ADP-16
chapter: 16
title: Resource-Aware Optimization
book_pages: "Ch. 16 (15 pp.)"
status: partial
evidence_repos: [bamr87/bamr87]
last_verified: 2026-10-31
owner_bot: executor (Grok Bot)
---
# Resource-Aware Optimization

## Summary

Agents spend money, tokens, time and compute. This pattern treats those limits as inputs to every decision. Send simple work to cheaper, faster models and hard work to stronger ones. Cap what one run can spend. Fall back to another option when the preferred one is unavailable. Trim the context so the model reads only what it needs. The book's examples include a router agent that picks between models, and a backup model that takes over when the main one fails (ch. 16). Its takeaway is that agents can "manage computational, temporal, and financial resources" on purpose. Good setups write the caps down as configuration, test them and make them visible, instead of scattering one-off constants through the code.

## When to use / not

- Use: any recurring or unattended LLM spend; shared CI minutes; subscription throughput ceilings.
- Avoid: tiering down without evidence that quality holds.

## Failure modes

- Caps that bound turns but not dollars.
- Unpriced proxies (wall-clock) mistaken for cost.
- Caps drifting from the code.

## Fleet evidence (`bamr87/bamr87@2321b3a`)

| Behavior | Permalink |
|---|---|
| Declarative per-call-site dollar caps + derivation rule (usd_per_turn 0.15) | [_data/fleet.yml L500-551](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/_data/fleet.yml#L500-L551) |
| Monthly ceilings: $200 AI, 40k billed Actions min ($0 net) | [_data/fleet.yml L745-748](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/_data/fleet.yml#L745-L748) |
| Pinned model tiers opus/sonnet/haiku-5-5; cheaper only if evals pass | [_data/fleet.yml L1534-1545](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/_data/fleet.yml#L1534-L1545), [constitution §13 L137-142](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/docs/constitution.md#L137-L142) |
| Caps enforced in workflows | [claude.yml L87](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/.github/workflows/claude.yml#L87), [fanout.yml L371](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/.github/workflows/fanout.yml#L371), [fleet-pulse.yml L386-388](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/.github/workflows/fleet-pulse.yml#L386-L388) |
| Test that every call site carries a cap ≥ usd_per_turn×max_turns | [test_ai_budget.py](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/.github/scripts/dash-gen/test_ai_budget.py) |
| Budget abort is a classified failure | [run.sh L231](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/.github/actions/claude-run/run.sh#L231) |
| Time budgets: timeout-minutes / cancel-in-progress on every workflow | `grep -n "timeout-minutes\|cancel-in-progress" .github/workflows/*.yml` |

### Reproduce

```bash
cd /tmp/hub && git checkout 2321b3a7c1199688042339d68b628f9d08bb46eb
python3 -m pytest -q .github/scripts/dash-gen/test_ai_budget.py
```

Expected: all pass (verified 2026-10-31). Also run by the drift gate: [Drift check run 41256758338](https://github.com/bamr87/bamr87/actions/runs/41256758338) (success).

## Gaps

1. **No dynamic router / tier-down**: the model is pinned per step; a `model` class failure (run.sh L235) or quota hit does not fall back to a cheaper allowed tier. Blocked on eval sets ([#530](https://github.com/bamr87/bamr87/issues/530)). → Issue: https://github.com/bamr87/bamr87/issues/533.
2. PRD $75 vs fleet.yml $200 ceiling contradiction — tracked [#502](https://github.com/bamr87/bamr87/issues/502).

## Cross-links

ADP-12, ADP-19; constitution §13 (eval-baseline-risk-tiers), §12.3 gated changes.
