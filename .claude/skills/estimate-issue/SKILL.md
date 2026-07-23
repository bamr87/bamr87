---
name: estimate-issue
description: Deep-analyze a GitHub issue into a client-engagement estimate — classify scope, refine the plan (approach/deliverables/acceptance), and record an agent-refined estimate in _data/engagements.yml. Use when asked to "estimate", "quote", "scope", or "price" an issue or a repo's backlog, or to review/refine a draft the estimator produced.
---

# estimate-issue

The estimation loop: `tools/dash estimate` (estimator-v1) drafts deterministic
estimates from labels/titles alone; this skill is the **analysis pass** that
reads the actual issue and codebase and refines scope, plan, and confidence.
Refined estimates are recorded with `method: agent` — mechanical re-runs never
overwrite them. Model + lifecycle: `docs/ESTIMATION.md`.

## Steps

1. Draft first (idempotent, offline):
   `tools/dash estimate --repo <name> --issue <n>` — creates/locates the
   engagement in `_data/engagements.yml` (COMMITTED) with an estimator-v1
   baseline. `--repo` is the registry `name` from `_data/projects.yml`.
2. Read the real work item:
   `gh issue view <n> -R <owner>/<repo> --json title,body,labels,comments`
   and, when the repo is a checked-out submodule, the code the issue touches
   (README-first). Judge true scope: files affected, tests needed, unknowns,
   cross-repo coupling.
3. Refine the engagement entry in `_data/engagements.yml`:
   - `estimate.tier` / `confidence` if the body changes the picture; keep the
     tier's effort/cost numbers consistent with the rate card
     (`_data/engagement_rates.yml`) — recompute, don't invent.
   - `estimate.method: agent` and append your reasoning to `estimate.drivers`
     (e.g. `agent: touches 3 layouts + JS, needs cypress spec -> tier m`).
   - `plan.approach` / `deliverables` / `acceptance` — make them concrete
     enough that delivery is checkable.
4. Settle the books: `tools/dash ledger` (recomputes rollups; use
   `--no-local` if local session costs shouldn't fold in).
5. Present the estimate to the human for approval. NEVER set
   `status: approved` yourself — approval is the broker's signature
   (`tools/dash ledger --set-status ENG-NNNN=approved`).

## Guardrail

Estimates are proposals: this skill may create and refine `estimated` entries
but must not transition status, record broker hours, or touch another
engagement's actuals. No secrets in the register — it is public site data.

## Pairs with

`triage-attention` (pick what to estimate from the inbox) and the daily
`ai-usage.yml` accrual (actuals settle against what you estimated here).
