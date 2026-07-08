---
layout: default
title: AI Activity
description: Shadow-priced Claude Code usage across every repo — tokens, sessions, and estimated API cost.
permalink: /ai-activity/
sidebar:
  nav: dash
---

# 🤖 AI Activity

Claude Code usage across **every repo touched from this machine**, shadow-priced at
Anthropic API list rates from the local session ledger (`~/.claude/projects/`).
Generated locally by `tools/dash ai` and **never committed** — spend data stays on
your machine unless you deliberately publish it.

{% assign ai = site.data.ai_activity %}
{% if ai == nil %}
<div class="alert alert-info">
No AI activity data yet. Run <code>tools/dash ai</code> locally — it scans
<code>~/.claude/projects/</code>, merges a persistent daily ledger
(<code>~/.claude/ai-activity-ledger.json</code>), and writes the gitignored
<code>_data/ai_activity.yml</code> this page renders. The published dash
intentionally shows this notice instead of usage data.
</div>
{% else %}

<div class="row text-center my-4">
  <div class="col-md-3 col-6 mb-3"><div class="card"><div class="card-body"><h2>${{ ai.totals.window_est_cost_usd | round: 2 }}</h2><div class="text-muted">Est. cost, last {{ ai.window_days }}d</div></div></div></div>
  <div class="col-md-3 col-6 mb-3"><div class="card"><div class="card-body"><h2>${{ ai.totals.est_cost_usd | round: 2 }}</h2><div class="text-muted">Est. cost, all time</div></div></div></div>
  <div class="col-md-3 col-6 mb-3"><div class="card"><div class="card-body"><h2>{{ ai.totals.cache_read_ratio_pct }}%</h2><div class="text-muted">Prompt tokens from cache</div></div></div></div>
  <div class="col-md-3 col-6 mb-3"><div class="card"><div class="card-body"><h2>{{ ai.totals.sessions }}</h2><div class="text-muted">Sessions · {{ ai.totals.repos }} repos</div></div></div></div>
</div>

{% if ai.unpriced_models.size > 0 %}
<div class="alert alert-warning">
Unpriced models counted at $0: <code>{{ ai.unpriced_models | join: ", " }}</code> —
add rates to <code>.github/scripts/dash-gen/ai_activity.py</code>.
</div>
{% endif %}

## Spend by repo

<div class="table-responsive">
<table class="table table-sm align-middle">
  <thead>
    <tr>
      <th>Repo</th><th>Est. {{ ai.window_days }}d</th><th>Est. total</th>
      <th>Sessions ({{ ai.window_days }}d / all)</th><th>Turns</th>
      <th>Cache reads</th><th>Top model</th><th>Last active</th>
    </tr>
  </thead>
  <tbody>
  {% for r in ai.repos %}
    <tr>
      <td>{% if r.repo_url %}<a href="{{ r.repo_url }}">{{ r.name }}</a>{% else %}{{ r.name }}{% endif %}
          {% unless r.registered %}<span class="badge bg-secondary">unregistered</span>{% endunless %}</td>
      <td>${{ r.window_est_cost_usd | round: 2 }}</td>
      <td>${{ r.est_cost_usd | round: 2 }}</td>
      <td>{{ r.window_sessions }} / {{ r.sessions }}</td>
      <td>{{ r.turns }}</td>
      <td>{{ r.cache_read_ratio_pct }}%</td>
      <td><small>{{ r.top_model }}</small></td>
      <td>{{ r.last_activity }}</td>
    </tr>
  {% endfor %}
  </tbody>
</table>
</div>

## Spend by model

<div class="table-responsive">
<table class="table table-sm align-middle">
  <thead>
    <tr>
      <th>Model</th><th>Est. total</th><th>Est. {{ ai.window_days }}d</th><th>Turns</th>
      <th>Input</th><th>Output</th><th>Cache write</th><th>Cache read</th>
    </tr>
  </thead>
  <tbody>
  {% for m in ai.models %}
    <tr>
      <td><code>{{ m.model }}</code></td>
      <td>${{ m.est_cost_usd | round: 2 }}</td>
      <td>${{ m.window_est_cost_usd | round: 2 }}</td>
      <td>{{ m.turns }}</td>
      <td>{{ m.tokens.input | divided_by: 1000000.0 | round: 1 }}M</td>
      <td>{{ m.tokens.output | divided_by: 1000000.0 | round: 1 }}M</td>
      <td>{{ m.tokens.cache_write | divided_by: 1000000.0 | round: 1 }}M</td>
      <td>{{ m.tokens.cache_read | divided_by: 1000000.0 | round: 1 }}M</td>
    </tr>
  {% endfor %}
  </tbody>
</table>
</div>

## Last 14 days

<div class="table-responsive">
<table class="table table-sm align-middle">
  <thead>
    <tr><th>Date</th><th>Est. cost</th><th>Turns</th><th>Output tokens</th></tr>
  </thead>
  <tbody>
  {% for d in ai.by_day %}
    <tr>
      <td>{{ d.date }}</td>
      <td>{% if d.est_cost_usd > 0 %}${{ d.est_cost_usd | round: 2 }}{% else %}—{% endif %}</td>
      <td>{{ d.turns }}</td>
      <td>{{ d.output_tokens }}</td>
    </tr>
  {% endfor %}
  </tbody>
</table>
</div>

<p class="small text-muted">
Generated {{ ai.generated_at }} on <code>{{ ai.machine }}</code> from the persistent
ledger (survives Claude Code's ~30-day transcript cleanup). {{ ai.pricing_note }}
The dollar estimate is a parallel accounting system, not a subscription quota gauge.
</p>
{% endif %}
