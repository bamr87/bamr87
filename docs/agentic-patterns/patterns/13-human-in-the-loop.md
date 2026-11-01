---
id: ADP-13
chapter: 13
title: Human-in-the-Loop
book_pages: 204-212 (PDF pages)
status: partial
evidence_repos: [bamr87/bamr87]
last_verified: 2026-10-31
owner_bot: Platform Architect
---
# Human-in-the-Loop

## Summary

Human-in-the-loop (HITL) deliberately combines human judgment with an agent's speed. In complex, ambiguous or high-stakes domains, full autonomy is imprudent, so people act as validators, escalation targets, labelers or co-decision-makers. Common mechanisms include review and approval queues, escalation when confidence is low or the action is risky, and feedback that improves the agent over time. The caveats Gulli notes are that HITL doesn't scale linearly, depends on the quality of the human reviewer, and can raise privacy concerns. "Human-on-the-loop", where a human sets the policy and the agent executes it, is a lighter variant. (Paraphrased from Gulli, Ch. 13.)

## When to use / not

Terms: `§` numbers refer to sections of the fleet's constitution (`docs/constitution.md`), its written governance rules. `needs-amr` is the label that marks a decision only Amr (the maintainer) can make. `agent:hold` and `human-review` are labels the issue pipeline obeys. QA Lead is a planned reviewer bot (#492). "Earned autonomy" means an agent gets more freedom only after a track record on lower-risk work.


- Use for irreversible, external, money, security or governance actions, and for anything ambiguous.
- Avoid for routine reversible steps, where a human gate only adds latency. Earn autonomy instead.

## Failure modes

- Rubber-stamp fatigue.
- Gates that agents can bypass.
- Unclear ownership of who approves.

## Fleet evidence (`bamr87/bamr87@2321b3a`)

| Sub-aspect | Rating | Evidence |
|---|---|---|
| Human approval gate on high-risk changes | proven (policy) | §12.3–12.5 review gate: `needs-amr` label, the maintainer alone removes it, and agents never merge gated PRs ([constitution](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/docs/constitution.md)) |
| Per-item human brakes | proven | `agent:hold` excludes an issue from every tier. `human-review` leaves the PR as a draft ([docs/ISSUE-PIPELINE.md](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/docs/ISSUE-PIPELINE.md) "The two human brakes"; [issue_pipeline.py](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/.github/scripts/dash-gen/issue_pipeline.py)). Live: #486 and #523–#526 carry `agent:hold` |
| Forced escalation by category | proven | `issue_pipeline.autonomy`: `never_merge: true`, and `assisted_types: [security]` / `assisted_sizes: [size:xl]` ([_data/fleet.yml](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/_data/fleet.yml) L325–330) |
| Human sets priority (human-on-the-loop) | proven | [_data/work_queue.yml](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/_data/work_queue.yml) `order:` overrides the computed priority |
| Dry run, then human confirmation, before writing back to GitHub | proven (policy+code) | §11.4: a write returns a plan (`plan_id`) and runs only after confirm; the `HARNESS_PROJECTS_WRITES` setting is off by default (constitution §11) |
| Risk tiers + earned autonomy (§13.6–13.7) | gap | Only the policy text exists, with no registry or enforcement code (`grep -rn risk_tier tools .github` returns nothing). Filed [#529](https://github.com/bamr87/bamr87/issues/529) |
| Bot reviewer (QA Lead) with Amr as fallback | partial | §15.5 interim bridge: until QA Lead exists, Amr reviews in its place. #492 is open |

### Reproduce

```bash
sed -n 69,76p docs/ISSUE-PIPELINE.md
sed -n 325,330p _data/fleet.yml
gh issue view 486 -R bamr87/bamr87 --json labels -q '[.labels[].name]'
python3 -m pytest -q .github/scripts/dash-gen/test_issue_pipeline.py
```

Output observed: the brakes table (`agent:hold` / `human-review`), `never_merge: true`, and #486 labels `agent:hold,feature,P2,size:l`. The pipeline tests are part of the "61 passed" run in ADP-06. CI: python-tests was green on 8ad8cf5 (https://github.com/bamr87/bamr87/actions/runs/41256529231); the cited files are identical at 2321b3a and the commands were rerun locally there.

## Gaps

- [#529](https://github.com/bamr87/bamr87/issues/529): risk-tier registry and earned-autonomy enforcement.
- #492 (existing): QA Lead.

## Cross-links

ADP-18 Guardrails, ADP-07, constitution §4, §11, §12, §13, §15.
