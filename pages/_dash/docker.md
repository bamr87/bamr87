---
layout: default
title: Docker
description: Every container, port and image in the fleet on one page — with a link to each running site, the version contract and what still drifts from it.
permalink: /docker/
sidebar:
  nav: dash
---

# 🐳 Docker

One page for everything containerized: **what to open**, what is running, which image each service is on, and where that diverges from the fleet's version contract. The join is done offline by `tools/dash docker view --write` over four registries that already exist — [`_data/ports.yml`](https://github.com/bamr87/bamr87/blob/main/_data/ports.yml) (allocation), [`_data/fleet.yml`](https://github.com/bamr87/bamr87/blob/main/_data/fleet.yml) `images:` (version contract), [`_data/smoke.yml`](https://github.com/bamr87/bamr87/blob/main/_data/smoke.yml) (what actually answered) and `.vscode/launch.json` (attach points) — plus the read-only [`docker_harmonize.py`](https://github.com/bamr87/bamr87/blob/main/tools/docker_harmonize.py) audit. Operator guides: [`docs/FLEET-COMPOSE.md`](https://github.com/bamr87/bamr87/blob/main/docs/FLEET-COMPOSE.md), [`docs/DOCKER.md`](https://github.com/bamr87/bamr87/blob/main/docs/DOCKER.md), [`docs/SMOKE.md`](https://github.com/bamr87/bamr87/blob/main/docs/SMOKE.md).

{% assign d = site.data.docker %}
{% if d == nil %}
<div class="alert alert-info">
No Docker view yet. Run <code>tools/dash docker view --write</code> locally — it reads committed data plus your checkout, and writes <code>_data/docker.yml</code>.
</div>
{% else %}

<div class="alert alert-secondary small">
<strong>The links below are <code>127.0.0.1</code>.</strong> They resolve on the machine running the fleet, not on this published site — same local-first posture as <a href="{{ '/ai-activity/' | relative_url }}">AI Activity</a>. Two of the inputs (the smoke recording and the conformance audit) only exist where the containers and submodules are, so this view is refreshed by the operator rather than by CI.
</div>

<div class="row text-center my-4">
  <div class="col-md-2 col-4 mb-3"><div class="card h-100"><div class="card-body p-2"><h3 class="mb-0">{{ d.summary.endpoints }}</h3><div class="text-muted small">Linkable endpoints</div></div></div></div>
  <div class="col-md-2 col-4 mb-3"><div class="card h-100 border-success"><div class="card-body p-2"><h3 class="mb-0 text-success">{{ d.summary.ok }}</h3><div class="text-muted small">Answering</div></div></div></div>
  <div class="col-md-2 col-4 mb-3"><div class="card h-100 {% if d.summary.broken > 0 %}border-danger{% endif %}"><div class="card-body p-2"><h3 class="mb-0 {% if d.summary.broken > 0 %}text-danger{% endif %}">{{ d.summary.broken }}</h3><div class="text-muted small">Broken</div></div></div></div>
  <div class="col-md-2 col-4 mb-3"><div class="card h-100 {% if d.summary.families_behind > 0 %}border-warning{% endif %}"><div class="card-body p-2"><h3 class="mb-0">{{ d.summary.families_behind }} / {{ d.images.size }}</h3><div class="text-muted small">Image families behind</div></div></div></div>
  <div class="col-md-2 col-4 mb-3"><div class="card h-100"><div class="card-body p-2"><h3 class="mb-0">{{ d.summary.pending_changes }}</h3><div class="text-muted small">Pending harmonize changes</div></div></div></div>
  <div class="col-md-2 col-4 mb-3"><div class="card h-100"><div class="card-body p-2"><h3 class="mb-0">{{ d.summary.stacks }}</h3><div class="text-muted small">Compose stacks</div></div></div></div>
</div>

<p class="small text-muted">
Generated {{ d.generated_at }} ·
{% if d.sources.smoke.present %}smoke recording {{ d.sources.smoke.recorded_at }} ({{ d.sources.smoke.age_hours }}h old){% else %}<span class="text-danger">no smoke recording</span> — run <code>tools/dash dev smoke record</code>{% endif %} ·
{{ d.sources.conformance.scanned }} repo(s) audited{% if d.sources.conformance.carried_forward > 0 %}, {{ d.sources.conformance.carried_forward }} carried forward from a previous run (not checked out){% endif %} · {{ d.sources.launch.attach_points }} launch/attach configurations.
</p>

