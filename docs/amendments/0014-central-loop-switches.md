<!-- kit: governance v0.1.0 -->
# 0014 — Every scheduled or AI workflow has a centrally managed kill switch

- **Status:** ratified
- **Number:** 0014
- **Date:** 2026-10-31
- **Proposed by:** agent (Grok Bot, on a branch opened for bamr87, approved to open by Amr on 2026-10-31)
- **Ratified by:** https://github.com/bamr87/bamr87/pull/528 (merged 2026-11-01 by @bamr87)
- **Affects:** constitution § 2 (new invariant), new § 17 (follows § 16 `ai-ready-foundation`, 0013); `_data/fleet.yml` (`switches:` map); feature `central-loop-switches` (HUB-NEW, bamr87/bamr87#527); requirement `FR54`
- **Supersedes:** none (extends § 7 and § 10)
- **Related:** issue bamr87/bamr87#526, PR bamr87/bamr87#527, #511 (fleet-wide agent pause), #512 (repo settings as code), 0008 `harness-prior-art-research`, 0011 `eval-baseline-risk-tiers`, 0013 `ai-ready-foundation` (warn-then-fail rollout)

## Context

On 2026-10-31 Amr paused the lifehacker.dev loops by hand: 17 per-repo `*_ENABLED` variables were set to `false`, and `nightly`, `zer0-doctor` and the Claude mention handler (`claude.yml`) had to be disabled outright because they had no switch. Kill switches today are scattered across per-loop repo variables, `_data/fleet.yml` `*.enabled` keys and `_data/backlog_fanout.yml`, with no single place that says what is paused, why, by whom and until when, and nothing requires a new loop to have a switch at all.

## Prior art

Per 0008, existing fleet assets and external patterns come first; the only new pieces are a rule, a schema and a conformance check.

**Fleet assets**

- **#511, fleet-wide agent pause (`FLEET_AGENTS_PAUSED`):** a single global switch for agent steps plus archived-repo auto-stop. Fit: the `global` level of the switch map. Extend, do not duplicate.
- **#512, repo settings as code and drift audit:** declarative settings with a drift report. Fit: projection of switch state to repo variables and the drift check. Reuse.
- **HUB-031, Harness Console MCP `workflow_kill_switch`:** a write tool behind `HARNESS_MCP_ALLOW_WRITES=1` and `confirm=true`. Fit: the gate pattern for pause/resume tools. Reuse.
- **HUB-034, workflow atlas `workflow_lines` (`filter=noswitch`):** already detects each workflow's kill switch and lists workflows without one. Fit: the conformance check. Extend into a lint rule.
- **`dash config sync`:** projects `_data/fleet.yml` to repo variables fleet-wide. Fit: the projection path. Extend with per-repo and per-loop scope and dry-run by default.

**External patterns**

- **Feature-flag kill switches (LaunchDarkly, Unleash):** central state with reason, owner, expiry and audit. Fit: the switch entry shape. Adopt the shape, not a service.
- **Kubernetes CronJob `suspend` and the GitHub Actions disable-workflow API:** per-job suspension. Fit: last resort for a workflow that cannot read a variable; loses reason and expiry. Allowed only as an exemption fallback.
- **Build-vs-adopt:** build only the `switches:` schema, a scoped projection op and one lint rule; everything else is reused.

## Amendment

Add to constitution § 2 (Invariants):

> - Every scheduled or AI-calling workflow has a kill switch whose state is managed centrally in `_data/fleet.yml` `switches:`; nothing pauses or resumes a loop except through that map. _(amendment `central-loop-switches`, § 17)_

Add constitution § 17 "Centrally managed loop switches" with this text:

> 1. **Every loop has a switch** — every workflow in the hub, `templates/` and the fleet that runs on a `schedule:` or calls an AI agent or model has a kill switch it checks before doing work.
> 2. **One source of truth** — switch state lives in `_data/fleet.yml` `switches:` at four levels: global, group, loop and repo. Each entry records state, reason, who set it, when, and an optional expiry. The effective state is the most restrictive level. Repo variables such as `*_ENABLED` are projections of this map, never edited by hand except in an emergency, which is recorded in the map in the same day.
> 3. **Projection is dry-run first** — the console op and MCP tools that apply switch state show the variable diff by default and change live variables only with an explicit apply and confirm, scoped to one repo, one loop, a group or everything. Nothing flips a switch automatically without that step.
> 4. **Audit** — every flip records who, what, scope, reason and old and new state in the fleet activity log, in addition to git history of `_data/fleet.yml`.
> 5. **Drift** — the drift check compares the map's effective state with live repo variables and reports mismatches and expired entries.
> 6. **Conformance and rollout** — the workflow atlas fails a scheduled or AI workflow without a switch that resolves through the map. The rule is warn-only for each repo until that repo's fan-out PR lands, then a hard failure.
> 7. **Exemptions** — a workflow with no schedule and no AI call (push, pull_request or manual dispatch only) is exempt. Archived and retired repos are exempt. Any other exemption needs a one-line reason in the workflow file's header that the § 15 completeness review accepts; a workflow that cannot read a variable may use the disable-workflow API as its switch if the map still records its state.
> 8. **No secrets** — switches are plain variables; no switch tool reads, prints or changes a secret.

## Consequences

- Follow-up: implement the feature `central-loop-switches` (#526, catalog PR #527) in the phases listed there, building on #511 and #512.
- Follow-up: add switches to `nightly`, `zer0-doctor` and the lifehacker.dev `claude.yml` mention handler.
- Fan-out: one PR per spoke repo after ratification wires its loops to the map and turns its check from warn to fail.
- Merging the pull request that carries this record ratifies it. An agent never merges it.
