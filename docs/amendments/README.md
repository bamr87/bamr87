<!-- kit: governance v0.1.0 -->
# Amendments — bamr87

The append-only log of changes to [the constitution](../constitution.md). Process: constitution § 8.

- A proposal is written as [`proposed/<kebab-slug>.md`](proposed/) with `**Number:** NEW` (copy [0000-template.md](0000-template.md)); `python3 -m tools.jev number apply` numbers it `NNNN-kebab-slug.md` here at merge and appends its row below. Numbers are never reused (amendment [0002](0002-conflict-free-numbering.md)).
- Status: `proposed` → `ratified` (PR merged) | `rejected` | `withdrawn` | `superseded`.
- Validate: `python3 <bamr87/bamr87>/tools/governance_lint.py check .`

| # | Title | Status | Affects |
| --- | --- | --- | --- |
| [0001](0001-ratify-constitution.md) | Ratify the constitution | ratified on merge | whole constitution |
| [0002](0002-conflict-free-numbering.md) | Assign sequential ids at merge, not in a pull request | proposed | constitution §2, §5, §6, §8; FR28, NFR11; HUB-035 |
| [0003](0003-github-projects-work-tracking.md) | GitHub Projects as the fleet's system of record for work | proposed | § 6, § 7, § 9; FR-NEW:projects-coverage, FR-NEW:projects-sync, NFR-NEW:projects-scope-honest; HUB-NEW:github-projects-framework, HUB-NEW:projects-coverage-gate, HUB-NEW:projects-sync-console |
| [0004](0004-generated-files-main-only.md) | Generated files are written on main only | proposed | constitution §2 (invariants); feature HUB-035 |
| [0005](0005-projects-devops-methodology.md) | DevOps methodology for GitHub Projects across all submodules, binding on AI agents | ratified | constitution §3 (AI agent row), new §10 (DevOps methodology); AGENTS.md standing rules; docs/PROJECTS-FRAMEWORK.md; PRD and feature ids: none |
| [0006](0006-projects-write-back.md) | Guarded harness write-back to GitHub Projects, issues and pull requests | proposed | constitution §4 (AI agent row), new §11 (Harness write-back to GitHub); AGENTS.md standing rules; docs/PROJECTS-FRAMEWORK.md; feature `projects-console` (HUB-NEW); PRD FR-NEW:`projects-aggregate`, FR-NEW:`projects-linked-view`, FR-NEW:`projects-writeback-guarded` |
| [0007](0007-public-docs-site.md) | Every fleet repo publishes a public site with all its documentation | proposed | constitution new § 14 (numbering contingent on § 12 from #481 and § 13 from #482); specs UPS-DOC (extended, not replaced); features `HUB-043`, `HUB-042`; requirements `FR36`, `FR35` |
| [0008](0008-harness-prior-art-research.md) | Prior-art research before any new harness or loop design | proposed | constitution §10 (new item 8, "Prior art first"); AGENTS.md standing rules (follow-up); harness and loop design docs |
| [0009](0009-agent-merge-review-gate.md) | Agent merge of mergeable PRs, and a review gate for human review | proposed | constitution § 4, new § 12; AGENTS.md "Never"; feature `HUB-045`; requirement `FR42` |
| [0010](0010-major-change-evidence.md) | Test evidence for major changes, visual evidence for frontend PRs, and a skilled-reviewer completeness pass | proposed | constitution new § 15 (§ 13 is reserved by `eval-baseline-risk-tiers`, #482, still open; § 14 is `public-docs-site`, 0007); § 12 (adds a completeness review to the review gate); specs UPS-QA-52 (raised from SHOULD to MUST by reference); `.github/pull_request_template.md`; features `HUB-047`, `HUB-046`; requirements `FR44`, `FR43` |
| [0011](0011-eval-baseline-risk-tiers.md) | Eval baseline and risk tiers for every agent, harness and loop | proposed | `_data/fleet.yml` `ai_models`; constitution new § 13 (follows § 12 proposed by `agent-merge-review-gate`, PR #481); § 10.6; features `HUB-048`, `HUB-049`; requirements `FR45`, `FR46` |
| [0012](0012-qa-lead-bridge.md) | QA Lead first: a short warn-only bridge for the § 15 completeness review, and § 15 numbering made final | proposed | constitution § 15 (header note and item 5 "Interim"); features: none (HUB-046 and HUB-047 already say "interim fallback" generically; the compiled features.yml is not hand-edited) |
| [0013](0013-ai-ready-foundation.md) | AI-ready foundation: every repo exposes an API layer, MCP, agent docs and machine-readable metadata, validated by AIEO | proposed | constitution new § 16; `tools/aieo/` (new home of AIEO, migrated from `bamr87/zer0-CMS` `apps/aieo/`) (follows § 15 `major-change-evidence`, 0010; § 13 is 0011); specs UPS-AGENT, UPS-BE-12/31, UPS-DOC (by reference); `templates/` (new `templates/ai-ready/` kit); features `HUB-050`, `HUB-051`; requirements `FR47`, `FR48` |
