<!-- kit: governance v0.1.0 -->
# 0008 — Prior-art research before any new harness or loop design

- **Status:** proposed
- **Number:** 0008
- **Date:** 2026-10-30
- **Proposed by:** agent (Grok Bot, on a branch opened for bamr87)
- **Ratified by:** _(blank until the pull request is merged)_
- **Affects:** constitution §10 (new item 8, "Prior art first"); AGENTS.md standing rules (follow-up); harness and loop design docs
- **Supersedes:** none (extends § 10)
- **Related:** #479 (live loop/harness map, the first application), #477 and PR #478 (architecture research harness), #476 (Starred Repos dashboard)

## Context

Harnesses and loops in the fleet have usually been designed from scratch. Mature tools often already solve much of the problem: graph renderers, workflow UIs, trace viewers, and orchestration consoles. Without a required survey, the fleet risks rebuilding what it could adopt, and design reviews have no record of the alternatives that were considered. Amr asked that existing-tools research be a standing requirement for all future harness and loop design.

## Amendment

Add to constitution § 10 (DevOps methodology):

> 8. **Prior art first** — every new harness or loop design (a new loop, harness, agent pipeline, or console surface that drives or visualizes them) includes, before implementation begins: (a) a **needs assessment** stating what the fleet actually requires, (b) a **prior-art / existing-tools survey** of relevant tools, libraries, and services, with one line each on fit, and (c) a recorded **build-vs-adopt decision** with reasons. The survey and decision live in the design issue or spec and are an acceptance criterion of it. Implementation PRs link them.

## Consequences

- New harness and loop epics and roadmap items get an "Existing-tools research (do this first)" scope section and a build-vs-adopt acceptance criterion. #479 is the first.
- Designs already in flight (for example #477 / PR #478) add the survey before any build phase starts.
- Follow-up: mention the rule in AGENTS.md standing rules and in the harness design docs.
- Merging the pull request that carries this record ratifies it. An agent never merges it.
