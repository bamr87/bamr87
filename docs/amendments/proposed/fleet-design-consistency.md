<!-- kit: governance v0.1.0 -->
# NEW — One front-end shell, layout and design language across the fleet

- **Status:** proposed
- **Number:** NEW
- **Date:** 2026-11-01
- **Proposed by:** agent (Grok Bot, on a branch opened for bamr87 at Amr's request on 2026-11-01)
- **Ratified by:** _(blank until the pull request is merged)_
- **Affects:** constitution new § 18 (follows § 17 `central-loop-switches`); `tools/conformance.py` (new check `design`); roadmap FF-0032; feature and requirement ids: HUB-NEW:frontend-platform, FR-NEW:frontend-platform (the fragment #566 adds, as its body asks)
- **Supersedes:** none (extends § 14 and § 15)
- **Related:** roadmap FF-0032 (bamr87/bamr87#553), [docs/DESIGN-HARMONIZATION.md](../../DESIGN-HARMONIZATION.md), 0007 `public-docs-site` (zer0 theme), 0010 `major-change-evidence` (visual evidence), 0013 `ai-ready-foundation` (warn-then-fail rollout), issue #364 (fleet theme contrast rollup)

## Context

The constitution fixes the docs-site theme (§ 14: GitHub Pages + `bamr87/zer0-mistakes`) and requires visual evidence for frontend PRs (§ 15), but says nothing about the app front-ends. The Harness Console (`tools/console/web`, React + Mantine), its earlier design package (`tools/console/design-system`, `@bamr87/harness-console-ui`), the fleetcore bashOS palette, the zer0 Jekyll theme family (owned by Sites) and per-repo apps (e.g. gitorio's archify-based console) each carry their own shell, layout and tokens. Users meet a different navigation, layout and look in each repo.

Prior art checked: § 14 / 0007 (zer0 for docs sites — kept, not replaced), fleetcore's shared palette (the token seed), `@bamr87/harness-console-ui` (the package pattern), 0013's warn-then-fail conformance rollout (the enforcement pattern). No existing section or amendment covers fleet-wide front-end layout, structure and design consistency.

## Amendment

Add to the constitution:

> ## 18. Fleet design consistency
>
> 1. **One design language** — every fleet front-end (apps, consoles, dashboards and public sites) uses the fleet's shared design tokens (colour, type, spacing, radius, motion), with light and dark themes.
> 2. **One shell** — app front-ends use the shared app shell from the hub (the Harness Console shell, roadmap FF-0032): collapsible, manageable, customizable regions with the same navigation model. Jekyll sites keep the zer0 theme (§ 14), which consumes the same tokens.
> 3. **Ownership** — the hub owns the tokens and the shell package; Sites owns the zer0 theme family; a repo may extend but not fork them.
> 4. **Conformance** — `tools/conformance.py` check `design` verifies tokens and shell (or zer0) are used; warn-only per repo until its fan-out PR lands, then a hard failure.
> 5. **Evidence** — design changes follow § 15 visual evidence.
> 6. **Exemptions** — CLIs, libraries without UI, and archived or retired repos are exempt; any other exemption needs a reason the § 15 completeness review accepts.

## Consequences

- The hub publishes a shared tokens + shell package and a conformance check (plan: docs/DESIGN-HARMONIZATION.md).
- zer0-mistakes adopts the shared tokens (Sites).
- Each front-end repo gets a fan-out PR; the check stays warn-only for that repo until it merges.
- Follow-ups: PRD requirement and feature catalog entry (ids TBD), AGENTS.md standing rule.
