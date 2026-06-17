---
layout: home
title: "Amr Abdel-Motaleb"
permalink: /
description: "Project command center — a live dashboard, monitoring board, and analytics across every repository I build and maintain."
---

{% assign projects = site.data.projects %}
{% assign health = site.data.project_health %}
{% assign red = health | where_exp: "h", "h.attention.level == 'red'" %}
{% assign amber = health | where_exp: "h", "h.attention.level == 'amber'" %}
{% assign green = health | where_exp: "h", "h.attention.level == 'green'" %}
{% assign active = projects | where: "status", "active" %}
{% assign subs = projects | where_exp: "p", "p.submodule_path" %}
{% assign featured = projects | where: "featured", true %}
{% assign rest = projects | where_exp: "p", "p.featured != true" %}
{% assign ordered = featured | concat: rest %}

<link rel="stylesheet" href="{{ '/assets/css/dashboard.css' | relative_url }}">

<div id="command-center" markdown="0">

  <!-- ============================ HERO =============================== -->
  <section class="cc-hero">
    <p class="cc-eyebrow">⛵ bamr87 · project command center</p>
    <h1>One place to run, watch, and ship every repo.</h1>
    <p class="cc-lede">A live dashboard across {{ projects.size }} projects — registry, CI &amp; security health, and analytics — generated at deploy time from a single source of truth (<code>_data/projects.yml</code>).</p>
    <div class="cc-stats">
      <div class="cc-stat"><div class="cc-num" data-count="{{ projects.size }}">{{ projects.size }}</div><div class="cc-label">Projects</div></div>
      <div class="cc-stat"><div class="cc-num" data-count="{{ active.size }}">{{ active.size }}</div><div class="cc-label">Active</div></div>
      <div class="cc-stat"><div class="cc-num" data-count="{{ subs.size }}">{{ subs.size }}</div><div class="cc-label">Submodules</div></div>
      <div class="cc-stat"><div class="cc-num" data-count="{{ featured.size }}">{{ featured.size }}</div><div class="cc-label">Featured</div></div>
      <div class="cc-stat cc-red"><div class="cc-num" data-count="{{ red.size }}">{{ red.size }}</div><div class="cc-label">🔴 Need attention</div></div>
      <div class="cc-stat cc-amber"><div class="cc-num" data-count="{{ amber.size }}">{{ amber.size }}</div><div class="cc-label">🟠 Watch</div></div>
      <div class="cc-stat cc-green"><div class="cc-num" data-count="{{ green.size }}">{{ green.size }}</div><div class="cc-label">🟢 Healthy</div></div>
    </div>
  </section>

  <!-- ============================ TOOLS ============================== -->
  <section class="cc-section cc-reveal">
    <div class="cc-section-head"><h2>🧰 Tools</h2><span class="cc-sub">jump into a command surface</span></div>
    <div class="cc-tools">
      <a class="cc-tool" href="{{ '/dashboard/' | relative_url }}"><span class="cc-ico">📊</span> Dashboard</a>
      <a class="cc-tool" href="{{ '/monitor/' | relative_url }}"><span class="cc-ico">🩺</span> Monitor</a>
      <a class="cc-tool" href="{{ '/projects/' | relative_url }}"><span class="cc-ico">🎨</span> Portfolio</a>
      <a class="cc-tool" href="{{ '/toolbox/' | relative_url }}"><span class="cc-ico">🧪</span> Toolbox</a>
      <a class="cc-tool" href="{{ '/docs/' | relative_url }}"><span class="cc-ico">📚</span> Docs</a>
      <a class="cc-tool" href="{{ '/resume/' | relative_url }}"><span class="cc-ico">📄</span> Resume</a>
      <a class="cc-tool" href="https://github.com/bamr87" rel="noopener"><span class="cc-ico">🐙</span> GitHub Profile</a>
    </div>
  </section>

  <!-- ====================== ATTENTION SPOTLIGHT ====================== -->
  {% if red.size > 0 %}
  <section class="cc-section cc-reveal">
    <div class="cc-section-head"><h2>🚨 Needs attention now</h2><span class="cc-sub">{{ red.size }} repos flagged red — open issues, failing CI, or security alerts</span></div>
    <div class="cc-attn">
      {% assign redsorted = red | sort: "attention_rank" %}
      {% for h in redsorted %}
      <div class="cc-attn-card">
        <a href="{{ h.repo_url }}" rel="noopener">{{ h.name }}</a>
        <div class="cc-reasons">{{ h.attention.reasons | join: " · " }}</div>
      </div>
      {% endfor %}
    </div>
  </section>
  {% endif %}

  <!-- ========================= PROJECT GRID ========================== -->
  <section class="cc-section cc-reveal">
    <div class="cc-section-head"><h2>🗂️ All projects</h2><span class="cc-sub">search, filter, and sort the portfolio</span></div>

    <div class="cc-controls">
      <input id="cc-search" class="cc-search" type="search" placeholder="🔍 Search projects, stacks, descriptions…" autocomplete="off" aria-label="Search projects">
      <select id="cc-sort" class="cc-sort" aria-label="Sort projects">
        <option value="featured">Sort: Featured first</option>
        <option value="name">Sort: Name (A→Z)</option>
        <option value="health">Sort: Health (worst first)</option>
        <option value="alerts">Sort: Security alerts</option>
        <option value="recent">Sort: Recently active</option>
        <option value="stars">Sort: Stars</option>
      </select>
      <span id="cc-count" class="cc-count"></span>
    </div>

    <div class="cc-controls">
      <div class="cc-chips" role="group" aria-label="Filters">
        <span class="cc-chip" data-group="reset" data-value="all" aria-pressed="false">All</span>
        <span class="cc-chip" data-group="cat" data-value="docs" aria-pressed="false">Docs</span>
        <span class="cc-chip" data-group="cat" data-value="full-stack-ai" aria-pressed="false">Full-stack / AI</span>
        <span class="cc-chip" data-group="cat" data-value="dev-tools" aria-pressed="false">Dev tools</span>
        <span class="cc-chip" data-group="status" data-value="active" aria-pressed="false">Active</span>
        <span class="cc-chip" data-group="status" data-value="experiment" aria-pressed="false">Experiment</span>
        <span class="cc-chip" data-group="featured" data-value="true" aria-pressed="false">★ Featured</span>
        <span class="cc-chip cc-chip-red" data-group="health" data-value="red" aria-pressed="false">🔴 Red</span>
        <span class="cc-chip cc-chip-amber" data-group="health" data-value="amber" aria-pressed="false">🟠 Amber</span>
        <span class="cc-chip cc-chip-green" data-group="health" data-value="green" aria-pressed="false">🟢 Green</span>
      </div>
    </div>

    <div id="cc-grid" class="cc-grid">
      {% for p in ordered %}
      {% assign h = health | where: "name", p.name | first %}
      {% if h %}{% assign lvl = h.attention.level %}{% else %}{% assign lvl = "unknown" %}{% endif %}
      <article class="cc-card{% if p.featured %} cc-featured{% endif %}"
        data-cat="{{ p.category }}" data-status="{{ p.status }}" data-health="{{ lvl }}"
        data-featured="{% if p.featured %}true{% else %}false{% endif %}"
        data-name="{{ p.name | escape }}" data-desc="{{ p.description | escape }}"
        data-stack="{{ p.stack | join: ' ' | escape }}"
        data-stars="{{ h.stars | default: 0 }}" data-alerts="{{ h.security.alerts | default: 0 }}"
        data-commitdays="{{ h.activity.last_commit_days | default: '' }}">
        <div class="cc-card-top">
          <span class="cc-dot {{ lvl }}" title="health: {{ lvl }}"></span>
          <h3><a href="{{ p.repo_url }}" rel="noopener">{{ p.name }}</a></h3>
          {% if h.stars and h.stars > 0 %}<span class="cc-star">★ {{ h.stars }}</span>{% endif %}
        </div>
        <div class="cc-badges">
          <span class="cc-badge s-{{ p.status }}">{{ p.status }}</span>
          {% if p.featured %}<span class="cc-badge cc-fav">★ featured</span>{% endif %}
          <span class="cc-badge">{{ p.category }}</span>
          {% if p.release %}<span class="cc-badge cc-rel cc-rel-{{ p.release.status }}" title="release pipeline: {{ p.release.status }}">⚙ {{ p.release.type }}</span>{% endif %}
        </div>
        <p class="cc-desc">{{ p.description }}</p>
        <div class="cc-stack">
          {% for s in p.stack %}<span class="cc-tag">{{ s }}</span>{% endfor %}
        </div>
        {% if h %}
        <div class="cc-metrics">
          <span>CI <b>{% if h.ci.last == 'success' %}✅{% elsif h.ci.last == nil %}—{% else %}❌{% endif %} {{ h.ci.pass_rate | default: '–' }}%</b></span>
          <span class="{% if h.security.alerts > 0 %}danger{% endif %}">Sec <b>{{ h.security.alerts | default: 0 }}</b></span>
          <span>Commit <b>{% if h.activity.last_commit_days %}{{ h.activity.last_commit_days }}d{% else %}—{% endif %}</b></span>
          {% if h.release.tag %}<span>Ver <b>{{ h.release.tag }}</b></span>{% else %}<span>PRs <b>{{ h.prs.open | default: 0 }}</b></span>{% endif %}
        </div>
        {% endif %}
        <div class="cc-links">
          <a class="cc-link" href="{{ p.repo_url }}" rel="noopener">Repo</a>
          {% if p.live_url %}<a class="cc-link cc-live" href="{{ p.live_url }}" rel="noopener">Live</a>{% endif %}
          {% if p.docs_url %}<a class="cc-link" href="{{ p.docs_url }}" rel="noopener">Docs</a>{% endif %}
        </div>
      </article>
      {% endfor %}
    </div>
    <div id="cc-empty" class="cc-empty">No projects match those filters. <span style="cursor:pointer;text-decoration:underline" onclick="document.querySelector('.cc-chip[data-group=reset]').click()">Clear filters</span></div>
  </section>

  <!-- ========================== ANALYTICS =========================== -->
  <section class="cc-section cc-reveal">
    <div class="cc-section-head"><h2>📈 Analytics</h2><span class="cc-sub">computed live from the registry &amp; monitoring data</span></div>
    <div class="cc-analytics">
      <div class="cc-chart-card"><h3>Health distribution</h3><div class="cc-chart-sub">attention level across all repos</div><div class="cc-chart-wrap"><canvas id="chart-health"></canvas></div></div>
      <div class="cc-chart-card"><h3>Projects by category</h3><div class="cc-chart-sub">how the portfolio breaks down</div><div class="cc-chart-wrap"><canvas id="chart-category"></canvas></div></div>
      <div class="cc-chart-card"><h3>Projects by status</h3><div class="cc-chart-sub">active · maintenance · experiment · archived</div><div class="cc-chart-wrap"><canvas id="chart-status"></canvas></div></div>
      <div class="cc-chart-card"><h3>Top security alerts</h3><div class="cc-chart-sub">open Dependabot / code-scanning alerts</div><div class="cc-chart-wrap"><canvas id="chart-security"></canvas></div></div>
      <div class="cc-chart-card"><h3>Most-used tech</h3><div class="cc-chart-sub">stack tags across the portfolio</div><div class="cc-chart-wrap"><canvas id="chart-stack"></canvas></div></div>
    </div>
  </section>

  <p class="cc-foot">
    Single source of truth: <code>_data/projects.yml</code> · monitoring regenerated at deploy time by <code>dash-gen health</code>{% if site.data.project_health_meta.generated_at %} · last refreshed {{ site.data.project_health_meta.generated_at }}{% endif %}.
    The profile <a href="https://github.com/bamr87" rel="noopener">README</a> stays the canonical bio.
  </p>

</div>

<script>
  window.DASH_PROJECTS = {{ projects | jsonify }};
  window.DASH_HEALTH = {% if health %}{{ health | jsonify }}{% else %}[]{% endif %};
</script>
<script defer src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<script defer src="{{ '/assets/js/dashboard.js' | relative_url }}"></script>
