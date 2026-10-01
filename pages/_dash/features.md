---
layout: default
title: Fleet Features
description: Every feature in the fleet with its docs, tests, user scenarios, evidence bundles, screenshots, and verification stamp — the index agents read for context, graded for coverage.
permalink: /features/
sidebar:
  nav: dash
---

# 🧪 Fleet Features

One listing of **what every repo does for a user** and **what proves it**. Each repo's `features/features.yml` (schema `features/v1`) is aggregated by `dash features fleet --write` (in [`fleet-pulse.yml`](https://github.com/bamr87/bamr87/blob/main/.github/workflows/fleet-pulse.yml)) into `_data/features_index.yml`, with coverage graded from **files on disk**: a feature is *covered* when a test or a user scenario exists, *evidenced* when a `test/evidence/<slug>/` bundle exists, *verified* when it carries a `verified:` stamp from the runner, an agent pass, or a human. This page is read-only observation; the levers are the `verify` PR label (the Claude Code pass in `fleet-verify.yml`), `node verify/runner.mjs --stamp`, and [`verify-fanout`](https://github.com/bamr87/bamr87/actions/workflows/verify-fanout.yml) (seed the kit). Standard: [`docs/VERIFICATION.md`](https://github.com/bamr87/bamr87/blob/main/docs/VERIFICATION.md) · spec rows UPS-QA-50..53.

{% assign fx = site.data.features_index %}
{% if fx == nil %}
<div class="alert alert-info">
No index yet. Run <code>tools/dash features fleet --write</code> (offline — reads every checked-out submodule), or wait for the daily <code>fleet-pulse</code> run, which writes <code>_data/features_index.yml</code>.
</div>
{% else %}

{% assign t = fx.totals %}
<div class="row text-center my-4">
  <div class="col-md-2 col-6 mb-3"><div class="card h-100"><div class="card-body p-2"><h3 class="mb-0">{{ t.features }}</h3><div class="text-muted small">features in {{ t.repos_with_index }}/{{ t.repos_scanned }} indexed repos</div></div></div></div>
  <div class="col-md-2 col-6 mb-3"><div class="card h-100"><div class="card-body p-2"><h3 class="mb-0">{{ fx.pct.coverage }}%</h3><div class="text-muted small">covered (test or scenario)</div></div></div></div>
  <div class="col-md-2 col-6 mb-3"><div class="card h-100 {% if fx.pct.ui_coverage < 80 %}border-warning{% endif %}"><div class="card-body p-2"><h3 class="mb-0">{{ t.ui_covered }} / {{ t.ui }}</h3><div class="text-muted small">UI features covered</div></div></div></div>
  <div class="col-md-2 col-6 mb-3"><div class="card h-100"><div class="card-body p-2"><h3 class="mb-0">{{ fx.pct.evidence }}%</h3><div class="text-muted small">evidenced · {{ t.screenshots }} screenshots</div></div></div></div>
  <div class="col-md-2 col-6 mb-3"><div class="card h-100 {% if fx.pct.verified < 50 %}border-warning{% endif %}"><div class="card-body p-2"><h3 class="mb-0">{{ fx.pct.verified }}%</h3><div class="text-muted small">verified ({{ t.verified }} stamped)</div></div></div></div>
  <div class="col-md-2 col-6 mb-3"><div class="card h-100 {% if t.repos_no_index > 0 %}border-warning{% endif %}"><div class="card-body p-2"><h3 class="mb-0">{{ t.repos_no_index | plus: t.repos_prose_only }}</h3><div class="text-muted small">repos without an index</div></div></div></div>
</div>

<p class="small text-muted">Snapshot {{ fx.generated_at }} · kit <code>verify v{{ fx.kit_version }}</code> · {{ t.scenarios }} user scenarios · {{ t.dangling }} dangling links.</p>

## Attention

<p class="small text-muted">Ranked, strongest first; each names its lever. Nothing here writes to a repo.</p>

{% if fx.attention.size > 0 %}
<div class="table-responsive">
<table class="table table-sm align-middle">
  <thead><tr><th></th><th>Repo</th><th>Finding</th><th>Lever</th></tr></thead>
  <tbody>
  {% for a in fx.attention %}
    <tr class="{% if a.severity >= 80 %}table-danger{% elsif a.severity >= 60 %}table-warning{% endif %}">
      <td><span class="badge bg-secondary">{{ a.kind }}</span></td>
      <td class="text-nowrap">{{ a.repo }}</td>
      <td class="small">{{ a.detail | escape }}</td>
      <td class="small"><code>{{ a.lever | escape }}</code></td>
    </tr>
  {% endfor %}
  </tbody>
</table>
</div>
{% else %}
<div class="alert alert-success">Every indexed UI feature is covered and verified. 🎉</div>
{% endif %}

## Repos

