---
layout: default
title: Cost Cockpit
description: The financial hub — AI spend and GitHub Actions consumption unified per repo, with drill-down to every run, commit, and PR that produced the numbers.
permalink: /cockpit/
sidebar:
  nav: dash
---

# 💰 Cost Cockpit

One financial surface for the whole fleet: **Claude Code spend** (real CI cost
from run logs + opt-in local estimates) and **GitHub Actions consumption**
(minutes, waste, effectiveness), unified per repo. Every number drills down —
to the [/ai-usage/]({{ '/ai-usage/' | relative_url }}) audit ledgers, the
[/actions/]({{ '/actions/' | relative_url }}) workflow table, and the runs,
commits, and PRs at the source.

{% assign ai = site.data.ai_usage %}
{% assign act = site.data.actions_usage %}
{% assign local = ai.local %}

{% if ai == nil and act == nil %}
<div class="alert alert-info">No cost data yet — the daily
<code>ai-usage.yml</code> and <code>actions-usage.yml</code> workflows commit
<code>_data/ai_usage.yml</code> and <code>_data/actions_usage.yml</code>,
which this page renders.</div>
{% else %}

<div class="row text-center my-4">
  {% if ai %}
  <div class="col-md-2 col-4 mb-3"><div class="card h-100 border-primary"><div class="card-body p-2"><h3 class="mb-0">${{ ai.totals.ci_cost_usd }}</h3><div class="text-muted small">Claude CI spend / {{ ai.window_days }}d</div></div></div></div>
  {% endif %}
  {% if local %}
  <div class="col-md-2 col-4 mb-3"><div class="card h-100"><div class="card-body p-2"><h3 class="mb-0">${{ local.totals.window_est_cost_usd | round: 2 }}</h3><div class="text-muted small">Local est. / {{ local.window_days }}d</div></div></div></div>
  {% endif %}
  {% if act %}
  <div class="col-md-2 col-4 mb-3"><div class="card h-100"><div class="card-body p-2"><h3 class="mb-0">{{ act.totals.total_hours }}h</h3><div class="text-muted small">Actions consumed / {{ act.window_days }}d</div></div></div></div>
  <div class="col-md-2 col-4 mb-3"><div class="card h-100 border-danger"><div class="card-body p-2"><h3 class="mb-0 text-danger">{{ act.totals.waste_hours }}h</h3><div class="text-muted small">Actions wasted ({{ 100 | minus: act.totals.effectiveness_pct | round }}%)</div></div></div></div>
  {% endif %}
  {% if ai %}
  <div class="col-md-2 col-4 mb-3"><div class="card h-100"><div class="card-body p-2"><h3 class="mb-0">{{ ai.totals.ci_runs }}</h3><div class="text-muted small">Claude runs · {{ ai.totals.turns }} turns</div></div></div></div>
  <div class="col-md-2 col-4 mb-3"><div class="card h-100"><div class="card-body p-2"><h3 class="mb-0">{{ ai.totals.commits }}+{{ ai.totals.prs }}</h3><div class="text-muted small">Claude commits + PRs</div></div></div></div>
  {% endif %}
</div>

## Cost by repo — the unified ledger

<p class="text-muted small">Actions minutes from the Actions API; Claude cost
from <code>claude-code-action</code> run logs. Row links: <b>repo</b> → GitHub,
<b>runs</b> → the repo's Actions tab, 🧮 → AI ledger, 📈 → workflow drill-down.</p>

<div class="table-responsive"><table class="table table-sm table-hover">
<thead><tr>
  <th>Repo</th>
  <th class="text-end">Claude $</th>
  <th class="text-end">Claude runs</th>
  <th class="text-end">Turns</th>
  <th class="text-end">Actions min</th>
  <th class="text-end">Waste min</th>
  <th class="text-end">Effective</th>
  <th class="text-end">Commits/PRs</th>
  <th>Drill down</th>
</tr></thead>
<tbody>
{% assign seen = "" %}
{% if act %}
{% for a in act.by_repo %}
  {% assign seen = seen | append: "|" | append: a.repo %}
  {% assign airow = ai.by_repo | where: "repo", a.repo | first %}
  <tr>
    <td><a href="https://github.com/bamr87/{{ a.repo }}"><code>{{ a.repo }}</code></a></td>
    <td class="text-end">{% if airow %}${{ airow.cost_usd }}{% else %}—{% endif %}</td>
    <td class="text-end">{% if airow %}{{ airow.runs }}{% else %}—{% endif %}</td>
    <td class="text-end">{% if airow %}{{ airow.turns }}{% else %}—{% endif %}</td>
    <td class="text-end">{{ a.total_min }}</td>
    <td class="text-end{% if a.waste_min > 60 %} text-danger{% endif %}">{{ a.waste_min }}</td>
    <td class="text-end">{{ a.effectiveness_pct }}%</td>
    <td class="text-end">{% if airow %}{{ airow.commits | default: 0 }}/{{ airow.prs | default: 0 }}{% else %}—{% endif %}</td>
    <td class="text-nowrap">
      <a href="https://github.com/bamr87/{{ a.repo }}/actions" title="Actions runs">runs</a> ·
      <a href="{{ '/ai-usage/' | relative_url }}" title="AI audit ledger">🧮</a> ·
      <a href="{{ '/actions/' | relative_url }}" title="Workflow drill-down">📈</a>
    </td>
  </tr>
{% endfor %}
{% endif %}
{% if ai %}
{% for r in ai.by_repo %}
  {% unless seen contains r.repo %}
  <tr>
    <td><a href="https://github.com/bamr87/{{ r.repo }}"><code>{{ r.repo }}</code></a></td>
    <td class="text-end">${{ r.cost_usd }}</td>
    <td class="text-end">{{ r.runs }}</td>
    <td class="text-end">{{ r.turns }}</td>
    <td class="text-end">—</td>
    <td class="text-end">—</td>
    <td class="text-end">—</td>
    <td class="text-end">{{ r.commits | default: 0 }}/{{ r.prs | default: 0 }}</td>
    <td class="text-nowrap">
      <a href="https://github.com/bamr87/{{ r.repo }}/actions">runs</a> ·
      <a href="{{ '/ai-usage/' | relative_url }}">🧮</a>
    </td>
  </tr>
  {% endunless %}
{% endfor %}
{% endif %}
</tbody></table></div>

