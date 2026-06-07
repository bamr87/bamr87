---
layout: default
title: Toolbox
description: Common scripts, AI skills, templates, and MCP servers — runnable from one place.
permalink: /toolbox/
---

# 🧰 Toolbox

Everything reusable, in one place. Run any of these from the central CLI:
`tools/dash run <tool>`, scaffold a new project with `tools/dash new <name>`.

## 🔧 Scripts

{% assign scripts = site.data.scripts %}
{% if scripts %}
<div class="row">
{% for s in scripts %}
  <div class="col-md-6 mb-3">
    <div class="card h-100"><div class="card-body">
      <h6 class="card-title"><code>{{ s.name }}</code></h6>
      <p class="card-text small">{{ s.description }}</p>
      {% if s.usage %}<pre class="small"><code>{{ s.usage }}</code></pre>{% endif %}
    </div></div>
  </div>
{% endfor %}
</div>
{% else %}
<p class="text-muted"><em>Populate <code>dash/_data/scripts.yml</code> to list the <code>scripts/</code> submodule tools.</em></p>
{% endif %}

## 🤖 AI Skills

{% assign skills = site.data.skills %}
{% if skills %}
<ul>
{% for sk in skills %}
  <li><strong>{{ sk.name }}</strong> — {{ sk.description }}</li>
{% endfor %}
</ul>
{% else %}
<p class="text-muted"><em>Populate <code>dash/_data/skills.yml</code> with a curated subset of the <code>skills/</code> submodule.</em></p>
{% endif %}

## 📄 Templates

{% assign templates = site.data.templates %}
{% if templates %}
<ul>
{% for t in templates %}
  <li><a href="{{ t.path }}"><strong>{{ t.name }}</strong></a> — {{ t.description }}</li>
{% endfor %}
</ul>
{% else %}
<p class="text-muted"><em>Populate <code>dash/_data/templates.yml</code> (README template, PR/issue templates, prompts, MCP config).</em></p>
{% endif %}

## 🔌 MCP Servers

Configured in the repo root [`.mcp.json`](https://github.com/bamr87/bamr87/blob/main/.mcp.json) — available to Claude Code in this workspace.
