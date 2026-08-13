---
layout: default
title: Issue Pipeline
description: The three-tier loop that turns an open issue into a merge-ready pull request — intake and evidence, implementation, completion.
permalink: /issue-pipeline/
sidebar:
  nav: dash
---

# 🧭 Issue Pipeline

Every open issue across the fleet, placed in the three-tier loop that carries it to a reviewable pull request. Snapshotted by [`.github/workflows/issue-pipeline.yml`](https://github.com/bamr87/bamr87/blob/main/.github/workflows/issue-pipeline.yml) (via `dash issues`) into `_data/issue_pipeline.yml`. Operator guide: [`docs/ISSUE-PIPELINE.md`](https://github.com/bamr87/bamr87/blob/main/docs/ISSUE-PIPELINE.md).

{% assign p = site.data.issue_pipeline %}
{% if p == nil %}
<div class="alert alert-info">
No pipeline data yet. Run <code>tools/dash issues</code> locally (needs <code>PyGithub</code> and a token that reaches the fleet), or wait for the daily <code>🧭 Issue Pipeline</code> workflow — it writes <code>_data/issue_pipeline.yml</code>, which this page renders.
</div>
{% else %}

{% unless p.enabled %}
<div class="alert alert-warning">
The pipeline is <strong>disabled</strong> in <code>_data/fleet.yml</code> (<code>issue_pipeline.enabled: false</code>). The snapshot below is still refreshed; no agent tier runs.
</div>
{% endunless %}

<div class="row text-center my-4">
  <div class="col-md-2 col-4 mb-3"><div class="card h-100"><div class="card-body p-2"><h3 class="mb-0">{{ p.totals.open_issues }}</h3><div class="text-muted small">Open issues</div></div></div></div>
  <div class="col-md-2 col-4 mb-3"><div class="card h-100"><div class="card-body p-2"><h3 class="mb-0">{{ p.totals.stages.intake | default: 0 }}</h3><div class="text-muted small">Awaiting intake</div></div></div></div>
  <div class="col-md-2 col-4 mb-3"><div class="card h-100 border-success"><div class="card-body p-2"><h3 class="mb-0 text-success">{{ p.totals.stages.ready | default: 0 }}</h3><div class="text-muted small">Ready to implement</div></div></div></div>
  <div class="col-md-2 col-4 mb-3"><div class="card h-100"><div class="card-body p-2"><h3 class="mb-0">{{ p.totals.pipeline_prs }}</h3><div class="text-muted small">Pipeline PRs</div></div></div></div>
  <div class="col-md-2 col-4 mb-3"><div class="card h-100 {% if p.totals.stages.blocked > 0 %}border-danger{% endif %}"><div class="card-body p-2"><h3 class="mb-0 {% if p.totals.stages.blocked > 0 %}text-danger{% endif %}">{{ p.totals.stages.blocked | default: 0 }}</h3><div class="text-muted small">Blocked on a human</div></div></div></div>
  <div class="col-md-2 col-4 mb-3"><div class="card h-100"><div class="card-body p-2"><h3 class="mb-0">{{ p.totals.stages.done | default: 0 }}</h3><div class="text-muted small">Handed off</div></div></div></div>
</div>

<p class="small text-muted">Snapshot {{ p.generated_at }} · {{ p.repos_scanned }} repo(s) scanned{% if p.repos_skipped %}{% for s in p.repos_skipped %} · {{ s[1].size }} {{ s[0] }}{% endfor %}{% endif %}.</p>

## This run's queues

<p class="small text-muted">The <strong>capped</strong> shortlists the agent tiers act on. Caps come from <code>_data/fleet.yml</code> → <code>issue_pipeline.tiers</code>; everything selective is decided deterministically before any model runs.</p>

### Tier 1 — intake & evidence <span class="badge bg-secondary">{{ p.totals.queued_intake }}</span>

<p class="small text-muted">Reproduced in an isolated virtual environment, rewritten into the house template, labelled, prioritized, and assigned — then marked <code>agent:ready</code> or <code>agent:blocked</code>.</p>

{% if p.queues.intake and p.queues.intake.size > 0 %}
<div class="table-responsive">
<table class="table table-sm table-hover align-middle">
  <thead><tr><th>Repo</th><th>Issue</th><th>Type</th><th>Pri</th><th>Size</th><th class="text-end">Ready</th><th>Autonomy</th><th>Gaps</th></tr></thead>
  <tbody>
  {% for i in p.queues.intake %}
    <tr class="{% if i.priority == 'P0' %}table-danger{% elsif i.priority == 'P1' %}table-warning{% endif %}">
      <td class="text-nowrap small">{{ i.repo }}</td>
      <td><a href="{{ i.url }}">#{{ i.number }} {{ i.title | escape }}</a></td>
      <td><span class="badge bg-secondary">{{ i.type }}</span></td>
      <td><strong>{{ i.priority }}</strong></td>
      <td class="small">{{ i.size | remove: 'size:' }}</td>
      <td class="text-end small">{{ i.readiness }}</td>
      <td class="small">{% if i.autonomy == 'auto' %}🤖 auto{% else %}👤 {{ i.autonomy }}{% endif %}</td>
      <td class="small">{% for g in i.gaps %}<code>{{ g.id }}</code>{% unless forloop.last %} {% endunless %}{% endfor %}</td>
    </tr>
  {% endfor %}
  </tbody>
</table>
</div>
{% else %}
<div class="alert alert-success mb-4">Nothing to intake — every open issue is enriched, blocked, in a PR, or on hold.</div>
{% endif %}

### Tier 2 — implement <span class="badge bg-secondary">{{ p.totals.queued_implement }}</span>

<p class="small text-muted">Implemented on <code>agent/issue-&lt;n&gt;</code> and landed as a <strong>draft</strong> pull request, with the test that fails before the fix and passes after.</p>

{% if p.queues.implement and p.queues.implement.size > 0 %}
<div class="table-responsive">
<table class="table table-sm table-hover align-middle">
  <thead><tr><th>Repo</th><th>Issue</th><th>Type</th><th>Pri</th><th>Size</th><th class="text-end">Ready</th><th>Autonomy</th></tr></thead>
  <tbody>
  {% for i in p.queues.implement %}
    <tr>
      <td class="text-nowrap small">{{ i.repo }}</td>
      <td><a href="{{ i.url }}">#{{ i.number }} {{ i.title | escape }}</a></td>
      <td><span class="badge bg-secondary">{{ i.type }}</span></td>
      <td><strong>{{ i.priority }}</strong></td>
      <td class="small">{{ i.size | remove: 'size:' }}</td>
      <td class="text-end small">{{ i.readiness }}</td>
      <td class="small">{% if i.autonomy == 'auto' %}🤖 auto{% else %}👤 {{ i.autonomy }}{% endif %}</td>
    </tr>
  {% endfor %}
  </tbody>
</table>
</div>
{% else %}
<div class="alert alert-info mb-4">No issue is at <code>agent:ready</code> without an open PR.</div>
{% endif %}

### Tier 3 — complete <span class="badge bg-secondary">{{ p.totals.queued_complete }}</span>

<p class="small text-muted">Driven to mergeable: CI green at the root cause, tests covering the change, docs current — then marked ready for review, unless <code>human-review</code> says a person makes that call. No tier ever merges.</p>

{% if p.queues.complete and p.queues.complete.size > 0 %}
<div class="table-responsive">
<table class="table table-sm table-hover align-middle">
  <thead><tr><th>Repo</th><th>Pull request</th><th>CI</th><th>State</th><th>Closes</th><th class="text-end">Idle</th></tr></thead>
  <tbody>
  {% for r in p.queues.complete %}
    <tr class="{% if r.ci == 'fail' %}table-danger{% endif %}">
      <td class="text-nowrap small">{{ r.repo }}</td>
      <td><a href="{{ r.url }}">#{{ r.number }} {{ r.title | escape }}</a></td>
      <td class="small">{% case r.ci %}{% when 'fail' %}<span class="badge bg-danger">fail</span>{% when 'pass' %}<span class="badge bg-success">pass</span>{% when 'pending' %}<span class="badge bg-warning text-dark">pending</span>{% else %}<span class="badge bg-secondary">{{ r.ci | default: 'none' }}</span>{% endcase %}</td>
      <td class="small">{% if r.draft %}draft{% else %}ready{% endif %}{% if r.human_review %} · 👤 human-review{% endif %}</td>
      <td class="small">{% for n in r.linked_issues %}#{{ n }} {% endfor %}</td>
      <td class="text-end small">{{ r.idle_days }}d</td>
    </tr>
  {% endfor %}
  </tbody>
</table>
</div>
{% else %}
<div class="alert alert-success mb-4">Every pipeline PR is green, non-draft, and waiting on a human.</div>
{% endif %}

## Fleet backlog by repo

<p class="small text-muted">Where every open issue sits in the state machine. Stage is derived from labels, so a human re-queues, skips, or stops any issue by editing one label.</p>

{% if p.by_repo and p.by_repo.size > 0 %}
<div class="table-responsive">
<table class="table table-sm table-hover align-middle">
  <thead><tr><th>Repo</th><th class="text-end">Open</th><th class="text-end">Intake</th><th class="text-end">Ready</th><th class="text-end">In PR</th><th class="text-end">Blocked</th><th class="text-end">Done</th><th class="text-end">Hold</th></tr></thead>
  <tbody>
  {% for r in p.by_repo %}
    <tr>
      <td><a href="{{ r.repo_url }}/issues">{{ r.name }}</a> <span class="text-muted small">{{ r.category }}</span></td>
      <td class="text-end">{{ r.open_issues }}</td>
      <td class="text-end">{{ r.stages.intake | default: 0 }}</td>
      <td class="text-end text-success">{{ r.stages.ready | default: 0 }}</td>
      <td class="text-end">{{ r.stages['in-pr'] | default: 0 }}</td>
      <td class="text-end {% if r.stages.blocked > 0 %}text-danger{% endif %}">{{ r.stages.blocked | default: 0 }}</td>
      <td class="text-end">{{ r.stages.done | default: 0 }}</td>
      <td class="text-end text-muted">{{ r.stages.hold | default: 0 }}</td>
    </tr>
  {% endfor %}
  </tbody>
</table>
</div>
{% else %}
<div class="alert alert-success">No open issues anywhere in the fleet. 🎉</div>
{% endif %}

## The label state machine

| Label | Meaning | Set by |
| --- | --- | --- |
| _(none)_ | New — awaiting intake | — |
| `agent:ready` | Enriched, evidence attached, spec complete | tier 1 |
| `agent:blocked` | A human decision is required; the question is in a comment | tier 1 or 2 |
| `agent:in-pr` | A draft pull request is open | tier 2 |
| `agent:done` | PR complete and marked ready for review | tier 3 |
| `agent:hold` | **Human brake** — excluded from every tier | a human |
| `human-review` | **Human brake** — the PR is finished but never auto-advanced | a human |

{% endif %}
