---
layout: default
title: AI Harnesses
description: Central management board for the fleet's AI harnesses and schedules — deployments, throughput vs caps, cost trends and forecasts, and the gaps the fan-out can close.
permalink: /harnesses/
sidebar:
  nav: dash
---

# 🛠️ AI Harnesses

The fleet's AI harness + schedule control board. Every registry repo is scanned daily for `claude-code-action` call sites and cron schedules by `dash-gen harnesses` (in [`fleet-pulse.yml`](https://github.com/bamr87/bamr87/blob/main/.github/workflows/fleet-pulse.yml)) into `_data/harness_registry.yml`, graded against the contract in `_data/fleet.yml` → `harnesses:`. This page is **read-only observation**; the levers are [`harness-fanout`](https://github.com/bamr87/bamr87/actions/workflows/harness-fanout.yml) (deploy/upgrade the kit), `token-rotation` (secrets), and the fleet-pulse doctor (failures). Operator guide: [`docs/HARNESS-OPS.md`](https://github.com/bamr87/bamr87/blob/main/docs/HARNESS-OPS.md) · the hub's own six-layer scorecard lives at [/harness/]({{ '/harness/' | relative_url }}).

{% assign hr = site.data.harness_registry %}
{% if hr == nil %}
<div class="alert alert-info">
No inventory yet. Run <code>tools/dash harnesses</code> (uses your <code>gh</code>/token; degrades to offline analytics without one), or wait for the daily <code>fleet-pulse</code> run, which writes <code>_data/harness_registry.yml</code>.
</div>
{% else %}

{% assign tp = hr.throughput %}
{% assign ai_trend = hr.trends.ai_cost_usd %}
<div class="row text-center my-4">
  <div class="col-md-2 col-6 mb-3"><div class="card h-100"><div class="card-body p-2"><h3 class="mb-0">{{ hr.totals.ai_workflows }}</h3><div class="text-muted small">AI workflows in {{ hr.totals.repos_with_ai }}/{{ hr.totals.repos_scanned }} repos</div></div></div></div>
  <div class="col-md-2 col-6 mb-3"><div class="card h-100"><div class="card-body p-2"><h3 class="mb-0">{{ hr.totals.mention_handlers }} + {{ hr.totals.scheduled_agents }}</h3><div class="text-muted small">mention handlers + scheduled agents</div></div></div></div>
  <div class="col-md-2 col-6 mb-3"><div class="card h-100 {% if tp.fleet_over_cap %}border-danger{% endif %}"><div class="card-body p-2"><h3 class="mb-0">{{ tp.est_scheduled_ai_per_day }} / {{ tp.cap_fleet }}</h3><div class="text-muted small">est. scheduled AI runs/day vs cap</div></div></div></div>
  <div class="col-md-2 col-6 mb-3"><div class="card h-100 {% if ai_trend.status == 'breach' %}border-danger{% endif %}"><div class="card-body p-2"><h3 class="mb-0">${{ ai_trend.projected_monthly }}</h3><div class="text-muted small">projected monthly AI spend (ceiling ${{ ai_trend.budget_monthly }})</div></div></div></div>
  <div class="col-md-2 col-6 mb-3"><div class="card h-100 {% if hr.totals.baseline_gaps > 0 %}border-warning{% endif %}"><div class="card-body p-2"><h3 class="mb-0">{{ hr.totals.baseline_ok }} / {{ hr.totals.baseline_ok | plus: hr.totals.baseline_gaps }}</h3><div class="text-muted small">repos at harness baseline</div></div></div></div>
  <div class="col-md-2 col-6 mb-3"><div class="card h-100 {% if hr.totals.attention > 0 %}border-warning{% endif %}"><div class="card-body p-2"><h3 class="mb-0">{{ hr.totals.attention }}</h3><div class="text-muted small">attention items</div></div></div></div>
</div>

<p class="small text-muted">Snapshot {{ hr.generated_at }} · scan {{ hr.scan.mode }}{% if hr.scan.scanned_at %} ({{ hr.scan.scanned_at }}){% endif %} · contract kit <code>{{ hr.contract.kit }} v{{ hr.contract.kit_version }}</code> · usage joins carry the committed ledgers' windows.</p>

## Attention

<p class="small text-muted">Ranked findings, strongest first, each naming its lever. A finding is an <strong>observation for a human or a dry-run fan-out</strong> — nothing on this board writes to a fleet repo.</p>

{% if hr.attention.size > 0 %}
<div class="table-responsive">
<table class="table table-sm align-middle">
  <thead><tr><th></th><th>Kind</th><th>Repo</th><th>Finding</th><th>Lever</th></tr></thead>
  <tbody>
  {% for a in hr.attention %}
    <tr class="{% if a.severity >= 80 %}table-danger{% elsif a.severity >= 60 %}table-warning{% endif %}">
      <td class="small text-muted">{{ a.severity }}</td>
      <td><code>{{ a.kind }}</code></td>
      <td>{% if a.repo %}<code>{{ a.repo }}</code>{% else %}<span class="text-muted">fleet</span>{% endif %}</td>
      <td class="small">{{ a.summary | escape }}</td>
      <td class="small text-muted">{{ a.action | escape }}</td>
    </tr>
  {% endfor %}
  </tbody>
