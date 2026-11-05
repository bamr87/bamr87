# NEW — Visual evidence is required for tutorials, guides and setup docs

- **Status:** proposed (ratification pending — Amr ratifies by merging this PR)
- **Number:** NEW
- **Date:** 2026-11-05
- **Proposed by:** Grok Bot (agent), on Amr's instruction as owner
- **Ratified by:** the merged PR URL (leave blank until merged)
- **Affects:** constitution § 24 (new, follows § 23 `writing-chronicle` on main; § 22 is proposed by open PR #660 `repo-cap-42` — § 24 stays free either way; renumber only if a later amendment claims 24 first); § 15 by reference (PR evidence stays there); feature `HUB-NEW:visual-evidence`; requirement `FR-NEW:visual-evidence`; roadmap FF-0039; docs `VISUAL-EVIDENCE.md`, `prd/VISUAL-EVIDENCE.md`
- **Supersedes:** none (extends § 7, § 15 and UPS-QA-52 to *guides*, without changing frontend-PR rules)
- **Related:** epic #678, backlog #679; amendment 0010 `major-change-evidence` (§ 15); `docs/VERIFICATION.md`; `test/evidence/`; Design for Failure (DFF, `.github/copilot-instructions.md`)

## Context

Amr's direction: make capturing screenshots and other visual front-end evidence a **standard practice** across the Harness Console and the entire monorepo for tutorials, articles and anything that guides a user through a system, computer or technology setup. The standard evolves in this hub first and fans out to other fleet repos from here.

Constitution § 15 already requires visual evidence for *frontend PRs*. It does not say when a *guide* (tutorial, how-to, setup doc, console help, walkthrough article) must ship screenshots, GIFs or recordings; how to name and store them; how to write alt text; how to redact secrets/PII/tokens in images; or when to re-capture after a UI change. An audit of hub-only docs (no submodule crawl) found most guide-like pages lack visuals — see #679 and `docs/visual-evidence-backlog.md`.

## Prior art

Per 0008, existing fleet tooling is reused:

- **§ 15 / UPS-QA-52 / `docs/VERIFICATION.md` / `test/evidence/<slug>/`:** PR visual evidence, viewports, `skip-evidence` with a reason. Fit: storage and skip pattern for guides. Extend, do not fork.
- **zer0-mistakes evidence kit / `visual-evidence` skill:** before/after montages. Fit: capture format. Adopt.
- **§ 23.3 chronicle redaction:** never record tokens/secrets. Fit: the same rule for pixels in images. Align.
- **Build-vs-adopt:** adopt the evidence kit and § 15 paths; new pieces are the guide standard, a warn-then-fail guides lint, console capture (later phase) and fleet fan-out.

## Amendment

New constitution section:

> ## 24. Visual evidence for guides and tutorials
>
> _(amendment `visual-evidence`, numbered at merge — see the [amendment log](amendments/README.md); follows § 23 `writing-chronicle` on main; § 22 is proposed by `repo-cap-42` (PR #660) — this section is § 24 either way; renumber only if another amendment claims 24 first; extends § 7 and § 15)_
>
> 1. **Guides need visuals** — any tutorial, how-to, setup doc, console/UI help page or article that walks a person through a system, computer, tool or technology setup ships visual front-end evidence: screenshots, a short recording, or a GIF of the relevant UI or terminal, unless a one-line `skip-visuals` reason says why nothing renders for the reader.
> 2. **When** — required when the reader is told to click, navigate, configure, install via a UI, or compare what they see on screen; not required for pure API/contract prose with no user-visible surface (still prefer a diagram when it clarifies).
> 3. **Where and naming** — store under `docs/assets/guides/<slug>/` for durable guide art, or under `test/evidence/<slug>/` when the same bundle also proves a feature scenario (`docs/VERIFICATION.md`). Names are kebab-case, viewport-tagged when size matters (`<slug>--desktop.png`, `<slug>--mobile.png`); recordings use `.gif` / `.webm` / `.mp4`.
> 4. **Alt text** — every image has meaningful alt text that describes what the reader should notice; decorative spacer images are forbidden in guides.
> 5. **Redaction** — a guide image never shows tokens, secrets, credentials, keys, cookies, private URLs with embedded credentials, or unredacted PII; redact before commit (same bar as § 23.3).
> 6. **Freshness** — when a change alters a UI a guide depicts, the same PR updates or re-captures the guide visuals (or adds `skip-visuals` with why). Stale screenshots are a defect, not documentation debt to ignore.
> 7. **Harness Console** — the console gains capture/attach helpers so operators and agents can record guide evidence without leaving the control plane (phased; see feature `HUB-NEW:visual-evidence`).
> 8. **Enforcement** — a guides visual lint (`tools/guides_visual_lint.py`) flags guide-like Markdown lacking an image, an evidence-bundle reference, or a `skip-visuals` reason; warn-only per repo until its adoption/fan-out PR lands, then a hard failure. Fleet fan-out follows the 0007 pattern (one spoke PR per repo).
> 9. **Fit with § 15** — frontend *PR* evidence stays under § 15; this section covers *published guides*. A change may need both.

## Design for Failure

| Failure | Behaviour |
| --- | --- |
| Stale screenshot (UI changed, guide did not) | Freshness rule (item 6): the UI-changing PR updates the guide or fails the lint once hard; prefer dated evidence bundles and viewport tags so reviewers can see age |
| Secrets / PII / tokens leaked in an image | Redaction rule (item 5): refuse the PR; scrub or replace the asset; never print the secret in the review comment |
| Broken image link / missing asset | Lint fails (once hard) when a referenced path is missing; warn-only until adoption |
| Capture tooling unavailable | `skip-visuals: capture unavailable — <reason>` is allowed temporarily; backlog the re-capture on #679 / P2 |
| Fan-out not yet landed in a spoke | Check stays warn-only for that repo (item 8); hub adopts first |

## Open questions

- Exact front-matter key: `skip-visuals:` in YAML front matter vs an HTML comment marker — default in the standard doc is front matter; confirm at review.
- Should guide assets live only under `docs/assets/guides/`, or may posts under `pages/posts/` keep images beside the post?
- OCR / secret-scanning of PNGs as a hard gate (aligned with the chronicle open question) — deferred; redaction is a human/agent duty until a scanner lands.

## Consequences

- Agents and humans authoring or updating a guide attach visuals or a `skip-visuals` reason in the same PR.
- Follow-up on #679: finish the lint fixtures, wire warn-only into hub CI, then P2 backfill of `docs/visual-evidence-backlog.md`.
- Follow-up (epic #678 P1): console capture/attach/redaction UX.
- Follow-up (epic #678 P3): spoke fan-out kit.
- Feature fragment `features/features.d/visual-evidence.yml` (`HUB-NEW`, `FR-NEW:visual-evidence`); roadmap `FF-0039`.
- Predicted ids at merge (as of 2026-11-05 on main): amendment **0022** if this merges before #660, else **0023**; feature **HUB-081**; requirement **FR79**. Section number **§ 24** either way relative to #660.
- Ratification: Amr ratifies this amendment by merging the PR; agents propose, never merge (§ 8).
