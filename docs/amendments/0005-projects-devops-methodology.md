<!-- kit: governance v0.1.0 -->
# 0005 — DevOps methodology for GitHub Projects across all submodules, binding on AI agents

- **Status:** ratified
- **Number:** 0005
- **Date:** 2026-10-30
- **Proposed by:** agent (Grok Bot, on a branch opened for bamr87)
- **Ratified by:** https://github.com/bamr87/bamr87/pull/452 (merged 2026-10-30)
- **Affects:** constitution §3 (AI agent row), new §10 (DevOps methodology); AGENTS.md standing rules; docs/PROJECTS-FRAMEWORK.md; PRD and feature ids: none
- **Supersedes:** none (extends amendment 0003)
- **Related:** amendment 0003 (`docs/amendments/0003-github-projects-work-tracking.md`), [docs/PROJECTS-FRAMEWORK.md](../../PROJECTS-FRAMEWORK.md), [templates/projects/framework.yml](../../../templates/projects/framework.yml), Fleet project https://github.com/users/bamr87/projects/14, example epic #446 (sub-issues #447–#451)

## Context

Amendment 0003 made GitHub Projects (v2) the system of record and defined the fields, lifecycle and label map. It does not say *how* work is planned and executed: AI agents and submodule loops still open work that never lands on a board, multi-phase changes arrive as one large PR without phases, labels such as `epic` are missing in some repos, agents touch the live harness on Amr's Mac during development, new tools ship with write access, and AI cost figures computed from token counts are reported as if they were real spend under the flat Claude Max subscription.

## Amendment

Add constitution §10 "DevOps methodology" with this text:

> Every human, bot and AI agent working in the hub or any submodule under `projects/` (and any repo the hub fans out to) follows these rules. They extend § 9 and amendment 0003; on conflict, `templates/projects/framework.yml` remains the source for fields, options and labels.
>
> 1. **Everything is an item.** Every piece of work — feature, fix, audit, plan — is an issue or PR on the shared **Fleet** project (user project #14, https://github.com/users/bamr87/projects/14), the fleet portfolio project of § 9. This includes AI-agent work and submodule work; a PR without a tracked issue is added itself.
> 2. **Epics for multi-phase work.** Work with more than one phase gets an issue labelled `epic`; each phase is a linked sub-issue, created in execution order, each stating **scope**, **acceptance criteria** and **guardrails**. Example: epic #446 with sub-issues #447–#451.
> 3. **Labels follow hub standards.** `epic` is purple `#6E40C9`, created in a repo if missing. Type labels are the canonical `bug`, `feature`, `chore`, `docs`, `ci`, `refactor`, `test`; priority labels `P0`–`P3` and the existing `size:*` labels apply as defined in the framework label map.
> 4. **Fields are set.** Every item carries the project **Status** and **Priority** fields (plus the other § 9 required fields).
> 5. **Hands off the Mac until deploy.** Nothing running on Amr's Mac — the checkout, containers, live jobs, the monitoring stack — is modified until a final, separate deploy step that requires Amr's explicit OK. Development, tests and builds run on branches, CI or a scratch environment.
> 6. **Tools are read-only by default.** A new tool (script, MCP tool, bot capability) is read-only unless a ratified need says otherwise, and has an allowlist of targets, a cap on results, a time limit and redaction of secrets and personal data in its output.
> 7. **Costs are labelled honestly.** Every AI cost figure derived from usage under the flat Claude Max subscription is labelled **"API-equivalent (estimate)"**; real metered API spend is tracked and reported separately.

Add to the AI agent row of §3 (Must): "follow § 10 (track every task on the Fleet project; epics for multi-phase work; no change to the live Mac before an approved deploy step)".

## Enforcement

- Agents comply by procedure: before starting work, find or create the issue (or epic + sub-issues), add it to Fleet project #14, and set Status and Priority; move Status as work proceeds; link the PR to the issue.
- Project writes need the `project` token scope (`gh auth refresh -s project`, or the `PROJECTS_TOKEN` of 0003). An agent without it says so in the PR or issue ("not added to Fleet: token lacks `project` scope") instead of silently skipping, and never changes auth on its own.
- Lint is optional and future: `tools/projects_lint.py coverage` (0003) already reports untracked items and missing fields; extending it to check `epic` sub-issue structure is a follow-up, not part of this amendment. No new tooling is built here.

## Fan-out to submodules

The rules bind every repo under `projects/` through the hub constitution, which each submodule's `AGENTS.md` points to. After ratification, `tools/fanout.sh` / `standardize-fanout` opens dry-run-first, PR-only, additive PRs that (a) add a one-line pointer to § 10 in each submodule's `AGENTS.md` and (b) create the `epic` label (`#6E40C9`) and canonical type labels where missing — in the 0003 rollout waves, never auto-merged.

## Consequences

- Agents gain a pre-work step (issue + project item + fields) and a hard stop before touching the live Mac.
- Cost reports, dashboards and PR bodies that show AI cost must carry the "API-equivalent (estimate)" label.
- Follow-up edits: AGENTS.md standing rules and docs/PROJECTS-FRAMEWORK.md (in this PR); submodule AGENTS.md pointers and labels (fan-out after ratification).