</table>
</div>
{% else %}
<div class="alert alert-success">No attention items — deployments, throughput, and spend are inside the contract.</div>
{% endif %}

## Cost trends &amp; forecast

<div class="row">
{% assign trend_keys = "ai_cost_usd|Claude CI spend (USD)|actions_minutes|Actions minutes" | split: "|" %}
{% for i in (0..1) %}{% assign k = i | times: 2 %}{% assign t = hr.trends[trend_keys[k]] %}{% assign lbl = k | plus: 1 %}
  <div class="col-md-6 mb-3">
    <div class="card h-100 {% if t.status == 'breach' %}border-danger{% elsif t.status == 'growing' %}border-warning{% endif %}">
      <div class="card-header d-flex justify-content-between"><strong>{{ trend_keys[lbl] }}</strong>
        <span class="badge {% if t.status == 'breach' %}bg-danger{% elsif t.status == 'growing' %}bg-warning text-dark{% elsif t.status == 'ok' %}bg-success{% else %}bg-secondary{% endif %}">{{ t.status }}</span></div>
      <div class="card-body p-2 small">
        <table class="table table-sm mb-0">
          <tr><td>Window total</td><td class="text-end">{{ t.window_total }}</td></tr>
          <tr><td>Last 7d / prior 7d</td><td class="text-end">{{ t.last7 }} / {{ t.prior7 }}</td></tr>
          <tr><td>Week-over-week</td><td class="text-end">{% if t.wow_delta_pct %}{{ t.wow_delta_pct }}%{% else %}—{% endif %}</td></tr>
          <tr><td><strong>Projected monthly</strong></td><td class="text-end"><strong>{{ t.projected_monthly }}</strong> vs ceiling {{ t.budget_monthly }}</td></tr>
        </table>
      </div>
    </div>
  </div>
{% endfor %}
</div>

<p class="small text-muted">Projection = last-7-day daily average × 30.44; the driver detail lives on <a href="{{ '/ai-usage/' | relative_url }}">/ai-usage/</a> and <a href="{{ '/actions/' | relative_url }}">/actions/</a>. Ceilings and the growth threshold are <code>harnesses.budget</code> in <code>_data/fleet.yml</code>.</p>

## Throughput

