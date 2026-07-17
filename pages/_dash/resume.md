---
layout: article
title: Resume / CV
description: Resume powered by the cv-builder-pro app.
permalink: /resume/
---

# 📄 Resume / CV

The interactive resume is built and exported with [**cv-builder-pro**](https://github.com/bamr87/cv-builder-pro) — the React/Vite CV builder in the [`projects/cv-builder-pro/`](https://github.com/bamr87/cv-builder-pro) submodule, which exports LaTeX, Markdown, and ASCII.

{% assign r = site.data.resume %}
{% if r %}
## {{ r.name }}
{{ r.headline }}

{% if r.experience %}
### Experience
{% for e in r.experience %}
- **{{ e.role }}**, {{ e.company }} ({{ e.period }}) — {{ e.summary }}
{% endfor %}
{% endif %}
{% else %}
> Optionally populate `dash/_data/resume.yml` to render structured resume data here,
> or run the CV builder locally:
>
> ```bash
> cd projects/cv-builder-pro && npm install && npm run dev   # http://localhost:5000
> ```
{% endif %}
