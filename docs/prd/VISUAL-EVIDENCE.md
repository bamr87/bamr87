# PRD — Visual evidence for guides and tutorials

> **Status: Draft / proposed.** Design + governance first; lint warn-only on the hub.
> Feature: `HUB-NEW` (slug `visual-evidence`) in [`features/features.d/visual-evidence.yml`](../../features/features.d/visual-evidence.yml). Number assigned at merge (likely **HUB-081**).
> Requirement: `FR-NEW:visual-evidence` (likely **FR79**).
> Roadmap: `FF-0039` in [`_data/roadmap.yml`](../../_data/roadmap.yml).
> Epic: [#678](https://github.com/bamr87/bamr87/issues/678). Backlog P0: [#679](https://github.com/bamr87/bamr87/issues/679).
> Standard: [`docs/VISUAL-EVIDENCE.md`](../VISUAL-EVIDENCE.md). Amendment: `docs/amendments/0022-visual-evidence.md`.

## 1. Overview / problem

Readers following hub tutorials, setup docs and console help often get prose and shell blocks with no screenshot of the UI they should see. Constitution § 15 already demands visual evidence for frontend PRs; guides were left out. The standard must evolve in this monorepo and fan out to the fleet.

## 2. Goals and non-goals

**Goals**

- One clear rule for when guides need visuals, where they live, how they are named, alt text, redaction and freshness.
- A warn-then-fail lint so gaps are visible before they are blocking.
- A path for the Harness Console to capture and attach evidence (phased).
- Hub-first fan-out to other repos.

**Non-goals (this slice)**

- Backfilling every lacking guide in the ratification PR (tracked on #679).
- Editing submodule repos.
- Replacing § 15 PR evidence.

## 3. Requirement

- **FR-NEW:visual-evidence** — Tutorials, how-tos, setup docs, console/UI help pages and walkthrough articles must ship visual front-end evidence (screenshots, a short recording or a GIF) under `docs/assets/guides/<slug>/` or `test/evidence/<slug>/` with meaningful alt text and redaction of secrets/PII/tokens, or a one-line `skip-visuals` reason; a guides visual lint must flag gaps (warn-only per repo until adoption, then hard fail); when a PR changes a depicted UI it must update or re-capture the guide visuals in the same PR.

## 4. User stories

- **US1:** As Amr, I open a setup guide and see the same Harness Console screen the prose describes, so I can follow the steps without guessing.
- **US2:** As a guide author (human or agent), I know the path, filename and alt-text rules before I attach a screenshot, and I can skip only with an explicit reason the lint accepts.
- **US3:** As a reviewer, I reject a guide PR that embeds a token or unredacted PII in an image, without the secret being reprinted in the review comment.
- **US4:** As a frontend-changing PR author, I am reminded to re-capture guide visuals that depict the UI I changed, in the same PR.
- **US5:** As a console operator, I capture and attach guide evidence from the Harness Console (P1) without copying files through an ad-hoc path.
- **US6:** As a spoke-repo maintainer, I get a fan-out PR that adopts the standard and flips the lint from warn to fail when we are ready (P3).

## 5. Phases

| Phase | Issue | Acceptance |
| --- | --- | --- |
| P0 Standard + lint | [#679](https://github.com/bamr87/bamr87/issues/679) | Amendment + § 24 + standard doc + warn-only lint + backlog checklist |
| P1 Console capture | (file under #678) | Capture/attach/redaction helpers in the console |
| P2 Backfill | #679 checklist | Priority hub guides gain visuals or documented skips |
| P3 Fan-out | (file under #678) | Seed kit; warn→fail per spoke |
| P4 Freshness automation | (file under #678) | Hook into § 15 frontend detection and/or drift |

## 6. Design for Failure

| Failure | Behaviour |
| --- | --- |
| Stale screenshot | Freshness rule; UI-changing PR updates the guide or the lint fails once hard |
| Secrets/PII in an image | Redaction rule; scrub/replace the asset; never echo the secret |
| Broken image link | Lint reports missing targets; hard-fail after adoption |
| Capture tooling down | Temporary `skip-visuals` with reason; re-capture on the backlog |
| Spoke not adopted | Warn-only for that repo until its fan-out PR merges |

## 7. Guardrails

PRs only; agents never merge; no force-push; no settings/secrets changes; never print tokens; nothing on Amr's Mac without his yes (§ 10.5).
