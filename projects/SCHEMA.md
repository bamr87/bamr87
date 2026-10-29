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
| `README/` | dir | Context engine for the bamr87 fleet: crawlers and distillers that build queryable docs for every pr… | terminal |
| `ai-world-view.github.io/` | dir | AI World View — the root site of the self-growing country knowledge-base network; the per-country r… | terminal |
| `bamr87.github.io/` | dir | Amr Abdel-Motaleb's personal profile, résumé and project portfolio site, built with Jekyll on GitHu… | terminal |
| `bash-365-apex/` | dir | Client-side redirect from the bash-365.com apex domain to www, served by GitHub Pages for BASH Cons… | terminal |
| `bash-365.com/` | dir | BASH Consulting's website at bash-365.com — a content site the content atlas already tracks, now ch… | terminal |
| `bashcrawl/` | dir | Learn real terminal skills by playing a fantasy dungeon crawl in your shell or in a free browser tr… | terminal |
| `bashos/` | dir | Terminal-first AI runtime that routes Claude slash commands through a LangGraph kernel onto the Ope… | terminal |
| `cv-pro/` | dir | CV as code and the CV Builder Pro app in one repository: cv/ holds the data, the CVData contract an… | terminal |
| `djangoerp/` | dir | Modular Django REST ERP: double-entry accounting, inventory, purchasing, sales, manufacturing and M… | terminal |
| `edgar-pipeline/` | dir | Data pipeline for SEC EDGAR filings: Dagster orchestration, dbt models on DuckDB, MLflow experiment… | terminal |
| `fleet-infra/` | dir | GitOps infrastructure for the bamr87 fleet: Terraform/HCL provisioning, a k3s cluster, and Helm cha… | terminal |
| `fleet-mobile/` | dir | Kotlin Multiplatform app to monitor the bamr87 fleet's bots, CI and PRs from a phone. | terminal |
| `fleet-observe/` | dir | Observability stack for the bamr87 fleet: OpenTelemetry Collector, Prometheus and Grafana, wired fo… | terminal |
| `fredgar-ai/` | dir | Django + React app for exploring SEC EDGAR company data and FRED macro series, with AI-assisted sum… | terminal |
| `githubai/` | dir | Claude Code SDLC framework: reusable GitHub Actions that triage issues, implement work, review PRs… | terminal |
| `gitorio/` | dir | Factorio-style factory builder for GitHub automation: blueprints compile to Actions workflows runni… | terminal |
| `godotgo/` | dir | Godot 4 game workspace: one reusable framework, five sample games and tooling that treats every pro… | terminal |
| `it-journey/` | dir | Gamified, open-source platform for learning IT and software development through hands-on quests, ze… | terminal |
| `kvlite/` | dir | A small LSM-tree key-value store in Rust, growing into a Raft-replicated cluster. | terminal |
| `law-ai/` | dir | Open legal-intelligence platform for prospective law students (LSAT lab), law students and practici… | terminal |
| `lifehacker.dev/` | dir | Tech knowledge, tools and comedy at lifehacker.dev: a Jekyll site on the zer0-mistakes theme, run b… | terminal |
| `netprobe/` | dir | A Go network diagnostics toolkit with a terminal UI: ping, port scan, DNS, traceroute and HTTP prob… | terminal |
| `ocrmd/` | dir | Scan books and pages into cross-checked Markdown: local OCR diffed against a Claude vision read, wi… | terminal |
| `outbox/` | dir | Async competitive outbox harness for three agents: mailbox protocol, injected lag, confidence race… | terminal |
| `ragio-ai/` | dir | Fully local RAG engine over Radiolab episodes: Whisper transcription, Qdrant hybrid retrieval, Llam… | terminal |
| `rewind-arcade/` | dir | Retro gaming workspace: browser arcade recreations, console emulation via ES-DE, and a physical gam… | terminal |
| `schema-lang/` | dir | A Rust DSL and compiler for gitorio/SCHEMA blueprints: parse, type-check and emit SCHEMA.md contrac… | terminal |
| `scripts/` | dir | Standalone Bash utilities for project scaffolding, GitHub repository management and multi-repo main… | terminal |
| `sec-lab/` | dir | A deliberately vulnerable practice app with SAST/DAST pipelines and CTF-style challenges. Local use… | terminal |
| `sensor-mesh/` | dir | ESP32 sensor firmware that publishes readings over MQTT, with a host-testable core. | terminal |
| `skills/` | dir | Microsoft Agent Skills — reusable markdown skills, MCP servers, and custom agents to ground coding… | terminal |
| `vs-sonic-pi/` | dir | VS Code extension to write and perform Sonic Pi music live: IntelliSense, hover docs, built-in tuto… | terminal |
| `year-of-ai.github.io/` | dir | Year of AI — the organization's root site and content hub, rendering the shared zer0-mistakes theme… | terminal |
| `zer0-cms/` | dir | The zer0 stack in one repository: an agent-native headless CMS (Django/Wagtail content plane, Rails… | terminal |
| `zer0-id/` | dir | A small OpenID Connect identity provider in Go with passkey (WebAuthn) login. | terminal |
| `zer0-kernel/` | dir | A hobby operating-system kernel in C, booted with Multiboot2 on QEMU. | terminal |
| `zer0-mistakes/` | dir | AI-native, Docker-first Jekyll theme for GitHub Pages sites, built on Bootstrap 5 and published as… | terminal |
| `zpl-viewer/` | dir | Label Studio: offline VS Code extension to read, preview, create, merge and deploy ZPL II and EPL2… | terminal |

## Placement

- New project → register in `.gitmodules` **and** `_data/projects.yml` first
  (see `docs/STANDARDS.md`), then regenerate this file.
- Seed a project's own pyramid with `tools/seed-schema.sh <name>`.

## Forbidden

- No project work committed via the hub: changes land in the submodule's own
  repo first; the hub only records pointer bumps (see CLAUDE.md).
- No non-submodule directories here — the drift gate flags strays.
