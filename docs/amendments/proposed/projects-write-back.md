<!-- kit: governance v0.1.0 -->
# NEW — Guarded harness write-back to GitHub Projects, issues and pull requests

- **Status:** proposed
- **Number:** NEW
- **Date:** 2026-10-30
- **Proposed by:** agent (Grok Bot, on a branch opened for bamr87)
- **Ratified by:** _(blank until the pull request is merged)_
- **Affects:** constitution §4 (AI agent row), new §11 (Harness write-back to GitHub); AGENTS.md standing rules; docs/PROJECTS-FRAMEWORK.md; feature `projects-console` (HUB-NEW); PRD FR-NEW:`projects-aggregate`, FR-NEW:`projects-linked-view`, FR-NEW:`projects-writeback-guarded`
- **Supersedes:** none (extends 0003 and 0005; also records 0005 as ratified by PR #452)
- **Related:** epic #468 (phases #469–#474), [docs/PROJECTS-FRAMEWORK.md](../../PROJECTS-FRAMEWORK.md), `tools/console/gh_projects.py`, `tools/console/gh_projects_write.py`

## Context

§ 10.6 makes new tools read-only by default. Amr wants the harness to create and update GitHub Projects, add, move and archive items, and edit issue and PR fields across every bamr87 owner, from one console. That is a new write capability over many repos, so it needs explicit, auditable limits in the constitution rather than in code alone.

## Amendment

1. In §4, the AI agent "May" cell gains: "plan GitHub write-back under § 11 and apply it only after the user confirms".
2. Add §11 "Harness write-back to GitHub" (text as in `docs/constitution.md` § 11): mutation allowlist; never merge, delete, settings, protection, secrets, workflows or visibility; off by default behind `HARNESS_PROJECTS_WRITES`; dry-run plan with deterministic `plan_id`, apply only with `confirm=true` and that `plan_id`; stale-plan refusal; idempotent ops; 50 ops per plan and 200 per hour; append-only redacted audit log; dedicated `PROJECTS_TOKEN` provisioned only by Amr.
3. Housekeeping: amendment 0005 is recorded as ratified by https://github.com/bamr87/bamr87/pull/452.

## Consequences

- Writes ship disabled. The P0 PR adds the service layer and tests only; UI and MCP write tools come in P3 (#472) and the live deploy in P5 (#474), which needs Amr's OK.
- Agents may draft plans but never apply one without the user's confirmation, and never through anything but this service.
- Merging the pull request that carries this record ratifies it.
