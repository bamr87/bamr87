# docs/ — monorepo documentation

Architecture and process docs for the root monorepo (the submodules carry their own docs).

| Doc | Purpose |
| --- | --- |
| [DASH.md](DASH.md) | **The dash architecture** — registry, surfaces, monitoring, drift gates, AI loop. Start here. |
| [AI-INTEGRATION.md](AI-INTEGRATION.md) | The AI layer — surfaces, Claude auth/secrets, feedback loops, fleet propagation. |
| [DAILY-ANALYSIS.md](DAILY-ANALYSIS.md) | The continuous analysis → implementation cycle — daily fleet digest + agent that fixes CI failures. |
| [STANDARDS.md](STANDARDS.md) | The per-tier standardization baseline every submodule is held to, and how it's enforced. |
| [SCHEMA-FRAMEWORK.md](SCHEMA-FRAMEWORK.md) | The Pyramid Schema — per-directory `SCHEMA.md` contracts and fleet adoption. |
| [RELEASES.md](RELEASES.md) | Versioning, changelogs, releases, and the merge-to-main quality gate. |
| [ARCHITECTURE.md](ARCHITECTURE.md) | System design, components, and design decisions. |
| [MONOREPO.md](MONOREPO.md) | Repository organization and submodule management. |
| [DEVELOPMENT.md](DEVELOPMENT.md) | Local setup and development workflow. |
| [README-TEMPLATE.md](README-TEMPLATE.md) | Template for standardizing project READMEs. |
| [SUBMODULE-CHECKLIST.md](SUBMODULE-CHECKLIST.md) | Narrative README checklist (historical — the operational standard is the tier system in STANDARDS.md). |
| [TESTING-REPORT.md](TESTING-REPORT.md) | Historical test snapshot from the January 2025 reorganization. |

See also the root [`CLAUDE.md`](../CLAUDE.md), [`AGENTS.md`](../AGENTS.md), and [`SUBMODULES.md`](../SUBMODULES.md).
