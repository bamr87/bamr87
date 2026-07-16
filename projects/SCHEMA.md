---
schema: "0.1"
coverage: listed
---

# SCHEMA — projects

> One directory per project: each is an independent Git submodule with its
> own repo, branch, and release cycle — a separate schema pyramid rooted at
> its **own** SCHEMA.md, which the hub never descends into.

<!-- GENERATED from .gitmodules + _data/projects.yml by
     tools/gen-projects-schema.py — regenerate instead of hand-editing. -->

## Structure

| entry | kind | purpose | rules |
|---|---|---|---|
| `README.md` | file | Projects index page | |
| `1987/` | dir | Self-growing knowledge base about the year 1987 — history, politics, science, and culture. | terminal |
| `2005/` | dir | Self-growing knowledge base about the year 2005 — history, science, arts, society, and people. | terminal |
| `Dodge-and-Reena-Book/` | dir | Children's picture book — Deputy Dodge & Ranger Reena monthly mystery stories with a full illustrat… | terminal |
| `README/` | dir | Documentation aggregation system organizing technical docs across repositories (MkDocs + Wiki.js). | terminal |
| `afms/` | dir | AFMS — Django accounting & financial management web app with role-based access and reporting. | terminal |
| `ai-seed/` | dir | AI-Seed evolution engine — a container-first, self-evolving project template grown through AI-human… | terminal |
| `aieo/` | dir | AI Engine Optimization — optimize content for AI engine citations (FastAPI backend + React UI). | terminal |
| `amrs-django/` | dir | Django web application (early scaffolding). | terminal |
| `amrs-project/` | dir | AMRS — modular Django accounting & financial management system with REST APIs (Bootstrap 5). | terminal |
| `bamr87.github.io/` | dir | Personal profile and portfolio website. | terminal |
| `barodybroject/` | dir | Full-stack responsive web app with OpenAI integrations and CMS functionality. | terminal |
| `bashconsultants/` | dir | BASH Consulting — Denver-based IT consulting firm website. | terminal |
| `bashcrawl/` | dir | Terminal game and command-line learning project. | terminal |
| `books/` | dir | Personal books and reference notes collection. | terminal |
| `csv-vscoode/` | dir | CSV Grid Viewer — VS Code extension to view .csv files in a grid and sum selected cells. | terminal |
| `cv/` | dir | LaTeX résumé/CV source (cv.tex + sections) with rendered PDF exports and headshots. | terminal |
| `cv-builder-pro/` | dir | AI-powered CV/resume builder with LaTeX/Markdown/ASCII export (React 19, TS, Vite 6, Firebase). | terminal |
| `django-fin/` | dir | Django finance app scaffold built around OpenEDGAR (SEC filings). | terminal |
| `djangoerp/` | dir | A Django-based ERP experiment exploring enterprise resource planning modules in Python. | terminal |
| `drsai/` | dir | Dr. Seuss-style AI poetry generator. | terminal |
| `edgar-data-parse/` | dir | SEC EDGAR + FRED data backend (Django REST) with a Vite/React UI. | terminal |
| `githubai/` | dir | AI-powered GitHub automation — issue management, docs generation, and semantic versioning (Django). | terminal |
| `gitorio/` | dir | Factorio-style factory builder for GitHub automation — blueprints compile to real GitHub Actions wo… | terminal |
| `it-journey/` | dir | From-zero-to-hero docs, tools, and scripts supporting an IT learning journey. | terminal |
| `jekyll/` | dir | Fork of Jekyll, the blog-aware static site generator in Ruby. | terminal |
| `law-ai/` | dir | LawGraph AI — AI-native dev environment for an open legal intelligence platform (local-first via Ol… | terminal |
| `lawmode/` | dir | Always-on AI lawyer concept for developers. | terminal |
| `lifehacker.dev/` | dir | Personal site at lifehacker.dev, built with the zer0-mistakes Jekyll remote theme on GitHub Pages. | terminal |
| `scripts/` | dir | Development and automation utilities for project setup, GitHub workflows, and local tooling. | terminal |
| `skills/` | dir | Microsoft Agent Skills — reusable markdown skills, MCP servers, and custom agents to ground coding… | terminal |
| `skills-github-pages/` | dir | Clone of the GitHub Skills "GitHub Pages" interactive course. | terminal |
| `sonic-pi/` | dir | Fork of Sonic Pi — the live-coding music synthesizer and IDE. | terminal |
| `vs-sonic-pi/` | dir | VS Code extension for writing and performing Sonic Pi music from the editor. | terminal |
| `vscode-front-matter/` | dir | Fork of Front Matter — a CMS running inside VS Code for static-site generators. | terminal |
| `wargames/` | dir | Curated OverTheWire security wargames (vendored, MIT) — extracted from it-journey. | terminal |
| `wtd/` | dir | Recursive TODO engine experiment for AI-orchestrated task decomposition. | terminal |
| `zer0-image-generator/` | dir | AI preview/social images for any Jekyll site — Claude directs & reviews, an image model renders. Po… | terminal |
| `zer0-mistakes/` | dir | GitHub Pages compatible Jekyll theme using Bootstrap 5 — the theme powering this dash. | terminal |
| `zer0-pages/` | dir | Product-requirements and planning notes for the zer0-pages concept. | terminal |
| `zer0-pages-remote/` | dir | Remote-theme GitHub Pages companion for the zer0-mistakes Jekyll theme. | terminal |
| `zpl-viewer/` | dir | ZPL Viewer — VS Code extension to render, validate, and export Zebra (ZPL II) label files fully off… | terminal |

## Placement

- New project → register in `.gitmodules` **and** `_data/projects.yml` first
  (see `docs/SUBMODULE-CHECKLIST.md`), then regenerate this file.
- Seed a project's own pyramid with `tools/seed-schema.sh <name>`.

## Forbidden

- No project work committed via the hub: changes land in the submodule's own
  repo first; the hub only records pointer bumps (see CLAUDE.md).
- No non-submodule directories here — the drift gate flags strays.