<div class="row">
  <div class="col-md-6">
    <ul class="small">
      <li>Estimated <strong>scheduled</strong> AI runs/day (from cron math): <strong>{{ tp.est_scheduled_ai_per_day }}</strong> vs fleet cap {{ tp.cap_fleet }} — per-repo cap {{ tp.cap_per_repo }}, max {{ tp.cap_per_utc_hour }} AI crons per UTC hour.</li>
      <li>Observed AI runs/day, <em>all</em> triggers (ai_usage window): <strong>{{ tp.observed_ai_runs_per_day | default: "—" }}</strong> — mention/PR traffic rides on top of the scheduled floor.</li>
    </ul>
  </div>
  <div class="col-md-6">
    {% if tp.repos_over_cap.size > 0 %}<p class="small mb-1"><strong>Over per-repo cap:</strong> {% for v in tp.repos_over_cap %}<code>{{ v.repo }}</code> ({{ v.est_per_day }}/d) {% endfor %}</p>{% endif %}
    {% if tp.hour_collisions.size > 0 %}<p class="small mb-1"><strong>UTC-hour collisions</strong> (the Claude loops share one OAuth account's rate limit):</p>
    <ul class="small">{% for c in tp.hour_collisions %}<li>{{ c.utc_hour }} — {{ c.count }} crons: {% for e in c.entries limit: 6 %}<code>{{ e }}</code> {% endfor %}</li>{% endfor %}</ul>{% endif %}
    {% if tp.repos_over_cap.size == 0 and tp.hour_collisions.size == 0 %}<p class="small text-success">No cap or adjacency violations.</p>{% endif %}
  </div>
</div>

## Deployment matrix

<p class="small text-muted">Which repo carries which harness, on which auth shape and kit version. <span class="badge bg-secondary">exempt</span> = external, archived, or excused in <code>harnesses.exempt</code>. Gaps sort first — they are what <code>harness-fanout</code>'s <code>gaps</code> target deploys to.</p>

<div class="table-responsive">
<table class="table table-sm align-middle">
  <thead><tr><th>Repo</th><th>Harness workflows</th><th>Auth</th><th>Kit</th><th>Context</th><th>OAuth secret</th><th class="text-end">Sched AI/day</th><th class="text-end">AI cost (win)</th><th>Baseline</th></tr></thead>
  <tbody>
  {% for r in hr.repos %}
    <tr class="{% unless r.coverage.ok or r.coverage.exempt %}table-warning{% endunless %}">
      <td><a href="https://github.com/{{ r.nwo }}"><code>{{ r.repo }}</code></a>{% if r.manifest %} <span title="declares fleet.manifest.yml">📜</span>{% endif %}{% if r.factory %} <span title="GitFactory-managed: .factory/ blueprints{% if r.factory_blueprints and r.factory_blueprints.size > 0 %} ({{ r.factory_blueprints | join: ', ' }}){% endif %}">⚙</span>{% endif %}</td>
      <td class="small">{% if r.harnesses.size > 0 %}{% for h in r.harnesses %}<div>{% case h.kind %}{% when 'mention-handler' %}💬{% when 'scheduled-agent' %}⏰{% else %}⚙️{% endcase %} <code>{{ h.path | replace: '.github/workflows/', '' }}</code>{% if h.model %} <span class="text-muted">{{ h.model }}{% if h.max_turns %}/{{ h.max_turns }}t{% endif %}</span>{% endif %}{% if h.last_conclusion == 'failure' %} <span class="badge bg-danger">failing</span>{% endif %}</div>{% endfor %}{% else %}<span class="text-muted">—</span>{% endif %}</td>
      <td class="small">{% for h in r.harnesses %}<div>{% if h.auth == 'oauth-first' or h.auth == 'oauth-only' %}<span class="text-success">{{ h.auth }}</span>{% else %}<span class="text-danger">{{ h.auth }}</span>{% endif %}</div>{% endfor %}</td>
      <td class="small">{% for h in r.harnesses %}<div>{% case h.kit_status %}{% when 'current' %}<span class="badge bg-success">v{{ h.kit }}</span>{% when 'upgradeable' %}<span class="badge bg-warning text-dark">v{{ h.kit }} ↑</span>{% when 'unstamped' %}<span class="text-muted">unstamped</span>{% else %}<span class="text-muted">{{ h.kit_status }}</span>{% endcase %}</div>{% endfor %}</td>
      <td class="small">{% if r.agent_context %}<code>{{ r.agent_context }}</code>{% else %}<span class="text-muted">—</span>{% endif %}</td>
      <td class="small">{% case r.oauth_secret %}{% when 'ok', 'hub' %}<span class="text-success">{{ r.oauth_secret }}</span>{% when 'stale' %}<span class="text-warning">stale</span>{% when 'missing' %}<span class="text-danger">missing</span>{% else %}<span class="text-muted">{{ r.oauth_secret }}</span>{% endcase %}</td>
      <td class="text-end small">{{ r.est_scheduled_ai_per_day }}</td>
      <td class="text-end small">{% if r.ai_usage and r.ai_usage.cost_usd %}${{ r.ai_usage.cost_usd }}{% else %}—{% endif %}</td>
      <td class="small">{% if r.coverage.exempt %}<span class="badge bg-secondary">exempt</span>{% elsif r.coverage.ok %}<span class="badge bg-success">ok</span>{% else %}{% for m in r.coverage.missing %}<span class="badge bg-warning text-dark">{{ m }}</span> {% endfor %}{% endif %}</td>
    </tr>
  {% endfor %}
  </tbody>
</table>
</div>

## Fleet schedule (UTC)

<p class="small text-muted">Every cron the scan found — AI first, then by standing load. Estimated fires/day is cron arithmetic (weekly ≈ 0.14), a load-planning figure rather than a fire predictor.</p>

<div class="table-responsive">
<table class="table table-sm align-middle">
  <thead><tr><th></th><th>Repo</th><th>Workflow</th><th>Cron</th><th>Schedule</th><th class="text-end">est/day</th></tr></thead>
  <tbody>
  {% for s in hr.schedule %}
    <tr>
      <td>{% if s.ai %}🤖{% endif %}</td>
      <td><code>{{ s.repo }}</code></td>
      <td class="small">{{ s.workflow }}</td>
      <td><code>{{ s.cron }}</code></td>
      <td class="small">{{ s.human }}</td>
      <td class="text-end small">{{ s.est_per_day | default: "?" }}</td>
    </tr>
  {% endfor %}
  </tbody>
</table>
</div>

## Operate

```bash
tools/dash harnesses                 # rebuild the inventory now (offline degrade without a token)
tools/dash harnesses gaps            # the repos the fan-out can fix, one per line
tools/dash harnesses deploy --gaps   # dry-run kit PRs for exactly those repos
tools/dash harnesses deploy --gaps --apply --upgrade   # open the PRs, refresh machine seeds
tools/dash config show harnesses     # the contract in force
```

CI equivalents: the daily refresh rides `fleet-pulse.yml`; mass deploy/update is the [`harness-fanout`](https://github.com/bamr87/bamr87/actions/workflows/harness-fanout.yml) dispatch (`target: gaps`, dry-run default). Full runbook — including the local Docker stack and the enterprise/cloud architecture — in [`docs/HARNESS-OPS.md`](https://github.com/bamr87/bamr87/blob/main/docs/HARNESS-OPS.md).
{% endif %}
