---
id: ADP-09
chapter: 9
title: Learning and Adaptation
book_pages: "Ch. 9 (12 pp.), book.txt L5971-6360"
status: partial
evidence_repos: [bamr87/bamr87]
last_verified: 2026-10-31
owner_bot: executor (Grok Bot)
---
# Learning and Adaptation

## Summary

An agent that never changes after it ships gets worse as the world around it changes. This pattern adds a feedback loop, so results feed back into how the agent behaves next time. The change can live in three places. It can live in the model's weights, through training methods such as reinforcement learning (RL, PPO) or preference tuning (DPO). It can live in the context, through worked examples in the prompt (few-shot) or saved memories. Or it can live in the agent's own code, where the agent edits itself and an evaluator scores each version (the book's examples are SICA and AlphaEvolve/OpenEvolve). The book frames adaptation as "the visible change in an agent's behavior or knowledge that comes from learning" (Ch. 9, Key Takeaways). A fleet like this one does not train its own models. For it, the practical forms are rules and memory that are updated after incidents, and self-edits that only land after an evaluator approves them.

## When to use / not

- Use: dynamic environments, recurring failure classes, personalization, problems with an objective scorer (AlphaEvolve needs a scoring function).
- Avoid: no trustworthy evaluator; safety-critical paths where self-modification can't be reviewed.

## Failure modes

- Reward hacking / overfitting the scorer.
- Silently accumulating bad "lessons".
- Self-edits without review.
- Drift no one measures.

## Fleet evidence (`bamr87/bamr87@2321b3a`)

| Behavior | Permalink |
|---|---|
| Ratchet: every failure becomes a permanent fix at the strongest rung (guide rule → sensor → environment) | [docs/HARNESS.md L145-152](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/docs/HARNESS.md#L145-L152) |
| Incident-derived standing rules (memory-based learning) | [AGENTS.md L78-94](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/AGENTS.md#L78-L94) |
| Postmortem → trip wire (`stale-data`) | [docs/HARNESS.md L17](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/docs/HARNESS.md#L17), lessons in [docs/DAILY-ANALYSIS.md L152-156](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/docs/DAILY-ANALYSIS.md#L152-L156) |
| Self-improvement loop (SICA-like, human-gated): weekly draft PRs per auto_evolve repo, one-open-PR backpressure | [.github/workflows/repo-evolution.yml L7-46](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/.github/workflows/repo-evolution.yml#L7-L46) |

### Reproduce

```bash
gh api repos/bamr87/bamr87/contents/docs/HARNESS.md?ref=2321b3a7c1199688042339d68b628f9d08bb46eb --jq .content | base64 -d | sed -n '145,152p'
gh run list -R bamr87/bamr87 -w repo-evolution.yml -L 3
```

Expected: ratchet table; latest repo-evolution run success — [run 40310186222](https://github.com/bamr87/bamr87/actions/runs/40310186222) (2026-10-26 04:47 MDT, success).

## Gaps

1. **GAP – no closed outcome loop**: merged/closed/reverted results of agent PRs (evolution, doctor, issue-pipeline) are not fed back into prompts or a lessons store; learning is manual (ratchet by humans). Dedupe: no matches for "outcome feedback learning" / "lessons memory agent" (open+closed). → [#539](https://github.com/bamr87/bamr87/issues/539) (`agent:queued`; overlaps [#535](https://github.com/bamr87/bamr87/issues/535) from ADP-00).
2. **GAP – no evaluator-gated self-modification** (AlphaEvolve-style scored candidates); depends on eval sets (ADP-19). → blocked on [#530](https://github.com/bamr87/bamr87/issues/530); the outcome record it needs is [#539](https://github.com/bamr87/bamr87/issues/539).

## Current-source cross-check

- AlphaEvolve: book presents it as a Google research agent; it is now **GA on Google Cloud (Jul 9 2026)**, default model gemini-4-argon since Oct 26 2026 — [Google Cloud blog](https://cloud.google.com/blog/products/ai-machine-learning/alphaevolve-is-available-for-everyone), [API ref](https://docs.cloud.google.com/gemini/enterprise/docs/alphaevolve/reference-guide/api-reference). **Outdated** framing.
- SICA (arXiv 2504.15228) and PPO/DPO descriptions: still accurate as concepts.

## Cross-links

ADP-19 Evaluation (scorer prerequisite), ADP-12 Exception handling (incident source), ADP-21 Exploration (repo-scout); constitution §13 (models/evals), §15 testing evidence.
