---
layout: home
title: "Amr Abdel-Motaleb"
permalink: /
mermaid: true
description: "Solutions Architect & ERP Specialist — building sustainable enterprise systems and empowering teams."
---

<div class="text-center my-5">

# 👋 Hi, I'm Amr Abdel-Motaleb

**Solutions Architect · ERP Specialist · Full-Stack Developer**

I build sustainable enterprise systems and empower internal teams, transforming
technology from a cost center into a strategic advantage.

[Connect on LinkedIn](https://linkedin.com/in/amrabdel){: .btn .btn-primary }
[bashconsultants.com](https://bashconsultants.com){: .btn .btn-outline-secondary }
[Download CV](https://github.com/bamr87/cv/blob/main/cv.pdf){: .btn .btn-outline-secondary }

</div>

---

## Explore

- 🚀 **[About](/about/)** — who I am and the technology I work with
- 💼 **[Experience](/experience/)** — 15+ years across ERP, finance systems, and engineering
- 🎯 **[Services](/services/)** — how I help teams build sustainable systems
- 🌐 **[Projects](/projects/)** — open-source tools, docs platforms, and apps
- ✍️ **[Blog](/blog/)** — notes on architecture, DevOps, and AI workflows
- 📬 **[Contact](/contact/)** — let's collaborate

---

## ⭐ Featured Projects

A snapshot of what I'm actively building — see the [full portfolio](/projects/) for everything.

<div class="row">
{% assign featured = site.data.projects | where: "featured", true %}
{% for p in featured %}
  <div class="col-lg-4 col-md-6 mb-4">
    <div class="card h-100 shadow-sm">
      <div class="card-body">
        <h5 class="card-title"><a href="{{ p.repo_url }}">{{ p.name }}</a></h5>
        <span class="badge bg-{% if p.status == 'active' %}success{% elsif p.status == 'experiment' %}info{% elsif p.status == 'archived' %}secondary{% else %}primary{% endif %}">{{ p.status }}</span>
        <p class="card-text mt-2">{{ p.description }}</p>
        <p>{% for t in p.stack %}<code class="me-1">{{ t }}</code>{% endfor %}</p>
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

---

## My Philosophy: People Over Profits

- 🌱 **Sustainable Technology** — building systems that adapt and scale with your business.
- 👥 **Employee Empowerment** — transferring knowledge to make your team self-sufficient.
- 📚 **Knowledge Sharing** — advancing collective capability through open-source education.
- 🌍 **Balanced Innovation** — treating environmental and social impact as measurable business drivers.

## Learning & Knowledge Sharing

I document my journey through three interconnected platforms:

- 🎯 **[it-journey.dev](https://it-journey.dev)** — tutorials on enterprise systems, DevOps, and cloud architecture.
- 🎨 **[zer0-mistakes.com](https://zer0-mistakes.com)** — software architecture patterns, UI/UX, and system design.
- 🚀 **[barodybroject.com](https://barodybroject.com)** — full-stack applications and integration showcases.

---

## Career at a Glance

```mermaid
mindmap
  root((Amr Abdel-Motaleb))
    Enterprise Architecture
      ERP Systems
        QAD ERP Suite
        Infor Cloud
        SAP Systems
      Financial Systems
        OneStream
        Oracle HFM
        Tagetik EPM
      System Integration
        RESTful APIs
        SOAP Services
        Data Warehousing
    Full-Stack Development
      Backend
        Python Django
        Ruby on Rails
        Node.js
      Frontend
        Angular
        React
        Jekyll
      DevOps
        Docker
        CI/CD Pipelines
        Cloud Orchestration
    Cloud Architecture
      AWS Services
      Azure Platform
      Google Cloud
      Multi-Cloud Strategy
    AI & Innovation
      AI Agent Platforms
      Prompt Engineering
      Intelligent Automation
      ML Integration
    Industry Expertise
      Manufacturing
        Automotive
        Electronics
        Agriculture
      Finance
        Financial Consolidation
        EPM Systems
        Accounting Systems
      FinTech
        Payment Integration
        Banking APIs
        eCommerce
```
