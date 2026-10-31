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

> 1. **Major change** — a PR is *major* when any of these holds, judged from its diff and labels: (a) it changes a public interface or user-visible behaviour (a CLI flag or command, an API route or schema, a workflow input or output, a published config key, or a page or route); (b) it touches an area gated by § 12.3; (c) it changes a feature with an id in `features/features.yml`, or adds or removes one; (d) it changes more than 300 lines of non-generated code or more than 10 non-generated files; (e) it adds or removes a dependency or changes a toolchain version; or (f) it carries the `major` label. Generated files, lockfile-free dependency bumps from automation and docs-only changes outside § 12.3 are not major on their own.
> 2. **Test evidence for major changes** — a major PR states, in its body: the tests added or updated (paths), or why none apply; and links to the green CI run for its head commit. A behaviour change without a new or changed test needs a reason the reviewer accepts.
> 3. **Frontend detection** — a PR *impacts the frontend* when it changes any file matching the repo's frontend globs. The defaults are `_layouts/**`, `_includes/**`, `_sass/**`, `assets/**`, `pages/**`, `_posts/**`, `**/*.{html,css,scss,jsx,tsx,vue,svelte}`, `tools/console/web/**` and `_config.yml`. A repo may add globs, but not remove defaults, in `verify/verify.yml` under `frontend_paths:`.
> 4. **Visual evidence on every frontend PR** — every PR that impacts the frontend, major or not, ships before and after screenshots, or a recording, of each affected page at two or more viewports. These come as a `test/evidence/<slug>/` bundle (docs/VERIFICATION.md) or as images in the PR body. `skip-evidence` is allowed only when the change has no rendered effect, with a one-line reason that the reviewer checks.
> 5. **Skilled-reviewer completeness pass** — every major or frontend PR gets a completeness review covering four things: does the evidence match the change, is every affected page or path shown, do the tests cover the behaviour that changed, and are docs and the feature index updated. A *skilled reviewer* is either Amr, a human Amr names in `_data/fleet.yml` `reviewers:`, or a designated QA-lead bot listed there that runs its own eval set under § 13 and has a recorded review history. The reviewer is never the PR's author and never approves its own work. A bot reviewer that finds gaps requests changes; it cannot waive a requirement.
> 6. **Fit with § 12** — the completeness review is a "required review" under § 12.1.2. For a PR the review gate (§ 12.3) holds, the completeness review is in addition to Amr's gate and does not replace it. Amr still alone ratifies amendments by merging (§ 8, § 12.5).
> 7. **Enforcement and rollout** — the PR template carries "Test evidence", "Visual evidence" and "Completeness review" sections. A conformance check in `tools/conformance.py` verifies that a major PR has test evidence and a green CI link, that a frontend PR has visual evidence or a valid `skip-evidence`, and that a qualifying completeness review exists. The check is warn-only for each repo until that repo's spoke fan-out PR lands, and a hard failure after (the 0007 pattern).

## Consequences

- UPS-QA-52 becomes MUST for frontend PRs under this section; follow-up edits `specs/QUALITY.md`, then `gen-specs-data.py` regenerates `_data/specs.yml`.
- Follow-up: add the three sections to `.github/pull_request_template.md` and to `bamr87/.github` `PULL_REQUEST_TEMPLATE.md`; add a `major` label; add `reviewers:` to `_data/fleet.yml`; add the two conformance check ids (feature `HUB-NEW:evidence-conformance`).
- Fan-out: one PR per spoke repo after ratification, which also turns that repo's check from warn to fail.
- Merging the pull request that carries this record ratifies it. An agent never merges it.
