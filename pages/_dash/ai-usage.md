---
layout: default
title: AI Usage
description: Every Claude Code touchpoint across the fleet — CI runs with real cost, Claude-attributed commits and PRs — published for full transparency and audit.
permalink: /ai-usage/
sidebar:
  nav: dash
---

# 🧮 Claude Code Usage — fleet ledger

Every Claude Code touchpoint the fleet leaves in public infrastructure, refreshed daily by `.github/workflows/ai-usage.yml` into `_data/ai_usage.yml`: **CI runs** of `anthropics/claude-code-action` (cost and turn counts scraped from run logs), **commits** carrying a `Co-Authored-By: Claude` trailer, and **PRs** carrying the Claude Code marker. Each ledger row links to its run, commit, or PR — the audit trail is the data, not a claim about it. Local (machine) sessions appear under **Local sessions** only when deliberately
published via `tools/dash-gen ai-usage`; see [/ai-activity/]({{ '/ai-activity/' | relative_url }})
for the local-only view.

{% assign u = site.data.ai_usage %}
{% if u == nil %}
<div class="alert alert-info">
No usage ledger yet. Run <code>tools/dash-gen ai-usage</code> (needs a GitHub token), or wait for the daily <code>AI Usage Refresh</code> workflow to commit
<code>_data/ai_usage.yml</code>.
</div>
{% else %}

<div class="row text-center my-4">
  <div class="col-md-2 col-4 mb-3"><div class="card h-100"><div class="card-body p-2"><h3 class="mb-0">${{ u.totals.ci_cost_usd }}</h3><div class="text-muted small">CI spend / {{ u.window_days }}d</div></div></div></div>
  <div class="col-md-2 col-4 mb-3"><div class="card h-100"><div class="card-body p-2"><h3 class="mb-0">{{ u.totals.ci_runs }}</h3><div class="text-muted small">Claude CI runs</div></div></div></div>
  <div class="col-md-2 col-4 mb-3"><div class="card h-100"><div class="card-body p-2"><h3 class="mb-0">{{ u.totals.turns }}</h3><div class="text-muted small">Agent turns</div></div></div></div>
  <div class="col-md-2 col-4 mb-3"><div class="card h-100"><div class="card-body p-2"><h3 class="mb-0">{{ u.totals.commits }}</h3><div class="text-muted small">Claude commits</div></div></div></div>
  <div class="col-md-2 col-4 mb-3"><div class="card h-100"><div class="card-body p-2"><h3 class="mb-0">{{ u.totals.prs }}</h3><div class="text-muted small">Claude PRs</div></div></div></div>
  <div class="col-md-2 col-4 mb-3"><div class="card h-100"><div class="card-body p-2"><h3 class="mb-0">{{ u.totals.repos_active }}</h3><div class="text-muted small">Repos active</div></div></div></div>
</div>

{% if u.totals.ci_unpriced_runs > 0 %}
<p class="text-muted small">{{ u.totals.ci_unpriced_runs }} of {{ u.totals.ci_runs }}
CI runs carried no parsable usage in their logs (skipped gates, expired logs) — counted as runs, priced at $0. CI logs expose cost and turn counts but no token breakdown — token detail comes from deliberately published local-ledger sections below.</p>
{% endif %}

## By repo

<div class="table-responsive"><table class="table table-sm table-hover">
<thead><tr><th>Repo</th><th>Category</th><th class="text-end">CI runs</th><th class="text-end">Cost</th><th class="text-end">Turns</th><th class="text-end">Minutes</th><th class="text-end">Commits</th><th class="text-end">PRs</th></tr></thead>
<tbody>
{% for r in u.by_repo %}
<tr>
  <td><code>{{ r.repo }}</code></td>
  <td><span class="badge bg-secondary">{{ r.category }}</span></td>
  <td class="text-end">{{ r.runs }}</td>
  <td class="text-end">${{ r.cost_usd }}</td>
  <td class="text-end">{{ r.turns }}</td>
  <td class="text-end">{{ r.minutes }}</td>
  <td class="text-end">{{ r.commits | default: 0 }}</td>
  <td class="text-end">{{ r.prs | default: 0 }}</td>
</tr>
{% endfor %}
</tbody></table></div>

## By workflow

