<!-- kit: governance v0.1.0 -->
# 0003 — GitHub Projects as the fleet's system of record for work

- **Status:** ratified
- **Date:** 2026-10-29
- **Proposed by:** Grok Bot (Fleet Ops / Platform Architect) for bamr87
- **Ratified by:** https://github.com/bamr87/bamr87/pull/439 (merged 2026-10-30 by @bamr87)
- **Affects:** constitution § 6 (change process), § 7 (quality gates), new § 9 (work tracking); PRD FR-NEW:projects-coverage, FR-NEW:projects-sync, NFR-NEW:projects-scope-honest; features HUB-NEW:github-projects-framework, HUB-NEW:projects-coverage-gate, HUB-NEW:projects-sync-console (fragments in `features/features.d/`; ids assigned at merge per amendment 0002)
- **Supersedes:** none
- **Related:** [docs/PROJECTS-FRAMEWORK.md](../PROJECTS-FRAMEWORK.md), [templates/projects/framework.yml](../../templates/projects/framework.yml)

> Numbering: 0002 is [conflict-free numbering](0002-conflict-free-numbering.md); 0003 was still free when main was merged in. The feature and requirement ids are assigned by `tools/jev/number.py` at merge.

## Context

Work across ~42 repos in bamr87 and five orgs is tracked by labels (`agent:*`, `P0–P3`, `size:*`, `area:*`), the issue pipeline and `_data/fleet_triage.yml`, but there are **no GitHub Projects (v2)** linking it, labels differ by repo, milestones are unused, and nothing ties an issue or PR to a feature id (HUB-NNN) or PRD requirement. The `gh` token in the harness lacks the `project` scope, so no tool can read or write projects today.

## Amendment

1. Every open issue and PR in a registry repo belongs to the fleet portfolio project and, where one exists, its domain project, with the required fields of `templates/projects/framework.yml` (Status, Priority, Area, Repo; Feature ID / PRD req when the item changes a feature or requirement).
2. `templates/projects/framework.yml` is the single source for projects, fields, options, lifecycle states and the label map; projects and labels are reconciled from it, never edited by hand.
3. Status follows one lifecycle: Inbox → Triaged → Ready → In progress → In review → Done (| Blocked, Won't do). The `agent:*` labels mirror Status, not the reverse.
4. `tools/projects_lint.py` joins the quality gates: offline it validates the framework spec; with project read access it reports items missing from a project or missing required fields (warning for 30 days after ratification, then error).
5. Agents and bots change project items only through the console MCP layer or the sanctioned sync workflow, never by hand-built API calls.

## Consequences

The hub gains a constitution § 9, three feature ids and three requirements. Rollout (docs/PROJECTS-FRAMEWORK.md) is phased; creating projects, editing labels and granting the token scope happen only after ratification.
