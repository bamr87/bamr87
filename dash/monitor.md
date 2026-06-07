---
layout: default
title: Monitor
description: Which repositories need attention — issues, CI build stats, and activity.
permalink: /monitor/
---

# 🩺 Monitor

Observability across every tracked repository. Data is generated at deploy time by
`.github/scripts/dash-gen health` (refreshed every few hours) and is **not** committed.

{% assign health = site.data.project_health %}
{% if health == nil %}
<div class="alert alert-info">
Monitoring data has not been generated yet. Run <code>tools/dash-gen health</code>
locally (requires <code>gh auth login</code>), or wait for the next scheduled
<code>build-dash</code> deploy.
</div>
{% else %}

{% assign ranked = health | sort: "attention_rank" %}

## Attention board

<div class="table-responsive">
<table class="table table-sm align-middle">
  <thead>
    <tr>
      <th>Repo</th><th>Health</th><th>CI</th><th>Activity</th>
      <th>Issues</th><th>PRs</th><th>Security</th><th>Why</th>
    </tr>
  </thead>
  <tbody>
  {% for h in ranked %}
    <tr class="table-{% if h.attention.level == 'red' %}danger{% elsif h.attention.level == 'amber' %}warning{% else %}light{% endif %}">
      <td><a href="{{ h.repo_url }}">{{ h.name }}</a></td>
      <td>{% if h.attention.level == 'red' %}🔴{% elsif h.attention.level == 'amber' %}🟠{% else %}🟢{% endif %}</td>
      <td>{% if h.ci.last == 'success' %}✅{% elsif h.ci.last == nil %}—{% else %}❌{% endif %} {{ h.ci.pass_rate }}%</td>
      <td>{{ h.activity.last_commit_days }}d · {{ h.activity.commits_30d }}/30d</td>
      <td>🐛 {{ h.issues.bugs }} · 🔰 {{ h.issues.good_first }} · 🕰 {{ h.issues.stale }}</td>
      <td>{{ h.prs.open }}{% if h.prs.stale > 0 %} ({{ h.prs.stale }} stale){% endif %}</td>
      <td>{% if h.security.alerts > 0 %}🔴 {{ h.security.alerts }}{% else %}—{% endif %}</td>
      <td><small>{{ h.attention.reasons | join: "; " }}</small></td>
    </tr>
  {% endfor %}
  </tbody>
</table>
</div>

## Open issues needing triage

{% for h in ranked %}
{% if h.issues.items and h.issues.items.size > 0 %}
### [{{ h.name }}]({{ h.repo_url }}/issues)
<ul>
{% for i in h.issues.items %}
  <li><a href="{{ i.url }}">#{{ i.number }} {{ i.title }}</a> {% for l in i.labels %}<span class="badge bg-secondary">{{ l }}</span> {% endfor %}<small class="text-muted">({{ i.age_days }}d)</small></li>
{% endfor %}
</ul>
{% endif %}
{% endfor %}

<p class="small text-muted">Generated {{ site.data.project_health_meta.generated_at | default: "(unknown)" }}.</p>
{% endif %}