## Where the money goes

<div class="row">
<div class="col-md-6">
<h4 class="h6 text-muted">Claude cost by workflow</h4>
<table class="table table-sm">
<thead><tr><th>Workflow</th><th class="text-end">Runs</th><th class="text-end">$</th></tr></thead>
<tbody>
{% for w in ai.by_workflow limit: 10 %}
<tr><td><code>{{ w.workflow }}</code></td><td class="text-end">{{ w.runs }}</td><td class="text-end">${{ w.cost_usd }}</td></tr>
{% endfor %}
</tbody></table>
</div>
<div class="col-md-6">
<h4 class="h6 text-muted">Actions minutes by type</h4>
<table class="table table-sm">
<thead><tr><th>Type</th><th class="text-end">Minutes</th><th class="text-end">Effective</th></tr></thead>
<tbody>
{% for t in act.by_type limit: 10 %}
<tr><td>{{ t.type }}</td><td class="text-end">{{ t.total_min }}</td><td class="text-end">{{ t.effectiveness_pct }}%</td></tr>
{% endfor %}
</tbody></table>
</div>
</div>

## Daily burn

<div class="row">
<div class="col-md-6">
<h4 class="h6 text-muted">Claude $ / day</h4>
<table class="table table-sm">
<thead><tr><th>Day</th><th class="text-end">Runs</th><th class="text-end">$</th></tr></thead>
<tbody>
{% assign aioff = ai.by_day.size | minus: 7 %}{% if aioff < 0 %}{% assign aioff = 0 %}{% endif %}
{% for d in ai.by_day offset: aioff %}
<tr><td>{{ d.day }}</td><td class="text-end">{{ d.runs }}</td><td class="text-end">${{ d.cost_usd }}</td></tr>
{% endfor %}
</tbody></table>
</div>
<div class="col-md-6">
<h4 class="h6 text-muted">Actions min / day</h4>
<table class="table table-sm">
<thead><tr><th>Day</th><th class="text-end">Runs</th><th class="text-end">Min</th></tr></thead>
<tbody>
{% assign actoff = act.by_day.size | minus: 7 %}{% if actoff < 0 %}{% assign actoff = 0 %}{% endif %}
{% for d in act.by_day offset: actoff %}
<tr><td>{{ d.date }}</td><td class="text-end">{{ d.runs }}</td><td class="text-end">{{ d.total_min }}</td></tr>
{% endfor %}
</tbody></table>
</div>
</div>

## Sources & audit trail

Every figure traces to public infrastructure — the cockpit is a view, never a claim:

- **Claude CI cost** — [`_data/ai_usage.yml`]({{ site.repository_url | default: 'https://github.com/bamr87/bamr87' }}/blob/main/_data/ai_usage.yml), refreshed daily by [`ai-usage.yml`](https://github.com/bamr87/bamr87/actions/workflows/ai-usage.yml); per-run cost scraped from `claude-code-action` logs, each ledger row on [/ai-usage/]({{ '/ai-usage/' | relative_url }}) links to its run.
- **Actions consumption** — [`_data/actions_usage.yml`](https://github.com/bamr87/bamr87/blob/main/_data/actions_usage.yml), refreshed daily by [`actions-usage.yml`](https://github.com/bamr87/bamr87/actions/workflows/actions-usage.yml) via the Actions API; per-workflow drill-down on [/actions/]({{ '/actions/' | relative_url }}).
- **Optimization loop** — the worst offenders become tracked issues via the Opus [`actions-review.yml`](https://github.com/bamr87/bamr87/actions/workflows/actions-review.yml) reviewer ([open issues](https://github.com/bamr87/bamr87/issues?q=is%3Aissue+label%3Aactions-review)).
- **Local sessions** — token-true estimates from each machine's ledger, published only by a deliberate local `tools/dash-gen ai-usage` run ([/ai-activity/]({{ '/ai-activity/' | relative_url }}) for the local-only view).

<p class="text-muted small">{% if ai %}Claude data {{ ai.generated }} · {% endif %}{% if act %}Actions data {{ act.generated_at }}{% endif %}</p>
{% endif %}
