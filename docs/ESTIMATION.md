# Engagement estimation & cost tracking

The dash's delivery-finance layer: every registry project is treated as a
**client**, every analyzed work item becomes an **engagement** — a statement
of work with a deterministic estimate, a plan, evidence-accrued actuals, and
a variance that closes the loop. Rendered at `/engagements/`; stored in
[`_data/engagements.yml`](../_data/engagements.yml); priced by the rate card
[`_data/engagement_rates.yml`](../_data/engagement_rates.yml); implemented in
[`.github/scripts/dash-gen/engagements.py`](../.github/scripts/dash-gen/engagements.py).

## Why

IT estimation is traditionally near-impossible to do accurately, so quotes get
inflated, change orders pile up, and client/consultant trust erodes. Two things
change when AI performs the implementation:

1. **The estimate becomes a reproducible function.** Same work-item facts +
   same rate card + same calibration history → the same number, every time.
   There is nothing to negotiate about how the quote was produced — argue with
   the rate card (a diffable, committed YAML), not the consultant.
2. **The division of labor inverts.** The AI implements; the human is the
   **broker** — builds the context and environment, defines goals and
   acceptance, guides, validates. So every estimate decomposes into
   `ai` (tokens at API list prices) + `human` (broker hours at the card rate) +
   `platform` (CI minutes at runner rates) + a confidence-based contingency —
   and carries a `traditional` comparison (the pre-AI consulting quote for the
   same scope) whose ratio to the estimate is the engagement's **leverage**.

Actuals are not claims — they are **linked evidence**: `claude-code-action` CI
runs with real cost scraped from run logs, Claude-attributed commits and PRs
(all from [`_data/ai_usage.yml`](../_data/ai_usage.yml)), and optionally this
machine's shadow-priced session ledger. Every accrued dollar has a URL.

## The loop

```text
 _data/fleet_triage.yml          _data/engagement_rates.yml
 (open work items, daily)        (the rate card, hand-edited)
          │                                │
          ▼                                ▼
  tools/dash estimate  ──────────►  _data/engagements.yml   ◄── broker edits
  (estimator-v1: classify,          (status: estimated —        status/plan/
   tier, price, plan)                a PROPOSAL)                 broker_hours
          │                                │
          │            approve: dash ledger --set-status ENG-NNNN=approved
          │                                │
          ▼                                ▼
   AI executes (sessions, CI runs, PRs) — the meter runs
          │                                │
          ▼                                ▼
 _data/ai_usage.yml  ──────────►  tools/dash ledger
 (daily evidence harvest,         (accrue evidence by URL, dedupe,
  ai-usage.yml workflow)           recompute variance + rollups)
                                           │
                                           ▼
                                   /engagements/ page
                          (pipeline, in-flight, variance, leverage)
```

1. **Estimate** — `tools/dash estimate` sweeps open issues from the committed
   triage snapshot (offline; `--repo`/`--issue` narrow it, `--issue` falls back
   to `gh api` live). estimator-v1 classifies each item from labels and title
   into a type (`bug`/`feature`/`docs`/`deps`/`ci`/`security`/`epic`/…), picks
   the type's base tier (xs–xl), adjusts deterministically (broad-scope titles
   up, good-first-issue down, stale items lose confidence), prices the tier's
   effort profile from the rate card, and blends in per-repo **calibration**
   (the client's average real cost per Claude CI run, from `ai_usage.yml`).
   Every driver is recorded in `estimate.drivers`. Fleet sweeps interleave
   clients round-robin and are idempotent — re-running with the same snapshot
   is a byte-identical no-op.
2. **Approve** — estimates are proposals. The broker refines `plan.*`, then
   signs with `tools/dash ledger --set-status ENG-NNNN=approved` (transitions
   are validated: estimated → approved → in_progress → delivered → reconciled,
   cancelled from any pre-reconciled state). Nothing accrues before approval.
3. **Execute & accrue** — the daily `ai-usage.yml` workflow harvests evidence
   and immediately runs `dash-gen ledger --no-local`: each CI run/commit/PR row
   for a client is attributed to that client's **oldest open engagement whose
   window covers the evidence day**, deduped by URL across the **whole
   register** (evidence booked into a closed engagement is never re-attributed;
   no-spend skipped runs are never booked), then actuals totals, variance
   (band: under / on / over at ±10%; no band when there is no estimate to
   compare), and the per-client + fleet rollups are recomputed. Broker time is
   a human entry (`--broker ENG-NNNN=1.5`), priced at the card rate.
4. **Deliver & reconcile** — `--set-status ENG-NNNN=delivered` stamps the date
   and freezes the accrual window; `reconciled` **closes the books**: a closed
   engagement is never restated — not by new evidence, not by broker-hour
   entries (refused), not by later rate-card changes. The variance and the
   *actual* leverage (traditional quote ÷ actual cost) are the report.

## Guardrails

- **Determinism** — estimator-v1 is pure code: no AI in the pricing path, no
  timestamps in the math, sweeps sorted and windowed so re-runs are no-ops.
- **Human approval** — status transitions are the broker's; the generator
  never advances one, and evidence never accrues to an unapproved estimate.
- **Evidence or it didn't happen** — actuals only enter via URL-deduped ledger
  rows; manual overrides live in human-owned fields, visible in the diff.
- **Attribution is explicit** — one evidence row goes to exactly one
  engagement (oldest-open-first). Concurrent engagements on one client share
  imperfectly; split windows or reconcile promptly. The limitation is by
  design — better a stated rule than a hidden model.
- **Public-data discipline** — the register is site data: titles, URLs,
  prices; no secrets (`_data/SCHEMA.md` Forbidden).

## Running it

```bash
tools/dash estimate                       # sweep the first 10 candidates fleet-wide
tools/dash estimate --repo law-ai --limit 5
tools/dash estimate --repo zer0-mistakes --issue 123   # one item, live fallback
tools/dash estimate --re-estimate --limit 50   # reprice estimator-v1 entries in the
                                               # first 50 candidates (rate-card change)

tools/dash ledger                         # accrue evidence + recompute (local ledger folded in)
tools/dash ledger --no-local              # CI form — committed evidence only
tools/dash ledger --set-status ENG-0007=approved
tools/dash ledger --set-status ENG-0007=in_progress --broker ENG-0007=1.5
tools/dash ledger --set-status ENG-0007=delivered
```

The `/engagements/` page re-renders on the next Pages deploy; the daily
`ai-usage.yml` run keeps actuals settling without any manual step.

## Files

| File | Role |
| --- | --- |
| `_data/engagements.yml` | The engagement register — committed; generator-managed with human-owned fields (status, plan, broker_hours, manual estimates) |
| `_data/engagement_rates.yml` | The rate card — hand-edited; broker/traditional rates, tier effort profiles, contingency, type→tier map |
| `.github/scripts/dash-gen/engagements.py` | `estimate` + `ledger` subcommands (registered in `dash_gen.py`; `tools/dash estimate` / `tools/dash ledger`) |
| `pages/_dash/engagements.md` | The `/engagements/` portal page |
| `.github/workflows/ai-usage.yml` | Daily evidence harvest + `ledger --no-local` accrual, one commit |
| `.claude/skills/estimate-issue/` | Agent skill: deep-analyze one issue and refine its engagement (method: agent) |
