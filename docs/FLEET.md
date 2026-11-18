# Fleet

> Organization structure, general information, and a per-repo context table for the bamr87 fleet, including about-section coverage as of 2026-11-16.

This is a snapshot to sit beside the standards in [ABOUT-SECTION.md](ABOUT-SECTION.md), [PORTFOLIO.md](PORTFOLIO.md), [SUBMODULES.md](SUBMODULES.md) and [STANDARDS.md](STANDARDS.md). Descriptions come from `_data/projects.yml` when the repo is in the registry, otherwise from the GitHub description, otherwise from a README sentence when one was read, otherwise marked *unknown*. Nothing here is invented. Public content in this file does not add descriptions that were not already on GitHub, in the registry, or in a README opened for this snapshot.

## 1. General information

The [bamr87/bamr87](https://github.com/bamr87/bamr87) hub is three things at once: Amr's GitHub profile README, the fleet control plane (the "dash") that vendors projects as Git submodules under `projects/`, and the public Harness Console site at [bamr87.github.io/bamr87](https://bamr87.github.io/bamr87/).

The hub's direction, and the three missions under it, live in [constitution § 1](constitution.md#1-mission). Standards are written and ratified in the hub first, then fanned out to each repo in its own PR. An amendment is ratified only when Amr merges the pull request (constitution § 8). Agents never assign sequential ids; new features, requirements, roadmap entries and amendments use `HUB-NEW`, `FR-NEW:<key>`, `FF-NEW` and `Number: NEW`, numbered on `main` at merge (amendment 0002).

The single project registry is [`_data/projects.yml`](../_data/projects.yml). It is cross-checked against [`.gitmodules`](../.gitmodules). A registry row may exist without a submodule (`submodule_path` empty) for archived, external or display-only repos. The Universal Project Standard lives in [`specs/`](../specs/README.md); kits in [`templates/`](../templates/) are fanned out by `tools/fanout.sh`. Work is tracked on [Fleet project #14](https://github.com/users/bamr87/projects/14) (constitution § 9–§ 11).

Counts in this snapshot (2026-11-16, afternoon MST): 45 rows in the project registry; 73 GitHub repositories across the bamr87 user account and the four organizations below; about 40 of the registry rows are mounted as submodules under `projects/`. Two registry rows are external mirrors the fleet does not write to: [microsoft/skills](https://github.com/microsoft/skills) and [tt-a1i/archify](https://github.com/tt-a1i/archify).

The profile README at the hub root is also a personal profile. Its about section for the control plane is the "This repository", Quick start, Documentation and License cluster, now held to [ABOUT-SECTION.md](ABOUT-SECTION.md).

## 2. Organization structure

### 2.1 GitHub owners

Amr is the maintainer of the fleet. The GitHub owners whose repos are the fleet (fan-out write list, `_data/fleet.yml` `hub.owners`) are `bamr87`, `bash-365`, `year-of-ai` and `ai-world-view`. JEV also scans `EissaLab` and `zer0-mistakes` (`jev.orgs`). `bamr87` is a personal account, not a GitHub organization.

| Owner | Kind | What it holds |
| --- | --- | --- |
| [bamr87](https://github.com/bamr87) | user account | Amr's personal GitHub account (not an organization) and the home of the hub plus most project repos. 44 repositories in this snapshot. |
| [year-of-ai](https://github.com/year-of-ai) | organization | Year of AI — a lineage of self-growing yearly knowledge bases around a root site. 14 repositories in this snapshot. |
| [ai-world-view](https://github.com/ai-world-view) | organization | AI World View — a self-growing country knowledge-base network around a root site. 5 repositories in this snapshot. |
| [bash-365](https://github.com/bash-365) | organization | BASH Consulting — the consulting website, its apex redirect, and the CSV Grid Editor extension. 3 repositories in this snapshot. |
| [EissaLab](https://github.com/EissaLab) | organization | A research organization. Most repositories are private; they are listed by name and existing description only. 7 repositories in this snapshot. |
| microsoft/skills, tt-a1i/archify | external mirrors | In the registry (skills is a submodule) so the dash can show them; `_data/fleet.yml` says the fleet never writes to them. |

### 2.2 Submodule layout

Mounted projects live at `projects/<name>` in the hub. The authoritative list is the registry plus `.gitmodules` — this document does not repeat every path (see [SUBMODULES.md](SUBMODULES.md)). All submodules track `main` unless `.gitmodules` says otherwise. A change is committed in the submodule's own repo first, then the pointer is recorded in the hub; do not bundle changes across multiple submodules into one PR.

The hub itself is not a submodule. Registry rows with no `submodule_path` are shown on the dash and are not checked out here.

### 2.3 Ownership and agents

Amr ratifies standards, PRD changes and releases by merging pull requests, and is the only person who changes settings, secrets or branch protection (constitution § 4). There is no per-repo bot-owner column in the registry today.

Work-item ownership lives on the Fleet project (Owner is Amr or a bot team / JEV, [PROJECTS-FRAMEWORK.md](PROJECTS-FRAMEWORK.md)). Hub agents are registered in [`_data/agents.yml`](../_data/agents.yml) with `owner: bamr87`. Agent roles are in constitution § 26 and [AGENTS.md](../AGENTS.md): Grok bots propose direction (constitution, amendments, PRD, features, roadmap); Claude Code executes software and console changes; neither merges an amendment; JEV and `bamr87-bot` / `github-actions[bot]` run the automated loops under the kill switches in `_data/fleet.yml`.

### 2.4 How a standard changes

1. A proposal is opened as a hub PR: constitution edit, `docs/amendments/proposed/<slug>.md` with `Number: NEW`, feature and requirement fragments, and any roadmap or operator docs.
2. Amr ratifies it by merging. Ids are assigned on `main` at merge. Amendments are never approved or merged by an agent.
3. Fan-out opens one PR per spoke repo. The spoke adopts the standard under its own constitution and amendment log.
4. Background or proactive runs never merge, release or approve.

## 3. Per-repo context (about section)

One line per repository that was listed under the owners above on 2026-11-16, plus the two external registry mirrors at the end. **Category** and **Submodule** come from the hub registry when the repo has a row; otherwise the category is `not in registry` and submodule is `no` (or `hub` for bamr87/bamr87).

The about column is the one-line description a visitor should see in GitHub About and in the README tagline. Prefer the registry wording when both exist.

### bamr87 (44)

| Repo | About | Category | Submodule | Notes |
| --- | --- | --- | --- | --- |
| [bamr87](https://github.com/bamr87/bamr87) | Amr's profile README and fleet control-plane monorepo: ~40 project submodules, shared standards, CI and dashboards. | not in registry | hub | — |
| [.github](https://github.com/bamr87/.github) | Shared reusable GitHub Actions workflows, release-please setup and community health files for every bamr87 repo. | dash | no | — |
| [amrchy](https://github.com/bamr87/amrchy) | Personal fork of Omarchy (omacom/omarchy), the opinionated Arch Linux + Hyprland desktop setup. | dev-tools | no | fork |
| [bamr87.github.io](https://github.com/bamr87/bamr87.github.io) | Amr Abdel-Motaleb's personal profile, résumé and project portfolio site, built with Jekyll on GitHub Pages. | docs | yes | — |
| [bashcrawl](https://github.com/bamr87/bashcrawl) | Learn real terminal skills by playing a fantasy dungeon crawl in your shell or in a free browser trainer. | dev-tools | yes | — |
| [bashos](https://github.com/bamr87/bashos) | Terminal-first AI runtime that routes Claude slash commands through a LangGraph kernel onto the OpenCode engine. | dev-tools | yes | — |
| [cv-pro](https://github.com/bamr87/cv-pro) | CV as code and the CV Builder Pro app in one repository: cv/ holds the data, the CVData contract and every render; app/ is the React builder. | full-stack-ai | yes | — |
| [djangoerp](https://github.com/bamr87/djangoerp) | Modular Django REST ERP: double-entry accounting, inventory, purchasing, sales, manufacturing and MRP planning. | full-stack-ai | yes | — |
| [edgar-pipeline](https://github.com/bamr87/edgar-pipeline) | Data pipeline for SEC EDGAR filings: Dagster orchestration, dbt models on DuckDB, MLflow experiments; feeds fredgar-ai and law-ai. | full-stack-ai | yes | — |
| [fleet-infra](https://github.com/bamr87/fleet-infra) | GitOps infrastructure for the bamr87 fleet: Terraform/HCL provisioning, a k3s cluster, and Helm charts reconciled from git. | dev-tools | yes | — |
| [fleet-mobile](https://github.com/bamr87/fleet-mobile) | Kotlin Multiplatform app to monitor the bamr87 fleet's bots, CI and PRs from a phone. | dev-tools | yes | — |
| [fleet-observe](https://github.com/bamr87/fleet-observe) | Observability stack for the bamr87 fleet: OpenTelemetry Collector, Prometheus and Grafana, wired for every fleet service. | dev-tools | yes | — |
| [fredgar-ai](https://github.com/bamr87/fredgar-ai) | Django + React app for exploring SEC EDGAR company data and FRED macro series, with AI-assisted summaries. | full-stack-ai | yes | — |
| [githubai](https://github.com/bamr87/githubai) | Claude Code SDLC framework: reusable GitHub Actions that triage issues, implement work, review PRs and cut releases. | full-stack-ai | yes | — |
| [gitorio](https://github.com/bamr87/gitorio) | Factorio-style factory builder for GitHub automation: blueprints compile to Actions workflows running Claude Code. | dev-tools | yes | — |
| [godotgo](https://github.com/bamr87/godotgo) | Godot 4 game workspace: one reusable framework, five sample games and tooling that treats every project the same. | dev-tools | yes | — |
| [it-journey](https://github.com/bamr87/it-journey) | Gamified, open-source platform for learning IT and software development through hands-on quests, zer0 to her0. | docs | yes | — |
| [kvlite](https://github.com/bamr87/kvlite) | A small LSM-tree key-value store in Rust, growing into a Raft-replicated cluster. | dev-tools | yes | — |
| [law-ai](https://github.com/bamr87/law-ai) | Open legal-intelligence platform for prospective law students (LSAT lab), law students and practicing lawyers: Django + CrewAI/LangGraph agents over a Neo4j knowledge graph, Claude-first provider chain with a local Ollama tier. Runs the fleet's spec-driven loop by reference. | full-stack-ai | yes | — |
| [lifehacker.dev](https://github.com/bamr87/lifehacker.dev) | Tech knowledge, tools and comedy at lifehacker.dev: a Jekyll site on the zer0-mistakes theme, run by Claude Code. | docs | yes | — |
| [netprobe](https://github.com/bamr87/netprobe) | A Go network diagnostics toolkit with a terminal UI: ping, port scan, DNS, traceroute and HTTP probes. | dev-tools | yes | — |
| [ocrmd](https://github.com/bamr87/ocrmd) | Scan books and pages into cross-checked Markdown: local OCR diffed against a Claude vision read, with full-text search. | full-stack-ai | yes | — |
| [outbox](https://github.com/bamr87/outbox) | Async competitive outbox harness for three agents: mailbox protocol, injected lag, confidence race and replay scorer. | full-stack-ai | yes | — |
| [ragio-ai](https://github.com/bamr87/ragio-ai) | Fully local RAG engine over Radiolab episodes: Whisper transcription, Qdrant hybrid retrieval, LlamaIndex, Ollama answers with timestamped citations, FastAPI UI. | full-stack-ai | yes | — |
| [README](https://github.com/bamr87/README) | Context engine for the bamr87 fleet: crawlers and distillers that build queryable docs for every project, incl. MCP. | docs | yes | — |
| [recon-engine](https://github.com/bamr87/recon-engine) | Recon Engine: operational events reconciled against the general ledger — one monthly residual, six gross-not-net buckets, a statistical layer scoring where interpretation drifts from fact. Spec stage; Django ERP adapter first. | full-stack-ai | yes | — |
| [rewind-arcade](https://github.com/bamr87/rewind-arcade) | Retro gaming workspace: browser arcade recreations, console emulation via ES-DE, and a physical game catalog. | dev-tools | yes | — |
| [SCHEMA](https://github.com/bamr87/SCHEMA) | Pyramid Schema: the SCHEMA.md protocol and linter that let AI agents look up repo structure instead of guessing it. | dev-tools | no | — |
| [schema-lang](https://github.com/bamr87/schema-lang) | A Rust DSL and compiler for gitorio/SCHEMA blueprints: parse, type-check and emit SCHEMA.md contracts. | dev-tools | yes | — |
| [scripts](https://github.com/bamr87/scripts) | Standalone Bash utilities for project scaffolding, GitHub repository management and multi-repo maintenance. | dev-tools | yes | — |
| [sec-lab](https://github.com/bamr87/sec-lab) | A deliberately vulnerable practice app with SAST/DAST pipelines and CTF-style challenges. Local use only. | dev-tools | yes | — |
| [sensor-mesh](https://github.com/bamr87/sensor-mesh) | ESP32 sensor firmware that publishes readings over MQTT, with a host-testable core. | dev-tools | yes | — |
| [vs-sonic-pi](https://github.com/bamr87/vs-sonic-pi) | VS Code extension to write and perform Sonic Pi music live: IntelliSense, hover docs, built-in tutorial, OSC control. | dev-tools | yes | — |
| [zer0-CMS](https://github.com/bamr87/zer0-CMS) | The zer0 stack in one repository: an agent-native headless CMS (Django/Wagtail content plane, Rails experience plane, VS Code extension) plus the image generator, books app, barodybroject and the zer0 sites, each imported with its history; the theme is developed in bamr87/zer0-mistakes again (ADR 0005). | dev-tools | yes | — |
| [zer0-id](https://github.com/bamr87/zer0-id) | A small OpenID Connect identity provider in Go with passkey (WebAuthn) login. | dev-tools | yes | — |
| [zer0-kernel](https://github.com/bamr87/zer0-kernel) | A hobby operating-system kernel in C, booted with Multiboot2 on QEMU. | dev-tools | yes | — |
| [zer0-mistakes](https://github.com/bamr87/zer0-mistakes) | AI-native, Docker-first Jekyll theme for GitHub Pages sites, built on Bootstrap 5 and published as a Ruby gem, with zer0 studio — the Rails workbench that designs, customizes and updates it. | docs | yes | — |
| [zpl-viewer](https://github.com/bamr87/zpl-viewer) | Label Studio: offline VS Code extension to read, preview, create, merge and deploy ZPL II and EPL2 thermal labels. | dev-tools | yes | — |
| [rsa-challenge](https://github.com/bamr87/rsa-challenge) | Generate RSA factoring/decryption challenges and self-check solutions on GitHub Pages | not in registry | no | — |
| [one-usb](https://github.com/bamr87/one-usb) | one-USB: multi-boot USB stick builder (folded into bashOS) | not in registry | no | private |
| [ai-seed](https://github.com/bamr87/ai-seed) | Self-evolving project template: plant a kernel in any repo and let Claude Code Actions germinate and grow it. | dev-tools | no | archived |
| [chui](https://github.com/bamr87/chui) | Rebuildable macOS terminal setup: Oh My Zsh, Powerlevel10k, Zellij and modern CLI tools, with backup and restore. | not in registry | no | archived |
| [cv](https://github.com/bamr87/cv) | Amr's CV as code: one cv.json rendered to Markdown, LaTeX, HTML and PDF, with automated publishing and releases. | not in registry | no | archived |
| [wtd](https://github.com/bamr87/wtd) | WTD (What To Do): turns TODOs, issues and failing workflows into queued work for a fleet of Claude agents. | not in registry | no | archived |

### year-of-ai (14)

| Repo | About | Category | Submodule | Notes |
| --- | --- | --- | --- | --- |
| [year-of-ai.github.io](https://github.com/year-of-ai/year-of-ai.github.io) | Year of AI — the organization's root site and content hub, rendering the shared zer0-mistakes theme via remote_theme; the lineage's year repos hang off it. | docs | yes | — |
| [1776](https://github.com/year-of-ai/1776) | A self-growing knowledge base about the year 1776. Next era of the year-of-ai lineage, spawned from 2005-2011. | not in registry | no | — |
| [1777](https://github.com/year-of-ai/1777) | A self-growing encyclopedic knowledge base covering the events, people, works, and discoveries of 1777. | not in registry | no | — |
| [1778](https://github.com/year-of-ai/1778) | Self-growing knowledge base: the year 1778 | not in registry | no | — |
| [2006](https://github.com/year-of-ai/2006) | A self-growing knowledge base about the year 2006. Successor in the year-of-ai lineage (2005 → 2006). | not in registry | no | — |
| [2007](https://github.com/year-of-ai/2007) | A self-growing knowledge base about the year 2007 — history, science, technology, arts, society, and people. | not in registry | no | description from README |
| [2008](https://github.com/year-of-ai/2008) | A self-growing knowledge base about the year 2008 | not in registry | no | — |
| [2009](https://github.com/year-of-ai/2009) | A self-growing knowledge base about the year 2009 | not in registry | no | — |
| [2010](https://github.com/year-of-ai/2010) | A self-growing knowledge base about the year 2010 — history, science, technology, arts, society, and people. | not in registry | no | description from README |
| [2011](https://github.com/year-of-ai/2011) | A self-growing knowledge base about the year 2011 | not in registry | no | — |
| [2012](https://github.com/year-of-ai/2012) | self-growing knowledge base — the year 2012 | not in registry | no | — |
| [2013](https://github.com/year-of-ai/2013) | self-growing knowledge base — the year 2013 | not in registry | no | — |
| [2014](https://github.com/year-of-ai/2014) | self-growing knowledge base — the year 2014 | not in registry | no | — |
| [2005](https://github.com/year-of-ai/2005) | A self-growing knowledge base about the year 2005 — history, science, arts, society, and people. | not in registry | no | archived |

### ai-world-view (5)

| Repo | About | Category | Submodule | Notes |
| --- | --- | --- | --- | --- |
| [ai-world-view.github.io](https://github.com/ai-world-view/ai-world-view.github.io) | AI World View — the root site of the self-growing country knowledge-base network; the per-country repos hang off it. | docs | yes | — |
| [china](https://github.com/ai-world-view/china) | self-growing knowledge base — the country china | not in registry | no | — |
| [japan](https://github.com/ai-world-view/japan) | self-growing knowledge base — the country japan | not in registry | no | — |
| [north-korea](https://github.com/ai-world-view/north-korea) | self-growing knowledge base — the country north korea | not in registry | no | — |
| [south-korea](https://github.com/ai-world-view/south-korea) | self-growing knowledge base — the country south korea | not in registry | no | — |

### bash-365 (3)

| Repo | About | Category | Submodule | Notes |
| --- | --- | --- | --- | --- |
| [bash-365-apex](https://github.com/bash-365/bash-365-apex) | Client-side redirect from the bash-365.com apex domain to www, served by GitHub Pages for BASH Consulting. | docs | yes | — |
| [bash-365.com](https://github.com/bash-365/bash-365.com) | BASH Consulting's website at bash-365.com — a content site the content atlas already tracks, now checked out in the hub too. | docs | yes | — |
| [csv-vscoode](https://github.com/bash-365/csv-vscoode) | CSV Grid Viewer — VS Code extension to view .csv files in a grid and sum selected cells. | dev-tools | no | — |

### EissaLab (7)

| Repo | About | Category | Submodule | Notes |
| --- | --- | --- | --- | --- |
| [eissalab.com](https://github.com/EissaLab/eissalab.com) | *unknown* (no GitHub description or registry row) | not in registry | no | description unknown |
| [cookie-monster](https://github.com/EissaLab/cookie-monster) | *unknown* (no GitHub description or registry row) | not in registry | no | private, description unknown |
| [iEEG_tones_task](https://github.com/EissaLab/iEEG_tones_task) | this is a repo for iEEG preliminary analyses of the tones task | not in registry | no | private, tree unread |
| [NeuralTones_Laavi](https://github.com/EissaLab/NeuralTones_Laavi) | *unknown* (no GitHub description or registry row) | not in registry | no | private, tree unread, description unknown |
| [SC_priors](https://github.com/EissaLab/SC_priors) | collaboration on SC representing priors between Eissa and Felsen Lab | not in registry | no | private |
| [tonesTask_behavior](https://github.com/EissaLab/tonesTask_behavior) | behavior analysis from | not in registry | no | private |
| [tonestask_neural](https://github.com/EissaLab/tonestask_neural) | *unknown* (no GitHub description or registry row) | not in registry | no | private, description unknown |

### External registry mirrors

| Repo | About | Category | Submodule | Notes |
| --- | --- | --- | --- | --- |
| [skills](https://github.com/microsoft/skills) | Microsoft Agent Skills — reusable markdown skills, MCP servers, and custom agents to ground coding agents. | dev-tools | yes | external mirror; never written to by fan-out |
| [archify](https://github.com/tt-a1i/archify) | Agent skill that compiles typed JSON IR into validated, self-contained HTML system diagrams — the hub vendors it to illustrate the harness and its loops (diagrams/, /harness/). | dev-tools | no | external mirror; never written to by fan-out |

## 4. About-section coverage (2026-11-16)

File presence on each repo's default branch, plus whether a live URL is set (registry `live_url` or GitHub homepage). This is not a full README-heading audit: Getting started is a README section (UPS-DOC-10) and was not scored from file presence alone. Mission scoring uses the 2026-11-16 constitution scan plus the two open mission PRs; a `Y` under Const means `docs/constitution.md` exists, not that § 1 already uses the three-mission format.

Legend: `Y` present, `—` not found, `?` not determined (private tree unreadable). `Gov` is Y only when constitution, amendments log, PRD and feature catalog are all present. `Contrib+` is Y when `CONTRIBUTING.md` exists (the code of conduct is listed separately). `Sec` is Y when any `SECURITY.md` path exists. No public repo in this snapshot had a `SUPPORT.md`.

| Repo | README | Mission | Docs idx | Contrib+ | CoC | Gov | Roadmap | Changelog | Sec | License | Live |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| [bamr87/.github](https://github.com/bamr87/.github) | Y | § 1 not yet 3-mission | — | Y | Y | Y | — | Y | Y | Y | — |
| [bamr87/ai-seed](https://github.com/bamr87/ai-seed) | Y | no constitution | — | — | — | — | — | Y | — | Y | — |
| [bamr87/amrchy](https://github.com/bamr87/amrchy) | Y | no constitution | — | — | — | — | — | — | Y | Y | — |
| [bamr87/bamr87](https://github.com/bamr87/bamr87) | Y | § 1 not yet 3-mission | Y | Y | — | Y | — | Y | — | Y | Y |
| [bamr87/bamr87.github.io](https://github.com/bamr87/bamr87.github.io) | Y | § 1 not yet 3-mission | Y | — | — | Y | — | Y | — | Y | Y |
| [bamr87/bashcrawl](https://github.com/bamr87/bashcrawl) | Y | § 1 not yet 3-mission | Y | — | — | Y | — | Y | — | Y | Y |
| [bamr87/bashos](https://github.com/bamr87/bashos) | Y | § 1 not yet 3-mission | Y | Y | — | — | — | Y | Y | Y | — |
| [bamr87/chui](https://github.com/bamr87/chui) | Y | no constitution | — | — | — | — | — | Y | — | Y | — |
| [bamr87/cv](https://github.com/bamr87/cv) | Y | no constitution | — | — | — | — | — | Y | — | Y | — |
| [bamr87/cv-pro](https://github.com/bamr87/cv-pro) | Y | § 1 not yet 3-mission | Y | — | — | — | — | Y | — | Y | — |
| [bamr87/djangoerp](https://github.com/bamr87/djangoerp) | Y | § 1 not yet 3-mission | Y | — | — | Y | — | Y | — | Y | — |
| [bamr87/edgar-pipeline](https://github.com/bamr87/edgar-pipeline) | Y | § 1 not yet 3-mission | Y | Y | Y | Y | — | Y | Y | Y | — |
| [bamr87/fleet-infra](https://github.com/bamr87/fleet-infra) | Y | § 1 not yet 3-mission | Y | Y | Y | Y | — | Y | Y | Y | — |
| [bamr87/fleet-mobile](https://github.com/bamr87/fleet-mobile) | Y | § 1 not yet 3-mission | Y | Y | Y | Y | — | Y | Y | Y | — |
| [bamr87/fleet-observe](https://github.com/bamr87/fleet-observe) | Y | § 1 not yet 3-mission | Y | Y | Y | Y | — | Y | Y | Y | — |
| [bamr87/fredgar-ai](https://github.com/bamr87/fredgar-ai) | Y | pending [PR #153](https://github.com/bamr87/fredgar-ai/pull/153) | Y | Y | — | Y | — | Y | — | Y | Y |
| [bamr87/githubai](https://github.com/bamr87/githubai) | Y | § 1 not yet 3-mission | Y | — | — | — | — | Y | — | Y | — |
| [bamr87/gitorio](https://github.com/bamr87/gitorio) | Y | § 1 not yet 3-mission | Y | Y | — | Y | Y | Y | Y | Y | Y |
| [bamr87/godotgo](https://github.com/bamr87/godotgo) | Y | § 1 not yet 3-mission | Y | — | — | Y | — | Y | Y | Y | — |
| [bamr87/it-journey](https://github.com/bamr87/it-journey) | Y | § 1 not yet 3-mission | Y | Y | Y | Y | Y | Y | Y | Y | Y |
| [bamr87/kvlite](https://github.com/bamr87/kvlite) | Y | § 1 not yet 3-mission | Y | Y | Y | Y | — | Y | Y | Y | — |
| [bamr87/law-ai](https://github.com/bamr87/law-ai) | Y | pending [PR #262](https://github.com/bamr87/law-ai/pull/262) | Y | — | — | Y | — | Y | — | Y | Y |
| [bamr87/lifehacker.dev](https://github.com/bamr87/lifehacker.dev) | Y | § 1 not yet 3-mission | Y | — | — | Y | — | Y | — | Y | Y |
| [bamr87/netprobe](https://github.com/bamr87/netprobe) | Y | § 1 not yet 3-mission | Y | Y | Y | Y | — | Y | Y | Y | — |
| [bamr87/ocrmd](https://github.com/bamr87/ocrmd) | Y | § 1 not yet 3-mission | Y | — | — | Y | — | Y | — | Y | — |
| [bamr87/one-usb](https://github.com/bamr87/one-usb) | Y | no constitution | Y | — | — | — | — | — | — | — | — |
| [bamr87/outbox](https://github.com/bamr87/outbox) | Y | § 1 not yet 3-mission | Y | — | — | Y | — | Y | — | Y | — |
| [bamr87/ragio-ai](https://github.com/bamr87/ragio-ai) | Y | § 1 not yet 3-mission | — | — | — | Y | — | Y | — | — | — |
| [bamr87/README](https://github.com/bamr87/README) | Y | § 1 not yet 3-mission | Y | — | — | Y | — | Y | — | Y | Y |
| [bamr87/recon-engine](https://github.com/bamr87/recon-engine) | Y | no constitution | — | — | — | — | — | — | — | Y | — |
| [bamr87/rewind-arcade](https://github.com/bamr87/rewind-arcade) | Y | § 1 not yet 3-mission | Y | — | — | Y | — | Y | Y | Y | Y |
| [bamr87/rsa-challenge](https://github.com/bamr87/rsa-challenge) | Y | § 1 not yet 3-mission | — | — | — | Y | — | Y | — | Y | — |
| [bamr87/SCHEMA](https://github.com/bamr87/SCHEMA) | Y | § 1 not yet 3-mission | Y | — | — | Y | — | Y | — | Y | — |
| [bamr87/schema-lang](https://github.com/bamr87/schema-lang) | Y | § 1 not yet 3-mission | Y | Y | Y | Y | — | Y | Y | Y | — |
| [bamr87/scripts](https://github.com/bamr87/scripts) | Y | § 1 not yet 3-mission | Y | — | — | Y | — | Y | Y | Y | — |
| [bamr87/sec-lab](https://github.com/bamr87/sec-lab) | Y | § 1 not yet 3-mission | Y | Y | Y | Y | — | Y | Y | Y | — |
| [bamr87/sensor-mesh](https://github.com/bamr87/sensor-mesh) | Y | § 1 not yet 3-mission | Y | Y | Y | Y | — | Y | Y | Y | — |
| [bamr87/vs-sonic-pi](https://github.com/bamr87/vs-sonic-pi) | Y | § 1 not yet 3-mission | Y | Y | Y | — | — | Y | Y | Y | — |
| [bamr87/wtd](https://github.com/bamr87/wtd) | Y | no constitution | — | — | — | — | — | Y | — | Y | — |
| [bamr87/zer0-CMS](https://github.com/bamr87/zer0-CMS) | Y | § 1 not yet 3-mission | Y | Y | Y | Y | — | Y | Y | Y | — |
| [bamr87/zer0-id](https://github.com/bamr87/zer0-id) | Y | § 1 not yet 3-mission | Y | Y | Y | Y | — | Y | Y | Y | — |
| [bamr87/zer0-kernel](https://github.com/bamr87/zer0-kernel) | Y | § 1 not yet 3-mission | Y | Y | Y | Y | — | Y | Y | Y | — |
| [bamr87/zer0-mistakes](https://github.com/bamr87/zer0-mistakes) | Y | § 1 not yet 3-mission | Y | Y | Y | — | — | Y | Y | Y | Y |
| [bamr87/zpl-viewer](https://github.com/bamr87/zpl-viewer) | Y | § 1 not yet 3-mission | Y | — | — | Y | — | Y | — | Y | — |
| [year-of-ai/1776](https://github.com/year-of-ai/1776) | Y | § 1 not yet 3-mission | — | — | — | Y | — | — | — | Y | Y |
| [year-of-ai/1777](https://github.com/year-of-ai/1777) | Y | § 1 not yet 3-mission | — | — | — | Y | — | — | — | Y | Y |
| [year-of-ai/1778](https://github.com/year-of-ai/1778) | Y | § 1 not yet 3-mission | — | — | — | Y | — | — | — | Y | Y |
| [year-of-ai/2005](https://github.com/year-of-ai/2005) | Y | no constitution | — | — | — | — | — | — | — | Y | Y |
| [year-of-ai/2006](https://github.com/year-of-ai/2006) | Y | § 1 not yet 3-mission | — | — | — | Y | — | — | — | Y | Y |
| [year-of-ai/2007](https://github.com/year-of-ai/2007) | Y | § 1 not yet 3-mission | — | — | — | Y | — | — | — | Y | Y |
| [year-of-ai/2008](https://github.com/year-of-ai/2008) | Y | § 1 not yet 3-mission | — | — | — | Y | — | — | — | Y | Y |
| [year-of-ai/2009](https://github.com/year-of-ai/2009) | Y | § 1 not yet 3-mission | — | — | — | Y | — | — | — | Y | Y |
| [year-of-ai/2010](https://github.com/year-of-ai/2010) | Y | § 1 not yet 3-mission | — | — | — | Y | — | — | — | Y | Y |
| [year-of-ai/2011](https://github.com/year-of-ai/2011) | Y | § 1 not yet 3-mission | — | — | — | Y | — | — | — | Y | Y |
| [year-of-ai/2012](https://github.com/year-of-ai/2012) | Y | § 1 not yet 3-mission | — | — | — | Y | — | — | — | Y | Y |
| [year-of-ai/2013](https://github.com/year-of-ai/2013) | Y | § 1 not yet 3-mission | — | — | — | Y | — | — | — | Y | Y |
| [year-of-ai/2014](https://github.com/year-of-ai/2014) | Y | § 1 not yet 3-mission | — | — | — | Y | — | — | — | Y | Y |
| [year-of-ai/year-of-ai.github.io](https://github.com/year-of-ai/year-of-ai.github.io) | Y | § 1 not yet 3-mission | Y | Y | Y | Y | — | Y | Y | Y | Y |
| [ai-world-view/ai-world-view.github.io](https://github.com/ai-world-view/ai-world-view.github.io) | Y | § 1 not yet 3-mission | Y | Y | Y | Y | — | Y | Y | Y | Y |
| [ai-world-view/china](https://github.com/ai-world-view/china) | Y | § 1 not yet 3-mission | — | — | — | Y | — | — | — | Y | Y |
| [ai-world-view/japan](https://github.com/ai-world-view/japan) | Y | § 1 not yet 3-mission | — | — | — | Y | — | — | — | Y | Y |
| [ai-world-view/north-korea](https://github.com/ai-world-view/north-korea) | Y | § 1 not yet 3-mission | — | — | — | Y | — | — | — | Y | Y |
| [ai-world-view/south-korea](https://github.com/ai-world-view/south-korea) | Y | § 1 not yet 3-mission | — | — | — | Y | — | — | — | Y | Y |
| [bash-365/bash-365-apex](https://github.com/bash-365/bash-365-apex) | Y | § 1 not yet 3-mission | Y | Y | Y | Y | — | Y | Y | Y | Y |
| [bash-365/bash-365.com](https://github.com/bash-365/bash-365.com) | Y | § 1 not yet 3-mission | Y | Y | Y | Y | — | Y | Y | Y | Y |
| [bash-365/csv-vscoode](https://github.com/bash-365/csv-vscoode) | Y | no constitution | Y | Y | — | — | — | Y | — | Y | Y |
| [EissaLab/cookie-monster](https://github.com/EissaLab/cookie-monster) | — | no constitution | — | — | — | — | — | — | — | — | — |
| [EissaLab/eissalab.com](https://github.com/EissaLab/eissalab.com) | — | no constitution | — | — | — | — | — | — | — | — | Y |
| [EissaLab/iEEG_tones_task](https://github.com/EissaLab/iEEG_tones_task) | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? |
| [EissaLab/NeuralTones_Laavi](https://github.com/EissaLab/NeuralTones_Laavi) | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? |
| [EissaLab/SC_priors](https://github.com/EissaLab/SC_priors) | — | no constitution | — | — | — | — | — | — | — | — | — |
| [EissaLab/tonesTask_behavior](https://github.com/EissaLab/tonesTask_behavior) | — | no constitution | — | — | — | — | — | — | — | — | — |
| [EissaLab/tonestask_neural](https://github.com/EissaLab/tonestask_neural) | Y | no constitution | — | — | — | — | — | — | — | — | — |

Among the 60 public, non-archived, non-fork repos whose trees could be read: 59 had a README, 58 a LICENSE, 57 a constitution and amendments log, 56 a feature catalog, 52 a PRD, 42 AGENTS.md, 42 a changelog, 39 a docs index, 25 CONTRIBUTING.md, 25 a SECURITY.md, 20 a code of conduct, 2 a local ROADMAP file, and 0 a SUPPORT.md. None of those default branches yet had the three-mission § 1 format; two open PRs (fredgar-ai#153, law-ai#262) already use it.

Notable gaps that were determined, not invented: [bamr87/ragio-ai](https://github.com/bamr87/ragio-ai) has no LICENSE file on the default branch; [bamr87/recon-engine](https://github.com/bamr87/recon-engine) and [bamr87/one-usb](https://github.com/bamr87/one-usb) have no constitution (one-usb is private and described as folded into bashOS); [EissaLab/eissalab.com](https://github.com/EissaLab/eissalab.com) is public but has no root README or LICENSE and no GitHub description (it does have a live URL). [year-of-ai/2007](https://github.com/year-of-ai/2007) and [year-of-ai/2010](https://github.com/year-of-ai/2010) are not GitHub-archived, but their READMEs say they were consolidated and are read-only.

## 5. Sources

- Hub registry [`_data/projects.yml`](../_data/projects.yml) and [`_data/fleet.yml`](../_data/fleet.yml) `hub.owners` / `jev.orgs`, read from `main` on 2026-11-16.
- A read-only scan of constitution § 1 on every bamr87-owned default branch, 2026-11-16 afternoon MST, plus the open mission PRs [fredgar-ai#153](https://github.com/bamr87/fredgar-ai/pull/153) and [law-ai#262](https://github.com/bamr87/law-ai/pull/262).
- GitHub default-branch trees for the 73 repositories listed under bamr87, year-of-ai, ai-world-view, bash-365 and EissaLab, also 2026-11-16, for about-section file presence. Two private EissaLab trees could not be read.
- README first lines were opened only for public repos that had no registry or GitHub description (year-of-ai/2007, year-of-ai/2010, EissaLab/eissalab.com).
