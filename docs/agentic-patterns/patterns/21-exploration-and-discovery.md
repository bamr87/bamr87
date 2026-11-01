---
id: ADP-21
chapter: 21
title: Exploration and Discovery
book_pages: "Ch. 21 (13 pp.), book.txt L13102-13620"
status: partial
evidence_repos: [bamr87/bamr87]
last_verified: 2026-10-31
owner_bot: executor (Grok Bot)
---
# Exploration and Discovery

## Summary

Beyond optimizing a known process, an exploring agent proactively looks for "unknown unknowns" (Ch. 21, Rule of thumb): it samples unfamiliar territory, generates hypotheses, runs experiments, and reports novel findings. The book's exemplars are Google Co-Scientist (generate → debate/tournament → evolve hypotheses under a supervisor) and Agent Laboratory (role agents for literature review, experimentation, report writing). Key mechanics: a prioritised frontier, diversity (avoid re-exploring the same area), an evaluator/tournament to rank finds, and a human who decides what to pursue.

## When to use / not

- Use: open-ended or fast-changing domains; backlog discovery; research ideation.
- Avoid: well-specified tasks (use planning/optimization); when you cannot absorb the findings (backpressure).

## Failure modes

- Noise floods (too many low-value finds).
- Duplicate discoveries.
- Exploration that writes to production.
- Hallucinated novelty without citations.

## Fleet evidence (`bamr87/bamr87@2321b3a`)

| Behavior | Permalink |
|---|---|
| Proactive discovery loop: deterministic plan → read-only scout agent → validated, deduped, capped filing | [.github/workflows/repo-scout.yml L1-40](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/.github/workflows/repo-scout.yml#L1-L40) |
| Frontier + diversity: fixed rotation sample=2/day, per-repo backpressure, kill switch default off | [_data/fleet.yml L430-446](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/_data/fleet.yml#L430-L446) |
| Code-writing explorer (Agent-Lab-like, draft PRs only) | [.github/workflows/repo-evolution.yml L7-46](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/.github/workflows/repo-evolution.yml#L7-L46) |
| In-session idea capture (feature-scout Stop hook) | [.claude/hooks/future_features_scout.py L1-15](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/.claude/hooks/future_features_scout.py#L1-L15) |

### Reproduce

```bash
cd /tmp/hub && git checkout 2321b3a7c1199688042339d68b628f9d08bb46eb
python3 .github/scripts/dash-gen/test_scout.py   # expect "OK — repo-scout fixture tests"
gh run view 41169651906 -R bamr87/bamr87 --json jobs --jq '.jobs[]|[.name,.conclusion]|@tsv'
```

Verified 2026-10-31: fixture tests OK; [repo-scout run 41169651906](https://github.com/bamr87/bamr87/actions/runs/41169651906) (2026-10-30 22:42 MDT) all 4 jobs success (plan, cv-pro, djangoerp, file).

## Gaps

1. **GAP – no ranked/novelty exploration**: sampling is a fixed rotation; no prioritisation by signal value, no tournament/critic ranking of proposals, no outward scan (upstream releases, ecosystem changes) for unknown unknowns. → [#545](https://github.com/bamr87/bamr87/issues/545) (`agent:queued`).
2. **GAP – scout uses model alias `sonnet`** (fleet.yml L441) contrary to "exact versions only, never aliases" (L1535-1538). Folded into [#540](https://github.com/bamr87/bamr87/issues/540).

## Current-source cross-check

- Co-Scientist: book cites the 2025 research preview; now **published in Nature and rolling out as "Hypothesis Generation" (May 19 2026)**, enterprise still restricted preview — [DeepMind blog](https://deepmind.google/blog/co-scientist-a-multi-agent-ai-partner-to-accelerate-research/), [Google Cloud docs](https://docs.cloud.google.com/gemini/enterprise/docs/co-scientist). Book status **outdated**.
- AlphaEvolve-based "Computational Discovery" added (Google I/O 2026) — [blog.google](https://blog.google/innovation-and-ai/technology/research/gemini-for-science-io-2026/).

## Cross-links

ADP-09 Learning (evolution loop), ADP-17 Reasoning (debate/tournament), ADP-19 Evaluation; constitution §10 DevOps, #528 kill switches.
