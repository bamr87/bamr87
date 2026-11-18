<!-- kit: governance v0.1.0 -->
# 0034 — Fleet mission statements and the repository about section

- **Status:** ratified
- **Number:** 0034
- **Date:** 2026-11-16
- **Proposed by:** Grok Bot, at Amr's request on 2026-11-16 (voice): write the fleet-wide mission-statement standard into the hub, add organization structure and per-repo about context, and design each repo's about section as a consistent public site map
- **Ratified by:** https://github.com/bamr87/bamr87/pull/907 (merged 2026-11-18 by @bamr87)
- **Affects:** constitution § 1 (rewritten to the fleet mission format); constitution new § 31 (follows § 29 `agentic-efficacy-contract`; [bamr87/bamr87#858](https://github.com/bamr87/bamr87/pull/858) already proposes § 30, so this section is numbered § 31 to avoid a collision, and may be renumbered if merge order changes); § 14 by reference; PRD § 1; features `HUB-122` and `HUB-118`; requirements `FR138` and `FR136`; roadmap `FF-0057` and `FF-0056`; UPS-DOC-11; [docs/ABOUT-SECTION.md](../ABOUT-SECTION.md); [docs/FLEET.md](../FLEET.md); [docs/PORTFOLIO.md](../PORTFOLIO.md)
- **Supersedes:** none
- **Related:** [fredgar-ai#153](https://github.com/bamr87/fredgar-ai/pull/153) (amendment 0002, first three-mission statement); [law-ai#262](https://github.com/bamr87/law-ai/pull/262) (amendment 0003, same format, plus matching README and AGENTS.md one-liners); the read-only scan of 2026-11-16; portfolio skeleton [docs/PORTFOLIO.md](../PORTFOLIO.md) § 4 and UPS-DOC-10

## Context

Until this amendment, a fleet repo's constitution § 1 was a single mission paragraph, usually copied from its PRD and ratified only by amendment 0001. That is not wrong, but it is not a shared standard: there is no required shape, no rule that README and AGENTS.md say the same thing, and no fleet-wide promise about what a visitor will find.

On 2026-11-16 Amr asked for mission statements in the governance model — exactly three numbered missions under one direction statement, comprehensive and aspirational, aiming at "the ultimate open home for all things [domain]," with the first mission providing data, tools, resources and transparency for all stakeholders, professionals in the field, and the general public — and for the README and AGENTS.md one-liners to match and link to constitution § 1. [fredgar-ai#153](https://github.com/bamr87/fredgar-ai/pull/153) and [law-ai#262](https://github.com/bamr87/law-ai/pull/262) already follow that shape; neither is merged, and no default branch in the bamr87 user account yet has it (scan of 2026-11-16).

In the same conversation Amr asked that each repo's about section function as a site map: a consistent, reliable, comprehensive public-facing section covering contribution, docs, and the other fundamental pages. The portfolio README skeleton ([docs/PORTFOLIO.md](../PORTFOLIO.md) § 4, UPS-DOC-10) already orders overview, features, quick start, docs, contributing, changelog and license, but it does not require a mission one-liner linked to § 1, a governance cluster (constitution, amendments, PRD, feature catalog), a roadmap entry, or security and support links. Those gaps are what a visitor hits when they try to use the README as a map of the repo.

The hub's own § 1 was still a single descriptive paragraph. This amendment writes the standard in the hub first, applies it to the hub, and leaves fan-out to each other repo as follow-up PRs, ratified by Amr merging.

## Amendment

Replace constitution § 1 with:

> ## 1. Mission
>
> The bamr87 hub's direction is to become the ultimate open home for the fleet: the control plane, the shared standards, and a public window onto every project.
>
> 1. Provide data, tools, resources and transparency for all stakeholders, operators, contributors and the general public — the project registry, the Harness Console, the public documentation site, and the catalogs that make every repo visible and auditable.
> 2. Be the source of fleet standards and the path they take into each repo — the constitution, amendments, the PRD, the feature catalog, the Universal Project Standard, kits and fan-out — so a rule is written once in the hub, ratified by the maintainer merging, and adopted consistently across the fleet.
> 3. Run a reliable, agentic control plane for the work itself — the dash, the loops, JEV, the issue pipeline and the harness — so planning, execution, review and cost across the mounted projects stay governed, observable and local-first where they can be.
>
> This § 1 format — one direction statement and exactly three numbered missions, adopted only through a numbered amendment — is the fleet-wide mission standard (see § 31). The README and AGENTS.md one-liners match this direction and link here.
>
> _Source: this section; [PRD.md](../PRD.md) § 1._

Add to the constitution, after § 29:

> ## 31. Fleet mission statements and the repository about section
>
> _(amendment `mission-and-about-section`, numbered at merge — see the [amendment log](amendments/README.md); follows § 29 `agentic-efficacy-contract`; [bamr87/bamr87#858](https://github.com/bamr87/bamr87/pull/858) proposes § 30, so this section is numbered § 31 to avoid a collision and may be renumbered if merge order changes; extends § 1 and § 14; features `HUB-122` and `HUB-118`)_
>
> 1. **Mission statements.** Every governed fleet repo states its purpose in constitution § 1 as one direction statement followed by exactly three numbered missions. The text is adopted only through a numbered amendment, ratified when the maintainer merges the PR (§ 8). Ambition is written as direction, not as a claim of current capability. The first mission provides data, tools, resources and transparency for all stakeholders in that repo's domain, including professionals in the field and the general public, unless a ratified amendment records a documented reason it does not apply (for example a private research repo).
> 2. **Matching one-liners.** The repo's README tagline and AGENTS.md opening one-liner match that direction and link to constitution § 1.
> 3. **About section as site map.** Every non-fork, non-archived fleet repo carries a public-facing about section, primarily in `README.md` and on the public docs site (§ 14), that functions as a site map of the repo's fundamental pages. The required and optional entries, and the exemptions for forks and archived repos, are defined in [docs/ABOUT-SECTION.md](ABOUT-SECTION.md). The section is consistent (the same entries in the same order), reliable (links resolve to files that exist) and comprehensive (every required entry is present, and every optional entry is present when the underlying page exists).
> 4. **Hub first, then fan-out.** The standard is written and ratified in this hub, then fanned out to each repo in its own PR. A repo may already be ahead of the standard (for example an open mission-statement amendment); those PRs stay valid and are ratified by the maintainer merging them.
> 5. **Conformance.** A `tools/conformance.py` check verifies the § 1 shape and the about-section links; warn-only per repo until its fan-out PR lands, then a hard failure for that repo. The check itself is follow-up work and is not in this amendment's pull request.
> 6. **Exemptions.** Forks keep the upstream README. Archived and retired repos need a README, a license when one exists, and a retired notice. Private repos are flagged, never made public by an agent, and may omit a public about section for sensitive research. Any other exemption needs a reason the § 15 completeness review accepts.

## Consequences

- The hub's README, AGENTS.md and PRD § 1 one-liners are updated in this same pull request so they match the new direction and link to constitution § 1. The profile README keeps its personal intro; the control-plane half carries the mission line and the site map.
- [docs/ABOUT-SECTION.md](../ABOUT-SECTION.md) is the operator doc for the site-map structure (required vs optional entries). [docs/FLEET.md](../FLEET.md) records organization structure, general fleet information, and a per-repo context table with about-section coverage as of 2026-11-16. [docs/PORTFOLIO.md](../PORTFOLIO.md) § 4 is extended, not replaced, so the existing skeleton still holds. UPS-DOC-11 is added beside UPS-DOC-10.
- `templates/governance/constitution.template.md` § 1 is updated to the three-mission format so later fan-out starts from the standard.
- Fan-out to other repos, and the conformance check in item 5, are follow-up PRs. This pull request does not merge, and it does not change spoke repositories.
- Feature and requirement ids, the amendment number, and the roadmap ids are assigned at merge (amendment 0002). They are referenced here by slug.