<div class="table-responsive"><table class="table table-sm">
<thead><tr><th>Workflow</th><th class="text-end">Runs</th><th class="text-end">Cost</th><th class="text-end">Turns</th></tr></thead>
<tbody>
{% for w in u.by_workflow limit: 20 %}
<tr><td><code>{{ w.workflow }}</code></td><td class="text-end">{{ w.runs }}</td><td class="text-end">${{ w.cost_usd }}</td><td class="text-end">{{ w.turns }}</td></tr>
{% endfor %}
</tbody></table></div>

## By category · by day

<div class="row">
<div class="col-md-5">
<table class="table table-sm">
<thead><tr><th>Category</th><th class="text-end">Runs</th><th class="text-end">Cost</th></tr></thead>
<tbody>
{% for c in u.by_category %}
<tr><td>{{ c.category }}</td><td class="text-end">{{ c.runs }}</td><td class="text-end">${{ c.cost_usd }}</td></tr>
{% endfor %}
</tbody></table>
</div>
<div class="col-md-7">
<table class="table table-sm">
<thead><tr><th>Day</th><th class="text-end">Runs</th><th class="text-end">Cost</th><th class="text-end">Turns</th></tr></thead>
<tbody>
{% for d in u.by_day reversed %}
<tr><td>{{ d.day }}</td><td class="text-end">{{ d.runs }}</td><td class="text-end">${{ d.cost_usd }}</td><td class="text-end">{{ d.turns }}</td></tr>
{% endfor %}
</tbody></table>
</div>
</div>

{% if u.local %}
## Local sessions (deliberately published {{ u.local.published }})

<p class="text-muted small">Shadow-priced at API list rates from the machine
ledger — subscription usage, not an invoice.</p>
<div class="row text-center my-3">
  <div class="col-md-3 col-6"><div class="card"><div class="card-body p-2"><h4 class="mb-0">${{ u.local.totals.window_est_cost_usd | round: 2 }}</h4><div class="text-muted small">Est. window cost</div></div></div></div>
  <div class="col-md-3 col-6"><div class="card"><div class="card-body p-2"><h4 class="mb-0">{{ u.local.totals.sessions }}</h4><div class="text-muted small">Sessions</div></div></div></div>
</div>
{% endif %}

## Audit ledger — recent CI runs

<div class="table-responsive"><table class="table table-sm table-hover">
<thead><tr><th>Day</th><th>Repo</th><th>Workflow</th><th>Event</th><th>Result</th><th class="text-end">Cost</th><th class="text-end">Turns</th><th></th></tr></thead>
<tbody>
{% for e in u.ci_ledger limit: 50 %}
<tr>
  <td class="text-nowrap">{{ e.day }}</td>
  <td><code>{{ e.repo }}</code></td>
  <td>{{ e.workflow }}</td>
  <td>{{ e.event }}</td>
  <td>{% if e.conclusion == "success" %}✅{% elsif e.conclusion == "failure" %}❌{% else %}{{ e.conclusion }}{% endif %}</td>
  <td class="text-end">{% if e.cost_usd %}${{ e.cost_usd }}{% else %}—{% endif %}</td>
  <td class="text-end">{{ e.turns | default: "—" }}</td>
  <td><a href="{{ e.url }}">run</a></td>
</tr>
{% endfor %}
</tbody></table></div>

## Audit ledger — commits & PRs

<div class="row">
<div class="col-md-6">
<table class="table table-sm">
<thead><tr><th>Day</th><th>Commit</th><th></th></tr></thead>
<tbody>
{% for c in u.commit_ledger limit: 25 %}
<tr><td class="text-nowrap">{{ c.day }}</td><td><code>{{ c.repo }}</code> {{ c.title }}</td><td><a href="{{ c.url }}">{{ c.sha }}</a></td></tr>
{% endfor %}
</tbody></table>
</div>
<div class="col-md-6">
<table class="table table-sm">
<thead><tr><th>Day</th><th>PR</th><th></th></tr></thead>
<tbody>
{% for p in u.pr_ledger limit: 25 %}
<tr><td class="text-nowrap">{{ p.day }}</td><td><code>{{ p.repo }}</code> {{ p.title }}</td><td><a href="{{ p.url }}">#{{ p.number }}</a></td></tr>
{% endfor %}
</tbody></table>
</div>
</div>

<p class="text-muted small">Generated {{ u.generated }} · window {{ u.window_days }}d ·
source <code>.github/scripts/dash-gen/ai_usage_collector.py</code></p>
{% endif %}
