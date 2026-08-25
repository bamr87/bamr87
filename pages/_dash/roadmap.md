---
layout: default
title: Roadmap
description: Feature backlog across every tracked repo — captured by the Future-Features pipeline.
permalink: /roadmap/
sidebar:
  nav: dash
---

# 🗺️ Roadmap

The feature backlog, generated from <code>_data/roadmap.yml</code> — the single source of truth captured by the **Future-Features** pipeline (`/future-features` + the `feature-scout` sub-agent). Each item is routed to a
target repo from [`_data/projects.yml`]({{ '/toolbox/' | relative_url }}), or to
`bamr87` for the monorepo itself.

{% assign roadmap = site.data.roadmap %}
{% if roadmap == nil or roadmap.size == 0 %}
<div class="alert alert-info">
No roadmap items yet. Capture one with <code>/future-features &lt;idea&gt;</code>, or let the <code>feature-scout</code> sub-agent harvest them from a session.
</div>
{% else %}

<div class="row text-center my-4">
  <div class="col-md-3 col-6 mb-3"><div class="card"><div class="card-body"><h2>{{ roadmap.size }}</h2><div class="text-muted">Total</div></div></div></div>
  <div class="col-md-3 col-6 mb-3"><div class="card"><div class="card-body"><h2>{{ roadmap | where: "status", "proposed" | size }}</h2><div class="text-muted">Proposed</div></div></div></div>
  <div class="col-md-3 col-6 mb-3"><div class="card"><div class="card-body"><h2>{{ roadmap | where: "status", "in-progress" | size }}</h2><div class="text-muted">In progress</div></div></div></div>
  <div class="col-md-3 col-6 mb-3"><div class="card"><div class="card-body"><h2>{{ roadmap | where: "status", "shipped" | size }}</h2><div class="text-muted">Shipped</div></div></div></div>
</div>

{% assign statuses = "in-progress,approved,backlog,proposed,shipped,declined" | split: "," %}
{% assign labels = "🚧 In progress,✅ Approved,🗂️ Backlog,💡 Proposed,🚀 Shipped,🚫 Declined" | split: "," %}

{% for st in statuses %}
{% assign items = roadmap | where: "status", st %}
{% if items.size > 0 %}
## {{ labels[forloop.index0] }} <small class="text-muted">({{ items.size }})</small>

<div class="table-responsive">
<table class="table table-sm align-middle">
  <thead>
    <tr><th>ID</th><th>Feature</th><th>Repo</th><th>Priority</th><th>Effort</th><th>Category</th></tr>
  </thead>
  <tbody>
  {% for it in items %}
    <tr>
      <td><code>{{ it.id | escape }}</code></td>
      <td>
        {% if it.issue_url %}<a href="{{ it.issue_url | escape }}">{{ it.title | escape }}</a>{% else %}{{ it.title | escape }}{% endif %}
        <br><small class="text-muted">{{ it.problem | strip_newlines | truncate: 130 | escape }}</small>
      </td>
      <td><a href="{{ it.repo_url | escape }}">{{ it.project | escape }}</a></td>
      <td><span class="badge bg-secondary">{{ it.priority | escape }}</span></td>
      <td>{{ it.effort | escape }}</td>
      <td>{{ it.category | escape }}</td>
    </tr>
  {% endfor %}
  </tbody>
</table>
</div>
{% endif %}
{% endfor %}

<p class="small text-muted">Source: <code>_data/roadmap.yml</code>. Add items with
<code>/future-features</code> or let the <code>feature-scout</code> sub-agent
harvest them from a session — nothing is backlogged without human approval.</p>
{% endif %}
