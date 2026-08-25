---
title: "Sitemap"
description: "Every page on this site, grouped the same way as the navigation."
layout: default
permalink: /sitemap/
---

# 🗺️ Sitemap

Every page on this site, grouped as in the header navigation. The machine-readable version is [sitemap.xml]({{ '/sitemap.xml' | relative_url }}).

{% assign nav = site.data.navigation.main %}
{% for group in nav %}

## {% if group.icon %}<i class="{{ group.icon }}"></i> {% endif %}[{{ group.title }}]({{ group.url | relative_url }})

{% if group.children and group.children.size > 0 %}
<ul>
{% for child in group.children %}
<li><a href="{{ child.url | relative_url }}">{{ child.title }}</a></li>
{% endfor %}
</ul>
{% else %}
<p><a href="{{ group.url | relative_url }}">{{ group.title }}</a></p>
{% endif %}
{% endfor %}

## 📝 Blog posts

<ul>
{% for post in site.posts %}
<li><a href="{{ post.url | relative_url }}">{{ post.title }}</a> <small class="text-muted">({{ post.date | date: "%Y-%m-%d" }})</small></li>
{% endfor %}
</ul>

<p class="small text-muted">Home is always one click away via the site title in the header. Dash pages also carry the Command Center sidebar for lateral movement.</p>
