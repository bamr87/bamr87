---
layout: default
title: Engagements
description: Every registry project as a client — deterministic estimates with an AI/broker/platform cost decomposition, evidence-accrued actuals, and estimate-vs-actual variance per engagement.
permalink: /engagements/
sidebar:
  nav: dash
---

# 💼 Engagements — estimates vs actuals

Every registry project is a **client**; every entry is a **statement of work** produced by
`tools/dash estimate` (deterministic estimator-v1 over open issues, priced by the
[rate card](https://github.com/bamr87/bamr87/blob/main/_data/engagement_rates.yml)) and settled by
`tools/dash ledger` (actuals accrued from auditable evidence — `claude-code-action` CI runs,
Claude-attributed commits and PRs — into `_data/engagements.yml`). Each estimate decomposes along
the AI-era division of labor: **AI** performs the implementation, the **human broker** builds
context, defines goals, and validates, the **platform** runs the pipelines. The `traditional`
column is what the same scope would have cost at pre-AI consulting hours — its ratio to the
estimate is the engagement's **leverage**. Model and lifecycle:
[docs/ESTIMATION.md](https://github.com/bamr87/bamr87/blob/main/docs/ESTIMATION.md).

{% assign e = site.data.engagements %}
{% if e == nil %}
<div class="alert alert-info">
No engagement ledger yet. Run <code>tools/dash estimate</code> (drafts estimates from the
committed triage snapshot) then <code>tools/dash ledger</code>, which write
<code>_data/engagements.yml</code> — the file this page renders.
</div>
{% else %}

<div class="row text-center my-4">
  <div class="col-md-2 col-4 mb-3"><div class="card h-100"><div class="card-body p-2"><h3 class="mb-0">${{ e.summary.pipeline_usd | round: 0 }}</h3><div class="text-muted small">Pipeline (estimated + approved)</div></div></div></div>
  <div class="col-md-2 col-4 mb-3"><div class="card h-100"><div class="card-body p-2"><h3 class="mb-0">${{ e.summary.in_flight_usd | round: 0 }}</h3><div class="text-muted small">In flight</div></div></div></div>
  <div class="col-md-2 col-4 mb-3"><div class="card h-100"><div class="card-body p-2"><h3 class="mb-0">${{ e.summary.delivered_est_usd | round: 0 }}</h3><div class="text-muted small">Delivered (est.)</div></div></div></div>
  <div class="col-md-2 col-4 mb-3"><div class="card h-100"><div class="card-body p-2"><h3 class="mb-0">${{ e.summary.actual_usd | round: 2 }}</h3><div class="text-muted small">Actuals to date</div></div></div></div>
  <div class="col-md-2 col-4 mb-3"><div class="card h-100"><div class="card-body p-2"><h3 class="mb-0">{{ e.summary.engagements }}</h3><div class="text-muted small">Engagements · {{ e.summary.clients }} clients</div></div></div></div>
  <div class="col-md-2 col-4 mb-3"><div class="card h-100 border-primary"><div class="card-body p-2"><h3 class="mb-0">{% if e.summary.avg_leverage_est %}{{ e.summary.avg_leverage_est }}×{% else %}—{% endif %}</h3><div class="text-muted small">Avg AI leverage (est.)</div></div></div></div>
</div>

<p class="text-muted small">
Status counts:
<span class="badge bg-secondary">estimated {{ e.summary.counts.estimated }}</span>
<span class="badge bg-info text-dark">approved {{ e.summary.counts.approved }}</span>
<span class="badge bg-warning text-dark">in progress {{ e.summary.counts.in_progress }}</span>
<span class="badge bg-success">delivered {{ e.summary.counts.delivered }}</span>
<span class="badge bg-primary">reconciled {{ e.summary.counts.reconciled }}</span>
<span class="badge bg-light text-dark border">cancelled {{ e.summary.counts.cancelled }}</span>
— estimates are <b>proposals</b>: nothing accrues actuals until a human approves
(<code>tools/dash ledger --set-status ENG-NNNN=approved</code>).
</p>

## Clients

<div class="table-responsive"><table class="table table-sm table-hover align-middle">
<thead><tr><th>Client</th><th class="text-end">Engagements</th><th class="text-end">Open</th><th class="text-end">Delivered</th><th class="text-end">Estimated</th><th class="text-end">Actuals</th></tr></thead>
<tbody>
{% for c in e.clients %}
<tr>
  <td><a href="https://github.com/{{ c.nwo }}"><code>{{ c.name }}</code></a></td>
  <td class="text-end">{{ c.engagements }}</td>
  <td class="text-end">{{ c.open }}</td>
  <td class="text-end">{{ c.delivered }}</td>
  <td class="text-end">${{ c.est_usd | round: 2 }}</td>
  <td class="text-end">{% if c.actual_usd > 0 %}${{ c.actual_usd | round: 2 }}{% else %}—{% endif %}</td>
</tr>
{% endfor %}
</tbody></table></div>

## Engagements

<p class="text-muted small">Est. = AI implementation + human brokerage + platform + confidence
contingency. Lev. = traditional-consulting quote ÷ estimate. Every actual links to its evidence
(run, commit, PR) inside <code>_data/engagements.yml</code>.</p>

<div class="table-responsive"><table class="table table-sm table-hover align-middle">
<thead><tr>
  <th>ID</th><th>Client</th><th>Work item</th><th>Type</th><th class="text-center">Tier</th>
  <th>Status</th><th class="text-end">Est.</th><th class="text-end">Actual</th>
  <th class="text-end">Variance</th><th class="text-end">Lev.</th>
</tr></thead>
<tbody>
{% for g in e.engagements %}
<tr>
  <td class="text-nowrap"><code>{{ g.id }}</code></td>
  <td><code>{{ g.client }}</code></td>
  <td><a href="{{ g.source.url }}">{{ g.title | truncate: 70 | escape }}</a></td>
  <td><span class="badge bg-light text-dark border">{{ g.type }}</span></td>
  <td class="text-center"><code>{{ g.estimate.tier }}</code></td>
  <td>
    {% case g.status %}
    {% when 'estimated' %}<span class="badge bg-secondary">estimated</span>
    {% when 'approved' %}<span class="badge bg-info text-dark">approved</span>
    {% when 'in_progress' %}<span class="badge bg-warning text-dark">in progress</span>
    {% when 'delivered' %}<span class="badge bg-success">delivered</span>
    {% when 'reconciled' %}<span class="badge bg-primary">reconciled</span>
    {% else %}<span class="badge bg-light text-dark border">{{ g.status }}</span>
    {% endcase %}
  </td>
  <td class="text-end">${{ g.estimate.total_usd | round: 2 }}</td>
  <td class="text-end">{% if g.actuals.total_usd > 0 %}${{ g.actuals.total_usd | round: 2 }}{% else %}—{% endif %}</td>
  <td class="text-end">{% if g.variance and g.variance.pct != nil %}<span class="{% if g.variance.band == 'over' %}text-danger{% elsif g.variance.band == 'under' %}text-success{% endif %}">{{ g.variance.pct }}%</span>{% else %}—{% endif %}</td>
  <td class="text-end">{% if g.variance.leverage_actual %}<b>{{ g.variance.leverage_actual }}×</b>{% elsif g.estimate.leverage %}{{ g.estimate.leverage }}×{% else %}—{% endif %}</td>
</tr>
{% endfor %}
</tbody></table></div>

## How an engagement flows

<div class="row">
<div class="col-md-7" markdown="1">

1. **Estimate** — `tools/dash estimate` classifies an open issue (labels, title, per-repo cost
   history) into a tier and prices it from the rate card: AI tokens at API list rates, broker
   hours at the card rate, CI minutes at runner rates, plus a confidence-based contingency.
   Same inputs, same estimate — the quote is reproducible, not negotiable.
2. **Approve** — the broker reviews the plan (approach, deliverables, acceptance), adjusts, and
   signs: `--set-status ENG-NNNN=approved`. Only then does the meter start.
3. **Execute** — the AI implements (sessions, CI runs, PRs). The daily
   [`ai-usage` refresh](https://github.com/bamr87/bamr87/blob/main/.github/workflows/ai-usage.yml)
   harvests the evidence; `tools/dash ledger` accrues it to the engagement, deduped by URL.
4. **Deliver & reconcile** — on `delivered`, variance closes the loop: estimate vs actual,
   band (±10% = on), and the *actual* leverage against the traditional quote.

</div>
<div class="col-md-5" markdown="1">

**Where the numbers come from**

- Estimates: [`_data/engagement_rates.yml`](https://github.com/bamr87/bamr87/blob/main/_data/engagement_rates.yml) (the rate card) — change a rate, re-run, and every open estimate reprices.
- Actuals: [/ai-usage/]({{ '/ai-usage/' | relative_url }}) ledgers (CI cost scraped from run logs, Claude commits/PRs) + optional local session costs from [/ai-activity/]({{ '/ai-activity/' | relative_url }}).
- Cross-fleet spend context: the [Cost Cockpit]({{ '/cockpit/' | relative_url }}).
- Work-item supply: the [/triage/]({{ '/triage/' | relative_url }}) snapshot.

</div>
</div>

<p class="small text-muted">Updated {{ e.summary.updated_at }} ·
source <code>.github/scripts/dash-gen/engagements.py</code> ·
register <code>_data/engagements.yml</code> · rate card <code>_data/engagement_rates.yml</code></p>
{% endif %}
