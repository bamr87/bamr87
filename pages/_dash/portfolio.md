---
layout: default
title: Projects
description: Featured and active projects, generated from the project registry.
permalink: /projects/
redirect_from:
  - /portfolio/
sidebar:
  nav: dash
---

# 🎨 Projects

Cards are generated from [`_data/projects.yml`]({{ '/toolbox/' | relative_url }}) — the single source of truth.

{% assign health = site.data.project_health %}
{% assign categories = "full-stack-ai,docs,dev-tools,dash" | split: "," %}
{% assign labels = "🚀 Full-Stack & AI,📚 Documentation,🛠️ Developer Tools,🛰️ Dash" | split: "," %}

{% for cat in categories %}
{% assign in_cat = site.data.projects | where: "category", cat %}
{% if in_cat.size > 0 %}
## {{ labels[forloop.index0] }}

<div class="row">
{% for p in in_cat %}
  <div class="col-lg-4 col-md-6 mb-4">
    <div class="card h-100 shadow-sm">
      <div class="card-body">
        <h5 class="card-title">
          <a href="{{ p.repo_url }}">{{ p.name }}</a>
          {% if p.featured %}<span class="badge bg-warning text-dark">★</span>{% endif %}
        </h5>
        <span class="badge bg-{% if p.status == 'active' %}success{% elsif p.status == 'experiment' %}info{% elsif p.status == 'archived' %}secondary{% else %}primary{% endif %}">{{ p.status }}</span>
        <p class="card-text mt-2">{{ p.description }}</p>
        <p>{% for t in p.stack %}<code class="me-1">{{ t }}</code>{% endfor %}</p>
        {% if health %}{% assign s = health | where: "name", p.name | first %}{% if s %}
        <p class="small text-muted">★ {{ s.stars }} · last commit {{ s.activity.last_commit_days }}d ago</p>
        {% endif %}{% endif %}
      </div>
      <div class="card-footer bg-transparent border-0">
        <a class="btn btn-sm btn-outline-secondary" href="{{ p.repo_url }}">Repo</a>
        {% if p.live_url %}<a class="btn btn-sm btn-outline-primary" href="{{ p.live_url }}">Live</a>{% endif %}
        {% if p.docs_url %}<a class="btn btn-sm btn-outline-info" href="{{ p.docs_url }}">Docs</a>{% endif %}
      </div>
    </div>
  </div>
{% endfor %}
</div>
{% endif %}
{% endfor %}
