---
layout: default
title: Dashboard
description: At-a-glance metrics across all tracked projects.
permalink: /dashboard/
---

# 📊 Dashboard

{% assign projects = site.data.projects %}
{% assign health = site.data.project_health %}

<div class="row text-center my-4">
  <div class="col-md-3 col-6 mb-3"><div class="card"><div class="card-body"><h2>{{ projects.size }}</h2><div class="text-muted">Projects</div></div></div></div>
  <div class="col-md-3 col-6 mb-3"><div class="card"><div class="card-body"><h2>{{ projects | where: "status", "active" | size }}</h2><div class="text-muted">Active</div></div></div></div>
  <div class="col-md-3 col-6 mb-3"><div class="card"><div class="card-body"><h2>{{ projects | where_exp: "p", "p.submodule_path" | size }}</h2><div class="text-muted">Submodules</div></div></div></div>
  <div class="col-md-3 col-6 mb-3"><div class="card"><div class="card-body"><h2>{{ projects | where: "featured", true | size }}</h2><div class="text-muted">Featured</div></div></div></div>
</div>

{% if health %}
<div class="row text-center my-4">
  {% assign red = health | where_exp: "h", "h.attention.level == 'red'" %}
  {% assign amber = health | where_exp: "h", "h.attention.level == 'amber'" %}
  {% assign green = health | where_exp: "h", "h.attention.level == 'green'" %}
  <div class="col-md-4 mb-3"><div class="card border-danger"><div class="card-body"><h2>🔴 {{ red.size }}</h2><div class="text-muted">Need attention</div></div></div></div>
  <div class="col-md-4 mb-3"><div class="card border-warning"><div class="card-body"><h2>🟠 {{ amber.size }}</h2><div class="text-muted">Watch</div></div></div></div>
  <div class="col-md-4 mb-3"><div class="card border-success"><div class="card-body"><h2>🟢 {{ green.size }}</h2><div class="text-muted">Healthy</div></div></div></div>
</div>

<p>See the <a href="{{ '/monitor/' | relative_url }}">Monitor</a> board for the full per-repo breakdown.</p>
{% else %}
<p class="text-muted"><em>Health metrics not generated yet — run <code>tools/dash-gen health</code>. See <a href="{{ '/monitor/' | relative_url }}">Monitor</a>.</em></p>
{% endif %}

## Projects by category

| Category | Count |
|---|---|
{% assign cats = projects | group_by: "category" -%}
{% for c in cats %}| {{ c.name }} | {{ c.size }} |
{% endfor %}
