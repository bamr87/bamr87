# docs/ — monorepo documentation

Operator documentation for the hub and the machinery that runs the fleet. The submodules carry their own docs.

**One topic, one home.** If a doc here starts re-explaining the submodule workflow, the port table, or the registry schema, it should link instead — those live in [`../SUBMODULES.md`](../SUBMODULES.md), [DASH.md](DASH.md), and [`../_data/projects.yml`](../_data/projects.yml) respectively.

| Doc | Purpose |
| --- | --- |
| [DASH.md](DASH.md) | **The dash architecture** — registry, surfaces, monitoring, drift gates, AI loop. Start here. |
| [DEVELOPMENT.md](DEVELOPMENT.md) | Local setup, containers, the everyday loop, and the pre-PR checklist. |
| [AI-INTEGRATION.md](AI-INTEGRATION.md) | The AI layer — surfaces, Claude auth/secrets, feedback loops, fleet propagation. |
| [DAILY-ANALYSIS.md](DAILY-ANALYSIS.md) | The daily fleet-pulse loop — signals gathered, queue built, doctor agent fixes. |
| [ESTIMATION.md](ESTIMATION.md) | Engagement estimation & cost tracking — every project a client, deterministic estimates, evidence-accrued actuals, variance. |
| [WORKFLOW-OPTIMIZATION.md](WORKFLOW-OPTIMIZATION.md) | Fleet-wide GitHub Actions audit — where the minutes go and what was optimized. |
| [STANDARDS.md](STANDARDS.md) | The per-tier standardization baseline every submodule is held to, and how it's enforced. |
| [DEPENDENCIES.md](DEPENDENCIES.md) | The **always-latest** dependency policy — no pins, no lockfiles; CI and the fleet-pulse loop absorb breakage. |
| [SCHEMA-FRAMEWORK.md](SCHEMA-FRAMEWORK.md) | The Pyramid Schema — per-directory `SCHEMA.md` contracts and fleet adoption. |
| [RELEASES.md](RELEASES.md) | Versioning, changelogs, releases, and the merge-to-main quality gate. |

Root-level companions: [`CLAUDE.md`](../CLAUDE.md) (agent context), [`AGENTS.md`](../AGENTS.md) (working principles), [`SUBMODULES.md`](../SUBMODULES.md) (the submodule workflow), [`CONTRIBUTING.md`](../CONTRIBUTING.md) (commit and branch conventions).

## Removed on 2026-08-09

Six documents were deleted rather than updated. Four of them opened with a banner admitting they were historical, and one described a four-submodule fleet that has been thirty-five for over a year — an indexed doc that is wrong is worse than a missing one, because agents and newcomers route by this table.

| Removed | Where its content lives now |
| --- | --- |
| `ARCHITECTURE.md` | [DASH.md](DASH.md) — it predated the dash and described MkDocs as the Pages surface. |
| `DEVELOPMENT.md` (519 lines) | Rewritten, ~80 lines. The old one was mostly one project's commands and a dead MkDocs workflow. |
| `MONOREPO.md` | [DASH.md](DASH.md) + [`../SUBMODULES.md`](../SUBMODULES.md) — it was a third copy of both. |
| `TESTING-REPORT.md` | Nothing. A January 2025 snapshot of a four-submodule repo. |
| `SUBMODULE-CHECKLIST.md` | [STANDARDS.md](STANDARDS.md) — the tier system superseded it, as its own banner said. |
| `README-TEMPLATE.md` | [`../.github/templates/README.template.md`](../.github/templates/README.template.md) — the copy the fan-out actually uses. Two templates existed, 361 diff lines apart, and humans found the wrong one first. |