## Open a service

<p class="small text-muted">Every allocation you can point a browser at, lowest port first. <strong>Answering</strong> means the last recording got a response on that port; <strong>on demand</strong> means it is served from inside the <code>devenv</code> container by a command you start (there is no container of its own, so the smoke harness skips it by design); <strong>profile</strong> means a compose profile gates it; <strong>unprobed</strong> means the container is up but this port is outside the registry the smoke harness walks, so nothing was measured.</p>

<div class="table-responsive">
<table class="table table-sm table-hover align-middle">
  <thead><tr><th>Port</th><th>Project</th><th>Service</th><th>Band</th><th>State</th><th>What answered</th><th>Start / attach</th></tr></thead>
  <tbody>
  {% for e in d.endpoints %}
    {% case e.verdict %}
      {% when 'ok' %}{% assign cls = 'success' %}{% assign lbl = 'answering' %}
      {% when 'broken' %}{% assign cls = 'danger' %}{% assign lbl = 'broken' %}
      {% when 'optional' %}{% assign cls = 'secondary' %}{% assign lbl = 'profile' %}
      {% when 'absent' %}{% assign cls = 'warning' %}{% assign lbl = 'stopped' %}
      {% when 'on-demand' %}{% assign cls = 'info' %}{% assign lbl = 'on demand' %}
      {% when 'unprobed' %}{% assign cls = 'info' %}{% assign lbl = 'unprobed' %}
      {% else %}{% assign cls = 'light text-dark' %}{% assign lbl = e.verdict %}
    {% endcase %}
    <tr>
      <td><a href="{{ e.url }}" target="_blank" rel="noopener"><code>{{ e.port }}</code></a></td>
      <td>{% if e.project == 'shared' %}<em>shared</em>{% else %}{{ e.project }}{% endif %}</td>
      <td><code>{{ e.service }}</code>{% if e.registered == false %} <span class="badge bg-warning text-dark" title="Published by the hub's compose but holds no _data/ports.yml allocation">unregistered</span>{% endif %}</td>
      <td class="small text-muted">{{ e.band }}</td>
      <td><span class="badge bg-{{ cls }}">{{ lbl }}</span>{% if e.health %} <span class="small text-muted">{{ e.health }}</span>{% endif %}</td>
      <td class="small">
        {%- if e.http.status -%}<code>{{ e.http.status }}</code> {{ e.http.ms }}ms{% if e.http.title %} — {{ e.http.title | escape | truncate: 60 }}{% endif %}
        {%- elsif e.comment -%}<span class="text-muted">{{ e.comment | escape }}</span>
        {%- elsif e.container -%}<span class="text-muted">container <code>{{ e.container }}</code></span>
        {%- else -%}<span class="text-muted">—</span>{%- endif -%}
      </td>
      <td class="small">{% if e.launch %}{{ e.launch }}{% elsif e.host == 'compose' %}<code>dash dev up {{ e.project }}</code>{% elsif e.alias %}<code>{{ e.alias }}</code>{% else %}—{% endif %}</td>
    </tr>
  {% endfor %}
  </tbody>
</table>
</div>

## Image contract

