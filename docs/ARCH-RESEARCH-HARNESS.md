# Architecture Research Harness — R&D loop for fleet architecture

> A research-and-development harness that studies the high-level architecture and the deeper structural challenges of every codebase in the bamr87 fleet, grounds each judgement in current software-architecture literature, and turns the hardest challenges into scoped research projects and full research papers. Design only — nothing here is implemented.

> **Status:** concept / proposed. Feature fragment [`features/features.d/arch-research-harness.yml`](../features/features.d/arch-research-harness.yml) (`HUB-NEW`, requirements `FR-NEW:arch-research-*`; numbers assigned at merge, amendment 0002). Related: Kaizen review [#454](https://github.com/bamr87/bamr87/issues/454), telemetry epic [#446](https://github.com/bamr87/bamr87/issues/446), Projects console epic [#468](https://github.com/bamr87/bamr87/issues/468).

## 1. Purpose and scope

**Purpose.** Answer, per repo and for the fleet as a whole: *is this structured the way current evidence says software of this kind should be structured, what are the deep, slow-moving challenges, and what do we not yet know?* Where the answer is "we don't know", the harness runs a research project and writes a paper.

**In scope:** system context and container boundaries, module/dependency structure, coupling and cohesion, data ownership and flows, deployment and runtime topology, cross-cutting quality attributes (ISO/IEC 25010), team/ownership fit (Conway / Team Topologies), evolvability, and fleet-level structure (hub ↔ submodules, shared libraries such as `libraries/fleetkit`, the harness console and its MCP, the control-plane loops).

**Out of scope:** line-level code review, lint, bugs, dependency bumps, UX, CI flakiness, and any implementation. Those belong to existing loops (below).

**Inputs (read-only):** the hub checkout and the ~39 submodules under `projects/` (read from GitHub, never the live Mac), `_data/projects.yml`, `_data/fleet.yml`, `_data/harness_registry.yml` (`harness-registry/v1`), `features/features.yml`, `PRD.md`, `docs/adr/` and each repo's ADRs/SCHEMA pyramid, `_data/conformance.yml`, `_data/fleet_triage.yml`, `_data/deep-dive.yml`, DORA-style delivery signals from fleet-pulse / the lake, and the **source registry** (§ 3).

**Outputs:** (a) an architecture fitness record per repo, (b) ranked findings, (c) research proposals, (d) research papers (§ 6), (e) Fleet project items that hand any implementation to Claude Code — never code itself.

### How it differs from what exists

| Loop / harness | Question it answers | Horizon | Arch Research Harness differs by |
| --- | --- | --- | --- |
| Kaizen review (#454) | Is the *process and operations* improving? (PDCA, telemetry, data freshness, hygiene) | weeks | Studies *structure*, not process; feeds Kaizen's quarterly retro with architecture findings |
| `repo-scout` (SCOUT.md) | What small issues should be filed in a sampled repo? | daily | Fewer, deeper, literature-grounded findings; files research items, not fix issues |
| `repo-evolution` (EVOLUTION.md) | What draft improvement PR can be made? | weekly | Never opens code PRs |
| `fleet-pulse` (DAILY-ANALYSIS.md) | What is failing or expensive today? | daily | Uses its signals as evidence only |
| Deep dive (DEEP-DIVE.md) | Full review of one repo per day | 42-day cycle | Architecture-only lens; cross-repo comparison; produces papers |
| UX harness (UX-HARNESS.md) | Is the UI usable/accessible? | per PR | Different concern entirely |

## 2. Loop structure

| Cycle | Frequency / trigger | Produces |
| --- | --- | --- |
| **Survey** | Weekly, rotating ~5 repos so every repo is covered each ~8 weeks; manual dispatch for one repo | Per-repo `fitness.yml` (C4 L1–L2 sketch, quality-attribute scores with evidence, ADR coverage, coupling metrics) and ranked findings |
| **Fleet synthesis** | Monthly (after the 4th survey) | Cross-repo patterns ("6 Jekyll sites duplicate X"), fleet C4 context, top-N challenges; candidate research questions |
| **Research project** | Opened when a challenge passes the research gate (§ 5); at most 1–2 active | Research plan → literature synthesis → analysis → paper draft PR |
| **Registry refresh** | Quarterly (+ ad hoc when a citation fails verification) | New `sources.yml` version |
| **Retro** | Quarterly, joined to Kaizen retro | Changes to rubric, cadence, caps (via PR; amendment only if a constitutional rule changes) |

Event triggers: a new submodule in `_data/projects.yml`, a new ADR, a conformance score drop, or a `arch-research` label on any issue queues an out-of-cycle survey. Caps live in `_data/fleet.yml` `arch_research:` (repos per run, tokens per run, max active projects) with a `vars.ARCH_RESEARCH_ENABLED` kill switch; schedule off the hour (e.g. Mondays 11:23 UTC) per the standing rules. Cost is reported as **API-equivalent (estimate)** per cycle.

**Division of labour.** Grok bots run survey, synthesis, literature work and drafting (high-level, low-risk, read-only). Implementation of any recommendation is a Fleet issue picked up by Claude Code through the issue pipeline. Amr reviews and merges papers.

## 3. Literature base and the source registry

Initial sources (each an entry in the registry with id, type, version/edition, date, URL/DOI, topics, and the claims we use):

- **Standards:** ISO/IEC/IEEE 42010 (architecture description), ISO/IEC 25010:2023 (quality model), ISO/IEC 25023 (measures), arc42, the C4 model.
- **Decision practice:** Nygard's ADRs, MADR, Y-statements, ATAM / SEI quality-attribute scenarios.
- **Books:** Bass/Clements/Kazman *Software Architecture in Practice* (4e); Richards & Ford *Fundamentals of Software Architecture* (2e) and *Software Architecture: The Hard Parts*; Ford/Parsons/Kua *Building Evolutionary Architectures* (2e, fitness functions); Evans *Domain-Driven Design* and Khononov *Learning DDD*; Newman *Building Microservices* (2e) / *Monolith to Microservices*; Ousterhout *A Philosophy of Software Design*; Kleppmann *Designing Data-Intensive Applications*; Skelton & Pais *Team Topologies*; Forsgren/Humble/Kim *Accelerate*; Google SRE books.
- **Frameworks:** AWS, Azure and Google Cloud Well-Architected; 12-Factor; CNCF cloud-native and platform-engineering white papers; OpenSSF Scorecard / SLSA; NIST SSDF.
- **Delivery & team research:** annual DORA *State of DevOps* reports, SPACE and DevEx frameworks, Thoughtworks Technology Radar.
- **Research venues:** ICSA, ECSA, ICSE/FSE, IEEE Software, JSS, arXiv cs.SE; practitioner talks (QCon, GOTO, InfoQ, SATURN archive).

**Keeping it current.** `docs/research/sources.yml` (`schema: arch-sources/v1`) is versioned (`version: YYYY.Q`). Each entry has `reviewed:` and `stale_after:`; the quarterly refresh checks new editions, new DORA/Radar issues and a venue scan, adds/retires entries in a PR, and bumps the version. Every finding and paper records the registry version it used, so a conclusion can be re-checked when a source changes. A finding may not cite anything absent from the registry; new sources are proposed in the same PR that first needs them.

## 4. Findings and traceability

Each finding is a block in `docs/research/findings/<yyyy-mm>/<repo>.md` (later a console panel):

```yaml
id: AR-<repo>-<yyyy-mm>-<n>
repo: bamr87/<repo>
attribute: maintainability.modularity     # ISO 25010 path
severity: structural | strategic | watch
evidence: [paths, metrics, ADR links]
sources: [iso-25010-2023, ford-evolutionary-2e]   # registry ids
features: [FEAT-012, HUB-029]             # feature catalog ids
prd: [FR24]                               # PRD requirement ids
recommendation: "…"                       # what, not how
handoff: <Fleet issue URL or none>
```

Findings link to the repo's `features.yml` ids (`HUB-NNN` in the hub, the repo's own prefix — `FEAT-NNN` — elsewhere) and PRD `FRn`/`NFRn`. A finding that touches no feature or requirement is flagged as a possible catalog gap. Accepted recommendations become Fleet project items (Status *Triaged*, Priority from severity, Feature ID / PRD req fields filled) and, when the decision is hard to reverse, a proposed ADR in the target repo.

## 5. From challenge to research project

A finding becomes a research project when it passes the **research gate**: it recurs in ≥ 2 repos or is fleet-level; the literature disagrees or is silent for our context; and the answer would change a decision (an ADR, a standard in `specs/`, or a roadmap item). Then:

1. **Frame** — write a research question in PICO-like form: *context* (which repos, which constraint), *intervention/option(s)*, *comparison*, *outcome* (ISO 25010 attribute or DORA metric). Add scope, non-goals, hypotheses and a time box. Filed as a `research` issue on Fleet project 14 (P3 default) linked to the findings.
2. **Gather** — structured literature search (registry first, then venue/arXiv search with logged query strings, inclusion/exclusion criteria, snowballing), lightweight systematic-review style; every candidate source is recorded.
3. **Verify citations** — each citation must resolve to a registry entry (added via the same PR if new), with DOI/URL reachable and the quoted claim checked against the source text; unverified claims are marked and cannot support a conclusion.
4. **Synthesize** — evidence table (source × claim × context fit × strength), noting agreement, conflict and gaps.
5. **Analyse the fleet** — apply the synthesis to the repos: metrics from the survey, ADR history, delivery data; options compared against quality-attribute scenarios (ATAM-style).
6. **Write** — the paper (§ 6); recommendations become Fleet items for Claude Code.

## 6. Papers

**Location.** `docs/research/<slug>/` containing:

- `paper.md` — the paper;
- `sources.yml` — the subset of the registry it cites, pinned to registry version, with verification status per citation;
- `meta.yml` — `schema: arch-paper/v1`, title, question, status (`draft | in-review | published | superseded`), authors (bot + reviewer), dates, registry version, repos studied, `features:` / `prd:` ids, linked findings and Fleet issues, API-equivalent (estimate) cost;
- `evidence/` — search log, evidence table, metrics snapshots.

`docs/research/` would get its own `SCHEMA.md` and a parent row in `docs/SCHEMA.md` when implemented; the `docs/README.md` index updates itself on `main`.

**Template (`paper.md`).**

1. Title, abstract (≤ 200 words), keywords
2. Problem statement — the challenge, where it shows in the fleet, the research question, scope and non-goals
3. Related work — synthesis of the literature, grouped by theme, with conflicts and gaps
4. Approach — method, search protocol, inclusion criteria, metrics, threats considered up front
5. Analysis — per-repo and cross-fleet evidence, option comparison against quality-attribute scenarios
6. Conclusions and recommendations — each tied to evidence and to `FEAT/HUB` and `FR/NFR` ids, with proposed Fleet items / ADRs
7. Limitations and threats to validity — construct, internal, external, AI-generation risks (hallucination, source bias)
8. References — only registry ids, rendered with full citation and DOI/URL

**Review and quality gate (before `published`).**

- *Automated:* `meta.yml` and `sources.yml` schema-valid; every in-text citation resolves to a verified source; every recommendation carries a feature or requirement id that exists in the target catalog/PRD; no secrets; one-paragraph-per-line; schema_lint clean.
- *AI peer review:* a second, independent reviewer pass using a reviewer rubric (question clarity, method fit, evidence strength, overclaiming, limitations honesty) that posts comments on the PR; the author pass must answer each.
- *Human:* Amr reviews and merges the PR; merging is publication. Agents never merge. A paper whose registry sources go stale is marked for re-review, and a later paper may supersede it.

## 7. Dependencies on fleet infrastructure

- **Hub `bamr87/bamr87`** — hosts the loop, registry, findings and papers; obeys check-drift, schema_lint, governance_lint.
- **Submodules under `projects/`** — read-only subjects; paths/branches from `_data/projects.yml` and `.gitmodules`.
- **`libraries/fleetkit` / `tools/fleetcore/`** — shared readers for the registry, features and lake; a future `arch_research` view goes there so console and TUI share it.
- **Harness console + MCP** — read tools (`arch_findings`, `arch_papers`) and a `/research` page; any Projects write goes through `gh_projects_write.py` under constitution § 11.
- **Harness registry** — a new entry in `_data/harness_registry.yml` (additive, so no schema bump) and caps in `_data/fleet.yml`.
- **Control-plane loops** — consumes fleet-pulse, deep-dive, conformance and repo-scout outputs; hands work to issue-pipeline; feeds Kaizen (#454) and uses telemetry from #446.
- **Fleet project 14** — research issues, handoff items and their Status/Priority/Feature ID/PRD req fields (#468 surface).

## 8. Governance

No new principle is introduced: the harness is read-only, PR-only, never merges, tracks work on project 14 and labels cost honestly — all already required by constitution §§ 4, 10, 11. **No amendment is needed.** Hard-to-reverse choices made while implementing (e.g. storing papers in the hub vs. a separate repo) would get an ADR then.

## 9. Roadmap (each a Fleet sub-issue, Claude Code implements)

1. Source registry v2026.Q4 + schemas (`arch-sources/v1`, `arch-paper/v1`)
2. Survey rubric and per-repo fitness record; pilot on 3 repos
3. Fleet synthesis + findings → Fleet items
4. Research-project pipeline and citation verifier
5. Paper template, review gate, first paper
6. Console page + MCP read tools; harness registry entry and caps
