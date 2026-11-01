---
id: ADP-17
chapter: 17
title: Reasoning Techniques
book_pages: "Ch. 17 (~24 pp.), book.txt L10098-11030"
status: partial
evidence_repos: [bamr87/bamr87]
last_verified: 2026-10-31
owner_bot: executor (Grok Bot)
---
# Reasoning Techniques

## Summary

This chapter is a catalog of ways to let a model think harder on harder problems. Chain-of-Thought asks the model to write out its steps. Tree-of-Thought tries several branches, scores them and backs up from dead ends. Self-correction has the model critique and fix its own draft. Program-aided models hand the math to real code. Reasoning models are trained (with RLVR, reinforcement learning from answers that can be checked) to think at length before they answer. ReAct alternates thinking, calling a tool and reading the result. Multi-agent debate (CoD/GoD) has several agents argue toward an answer. MASS searches automatically for better prompts and agent layouts. The chapter also notes a scaling rule: a smaller model given more thinking time can match a larger one. The book's point is that more time to think allows "thorough debugging" and "adjusting plans based on real-time feedback (ReAct)" (Ch. 17 intro).

## When to use / not

- Use: multi-step, verifiable tasks (code, math, triage); escalate compute only when cheap tiers fail.
- Avoid: explicit "think step by step" on native reasoning models (see cross-check); latency-critical paths.

## Failure modes

- Overthinking (cost without accuracy).
- Unfaithful rationales.
- Self-critique that rubber-stamps.
- ReAct loops without turn caps.

## Fleet evidence (`bamr87/bamr87@2321b3a`)

| Technique | Permalink |
|---|---|
| Inference-scaling ladder: tier0 deterministic → tier1 Haiku (8 turns) → tier2 Sonnet (24 turns) → tier3 human | [_data/fleet.yml L619-631](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/_data/fleet.yml#L619-L631), [tools/jev/conflicts.py L328, L401](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/tools/jev/conflicts.py#L328) |
| PAL-style: deterministic tier0 + `classify.py` triage before any model | [tools/jev/classify.py L229](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/tools/jev/classify.py#L229) |
| ReAct with bounded turns (agent loops, max_turns 40/120) | [_data/fleet.yml L414, L440, L471](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/_data/fleet.yml#L414) |
| Self-correction via external verifier: post-resolution validation tests | `tools/test_jev_conflicts.py` (test_validation_*) |

### Reproduce

```bash
cd /tmp/hub && git checkout 2321b3a7c1199688042339d68b628f9d08bb46eb
python3 tools/test_jev_classify.py   # expect 13/13 passed
python3 tools/test_jev_conflicts.py  # expect 20/20 passed
```

Verified locally 2026-10-31 (13/13, 20/20). Live runs: [jev-conflicts 41258398529](https://github.com/bamr87/bamr87/actions/runs/41258398529) success (2026-10-31 18:48 MDT).

## Gaps

1. **GAP – JEV tiers pin models outside the allow-list**: tier1 `claude-haiku-4-5-20251001`, tier2 `claude-sonnet-5` (fleet.yml L623, L628) vs `ai_models.allowed` = opus/sonnet/haiku-5-5 (L1541-1545). Standards/§12.3 gated → needs-amr. → [#540](https://github.com/bamr87/bamr87/issues/540) (`agent:queued`, `needs-amr`).
2. **GAP – no reasoning-effort / thinking-budget knob per call site**; depth is controlled only by turns and model. Budget item. → [#544](https://github.com/bamr87/bamr87/issues/544) (`agent:queued`, `needs-amr`).
3. **GAP (tracked)** – no self-critique/debate pass on agent PRs; covered by open [#492 QA Lead completeness-review](https://github.com/bamr87/bamr87/issues/492) — already tracked.
4. ToT/MASS search: not implemented; low value until evals exist; blocked on ([#530](https://github.com/bamr87/bamr87/issues/530)).

## Current-source cross-check

- **Outdated-ish**: CoT prompting as default advice. For native reasoning models explicit CoT gives marginal gains at high token cost — [Prompting Science Report 2, arXiv 2506.07142](https://arxiv.org/pdf/2506.07142); CoT helps mainly math/symbolic — [arXiv 2409.12183](https://arxiv.org/html/2409.12183v1). Use effort/thinking-budget parameters instead.
- Scaling-inference law: holds with diminishing returns; overthinking documented — [ACL Findings 2026](https://aclanthology.org/2026.findings-acl.1285.pdf).

## Cross-links

ADP-16 Resource-aware (tier routing), ADP-19 Evaluation (#530), ADP-09 Learning; constitution §12 review gate, §13 models.
