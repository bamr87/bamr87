---
layout: landing
title: bamr87 Dashboard
sub-title: One place to manage, view, and evolve every project
description: Central dash, portfolio, and AI-augmented toolkit.
permalink: /
---

# 🛰️ bamr87 Dashboard

A single place to **manage**, **view**, **run**, and **evolve** a portfolio of
projects — backed by a machine-readable registry, a live monitoring board, and
an AI orchestration layer.

<div class="row text-center my-4">
  <div class="col-md-3 col-6 mb-3"><a class="btn btn-outline-primary w-100" href="{{ '/portfolio/' | relative_url }}">🎨 Portfolio</a></div>
  <div class="col-md-3 col-6 mb-3"><a class="btn btn-outline-primary w-100" href="{{ '/dashboard/' | relative_url }}">📊 Dashboard</a></div>
  <div class="col-md-3 col-6 mb-3"><a class="btn btn-outline-primary w-100" href="{{ '/monitor/' | relative_url }}">🩺 Monitor</a></div>
  <div class="col-md-3 col-6 mb-3"><a class="btn btn-outline-primary w-100" href="{{ '/toolbox/' | relative_url }}">🧰 Toolbox</a></div>
</div>

## ⚠️ Needs Attention

{% assign health = site.data.project_health %}
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
  <ul class="list-group">
    {% assign ranked = flagged | sort: "attention_rank" %}
    {% for h in ranked %}
    <li class="list-group-item d-flex justify-content-between align-items-start">
      <div>
        {% if h.attention.level == "red" %}🔴{% else %}🟠{% endif %}
        <a href="{{ h.repo_url }}">{{ h.name }}</a>
        <small class="text-muted"> — {{ h.attention.reasons | join: "; " }}</small>
      </div>
    </li>
    {% endfor %}
  </ul>
  {% endif %}
{% else %}
<p class="text-muted"><em>Monitoring data not generated yet. Run <code>tools/dash-gen health</code> (or wait for the next scheduled deploy).</em></p>
{% endif %}

## 📈 At a glance

{% assign projects = site.data.projects %}
- **{{ projects.size }}** tracked projects
- **{{ projects | where: "featured", true | size }}** featured
- **{{ projects | where: "status", "active" | size }}** active · **{{ projects | where: "status", "experiment" | size }}** experiments
