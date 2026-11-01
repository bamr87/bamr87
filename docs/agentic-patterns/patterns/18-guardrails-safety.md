---
id: ADP-18
chapter: 18
title: Guardrails / Safety Patterns
book_pages: 286-305 (PDF pages)
status: partial
evidence_repos: [bamr87/bamr87]
last_verified: 2026-10-31
owner_bot: Platform Architect
---
# Guardrails / Safety Patterns

## Summary

Guardrails are layered controls that keep an agent safe, on task and compliant as its autonomy grows. Gulli places them at several layers: input validation and sanitization, output filtering, behavioral constraints set in prompts, tool-use restrictions, external moderation, and human oversight. A cheap, fast model can pre-screen inputs or double-check outputs. Supporting engineering practices include least privilege, checkpoint and rollback, structured logging and observability, and treating guardrails as part of the design rather than an afterthought. The aim is not to cripple the agent but to make its behavior predictable and trustworthy. (Paraphrased from Gulli, Ch. 18.)

## When to use / not

Terms: `§` numbers refer to sections of the fleet's constitution (`docs/constitution.md`), its written governance rules. A kill switch is a setting that stops a scheduled loop without a code change. Prompt injection is untrusted text that tries to give an agent new instructions. The "lethal trifecta" is an agent that combines private data, untrusted input and a way to send data out; any two are tolerable, all three are not. Evals are fixed test sets that score an AI step's output. HITL means human-in-the-loop (ADP-13).


- Always use them in some form. Scale the layers to the risk: public triggers, secrets, external sends and money get the most.

## Failure modes

- A single layer of defense.
- Prompt-only rules.
- Guardrails nobody tests.
- Kill switches that are scattered or undocumented.

## Fleet evidence (`bamr87/bamr87@2321b3a`)

| Sub-aspect | Rating | Evidence |
|---|---|---|
| Input gating on who may trigger an agent | proven | [claude.yml](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/.github/workflows/claude.yml): `@claude` runs only for OWNER/MEMBER/COLLABORATOR `author_association`. Least-privilege `permissions:` (the workflow token gets only contents/issues/PR read) |
| Tool restrictions and budget caps | proven | [claude-run/action.yml](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/.github/actions/claude-run/action.yml): `allowed-tools`, `max-turns`, and `max-budget-usd` defaulting to the fleet `budget.default_usd` (asserted by test_ai_budget.py) |
| Model allowlist / pinning (exact model versions only) | proven | `ai_models.allowed` = claude-opus-5-5 / sonnet-5-5 / haiku-5-5 ([_data/fleet.yml](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/_data/fleet.yml) L1540), policy in §13.3 |
| Action allowlist plus never-list for write-back | proven (policy) | §11.1–11.2 `ALLOWLIST` in tools/console/gh_projects_write.py, which never merges, deletes or touches settings or secrets |
| Behavioral constraints / governance as code (rules checked by a linter, not just written down) | proven | [constitution](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/docs/constitution.md) §2 invariants, §4 roles. [tools/governance_lint.py](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/tools/governance_lint.py) check passes (output below) |
| Kill switches | partial | Per-loop variables gate schedules: `ISSUE_PIPELINE_ENABLED`, `REPO_SCOUT_ENABLED`, `FLEET_PULSE_ENABLED`, `JEV_CONFLICTS_ENABLED`, `REPO_EVOLUTION_ENABLED`, `API_KEYS_ENABLED` (e.g. [issue-pipeline.yml](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/.github/workflows/issue-pipeline.yml) L115). The central `switches:` map (proposed §17, PR #528) is not in fleet.yml yet: #526, PR #528 open, catalog PR #527 merged |
| Human oversight | proven | See ADP-13 (§12 gate, `agent:hold`) |
| Input sanitization for injection / output secret scan / trifecta gate | gap | No code yet. Filed [#531](https://github.com/bamr87/bamr87/issues/531) |
| Guardrail evals (§13.1) | gap | Filed [#530](https://github.com/bamr87/bamr87/issues/530) |

### Reproduce

```bash
python3 tools/governance_lint.py check .
grep -ho "vars\.[A-Z_]*ENABLED" .github/workflows/*.yml | sort -u
grep -n "author_association" .github/workflows/claude.yml
grep -n "switches:" _data/fleet.yml   # no match on main -> the proposed loop-switch amendment (PR #528) is not live
```

Actual output:

```
/tmp/adp-hub: ok (prd=PRD.md, features=features/features.yml, constitution=docs/constitution.md, amendments=13)
  warn:  HUB-039: names no PRD requirement (`prd: [TBD]` if unknown)
vars.API_KEYS_ENABLED vars.FLEET_PULSE_ENABLED vars.ISSUE_PIPELINE_ENABLED vars.JEV_CONFLICTS_ENABLED vars.REPO_EVOLUTION_ENABLED vars.REPO_SCOUT_ENABLED
```

Note: the variables are not uniform in polarity. Issue pipeline runs unless the variable is `'false'`, while repo scout runs only when it is `'true'`. CI: python-tests was green on 8ad8cf5 (https://github.com/bamr87/bamr87/actions/runs/41256529231); the cited files are identical at 2321b3a and the commands were rerun locally there.

## Gaps

- [#531](https://github.com/bamr87/bamr87/issues/531): input/output guardrails and the lethal-trifecta gate.
- [#530](https://github.com/bamr87/bamr87/issues/530): evals.
- #526 / #528 (existing): central kill switches.

## Cross-links

ADP-13, ADP-07, constitution §2, §11, §12, §13; proposed loop-switch amendment (PR #528).
