# 0027 — AI runs in a local session first, and merge conflicts resolve themselves

- **Status:** proposed
- **Number:** 0027
- **Date:** 2026-11-06
- **Proposed by:** agent, at the maintainer's request (2026-11-06: "merge conflicts should automatically resolve either by script, or with an AI workflow. as a general rule, all AI workflows and sessions should utilize a local session when possible.")
- **Ratified by:**
- **Affects:** constitution § 10 (new item 9), § 12 (new item 7); `_data/fleet.yml` `jev.auto_tiers`, `jev.ci_tiers`; AGENTS.md standing rules
- **Supersedes:** none
- **Related:** ADR 0002 (the local loop runner), ADR 0008 (Actions as the SDLC substrate), bamr87/bamr87#484

## Context

The conflict engine (`tools/jev/conflicts.py`) was built and never turned on. Its switch is unset and its ledger has no rows, while 8 eligible PRs sit in conflict. `auto_tiers` held only the script tier, and a dry run shows that alone isn't enough: 7 of the 8 need a model.

Running everything locally was a standing direction with no rule behind it: every loop *can* run locally, but nothing says it should prefer to. AGENTS.md and this constitution were silent.

## Amendment

Add to constitution § 10:

> 9. **Local first** — AI work runs in a local Claude Code session when one can do the job: an interactive session, or `claude -p` through `tools/dash loop` and `tools/dash conflicts`, with JEV's tiers, caps and ledger. A CI agent step is the fallback for work that must react inside GitHub or when no local host is available, not the default, and new AI work ships with a local entry point first.

Add to constitution § 12:

> 7. **Conflicts resolve themselves** — a merge conflict on an open PR from a trusted author is resolved automatically by JEV, by script where the files allow and otherwise by a capped model in a local session (§ 10.9). It merges the base with a merge commit, validates with the repo's own checks, and never force-pushes or merges the PR. A model's resolution is a non-trivial conflict resolution, so it carries the gate of item 3. A human takes over only when JEV cannot resolve it.

## Consequences

- CI runs the script tier only. A conflict that needs a model waits, unlabelled, for `tools/dash conflicts sweep`.
- A model tier in a local session spends inside `budget.jev`, $10 a month. It's an API-equivalent estimate under OAuth.
- `tools/install-conflict-sweep.sh` runs the sweep on a schedule. It changes the Mac, so the maintainer installs it (§ 10.5).
- A CI agent step that has no local entry point yet is a gap to close under #484, not a violation today. A mention handler such as `claude.yml` reacts inside GitHub, so it stays in CI.
- ADR 0008 keeps Actions as the substrate for gates and typed decisions on a PR. Those must run inside GitHub, so this rule's "when one can do the job" leaves them in CI.
- Merging the pull request that carries this record ratifies it. An agent never merges it.
