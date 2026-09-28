---
layout: default
title: AI Activity
description: Shadow-priced Claude Code usage across every repo — tokens, sessions, and estimated API cost.
permalink: /ai-activity/
sidebar:
  nav: dash
---

# 🤖 AI Activity

Claude Code usage across **every repo touched from this machine**, shadow-priced at Anthropic API list rates from the local session ledger (`~/.claude/projects/`). Generated locally by `tools/dash ai` and **never committed** — spend data stays on your machine unless you deliberately publish it.

Two accountings live here and are deliberately kept apart. The tables below are **estimates** at list prices, derived from session transcripts. [Headless runs](#headless-runs-dash-ai-run) are **billed costs** the CLI reported for itself under `tools/dash ai run`'s dollar cap. A headless run leaves a transcript too, so the same spend appears in both — they are never summed.

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

## Headless runs (`dash ai run`)

{% assign hl = ai.headless %}
{% if hl == nil or hl.count == 0 %}
<div class="alert alert-secondary">
No headless runs recorded. <code>tools/dash ai run -- &lt;args&gt;</code> wraps
<code>claude -p</code> with the dollar ceiling from <code>_data/fleet.yml</code>
(<code>budget.local_usd</code>) and records what each run actually cost.
</div>
{% else %}

<div class="alert alert-info">
<strong>Billed, not estimated.</strong> {{ hl.note }}
</div>

<div class="row text-center my-3">
  <div class="col-md-4 col-6 mb-3"><div class="card"><div class="card-body"><h2>${{ hl.window_billed_cost_usd | round: 2 }}</h2><div class="text-muted">Billed, last {{ ai.window_days }}d</div></div></div></div>
  <div class="col-md-4 col-6 mb-3"><div class="card"><div class="card-body"><h2>${{ hl.billed_cost_usd | round: 2 }}</h2><div class="text-muted">Billed, all time</div></div></div></div>
  <div class="col-md-4 col-12 mb-3"><div class="card"><div class="card-body"><h2>{{ hl.count }}</h2><div class="text-muted">Recorded runs</div></div></div></div>
</div>

<div class="table-responsive">
<table class="table table-sm align-middle">
  <thead>
    <tr>
      <th>When</th><th>Repo</th><th>Billed</th><th>Turns</th>
      <th>Models</th><th>Source</th><th>Session</th>
    </tr>
  </thead>
  <tbody>
  {% for r in hl.runs %}
    <tr>
      <td>{{ r.timestamp | slice: 0, 16 }}</td>
      <td>{{ r.repo }}</td>
      <td>${{ r.billed_cost_usd | round: 4 }}</td>
      <td>{{ r.turns }}</td>
      <td><small>{{ r.models | join: ", " }}</small></td>
      <td><small><code>{{ r.source }}</code></small></td>
      <td><small class="text-muted">{{ r.session_id | slice: 0, 8 }}{% if r.also_in_scan %} <span class="badge bg-secondary" title="This session's transcript is also counted in the estimates above — the two numbers are the same spend measured twice, never added">also estimated</span>{% endif %}</small></td>
    </tr>
  {% endfor %}
  </tbody>
</table>
</div>
{% endif %}

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
Generated {{ ai.generated_at }} on <code>{{ ai.machine }}</code> from the persistent ledger (survives Claude Code's ~30-day transcript cleanup). {{ ai.pricing_note }} The dollar estimate is a parallel accounting system, not a subscription quota gauge.
</p>
{% endif %}
