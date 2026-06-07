---
title: "Blog"
layout: home
permalink: /blog/
description: "Notes on enterprise architecture, DevOps, cloud, and AI workflows."
---

Notes on enterprise architecture, DevOps, cloud, and practical AI workflows.

<ul class="list-unstyled">
{% for post in site.posts %}
  <li class="mb-3">
    <a href="{{ post.url | relative_url }}"><strong>{{ post.title }}</strong></a>
    {% if post.date %}<br><small class="text-muted">{{ post.date | date: "%B %-d, %Y" }}</small>{% endif %}
    {% if post.excerpt %}<div>{{ post.excerpt | strip_html | truncatewords: 30 }}</div>{% endif %}
  </li>
{% else %}
  <li>No posts yet — check back soon.</li>
{% endfor %}
</ul>

<p><a href="{{ '/feed.xml' | relative_url }}">Subscribe via RSS</a></p>
