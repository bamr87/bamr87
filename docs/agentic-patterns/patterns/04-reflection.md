---
id: ADP-04
chapter: 4
title: Reflection
book_pages: "Ch. 4 (13 pp.)"
status: proven
evidence_repos: [bamr87/law-ai]
last_verified: 2026-10-31
owner_bot: Grok Bot
---
# Reflection

## Summary

Reflection adds a feedback loop. An agent produces output, the output is evaluated (by the same model or, better, a separate "critic" role), and the critique goes back in for a revision. This repeats until the output is good enough or a round cap is hit. Gulli frames this as a producer–critic split, and it works best when the critic has a distinct mandate and clear criteria. The cost is more calls, more latency, and more context per round, so loops must be bounded and should stop early once the output is acceptable.

## When to use / not

- **Use** when quality, correctness, or policy compliance matters more than speed (code, legal or educational content), and when objections can be stated concretely.
- **Skip** for latency-critical or low-stakes outputs, or when a deterministic check can verify the result. Use the check instead of an LLM critic.

## Failure modes

- Unbounded loops and runaway cost.
- A critic that rubber-stamps or nitpicks forever.
- Self-critique sharing the producer's blind spots.
- Revision regressing parts that were already correct.
- Loops quietly replacing human review.

## Fleet evidence (`bamr87/law-ai@0870d4c`)

1. **Author → gates → judge → revise loop.** [lsat/factory/revise.py L1-67](https://github.com/bamr87/law-ai/blob/0870d4c56ed495a6fad97af33c79885264522c39/backend/law_ai/lsat/factory/revise.py#L1-L67) defines `DEFAULT_MAX_ROUNDS = 3` and a per-round history (`ReviseRound`: gate issues, judge verdict, critique). `author_with_review` [L132-212](https://github.com/bamr87/law-ai/blob/0870d4c56ed495a6fad97af33c79885264522c39/backend/law_ai/lsat/factory/revise.py#L132-L212) runs deterministic gates and then an adversarial judge, and feeds every objection back as `critique` for the next round. It stops early on acceptance and runs an optional final reviewer. Output goes to the **HITL queue**: the loop "improves what a human is shown, never who decides" (module docstring, citing constitution §5).
2. **Applied to the existing bank.** [lsat/services/rewrite.py L1-14, L174-238](https://github.com/bamr87/law-ai/blob/0870d4c56ed495a6fad97af33c79885264522c39/backend/law_ai/lsat/services/rewrite.py#L174-L238) has the judge review bank items. On an objection it runs the loop and files a pending `rewrite` proposal for a human to promote. The gates include a routing self-check ([L92-97](https://github.com/bamr87/law-ai/blob/0870d4c56ed495a6fad97af33c79885264522c39/backend/law_ai/lsat/services/rewrite.py#L92-L97)): a rewrite whose stem reclassifies to a different archetype is rejected.
3. **Verify-after-revise.** `polish_item` [lsat/synth/polish.py L365-396](https://github.com/bamr87/law-ai/blob/0870d4c56ed495a6fad97af33c79885264522c39/backend/law_ai/lsat/synth/polish.py#L365-L396) re-verifies a model-polished item and keeps the original if verification fails. It records yield in provenance.

### Reproduce

```bash
T=$(mktemp -d) && git clone -q https://github.com/bamr87/law-ai $T/law-ai && cd $T/law-ai && git checkout -q 0870d4c56ed495a6fad97af33c79885264522c39
cd backend && uv sync -q --managed-python -p 3.13 --all-extras --all-groups
uv run --managed-python -p 3.13 pytest -p no:cacheprovider --no-cov -W ignore \
  tests/lsat/test_revise.py tests/core/test_llm_chain.py tests/lsat/test_playbooks.py
```

Expected: `122 passed` (verified 2026-10-31 on the box; no model calls, providers stubbed). Tests: `tests/lsat/test_revise.py` (rounds, cap, critique hand-off, acceptance).

## Gaps

- The lawmode PR reviewer ([pr_reviewer.py L17-41](https://github.com/bamr87/law-ai/blob/0870d4c56ed495a6fad97af33c79885264522c39/lawmode/lawmode/github/pr_reviewer.py#L17-L41)) is single-pass, with no critic round. Filed as **https://github.com/bamr87/law-ai/issues/205** (agent:queued, feature, P3).

## Cross-links

ADP-02 Routing, ADP-13 Human-in-the-Loop, ADP-19 Evaluation & Monitoring; constitution §5 (humans decide), §15 testing evidence.
