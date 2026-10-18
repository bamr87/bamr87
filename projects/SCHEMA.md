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
| `1987/` | dir | Self-growing, AI-tended knowledge base about the year 1987: history, politics, science, culture and… | terminal |
| `2005/` | dir | Year-2005 knowledge base — content archive of the year-of-ai lineage (framework consolidated into y… | terminal |
| `README/` | dir | Context engine for the bamr87 fleet: crawlers and distillers that build queryable docs for every pr… | terminal |
| `ai-seed/` | dir | Self-evolving project template: plant a kernel in any repo and let Claude Code Actions germinate an… | terminal |
| `aieo/` | dir | AI Engine Optimization: score and optimize website content so AI engines like ChatGPT and Claude wi… | terminal |
| `bamr87.github.io/` | dir | Amr Abdel-Motaleb's personal profile, résumé and project portfolio site, built with Jekyll on GitHu… | terminal |
| `barodybroject/` | dir | Django + React web app that generates and publishes AI-written parody news, with a Jekyll site and… | terminal |
| `bashconsultants/` | dir | Source of bash-365.com, BASH Consulting's IT consulting site (Jekyll), plus a Prompt Orchestrator V… | terminal |
| `bashcrawl/` | dir | Learn real terminal skills by playing a fantasy dungeon crawl in your shell or in a free browser tr… | terminal |
| `bashos/` | dir | Terminal-first AI runtime that routes Claude slash commands through a LangGraph kernel onto the Ope… | terminal |
| `books/` | dir | Plain-markdown book-writing workspace with a CLI, a studio editor, validation checks and an AI writ… | terminal |
| `chui/` | dir | Rebuildable macOS terminal setup: Oh My Zsh, Powerlevel10k, Zellij and modern CLI tools, with backu… | terminal |
| `csv-vscoode/` | dir | CSV Grid Viewer — VS Code extension to view .csv files in a grid and sum selected cells. | terminal |
| `cv/` | dir | Amr's CV as code: one cv.json rendered to Markdown, LaTeX, HTML and PDF, with automated publishing… | terminal |
| `cv-builder-pro/` | dir | React web app for building CVs and résumés with LaTeX templates, Markdown/PDF export and optional A… | terminal |
| `djangoerp/` | dir | Modular Django REST ERP: double-entry accounting, inventory, purchasing, sales, manufacturing and M… | terminal |
| `drsai/` | dir | AI-assisted children's storybook platform: verse, OpenAI-rendered illustrations and picture books o… | terminal |
| `fredgar-ai/` | dir | Django + React app for exploring SEC EDGAR company data and FRED macro series, with AI-assisted sum… | terminal |
| `git-with-the-program/` | dir | Agentic governance framework that distills git history into a core memory and scores every change f… | terminal |
| `githubai/` | dir | Claude Code SDLC framework: reusable GitHub Actions that triage issues, implement work, review PRs… | terminal |
| `gitnexus/` | dir | Nexus Forge: a static rebuild-spec workbench (PRD, architecture, 14-step playbook) for reimplementi… | terminal |
| `gitorio/` | dir | Factorio-style factory builder for GitHub automation: blueprints compile to Actions workflows runni… | terminal |
| `irony-works/` | dir | The perpetual encyclopedia of irony: a self-growing, AI-tended Obsidian vault published with zer0-m… | terminal |
| `it-journey/` | dir | Gamified, open-source platform for learning IT and software development through hands-on quests, ze… | terminal |
| `law-ai/` | dir | Open legal intelligence platform prototype: Django, CrewAI agents and a Neo4j knowledge graph, loca… | terminal |
| `lawmode/` | dir | Always-on AI legal reviewer for developers: checks code, prompts and commits, and gates non-complia… | terminal |
| `lifehacker.dev/` | dir | Tech knowledge, tools and comedy at lifehacker.dev: a Jekyll site on the zer0-mistakes theme, run b… | terminal |
| `ocrmd/` | dir | Scan books and pages into cross-checked Markdown: local OCR diffed against a Claude vision read, wi… | terminal |
| `outbox/` | dir | Async competitive outbox harness for three agents: mailbox protocol, injected lag, confidence race… | terminal |
| `raising-eliza/` | dir | Weizenbaum's 1966 MAD-SLIP ELIZA, revived by an AI agent under a gated method and tied out to the o… | terminal |
| `retro-pi/` | dir | Portable retro-gaming workspace for macOS and Raspberry Pi: declarative manifests drive EmulationSt… | terminal |
| `rewind-arcade/` | dir | Retro gaming workspace: browser arcade recreations, console emulation via ES-DE, and a physical gam… | terminal |
| `scripts/` | dir | Standalone Bash utilities for project scaffolding, GitHub repository management and multi-repo main… | terminal |
| `skills/` | dir | Microsoft Agent Skills — reusable markdown skills, MCP servers, and custom agents to ground coding… | terminal |
| `vs-sonic-pi/` | dir | VS Code extension to write and perform Sonic Pi music live: IntelliSense, hover docs, built-in tuto… | terminal |
| `wargames/` | dir | OverTheWire security wargames (Bandit, Natas and more) mirrored as a Jekyll study site, extracted f… | terminal |
| `wtd/` | dir | WTD (What To Do): turns TODOs, issues and failing workflows into queued work for a fleet of Claude… | terminal |
| `zer0-cms/` | dir | Fork of Front Matter CMS reworked into zer0-CMS: a governed VS Code + Rails CMS for zer0-themed mar… | terminal |
| `zer0-image-generator/` | dir | Jekyll plugin, CLI and web app that generate AI preview and social images for any Jekyll site, dire… | terminal |
| `zer0-mistakes/` | dir | AI-native, Docker-first Jekyll theme for GitHub Pages sites, built on Bootstrap 5 and published as… | terminal |
| `zer0-pages/` | dir | Obsidian vault published as a Jekyll knowledge site via build-time bridge plugins; the second brain… | terminal |
| `zer0-pages-remote/` | dir | Minimal three-file GitHub Pages site showing the zer0-mistakes Jekyll remote theme with zero local… | terminal |
| `zpl-viewer/` | dir | Label Studio: offline VS Code extension to read, preview, create, merge and deploy ZPL II and EPL2… | terminal |

## Placement

- New project → register in `.gitmodules` **and** `_data/projects.yml` first
  (see `docs/STANDARDS.md`), then regenerate this file.
- Seed a project's own pyramid with `tools/seed-schema.sh <name>`.

## Forbidden

- No project work committed via the hub: changes land in the submodule's own
  repo first; the hub only records pointer bumps (see CLAUDE.md).
- No non-submodule directories here — the drift gate flags strays.
