<!-- kit: governance v0.1.0 -->
# NEW — Test evidence for major changes, visual evidence for frontend PRs, and a skilled-reviewer completeness pass

- **Status:** proposed
- **Number:** NEW
- **Date:** 2026-10-30
- **Proposed by:** agent (Grok Bot, on a branch opened for bamr87)
- **Ratified by:** _(blank until the pull request is merged)_
- **Affects:** constitution new § 15 (§ 13 is reserved by `eval-baseline-risk-tiers`, #482, still open; § 14 is `public-docs-site`, 0007); § 12 (adds a completeness review to the review gate); specs UPS-QA-52 (raised from SHOULD to MUST by reference); `.github/pull_request_template.md`; features `HUB-NEW:major-change-evidence`, `HUB-NEW:evidence-conformance`; requirements `FR-NEW:major-change-evidence`, `FR-NEW:evidence-conformance`
- **Supersedes:** none (extends § 7, § 12 and UPS-QA-50..53)
- **Related:** 0007 `public-docs-site` (per-repo warn-then-fail rollout pattern), 0008 `harness-prior-art-research`, 0009 `agent-merge-review-gate`, #482, docs/VERIFICATION.md, `.github/workflows/fleet-verify.yml`, `templates/verify/`, `templates/site-quality/`

## Context

Amr's direction: "there needs to be a constitutional amendment that requires testing and evidence of major changes. if the frontend is impacted, visual evidence is required with every PR, and a skilled reviewer analyzes for completeness." Today evidence for user-visible changes is only a SHOULD (UPS-QA-52), "major" is undefined, and no rule says who reviews a PR for completeness or how that review relates to the § 12 review gate.

## Prior art

Per 0008, existing fleet tooling is reused, and no new tool is built:

- **Verification standard (docs/VERIFICATION.md, UPS-QA-50..53, `fleet-verify.yml`, `templates/verify/`):** the feature index, user scenarios, the Playwright runner and evidence bundles under `test/evidence/<slug>/` at two or more viewports, with a `skip-evidence` label plus a reason for non-visual changes. Fit: this is the visual-evidence mechanism. Adopt, and raise UPS-QA-52 to MUST for frontend PRs.
- **zer0-mistakes `test/visual/evidence-kit.mjs` and its `visual-evidence` skill:** before/after screenshot montages plus `metrics.json`. Fit: the before/after format. Adopt.
- **Site quality kit (`templates/site-quality/`, it-journey#790, lifehacker.dev#683):** Lighthouse, axe and pa11y on Jekyll sites. Fit: an automated layer under the human review of a frontend PR. Adopt as-is.
- **PR templates:** the hub's `.github/pull_request_template.md` (Definition of Done) and `bamr87/.github` `PULL_REQUEST_TEMPLATE.md` (fleet default). Fit: add the evidence sections there rather than to a new form. Extend.
- **AGENTS.md "Verify like a user" convention and `tools/conformance.py`:** the existing rule and the existing gate. Fit: host the check as new check ids. Extend.
- **Build-vs-adopt:** adopt all of the above. The new pieces are only the definitions, two template sections and two conformance check ids.

## Amendment

Add constitution § 15 "Evidence for major changes and frontend PRs" with this text:

> 1. **Major change: JEV decides** — whether a PR is *major* is a judgment made by JEV, the fleet's harness-level agent logic engine ([docs/JEV.md](../../JEV.md)), which is also slated to triage merge conflicts. JEV weighs these heuristic inputs, none of which is decisive on its own: a change to a public interface or user-visible behaviour (a CLI flag or command, an API route or schema, a workflow input or output, a published config key, a page or route); a touch on an area gated by § 12.3; a change to, or the addition or removal of, a feature in `features/features.yml`; the size and spread of the non-generated diff; and a change to dependencies or a toolchain version. There are no fixed line or file thresholds. The `major` label is a manual override: a PR carrying it is major whatever JEV decides. Once § 13 (#482) is ratified, JEV must itself meet its eval-set requirements before its decisions count.
>    **Interim fallback (until JEV exists):** the heuristics above are applied as a checklist that flags candidate PRs, and the completeness reviewer (item 5) makes the call. When in doubt, the PR is treated as major. This fallback lapses when JEV is deployed and passes its evals.
> 2. **Test evidence for major changes** — a major PR states, in its body: the tests added or updated (paths), or why none apply; and links to the green CI run for its head commit. A behaviour change without a new or changed test needs a reason the reviewer accepts.
> 3. **Frontend detection** — a PR *impacts the frontend* when it changes any file matching the repo's frontend globs. The defaults are `_layouts/**`, `_includes/**`, `_sass/**`, `assets/**`, `pages/**`, `_posts/**`, `**/*.{html,css,scss,jsx,tsx,vue,svelte}`, `tools/console/web/**` and `_config.yml`. A repo may add globs, but not remove defaults, in `verify/verify.yml` under `frontend_paths:`.
> 4. **Visual evidence on every frontend PR** — every PR that impacts the frontend, major or not, ships before and after screenshots, or a recording, of each affected page at two or more viewports. These come as a `test/evidence/<slug>/` bundle (docs/VERIFICATION.md) or as images in the PR body. `skip-evidence` is allowed only when the change has no rendered effect, with a one-line reason that the reviewer checks.
> 5. **Completeness review by JEV and QA Lead** — every major or frontend PR gets a completeness review covering four things: does the evidence match the change, is every affected page or path shown, do the tests cover the behaviour that changed, and are docs and the feature index updated. The reviewers are JEV and the QA bot **QA Lead** (the role in [docs/PROJECTS-FRAMEWORK.md](../../PROJECTS-FRAMEWORK.md) that moves In review → Done on verified evidence). Both must pass. A reviewer is never the PR's author, and neither bot approves its own work: if JEV or QA Lead authored the PR, that bot's review is replaced by Amr's. A reviewer that finds gaps requests changes; it cannot waive a requirement.
>    **Interim fallback:** until JEV exists, QA Lead alone does the review. Until QA Lead exists too, Amr does the completeness review (**flagged: proposed fallback, Amr to confirm**). Major and frontend PRs then wait for Amr's review, and the check's warn-only phase records the PRs that wait.
> 6. **Fit with § 12** — the completeness review is a "required review" under § 12.1.2. For a PR the review gate (§ 12.3) holds, the completeness review is in addition to Amr's gate and does not replace it. Amr still alone ratifies amendments by merging (§ 8, § 12.5).
> 7. **Enforcement and rollout** — the PR template carries "Test evidence", "Visual evidence" and "Completeness review" sections. A conformance check in `tools/conformance.py` verifies that a major PR has test evidence and a green CI link, that a frontend PR has visual evidence or a valid `skip-evidence`, and that a qualifying completeness review exists. The check is warn-only for each repo until that repo's spoke fan-out PR lands, and a hard failure after (the 0007 pattern).

## Consequences

- UPS-QA-52 becomes MUST for frontend PRs under this section; follow-up edits `specs/QUALITY.md`, then `gen-specs-data.py` regenerates `_data/specs.yml`.
- Follow-up: add the three sections to `.github/pull_request_template.md` and to `bamr87/.github` `PULL_REQUEST_TEMPLATE.md`; add a `major` label; add the two conformance check ids (feature `HUB-NEW:evidence-conformance`).
- Dependencies: JEV's major-change judgment and review need JEV to be built (docs/JEV.md roadmap) and, after #482, to pass its eval set. QA Lead must be deployed as a bot. Until then, the interim fallbacks in items 1 and 5 apply.
- Fan-out: one PR per spoke repo after ratification, which also turns that repo's check from warn to fail.
- Merging the pull request that carries this record ratifies it. An agent never merges it.
