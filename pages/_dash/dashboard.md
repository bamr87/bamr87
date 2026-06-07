---
layout: default
title: Dashboard
description: Command center — at-a-glance metrics and repos that need attention.
permalink: /dashboard/
sidebar:
  nav: dash
---

# 📊 Dashboard

A single place to **manage**, **view**, **run**, and **evolve** the project
portfolio — backed by a machine-readable registry, a live monitoring board, and
an AI orchestration layer.

<div class="row text-center my-4">
  <div class="col-md-3 col-6 mb-3"><a class="btn btn-outline-primary w-100" href="{{ '/projects/' | relative_url }}">🎨 Portfolio</a></div>
  <div class="col-md-3 col-6 mb-3"><a class="btn btn-outline-primary w-100" href="{{ '/monitor/' | relative_url }}">🩺 Monitor</a></div>
  <div class="col-md-3 col-6 mb-3"><a class="btn btn-outline-primary w-100" href="{{ '/toolbox/' | relative_url }}">🧰 Toolbox</a></div>
  <div class="col-md-3 col-6 mb-3"><a class="btn btn-outline-primary w-100" href="{{ '/resume/' | relative_url }}">📄 Resume</a></div>
</div>

{% assign projects = site.data.projects %}
{% assign health = site.data.project_health %}

<div class="row text-center my-4">
  <div class="col-md-3 col-6 mb-3"><div class="card"><div class="card-body"><h2>{{ projects.size }}</h2><div class="text-muted">Projects</div></div></div></div>
  <div class="col-md-3 col-6 mb-3"><div class="card"><div class="card-body"><h2>{{ projects | where: "status", "active" | size }}</h2><div class="text-muted">Active</div></div></div></div>
  <div class="col-md-3 col-6 mb-3"><div class="card"><div class="card-body"><h2>{{ projects | where_exp: "p", "p.submodule_path" | size }}</h2><div class="text-muted">Submodules</div></div></div></div>
  <div class="col-md-3 col-6 mb-3"><div class="card"><div class="card-body"><h2>{{ projects | where: "featured", true | size }}</h2><div class="text-muted">Featured</div></div></div></div>
</div>

## ⚠️ Needs Attention

{% if health %}
  {% assign flagged = "" | split: "" %}
  {% for h in health %}
    {% if h.attention.level == "red" or h.attention.level == "amber" %}
      {% assign flagged = flagged | push: h %}
    {% endif %}
  {% endfor %}
  {% if flagged.size == 0 %}
  <p>✅ All tracked repositories are healthy.</p>
  {% else %}
  <ul class="list-group mb-4">
    {% assign ranked = flagged | sort: "attention_rank" %}
    {% for h in ranked %}
    <li class="list-group-item">
      {% if h.attention.level == "red" %}🔴{% else %}🟠{% endif %}
      <a href="{{ h.repo_url }}">{{ h.name }}</a>
      <small class="text-muted"> — {{ h.attention.reasons | join: "; " }}</small>
    </li>
    {% endfor %}
  </ul>
  {% endif %}

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
<p class="text-muted"><em>Monitoring data not generated yet — run <code>tools/dash-gen health</code> (or wait for the next scheduled deploy). See <a href="{{ '/monitor/' | relative_url }}">Monitor</a>.</em></p>
{% endif %}

## Projects by category

| Category | Count |
|---|---|
{% assign cats = projects | group_by: "category" -%}
{% for c in cats %}| {{ c.name }} | {{ c.size }} |
{% endfor %}