<p class="small text-muted">Versions live in <strong>one</strong> place — <code>_data/fleet.yml</code> <code>images:</code> — and <code>dash docker apply</code> converges every repo to it. Comparison happens <strong>at the contract's precision</strong>: <code>python:3.11</code> is behind <code>3.14</code> even though the major matches. Three things are below the contract and are <em>not</em> drift, so they are counted separately: a deliberate <code># pinned</code> (the hub's Postgres 15 holds Wiki.js content written by that major), a <code>image_overrides:</code> ceiling (law-ai's Python, because crewai publishes nothing for 3.14), and a floating tag like <code>alpine</code>, which declares no version to be behind.</p>

<div class="table-responsive">
<table class="table table-sm align-middle">
  <thead><tr><th>Family</th><th>Contract</th><th>Status</th><th>Behind</th><th>Pinned / ceiling / floating</th></tr></thead>
  <tbody>
  {% for i in d.images %}
    <tr class="{% unless i.conforming %}table-warning{% endunless %}">
      <td><code>{{ i.family }}</code></td>
      <td><strong>{{ i.contract }}</strong></td>
      <td>{% if i.conforming %}<span class="badge bg-success">at contract</span>{% else %}<span class="badge bg-warning text-dark">behind</span>{% endif %}</td>
      <td class="small">
        {%- if i.behind.size == 0 -%}—{%- else -%}
        <ul class="mb-0 ps-3">{% for b in i.behind %}<li><code>{{ b[0] }}</code> — {{ b[1] | join: ", " }}</li>{% endfor %}</ul>
        {%- endif -%}
      </td>
      <td class="small text-muted">
        {%- for p in i.pinned %}<div>📌 {{ p.project }} <code>{{ p.tag }}</code> pinned</div>{% endfor -%}
        {%- for c in i.ceilings %}<div>🧢 {{ c.project }} <code>{{ c.tag }}</code>, ceiling {{ c.ceiling }} — {{ c.reason | escape | truncate: 90 }}</div>{% endfor -%}
        {%- if i.floating.size > 0 %}<div>🌊 floating: {% for f in i.floating %}<code>{{ f }}</code> {% endfor %}</div>{% endif -%}
      </td>
    </tr>
  {% endfor %}
  </tbody>
</table>
</div>

{% if d.unmanaged_images.size > 0 %}
<p class="small text-muted"><strong>Outside the contract</strong> ({{ d.unmanaged_images.size }} images the registry does not govern — application images, and third-party services with their own release cadence): {% for u in d.unmanaged_images %}<code>{{ u }}</code>{% unless forloop.last %} · {% endunless %}{% endfor %}</p>
{% endif %}

## Stacks

<p class="small text-muted">One compose project per submodule, launched from the hub. Relational and cache allocations get a connect command rather than a link — a <code>psql://</code> href helps nobody — and the credential is read from the container's own environment, which is the only form that is right for every repo.</p>

{% for p in d.projects %}
{% if p.services.size > 0 or p.debug.size > 0 %}
<div class="card mb-3">
  <div class="card-header d-flex justify-content-between align-items-center flex-wrap gap-2">
    <div>
      <strong>{{ p.name }}</strong>
      <span class="badge bg-{% if p.host == 'hub' %}dark{% elsif p.host == 'compose' %}primary{% else %}secondary{% endif %}">{{ p.host }}</span>
      {% unless p.present %}<span class="badge bg-light text-dark">not checked out</span>{% endunless %}
      {% for c in p.counts %}<span class="small text-muted">{{ c[1] }} {{ c[0] }}</span>{% unless forloop.last %}<span class="text-muted">·</span>{% endunless %}{% endfor %}
    </div>
    <div class="small text-muted">{% if p.up %}<code>{{ p.up }}</code>{% else %}served by <code>devenv</code>{% endif %}</div>
  </div>
  <div class="card-body p-0">
    <table class="table table-sm mb-0 align-middle">
      <tbody>
      {% for s in p.services %}
        {% case s.verdict %}
          {% when 'ok' %}{% assign cls = 'success' %}
          {% when 'broken' %}{% assign cls = 'danger' %}
          {% when 'optional' %}{% assign cls = 'secondary' %}
          {% when 'absent' %}{% assign cls = 'warning' %}
          {% else %}{% assign cls = 'info' %}
        {% endcase %}
        <tr>
          <td style="width:7rem"><span class="badge bg-{{ cls }}">{{ s.verdict }}</span></td>
          <td style="width:10rem"><code>{{ s.service }}</code></td>
          <td style="width:9rem">{% if s.url %}<a href="{{ s.url }}" target="_blank" rel="noopener">{{ s.port }}</a>{% else %}<code>{{ s.port }}</code>{% endif %}
            <span class="small text-muted">{{ s.band }}</span></td>
          <td class="small">
            {%- if s.connect -%}<code>{{ s.connect }}</code>
            {%- elsif s.http.status -%}<code>{{ s.http.status }}</code> {{ s.http.ms }}ms{% if s.http.title %} — {{ s.http.title | escape | truncate: 50 }}{% endif %}
            {%- elsif s.launch -%}{{ s.launch }}
            {%- else -%}<span class="text-muted">{{ s.address }}</span>{%- endif -%}
          </td>
          <td class="small text-muted" style="width:14rem">
            {%- if s.image %}<code>{{ s.image }}</code>{% endif -%}
            {%- if s.version %} <span class="badge bg-light text-dark">{{ s.version }}</span>{% endif -%}
            {%- if s.user %} · {{ s.user }}{% endif -%}
            {%- if s.profiles.size > 0 %} · profile {{ s.profiles | join: "," }}{% endif -%}
          </td>
        </tr>
      {% endfor %}
      {% for s in p.debug %}
        <tr class="table-light">
          <td><span class="badge bg-dark">debug</span></td>
          <td><code>{{ s.service }}</code></td>
          <td><code>{{ s.port }}</code> <span class="small text-muted">{{ s.kind_detail }}</span></td>
          <td class="small">{{ s.attach }}</td>
          <td class="small text-muted">{{ s.path_mapping }}</td>
        </tr>
      {% endfor %}
      </tbody>
    </table>
  </div>
  {% if p.notes or p.excluded or p.unique or p.conformance %}
  <div class="card-footer small text-muted">
    {% if p.notes %}<div>{{ p.notes | escape }}</div>{% endif %}
    {% if p.excluded %}{% for x in p.excluded %}<div>⛔ <code>{{ x[0] }}</code> excluded — {{ x[1] | escape }}</div>{% endfor %}{% endif %}
    {% if p.unique %}<div>🔒 not deconflicted (unique to this stack):{% for u in p.unique %} <code>{{ u[0] }}</code> {{ u[1] | join: ", " }}{% endfor %}</div>{% endif %}
    {% if p.conformance %}
    <div>
      {% if p.conformance.stale %}<span class="badge bg-light text-dark">stale audit</span> {% endif %}
      {% if p.conformance.changes == 0 %}<span class="text-success">✓ harmonized</span>{% else %}<strong>{{ p.conformance.changes }}</strong> pending change(s){% for r in p.conformance.rules %} <code>{{ r[0] }}</code>×{{ r[1] }}{% endfor %}{% endif %}
      {% if p.conformance.pinned.size > 0 %} · 📌 pinned: {{ p.conformance.pinned | join: ", " }}{% endif %}
      {% for h in p.conformance.held %} · 🧢 {{ h.image }} held at {{ h.version }}{% endfor %}
      {% if p.conformance.compose_files.size > 0 %} · {{ p.conformance.compose_files | join: ", " }}{% endif %}
    </div>
    {% endif %}
  </div>
  {% endif %}
</div>
{% endif %}
{% endfor %}

## The hub's own stack

<p class="small text-muted">The hub has no override layer, so what <code>docker-compose.yml</code> declares is what runs. Four of its services are grandfathered onto the conventional ports (Wiki.js 3000, pgAdmin 5050, Postgres 5432, Redis 6379) and so appear in no band — correctly, since there is exactly one hub and nothing to deconflict, but they are working services and belong on this page.</p>

<div class="table-responsive">
<table class="table table-sm align-middle">
  <thead><tr><th>Service</th><th>Published</th><th>Registry</th><th>State</th><th>Note</th></tr></thead>
  <tbody>
  {% for h in d.hub_stack %}
    <tr>
      <td><code>{{ h.service }}</code></td>
      <td>{% if h.url %}<a href="{{ h.url }}" target="_blank" rel="noopener">{{ h.port }}</a>{% elsif h.range %}<code>{{ h.range }}</code>{% else %}<code>{{ h.port }}</code>{% endif %}
        {% if h.var %}<span class="small text-muted"><code>${{ h.var }}</code></span>{% endif %}</td>
      <td>{% if h.registered %}<span class="badge bg-success">allocated</span>{% else %}<span class="badge bg-warning text-dark">outside the registry</span>{% endif %}</td>
      <td class="small">{% if h.state %}{{ h.state }}{% if h.health %} · {{ h.health }}{% endif %}{% else %}<span class="text-muted">not running</span>{% endif %}</td>
      <td class="small text-muted">{{ h.comment | default: h.note | escape }}{% if h.image %} · <code>{{ h.image }}</code>{% endif %}</td>
    </tr>
  {% endfor %}
  </tbody>
</table>
</div>

## Shared services

<p class="small text-muted">Exactly one instance, hub-owned, on the external <code>fleet-net</code> network. An app container reaches these by alias, so nothing has to be re-pointed per project. Service names become DNS aliases on <em>every</em> network a container joins — which is why membership in <code>fleet-net</code> is earned rather than granted: a generic name like <code>db</code> on a shared network resolves for everyone.</p>

<div class="row">
{% for s in d.shared %}
  <div class="col-md-4 mb-3">
    <div class="card h-100">
      <div class="card-body">
        <h6 class="card-title"><code>{{ s.alias }}</code> {% if s.default %}<span class="badge bg-success">default</span>{% else %}<span class="badge bg-secondary">opt-in</span>{% endif %}</h6>
        <p class="small mb-1">{% for pr in s.ports %}<code>{{ pr[0] }}:{{ pr[1] }}</code> {% endfor %}{% if s.url %}· <a href="{{ s.url }}" target="_blank" rel="noopener">open</a>{% endif %}</p>
        {% if s.image %}<p class="small text-muted mb-1"><code>{{ s.image }}</code></p>{% endif %}
        <p class="small text-muted mb-0">{{ s.rationale | escape }}</p>
      </div>
    </div>
  </div>
{% endfor %}
</div>

## Port bands

<p class="small text-muted">Every allocation falls inside its role's range, and drift check (m) gates it. The old standard mandated one port map for every repo — 5432, 5000, 8000 — which is correct for one repo at a time and impossible for the fleet at once.</p>

<div class="table-responsive">
<table class="table table-sm align-middle">
  <thead><tr><th>Band</th><th>Range</th><th>Used</th><th style="width:20%">Utilization</th><th>Purpose</th></tr></thead>
  <tbody>
  {% for b in d.bands %}
    <tr>
      <td><code>{{ b.band }}</code></td>
      <td class="small">{{ b.from }}–{{ b.to }}</td>
      <td class="small">{{ b.used }} / {{ b.size }}</td>
      <td><div class="progress" style="height:.6rem"><div class="progress-bar {% if b.pct > 80 %}bg-danger{% elsif b.pct > 50 %}bg-warning{% endif %}" style="width:{{ b.pct }}%"></div></div></td>
      <td class="small text-muted">{{ b.purpose | escape }}</td>
    </tr>
  {% endfor %}
  </tbody>
</table>
</div>

## Gaps

<div class="row">
  <div class="col-lg-6 mb-3">
    <h6>Repos with Docker files and no allocation</h6>
    <p class="small text-muted">Invisible to the port gate, to the smoke harness and to <code>dash dev up</code>.</p>
    {% if d.unregistered_repos.size == 0 %}<p class="small text-success">None.</p>{% else %}
    <ul class="small">
    {% for r in d.unregistered_repos %}<li><code>{{ r.name }}</code> — {{ r.compose_files.size }} compose, {{ r.dockerfiles.size }} Dockerfile(s), {{ r.changes }} pending change(s)</li>{% endfor %}
    </ul>{% endif %}
    {% if d.missing_checkouts.size > 0 %}
    <p class="small text-muted">Registered but not checked out: {% for m in d.missing_checkouts %}<code>{{ m }}</code> {% endfor %}</p>
    {% endif %}
  </div>
  <div class="col-lg-6 mb-3">
    <h6>Containers with no allocation</h6>
    <p class="small text-muted">Normal for a service that publishes no host port — workers, one-shot jobs, and the hub's own services that are allocated elsewhere.</p>
    <div class="table-responsive" style="max-height:20rem;overflow:auto">
    <table class="table table-sm small mb-0">
      <tbody>
      {% for c in d.unallocated %}
        <tr><td>{{ c.project }}</td><td><code>{{ c.service }}</code></td><td>{{ c.state }}{% if c.health %} · {{ c.health }}{% endif %}</td><td class="text-muted">{{ c.image | truncate: 28 }}</td></tr>
      {% endfor %}
      </tbody>
    </table>
    </div>
  </div>
</div>

## Runbook

<div class="table-responsive">
<table class="table table-sm align-middle">
  <tbody>
  {% for c in d.commands %}
    <tr><td style="width:40%"><code>{{ c.cmd }}</code></td><td class="small text-muted">{{ c.does }}</td></tr>
  {% endfor %}
  </tbody>
</table>
</div>
{% endif %}
