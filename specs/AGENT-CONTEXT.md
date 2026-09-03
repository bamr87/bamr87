# UPS-AGENT — Agent context

> What an AI agent must be able to read in any fleet repo to work safely without asking, and what the hub does and does not fan out into `.claude/`.

Evidence base: 35 of 37 repos have a `CLAUDE.md` (missing: `vs-sonic-pi`, `skills`); 7 have `AGENTS.md`; 12 have `copilot-instructions.md`; 11 have a populated `.claude/` (agents/skills/settings); hooks exist in 4. `SCHEMA.md` exists in only 3 repos and is CI-enforced in 1 (`zer0-pages`). 31 of 34 `claude.yml` copies are byte-identical to the kit.

## The context file

| id | level | applies | requirement | satisfied by | seed |
| --- | --- | --- | --- | --- | --- |
| UPS-AGENT-01 | MUST | all except fork | A root `CLAUDE.md` exists. `AGENTS.md`, when present, is the tool-neutral copy and MUST NOT contradict it; `CLAUDE.md` may be a one-line pointer to `AGENTS.md`. | file present | `templates/agent-context/CLAUDE.template.md` |
| UPS-AGENT-02 | MUST | all except fork | `CLAUDE.md` carries these headings, in order: **What this repo is** (one paragraph, who it serves, what "done" means) · **Stack & commands** (install/run/test/lint/build as fenced commands, identical to README Quick start) · **Layout** (top-level dirs, or "see SCHEMA.md") · **Conventions** (commits, branches, the do-nots) · **Fleet context** (the submodule rule + link to the hub) · **Standard deviations** (UPS ids waived and why; "none" if none). | headings present; no `TODO:` scaffold markers left | kit scaffold + hand fill |
| UPS-AGENT-03 | MUST | all except fork | The kit stamp `<!-- kit: agent-context vX.Y.Z -->` is preserved so `dash audit` can flag version drift and unfilled scaffolds. | stamp present | kit |
| UPS-AGENT-04 | MUST | all except fork | The do-nots are explicit: never push to the default branch, never commit lockfiles or secrets, never suppress type errors, never leave empty exception handlers, never edit generated files by hand. | text present | kit |
| UPS-AGENT-05 | SHOULD | all | Where the repo has scoped rules, they live in `.github/instructions/*.instructions.md` with `applyTo` globs (Copilot format, readable by every agent), not scattered in comments. | dir present | hub `.github/instructions/` as reference |
| UPS-AGENT-06 | MUST | all except fork | `.github/workflows/claude.yml` is the kit's `@claude` mention handler, OAuth-first (`CLAUDE_CODE_OAUTH_TOKEN`, `ANTHROPIC_API_KEY` fallback), with `checkout@v7`. Hand-modified copies keep the kit stamp and are excluded from `--upgrade`. | byte-identical to kit or archive, or stamped + documented | `tools/fanout.sh --artifacts claude` |

## `.claude/` baseline

| id | level | applies | requirement | satisfied by | seed |
| --- | --- | --- | --- | --- | --- |
| UPS-AGENT-10 | SHOULD | all except fork | `.claude/settings.json` exists with the schemastore `$schema` and the kit's read-only permission allowlist as its floor; repos add to it, never remove from it. | file present, superset of kit | `--artifacts claude-settings` |
| UPS-AGENT-11 | MUST | all | Hooks, skills, commands, agents, and agent memory are **repo-local** and never fanned out by default. Two sanctioned opt-in kit artifacts exist: `claude-guardrails` (`.claude/skills/_shared/quarantine.md`) and `claude-agent-auditor`. | kit VERSION 0.4.0 position | `templates/agent-context/` |
| UPS-AGENT-12 | MUST | all with `.claude/hooks` | Hooks are `python3`, fail-open (exit 0 when a dependency is missing), throttled, and never write silently. | code review | hub `.claude/hooks/` as reference |
| UPS-AGENT-13 | SHOULD | all with `.claude/` | Frontmatter names are kebab-case; no `model:` pins unless a role demonstrably needs one; command names are namespaced to avoid collisions with hub commands (`/evolve`, `/dash-status`). | review | kit VERSION notes |
| UPS-AGENT-14 | MUST | all with `.claude/agents` | Every agent cites the shared guardrails doc in one line instead of restating them (untrusted-input quarantine, honesty rule, merge discipline). | line present | `--artifacts claude-guardrails` |
| UPS-AGENT-15 | SHOULD | app, api, lib | `.mcp.json` declares the MCP servers the repo's agents rely on (fleet baseline: `github`, `memory`, `sequentialthinking`, `context7`), with no credentials inline. | file present | hub `.mcp.json` |

## Structural contract (Pyramid Schema)

| id | level | applies | requirement | satisfied by | seed |
| --- | --- | --- | --- | --- | --- |
| UPS-AGENT-20 | SHOULD | all except fork, content | The repo carries a `SCHEMA.md` pyramid (one per directory, from the kit template), the vendored `tools/schema_lint.py`, the `schema-check.yml` gate, and the protocol snippet in `CLAUDE.md`. Registry `schema.status` records adoption. | `schema_lint.py check .` passes | `tools/seed-schema.sh` / `schema-fanout.yml` |
| UPS-AGENT-21 | MUST | all with SCHEMA.md | Any add/remove/rename updates the local `SCHEMA.md` in the same commit; generated entries are marked `generated`; sub-repos and vendored trees are `terminal`. | lint clean | kit |
| UPS-AGENT-22 | MUST | all | Vendored hub tools (`schema_lint.py`, `unwrap-prose.py`) stay byte-identical to the hub copy; drift check (i) reports divergence. | `cmp` | fan-out re-vendor |

## Agent-facing operational rules

| id | level | applies | requirement | satisfied by | seed |
| --- | --- | --- | --- | --- | --- |
| UPS-AGENT-30 | MUST | all | Agents open PRs only — never merge, never push to a protected branch; workflows that publish data use the hub's `publish-data` pattern (direct push, PR fallback). | workflow review | hub `.github/actions/utilities/publish-data` |
| UPS-AGENT-31 | MUST | all | A PR that must have CI is opened with `FLEET_TOKEN`, never `GITHUB_TOKEN`; the token is probed (`gh api user`) not presence-checked. | workflow review | hub `resolve-fleet-token` action |
| UPS-AGENT-32 | MUST | all | Issue state for automation lives in labels from the fleet taxonomy (`agent:*`, type, `P0–P3`, `size:*`), never in a database or an event chain; `agent:hold` and `human-review` are the human brakes and are honoured everywhere. | labels exist in repo (`gh label list`) | `templates/community/labels.yml` (gap) |
| UPS-AGENT-33 | SHOULD | all | The repo's README or `CLAUDE.md` names the loops that act on it (fleet-pulse doctor, issue pipeline, repo-evolution opt-in) so an agent knows what else is running. | Fleet context section | kit |