<div class="table-responsive">
<table class="table table-sm table-hover align-middle">
  <thead><tr><th>Repo</th><th>Index</th><th class="text-end">Features</th><th class="text-end">UI covered</th><th class="text-end">Coverage</th><th class="text-end">Verified</th><th>Kit</th><th>Last run</th></tr></thead>
  <tbody>
  {% for r in fx.repos %}
    <tr>
      <td class="text-nowrap"><a href="#repo-{{ r.slug }}">{{ r.name }}</a></td>
      <td class="small">{% if r.index.path %}<code>{{ r.index.format }}</code>{% unless r.index.valid %} <span class="badge bg-danger">invalid</span>{% endunless %}{% else %}<span class="text-muted">none</span>{% endif %}</td>
      <td class="text-end">{{ r.counts.features }}</td>
      <td class="text-end">{{ r.counts.ui_covered }} / {{ r.counts.ui }}</td>
      <td class="text-end">{{ r.pct.coverage }}%</td>
      <td class="text-end">{{ r.pct.verified }}%</td>
      <td class="small">{% if r.kit.config %}config{% endif %}{% if r.kit.scenarios > 0 %} · {{ r.kit.scenarios }} scen{% endif %}{% if r.kit.workflow %} · ci{% if r.kit.workflow_gate %} (gated){% endif %}{% endif %}{% if r.kit.skill %} · skill{% endif %}{% if r.kit.legacy_evidence_kit %} · evidence-kit{% endif %}</td>
      <td class="small">{% if r.last_run %}{{ r.last_run.passed }}/{{ r.last_run.total }} {{ r.last_run.by }} {{ r.last_run.generated | slice: 0, 10 }}{% else %}—{% endif %}</td>
    </tr>
  {% endfor %}
  </tbody>
</table>
</div>

{% for r in fx.repos %}
{% if r.counts.features > 0 %}
<h3 id="repo-{{ r.slug }}">{{ r.name }} <small class="text-muted">{{ r.counts.features }} features · {{ r.pct.coverage }}% covered · {{ r.pct.verified }}% verified</small></h3>

<p class="small"><a href="{{ r.repo_url }}">{{ r.repo_url }}</a>{% if r.live_url %} · <a href="{{ r.live_url }}">live</a>{% endif %}{% if r.index.path %} · <a href="{{ r.repo_url }}/blob/{{ r.branch }}/{{ r.index.path }}"><code>{{ r.index.path }}</code></a>{% endif %}</p>

{% if r.gaps.size > 0 %}
<ul class="small">
{% for g in r.gaps %}<li>{{ g | escape }}</li>{% endfor %}
</ul>
{% endif %}

{% if r.counts.features > 0 %}
<div class="table-responsive">
<table class="table table-sm align-middle">
  <thead><tr><th>Id</th><th>Feature</th><th>Surface</th><th>Docs</th><th>Proof</th><th>Evidence</th><th>Verified</th></tr></thead>
  <tbody>
  {% for f in r.items %}
    <tr class="{% if f.implemented and f.surface == 'ui' and f.covered == false %}table-warning{% endif %}">
      <td class="text-nowrap"><code>{{ f.id }}</code>{% unless f.implemented %}<br><span class="badge bg-secondary">planned</span>{% endunless %}</td>
      <td>{% if f.urls.link %}<a href="{{ f.urls.link }}">{{ f.title | escape }}</a>{% else %}{{ f.title | escape }}{% endif %}<div class="small text-muted">{{ f.summary | escape }}</div>{% if f.tags.size > 0 %}<div class="small">{% for tg in f.tags limit: 6 %}<span class="badge bg-light text-dark">{{ tg }}</span> {% endfor %}</div>{% endif %}</td>
      <td class="small">{{ f.surface }}</td>
      <td class="small">{% if f.urls.docs %}<a href="{{ f.urls.docs }}">docs</a>{% else %}—{% endif %}</td>
      <td class="small">{% for u in f.urls.tests %}<a href="{{ u }}">test</a> {% endfor %}{% for u in f.urls.scenarios %}<a href="{{ u }}">scenario</a> {% endfor %}{% if f.waived.size > 0 %}<span class="text-muted" title="{{ f.waived | first | escape }}">n/a</span>{% endif %}{% if f.covered == false %}<span class="text-danger">none</span>{% endif %}{% if f.dangling.size > 0 %} <span class="badge bg-warning text-dark" title="{{ f.dangling | join: ', ' | escape }}">dangling</span>{% endif %}</td>
      <td class="small">{% for u in f.urls.evidence %}<a href="{{ u }}">bundle</a> {% endfor %}{% if f.urls.screenshots.size > 0 %}<a href="{{ f.urls.screenshots | first }}"><img src="{{ f.urls.screenshots | first }}" alt="{{ f.title | escape }} screenshot" loading="lazy" style="max-width:140px;max-height:90px;border:1px solid var(--bs-border-color)"></a>{% if f.urls.screenshots.size > 1 %} <span class="text-muted">+{{ f.urls.screenshots.size | minus: 1 }}</span>{% endif %}{% elsif f.urls.evidence.size == 0 %}—{% endif %}</td>
      <td class="small text-nowrap">{% if f.verified %}{% if f.verified.run %}<a href="{{ f.verified.run }}">{% endif %}{{ f.verified.date }} {{ f.verified.by }}{% if f.verified.run %}</a>{% endif %}{% else %}—{% endif %}</td>
    </tr>
  {% endfor %}
  </tbody>
</table>
</div>
{% if r.truncated %}<p class="small text-muted">Truncated — see the repo's index for the full list.</p>{% endif %}
{% endif %}
{% endif %}
{% endfor %}

{% endif %}
