---
layout: default
title: Fleet Triage
description: The fleet's open-state inbox — every open issue, pull request, and failing workflow across all registry repos, prioritized daily.
permalink: /triage/
sidebar:
  nav: dash
---

# 📥 Fleet Triage

Every **open issue**, **open PR**, and **failing workflow** across the fleet, snapshotted daily by `.github/workflows/daily-repo-analysis.yml` (via `dash-gen triage`) into `_data/fleet_triage.yml` — the reviewable, diffable companion to the daily digests in [`_reports/daily/`](https://github.com/bamr87/bamr87/tree/main/_reports/daily).

{% assign t = site.data.fleet_triage %}
{% if t == nil %}
<div class="alert alert-info">
No triage data yet. Run <code>tools/dash triage</code> locally (needs <code>PyGithub</code> + a GitHub token), or wait for the daily <code>🗓️ Daily Repo Analysis</code> workflow. It inventories every registry repo's open issues, PRs, and CI state into <code>_data/fleet_triage.yml</code>, which this page renders.
</div>
{% else %}

<div class="row text-center my-4">
  <div class="col-md-2 col-4 mb-3"><div class="card h-100"><div class="card-body p-2"><h3 class="mb-0">{{ t.totals.open_issues }}</h3><div class="text-muted small">Open issues</div></div></div></div>
  <div class="col-md-2 col-4 mb-3"><div class="card h-100"><div class="card-body p-2"><h3 class="mb-0">{{ t.totals.open_prs }}</h3><div class="text-muted small">Open PRs ({{ t.totals.draft_prs }} draft)</div></div></div></div>
  <div class="col-md-2 col-4 mb-3"><div class="card h-100 {% if t.totals.prs_ci_failing > 0 %}border-danger{% endif %}"><div class="card-body p-2"><h3 class="mb-0 {% if t.totals.prs_ci_failing > 0 %}text-danger{% endif %}">{{ t.totals.prs_ci_failing }}</h3><div class="text-muted small">PRs failing checks</div></div></div></div>
  <div class="col-md-2 col-4 mb-3"><div class="card h-100 {% if t.totals.failing_workflows > 0 %}border-danger{% endif %}"><div class="card-body p-2"><h3 class="mb-0 {% if t.totals.failing_workflows > 0 %}text-danger{% endif %}">{{ t.totals.failing_workflows }}</h3><div class="text-muted small">Failing workflows</div></div></div></div>
  <div class="col-md-2 col-4 mb-3"><div class="card h-100"><div class="card-body p-2"><h3 class="mb-0">🔴 {{ t.totals.repos_red }} 🟠 {{ t.totals.repos_amber }}</h3><div class="text-muted small">Repos needing attention</div></div></div></div>
  <div class="col-md-2 col-4 mb-3"><div class="card h-100"><div class="card-body p-2"><h3 class="mb-0">{{ t.totals.dependabot_prs }}</h3><div class="text-muted small">Dependabot PRs</div></div></div></div>
</div>

## Inbox — what to act on first

<p class="small text-muted">The unified queue: failing workflows, PRs with red checks or long idle time, bug-labeled and long-idle issues — fleet repos only, priority-ordered by the generator.</p>

{% if t.inbox and t.inbox.size > 0 %}
<div class="table-responsive">
<table class="table table-sm table-hover align-middle">
  <thead><tr><th></th><th>Repo</th><th>Item</th><th>Why</th><th class="text-end">Age</th></tr></thead>
  <tbody>
  {% for x in t.inbox %}
    <tr class="{% if x.priority >= 90 %}table-danger{% elsif x.priority >= 70 %}table-warning{% endif %}">
      <td>{% case x.kind %}{% when 'workflow' %}<span class="badge bg-danger">CI</span>{% when 'pr' %}<span class="badge bg-primary">PR</span>{% else %}<span class="badge bg-secondary">issue</span>{% endcase %}</td>
      <td class="text-nowrap">{{ x.repo }}</td>
      <td><a href="{{ x.url }}">{{ x.ref | escape }} {{ x.title | escape }}</a></td>
      <td class="small">{{ x.why | escape }}</td>
      <td class="text-end small">{% if x.age_days %}{{ x.age_days }}d{% endif %}</td>
    </tr>
  {% endfor %}
  </tbody>
</table>
</div>
{% else %}
<div class="alert alert-success">Inbox zero — no failing workflows, red PRs, or flagged issues across the fleet. 🎉</div>
{% endif %}

## Backlog by repo

<p class="small text-muted">Sorted by attention score. Items are capped at 30 per repo per list — counts are exact; follow the repo links for the full lists.</p>

{% for r in t.by_repo %}
{% assign has_backlog = r.issues.open | plus: r.prs.open | plus: r.workflows.failing.size %}
{% if has_backlog > 0 %}
<details class="mb-2">
<summary>
{% if r.attention.level == 'red' %}🔴{% elsif r.attention.level == 'amber' %}🟠{% else %}🟢{% endif %}
<strong>{{ r.name }}</strong>{% if r.external %} <span class="badge bg-light text-dark border">external</span>{% endif %}{% if r.private %} <span class="badge bg-light text-dark border">private</span>{% endif %}
— {{ r.issues.open }} issue(s) · {{ r.prs.open }} PR(s){% if r.workflows.failing.size > 0 %} · <span class="text-danger">{{ r.workflows.failing.size }} failing workflow(s)</span>{% endif %}
<span class="text-muted small">({{ r.attention.reasons | join: ", " }})</span>
</summary>
<div class="ms-3 mt-2">
{% if r.workflows.failing.size > 0 %}
<p class="mb-1"><strong>❌ Failing workflows</strong></p>
<ul class="small">
{% for w in r.workflows.failing %}
<li><a href="{{ w.run_url }}">{{ w.workflow | escape }}</a> → <code>{{ w.conclusion }}</code> <span class="text-muted">({{ w.run_at }} · {{ w.path | escape }})</span></li>
{% endfor %}
</ul>
{% endif %}
{% if r.prs.items and r.prs.items.size > 0 %}
<p class="mb-1"><strong>🔀 Open PRs</strong> <span class="text-muted small">{{ r.prs.open }} open · {{ r.prs.draft }} draft · {{ r.prs.stale }} stale{% if r.prs.capped %} · list capped at 30{% endif %} · <a href="{{ r.repo_url }}/pulls">all →</a></span></p>
<ul class="small">
{% for p in r.prs.items %}
<li><a href="{{ p.url }}">#{{ p.number }} {{ p.title | escape }}</a> <span class="text-muted">by {{ p.author | escape }} · {{ p.age_days }}d</span>{% if p.draft %} <span class="badge bg-secondary">draft</span>{% endif %}{% if p.dependabot %} <span class="badge bg-info text-dark">dependabot</span>{% endif %}{% case p.ci %}{% when 'fail' %} <span class="badge bg-danger">checks failing</span>{% when 'pass' %} <span class="badge bg-success">checks pass</span>{% when 'pending' %} <span class="badge bg-warning text-dark">checks pending</span>{% endcase %}</li>
{% endfor %}
</ul>
{% endif %}
{% if r.issues.items and r.issues.items.size > 0 %}
<p class="mb-1"><strong>🐛 Open issues</strong> <span class="text-muted small">{{ r.issues.open }} open · {{ r.issues.stale }} stale · {{ r.issues.bugs }} bug(s){% if r.issues.capped %} · list capped at 30{% endif %} · <a href="{{ r.repo_url }}/issues">all →</a></span></p>
<ul class="small">
{% for i in r.issues.items %}
<li><a href="{{ i.url }}">#{{ i.number }} {{ i.title | escape }}</a> <span class="text-muted">by {{ i.author | escape }} · idle {{ i.idle_days }}d</span> {% for l in i.labels %}<span class="badge bg-secondary">{{ l | escape }}</span> {% endfor %}</li>
{% endfor %}
</ul>
{% endif %}
</div>
</details>
{% endif %}
{% endfor %}

{% assign clear = t.by_repo | where_exp: "r", "r.issues.open == 0" | where_exp: "r", "r.prs.open == 0" | where_exp: "r", "r.workflows.failing.size == 0" %}
{% if clear.size > 0 %}
<p class="small text-muted mt-3">🟢 {{ clear.size }} repo(s) with nothing open: {% for r in clear %}{{ r.name }}{% unless forloop.last %} · {% endunless %}{% endfor %}</p>
{% endif %}

{% if t.repos_unreachable and t.repos_unreachable.size > 0 %}
<p class="small text-muted">⚠️ Unreachable this run (no access / 404): {{ t.repos_unreachable | join: ", " }}</p>
{% endif %}

<p class="small text-muted">{{ t.note }}</p>

<p class="small text-muted">Generated {{ t.generated_at }} · {{ t.repos_scanned }} repos scanned · refreshed daily by <code>🗓️ Daily Repo Analysis</code> · pipeline doc: <a href="https://github.com/bamr87/bamr87/blob/main/docs/DAILY-ANALYSIS.md">DAILY-ANALYSIS.md</a>.</p>

{% endif %}
