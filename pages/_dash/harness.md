---
layout: default
title: Harness
description: The six-layer harness scorecard and trip wires, plus the diagrams that illustrate how the hub's loops run across the fleet.
permalink: /harness/
sidebar:
  nav: dash
---

# 🧬 Harness

**Agent = Model + Harness.** The model reasons; everything else — guides, sensors, bounded loops, memory, permissions, observability — is this repo. The scorecard and trip wires below are computed **offline** from the committed fleet signals by `dash-gen harness` (refreshed daily by [`fleet-pulse.yml`](https://github.com/bamr87/bamr87/blob/main/.github/workflows/fleet-pulse.yml)) into `_data/harness_health.yml`. Thresholds live in `_data/fleet.yml` → `harness:`. Operator guide: [`docs/HARNESS.md`](https://github.com/bamr87/bamr87/blob/main/docs/HARNESS.md).

{% assign h = site.data.harness_health %}
{% if h == nil %}
<div class="alert alert-info">
No harness data yet. Run <code>tools/dash harness</code> locally (offline — it reads only committed <code>_data/</code> files), or wait for the daily <code>fleet-pulse</code> run, which writes <code>_data/harness_health.yml</code>.
</div>
{% else %}

{% assign tripped = h.trip_wires | where: "tripped", true %}
<div class="row text-center my-4">
  <div class="col-md-3 col-6 mb-3"><div class="card h-100 {% if tripped.size > 0 %}border-danger{% else %}border-success{% endif %}"><div class="card-body p-2"><h3 class="mb-0 {% if tripped.size > 0 %}text-danger{% else %}text-success{% endif %}">{{ tripped.size }} / {{ h.trip_wires.size }}</h3><div class="text-muted small">Trip wires tripped</div></div></div></div>
  <div class="col-md-3 col-6 mb-3"><div class="card h-100"><div class="card-body p-2"><h3 class="mb-0">{{ h.scorecard.completion_rate_pct.value }}%</h3><div class="text-muted small">Completion rate (floor {{ h.scorecard.completion_rate_pct.threshold }})</div></div></div></div>
  <div class="col-md-3 col-6 mb-3"><div class="card h-100"><div class="card-body p-2"><h3 class="mb-0">{{ h.scorecard.effectiveness_pct.value }}%</h3><div class="text-muted small">Effectiveness (floor {{ h.scorecard.effectiveness_pct.threshold }})</div></div></div></div>
  <div class="col-md-3 col-6 mb-3"><div class="card h-100"><div class="card-body p-2"><h3 class="mb-0">{{ h.scorecard.standing_failures.value }}</h3><div class="text-muted small">Standing failures</div></div></div></div>
</div>

<p class="small text-muted">Snapshot {{ h.generated_at }} · inputs:{% for s in h.sources %} <code>{{ s[0] }}</code>{% if s[1].present %} ({{ s[1].age_days }}d){% else %} <span class="text-danger">missing</span>{% endif %}{% endfor %}.</p>

## Trip wires

<p class="small text-muted">A tripped wire is an <strong>attention item, not an action</strong> — the doctor, issue pipeline, and rotation loops own the fixes. Every wire is listed, armed or tripped, so a quiet panel is distinguishable from a lost one.</p>

<div class="table-responsive">
<table class="table table-sm align-middle">
  <thead><tr><th></th><th>Wire</th><th>State</th></tr></thead>
  <tbody>
  {% for w in h.trip_wires %}
    <tr class="{% if w.tripped %}table-danger{% endif %}">
      <td>{% if w.tripped %}<span class="badge bg-danger">TRIPPED</span>{% else %}<span class="badge bg-success">armed</span>{% endif %}</td>
      <td><code>{{ w.id }}</code></td>
      <td class="small">{{ w.summary | escape }}{% if w.detail and w.detail.size > 0 %}<ul class="mb-0 mt-1">{% for d in w.detail limit: 8 %}<li>{{ d.repo }} · <code>{{ d.workflow }}</code>{% if d.avg_min %} — {{ d.avg_min }} min avg over {{ d.runs }} runs{% endif %}</li>{% endfor %}</ul>{% endif %}</td>
    </tr>
  {% endfor %}
  </tbody>
</table>
</div>

## Scorecard

<div class="table-responsive">
<table class="table table-sm align-middle">
  <thead><tr><th>Metric</th><th class="text-end">Value</th><th>Better</th><th>Threshold</th><th>Status</th></tr></thead>
  <tbody>
  {% for m in h.scorecard %}
    <tr class="{% if m[1].status == 'breach' or m[1].status == 'fail' %}table-warning{% endif %}">
      <td><code>{{ m[0] }}</code></td>
      <td class="text-end">{{ m[1].value }}</td>
      <td class="small">{% case m[1].direction %}{% when 'up' %}↑ higher{% when 'down' %}↓ lower{% else %}→ steady{% endcase %}</td>
      <td class="small">{{ m[1].threshold | default: "—" }}</td>
      <td class="small">{{ m[1].status | default: "—" }}</td>
    </tr>
  {% endfor %}
  </tbody>
</table>
</div>
{% endif %}

## How it runs — illustrated

<p class="small text-muted">Interactive diagrams authored as typed JSON in <a href="https://github.com/bamr87/bamr87/tree/main/diagrams"><code>diagrams/</code></a> and compiled by the vendored <a href="https://github.com/tt-a1i/archify">archify</a> skill (<code>tools/render-diagrams.sh</code>). Each opens standalone with search, focus, route tracing, dark/light theme, and export. Guided chapters are in the ▶ views menu.</p>

{% assign diagrams = "harness-layers.architecture|The six layers, mapped onto the hub|fleet-pulse.workflow|fleet-pulse.yml — the daily loop|fleet-signals.dataflow|Fleet signals — from GitHub to the alarm panel|issue-pipeline.lifecycle|issue-pipeline.yml — labels as state|repo-evolution.sequence|repo-evolution.yml — a draft PR into a submodule's own upstream" | split: "|" %}
{% for i in (0..4) %}{% assign k = i | times: 2 %}{% assign file = diagrams[k] %}{% assign j = k | plus: 1 %}
<div class="card mb-4">
  <div class="card-header d-flex justify-content-between align-items-center"><strong>{{ diagrams[j] }}</strong><a class="btn btn-sm btn-outline-secondary" href="{{ '/diagrams/' | append: file | append: '.html' | relative_url }}" target="_blank" rel="noopener">Open standalone ↗</a></div>
  <iframe src="{{ '/diagrams/' | append: file | append: '.html' | relative_url }}" title="{{ diagrams[j] }}" loading="lazy" style="width:100%;height:900px;border:0;background:transparent"></iframe>
</div>
{% endfor %}
