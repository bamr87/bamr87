---
layout: article
title: Documentation
description: Entry points into the documentation across projects.
permalink: /docs/
---

# 📚 Documentation

Deep documentation lives in each project. The dash links out rather than re-aggregating.

## Dash & monorepo

- [Dash architecture](https://github.com/bamr87/bamr87/blob/main/docs/DASH.md)
- [Monorepo guide](https://github.com/bamr87/bamr87/blob/main/docs/MONOREPO.md)
- [Architecture](https://github.com/bamr87/bamr87/blob/main/docs/ARCHITECTURE.md)
- [Development](https://github.com/bamr87/bamr87/blob/main/docs/DEVELOPMENT.md)
- [Submodules](https://github.com/bamr87/bamr87/blob/main/SUBMODULES.md)

## Per-project docs

{% assign with_docs = site.data.projects | where_exp: "p", "p.docs_url" %}
<ul>
{% for p in with_docs %}
  {% if p.docs_url %}<li><a href="{{ p.docs_url }}">{{ p.name }}</a> — {{ p.description }}</li>{% endif %}
{% endfor %}
</ul>
