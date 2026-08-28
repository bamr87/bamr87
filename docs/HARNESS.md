# Harness Engineering — the six-layer architecture, mapped onto this control plane

> **Formula:** Agent = Model + Harness. The model provides reasoning; the harness provides everything else — guides that prevent known failures, sensors that catch new ones, bounded loops, persistent memory, enforced permissions, and full observability.
>
> Source framework: the 2026 "Harness Engineering: Agent = Model + Harness" playbook (`harness_final.pdf` — a synthesis of Mitchell Hashimoto's ratchet methodology, OpenAI's Codex field report, Martin Fowler's guides-and-sensors taxonomy, and LangChain/Cursor engineering material). This document is the hub's **adoption of that framework**: the architecture mapping, the gap analysis, what was implemented, and the plan for what remains.

## Why this document exists

The playbook's claim is empirical: holding the model fixed and improving only the harness produces gains as large as model upgrades (a 44-point GAIA swing, a 25-rank Terminal Bench climb, a million-line codebase with zero manually written code). This hub runs four scheduled agent loops against ~40 repositories unattended — it *is* a harness, built incrementally over 2026 before the vocabulary existed. Adopting the framework therefore meant three things, in order:

1. **Map** — name what already exists in the playbook's terms, so future decisions land at the right layer (§ The six layers, mapped).
2. **Score** — audit the hub against the playbook's production readiness checklist (§ Production readiness).
3. **Fill** — implement what the audit found missing, smallest-first per the playbook's decision framework (§ What was added, § Roadmap).

The audit's headline: five of six layers were already strong. The gap was in Layer 6 — the hub tracked everything but **alerted on nothing**. There was no trip wire and no scorecard, and the fleet has already paid for that once: the four pre-`fleet-pulse` data workflows died silently for three weeks because a branch ruleset rejected their closing `git push` and nothing said so. That postmortem is now a permanent wire (`stale-data`, below) — the ratchet principle applied to the harness itself.

## The six layers, mapped

```text
+------------------+     +------------------+     +------------------+
|     GUIDES       |     |   AGENTIC LOOP   |     |    SENSORS       |
| CLAUDE.md        |     | fleet-pulse      |     | drift gate (a–l) |
| AGENTS.md        +---->+ issue-pipeline   +---->+ schema_lint      |
| SCHEMA.md chain  |     | token-rotation   |     | per-repo CI      |
| .github/instr.   |     | repo-evolution   |     | pre-commit       |
+--------+---------+     +--------+---------+     +--------+---------+
         |                        |                        |
         v                        v                        v
+--------+---------+     +--------+---------+     +--------+---------+
|    MEMORY        |     |   PERMISSIONS    |     | OBSERVABILITY    |
| _data/*.yml      |     | fleet.yml caps   |     | actions_usage    |
| labels-as-state  |     | draft-PR-only    |     | fleet_triage     |
| ledgers/digests  |     | never-merge      |     | harness_health   |
+------------------+     +------------------+     +------------------+
```

### Layer 1 — Guides (feedforward: prevent known failures)

| Playbook component | Hub implementation |
| --- | --- |
| Primary guide file | [`CLAUDE.md`](../CLAUDE.md) — build/test/lint commands, submodule workflow, conventions |
| Agent operating manual | [`AGENTS.md`](../AGENTS.md) + scoped [`.github/instructions/*.instructions.md`](../.github/instructions/) |
| Structural contract | The `SCHEMA.md` pyramid — one lintable placement contract per directory ([`docs/SCHEMA-FRAMEWORK.md`](SCHEMA-FRAMEWORK.md)) |
| Rules traced to failures | The **standing rules** in `CLAUDE.md`, each born from a named incident: never end a workflow in a bare `git push` to a protected branch; prefer `needs:` over `workflow_run`; CI-bearing PRs cannot use `GITHUB_TOKEN`; fleet-wide secrets are written hub-first |
| Per-repo guides | The agent-context kit (`templates/agent-context/`) seeds `CLAUDE.md` scaffolds into submodules via `standardize-fanout.yml` |

The hub already practices the playbook's strongest guide discipline: rules are dated by their incidents, encoded where they bind (a standing rule in `CLAUDE.md` *and* a drift-gate check where checkable), and the guide file outranks the conversation.

### Layer 2 — Sensors (feedback: catch what guides couldn't prevent)

| Sensor | Type | Runs |
| --- | --- | --- |
| [`tools/check-drift.sh`](../tools/check-drift.sh) checks (a)–(l) | Computational | Every PR + nightly |
| `tools/schema_lint.py` (drift check (h) — warnings fail CI) | Computational | Every PR |
| shellcheck, markdownlint, prettier, black/flake8 (pre-commit) | Computational | Every commit |
| Per-repo CI via reusable `standard-ci.yml` | Computational | Every push, fleet-wide |
| Self-healing markdown-oneline gate (CI fixes and pushes) | Computational | Every PR |
| Fixture tests for every deterministic planner (`test_*.py` in `dash-gen/`) | Computational | Every PR |
| Fleet-pulse **doctor**, issue-pipeline tiers (Opus agents reading logs/evidence) | Inferential | Daily, capped |

The playbook's ordering — computational sensors first, inferential only where semantics demand it — is already the hub's shape: the deterministic planners (`remediate`, `issues`, `targets`) pre-vet and cap everything before an LLM sees it, and the agents' outputs land as draft PRs behind the same computational sensors as human work.

### Layer 3 — The agentic loop (plan → execute → verify → fix, bounded)

The hub runs four production loops, every one matching the playbook's required shape — a deterministic plan step, a bounded execute step, verification by sensors, and escalation instead of silent failure:

| Loop | Plan (deterministic) | Execute (bounded) | Escalation |
| --- | --- | --- | --- |
| `fleet-pulse.yml` doctor (daily) | `dash-gen remediate`: ranked, deduped, capped queue | Opus agent, `--max-turns` paired to `max_candidates` | Falls back to a hub issue when it can't fix |
| `issue-pipeline.yml` T1→T3 (daily) | `dash-gen issues`: label-derived stages, per-tier caps | Three tiers, evidence in isolated virtual env | `agent:blocked`, `human-review`; **no tier ever merges** |
| `token-rotation.yml` (weekly) | Staleness plan from the ledger | Hub-first, abort-on-hub-failure, `max_failures` | ONE deduped tracking issue when re-mint needs a human |
| `repo-evolution.yml` (weekly) | `dash-gen targets`: opt-in, capped, one-open-PR backpressure | One agent per repo, no persisted credentials, read-only allowlist | Draft PR only; skipped while previous PR is open |

Playbook loop bounds vs the hub: retries (caps + one-open-PR backpressure), tool budgets (`--max-turns` wired to the caps and asserted by fixture tests), wall-clock (`timeout-minutes` on every job), stopping condition (always: publish what was gathered, report what wasn't). The missing bound is a **per-run dollar/token budget** — tracked shadow-priced after the fact (`dash ai`, engagements ledger) but not enforced mid-run; see Roadmap.

Escalation-is-not-failure is structural here: stage lives in labels, so a missed run costs latency rather than a stuck workflow, and a human re-queues or stops anything by editing one label (`agent:hold`, `human-review`).

### Layer 4 — Memory and state (the filesystem is the memory)

The playbook's recommended implementation — files over vector stores — is exactly the hub's: **the registry and ledgers under [`_data/`](../_data/) are the shared state model**, committed and diffable.

| Playbook layer | Hub implementation |
| --- | --- |
| Artifact store | `_data/*.yml` registries + ledgers, `_reports/daily/` digests — all in git |
| Decision log | Standing rules in `CLAUDE.md` with their incidents; workflow header comments narrating *why* |
| Checkpoint / recovery | Labels-as-state in the issue pipeline: any run resumes from current label state, no event chain to lose |
| Scratchpad | Ephemeral work orders (`remediation-workorder.md`, `evolution-workorders/`) — gitignored, rebuilt each run |
| Cleanup (stale-checkpoint hygiene) | Evidence bundles expire by TTL (`evidence.ttl_days`); ephemera are regenerated, never trusted stale |

### Layer 5 — Permissions and budgets (the harness is the security boundary)

| Playbook control | Hub implementation |
| --- | --- |
| Capability budget (scope) | `FLEET_TOKEN` fine-grained scopes, probed (`gh api user`) rather than presence-checked; evolution agents run on checkouts with **no persisted credentials** and a read-only tool allowlist |
| Rate limits | Every loop's caps in [`_data/fleet.yml`](../_data/fleet.yml) (`remediation.max_candidates`, `issue_pipeline.tiers.*`, `evolution.max_targets/max_parallel`) |
| Reversibility | Draft PRs only, `never_merge: true`, deletions never auto-applied (reconcile), additive-only fan-outs, `hub_first` + abort on hub failure for secret writes |
| Approval gates | `assisted_types: [security]`, `assisted_sizes: [size:xl]`, `human-review` label, dry-run defaults on every fan-out |
| Trusted/untrusted split | Issue/PR content reaches agents as *data* inside work orders built by deterministic planners; the instructions come from versioned prompts and guide files, not from the untrusted payload |
| Visibility | Every loop publishes a committed record of what it did (ledgers, snapshots, PR markers) |

### Layer 6 — Observability (track everything, alert on drift)

What existed: per-workflow cost/effectiveness/waste (`_data/actions_usage.yml`), standing open-state (`_data/fleet_triage.yml`), daily digests (`_reports/daily/`), credential ages (`_data/token_rotation.yml`), shadow-priced AI cost per repo and per engagement (`_data/ai_usage.yml`, `_data/engagements.yml`). Cost attribution is already per-task, the metric the playbook calls "real."

What was missing — and is now implemented (see next section): the **health scorecard** and **trip wires**.

## What was added (this adoption)

One new generator, one config block, one committed surface, wired into the existing daily loop — deliberately the smallest change that closes the audit's gap, per the playbook's own decision framework ("start with the simplest layer that addresses the observed failure").

| Piece | What it is |
| --- | --- |
| [`_data/fleet.yml`](../_data/fleet.yml) `harness:` | The self-observation contract: scorecard thresholds + trip-wire triggers, versioned and reviewable like every other cap |
| [`.github/scripts/dash-gen/harness.py`](../.github/scripts/dash-gen/harness.py) | `dash-gen harness` / `dash harness` — **offline and deterministic**: reads only the committed fleet signals, computes the scorecard, evaluates the wires. No network, no LLM |
| `_data/harness_health.yml` | The committed output: source freshness, scorecard, every wire (armed *and* tripped — a quiet panel must be distinguishable from a lost one) |
| [`fleet-pulse.yml`](../.github/workflows/fleet-pulse.yml) wiring | Runs last in the `pulse` gather steps — after the signals it watches — and publishes in the same single commit; tripped count surfaces in the run summary |
| [`test_harness.py`](../.github/scripts/dash-gen/test_harness.py) | Fixture tests guarding the invariants (missing input trips, never crashes; median not mean; external/low-run/cheap workflows can't trip cost-spike; absent config degrades to defaults) |

### The scorecard (playbook Table VIII, from signals the fleet already keeps)

| Metric | Source | Direction |
| --- | --- | --- |
| `completion_rate_pct` — verified runs / started runs, fleet-wide | actions_usage | up (threshold: 80) |
| `effectiveness_pct` — minutes ending in success / all minutes | actions_usage | up (threshold: 70) |
| `waste_hours`, `cost_min_per_verified_run` | actions_usage | down |
| `standing_failures`, `repos_red` | fleet_triage | down |
| `escalations_open` (blocked + hold), `agent_prs_open` | issue_pipeline | down / steady |
| `oldest_credential_age_days` | token_rotation | down |

### The trip wires (playbook Table VII, adapted to this fleet's real failure modes)

| Wire | Playbook analogue | Why this fleet needs it |
| --- | --- | --- |
| `stale-data` | "Would you know within an hour if the agent started failing?" | The three-week silent data death, made structurally loud. Watches every input's `generated_at`, including its own inputs' absence |
| `pass-rate-floor` | Sensor pass rate drops → quality regression | Fleet-wide CI success below 75% |
| `waste-ceiling` | Cost exceeds average → runaway | Non-success minutes above 30% of all minutes |
| `cost-spike` | Duration exceeds 3× → stuck/runaway | Workflows ≥3× the fleet *median* run time **and** ≥5 min absolute (the floor keeps a sub-minute-median fleet from alarming on ordinary CI) |
| `standing-failures` | Same error repeats → guide/sensor gap | Red-workflow backlog beyond what the doctor's caps can drain per week |
| `credential-overdue` | Permission drift | A fleet credential past its own rotation policy + grace — the state where the weekly loop is waiting on a human |

A tripped wire is an **attention item, not an action**: the doctor, pipeline, and rotation loops own the fixes; this is the alarm panel above them. `dash harness` prints it on demand; the pulse job publishes it daily.

## The ratchet, as house process

The playbook's core discipline — every failure becomes a permanent fix at the strongest layer — is adopted as the explicit routing rule for this repo. When an agent (or a loop, or CI) fails, fix it at the highest reliable rung it can be checked at:

| Rung (reliability ↑) | Hub form | Use when |
| --- | --- | --- |
| Prompt / conversation | A correction in-session | Never as the *final* fix |
| Guide rule | A dated standing rule in `CLAUDE.md` / `AGENTS.md`, with its incident | The failure needs judgment to avoid |
| Sensor | A drift-gate check, fixture test, or lint rule | The rule is checkable without interpretation |
| Environment / permission | A `fleet.yml` cap, workflow constraint, token scope, or ruleset | The failure should be structurally impossible |

Existing precedents to imitate (each one incident → strongest layer): the bare-`git-push` deaths → `publish-data` composite + standing rule; the `workflow_run` skip → `needs:` + standing rule; the three divergent `schema_lint.py` forks → drift check (i); the `action.yml` expression crash → drift check (l); the doctor's overlong queue → `max_candidates` paired to `--max-turns`, asserted by a fixture test. Cursor's three-strikes rule applies: a correction made three times becomes a sensor, and the fourth time should never happen.

## Production readiness (playbook Table XIII, scored)

| # | Requirement | Status |
| --- | --- | --- |
| 1 | Guide file with build/test/lint | ✅ `CLAUDE.md`, per-repo scaffolds |
| 2 | 5+ guide rules from failures | ✅ standing rules, each with a named incident |
| 3 | Computational sensor per task | ✅ drift gate + CI + fixture tests |
| 4 | Bounded retry + escalation | ✅ caps, turn budgets, brake labels, fallback issues |
| 5 | State checkpoint to filesystem | ✅ `_data/` ledgers, labels-as-state |
| 6 | Permission boundary | ✅ scoped tokens, draft-only, never-merge |
| 7 | Token and cost budget | ⚠️ turn/time budgets enforced; dollar budgets tracked post-hoc, not enforced mid-run |
| 8 | Structured logging | ✅ committed snapshots + run summaries |
| 9 | Trip wire on cost/error rate | ✅ **added** — `dash-gen harness` |
| 10 | Trusted/untrusted input split | ✅ deterministic work orders carry payloads as data |
| 11 | Emergency stop + state preserve | ✅ `agent:hold` / label edits; state is committed files |
| 12 | 3 successful unattended runs | ✅ the loops have run daily/weekly in production since 2026-08 |

## Roadmap — remaining gaps, smallest-first

Phase 2 (worth doing next, each one small):

- **Dash surface**: render `_data/harness_health.yml` at `/harness/` in `pages/_dash/`, alongside `/triage/` and `/actions/` — the scorecard with trend arrows, the wire panel with tripped state.
- **Enforced cost budget (checklist #7)**: a per-run token ceiling for the Claude loops, read from `fleet.yml` and passed to `claude-code-action`, closing the gap between shadow-priced tracking and mid-run enforcement.
- **Guide hygiene cadence**: fold a monthly guide review into the repo-evolution loop's hub pass — prune rules that sensors now enforce, reconcile contradictions, verify each standing rule still traces to a live constraint.
- **Wire → doctor handoff**: let a tripped `cost-spike`/`standing-failures` wire annotate the remediation queue's ranking, so the alarm and the fix queue converge on the same candidates (today they compute independently from the same data).

Deliberately **not** planned, per the playbook's over-engineering warnings: no LLM-as-judge gates (the deterministic sensors are the gates; the agents are already advisory), no knowledge graph (the `_data/` files are the shared state and the recovery test passes without one), no additional approval workflow (the caps + draft-only + brake labels are the graduated scope the playbook prescribes).

## Multi-agent extensions (playbook §XVII)

The hub is a multi-agent system by construction, and the playbook's extensions map cleanly:

| Extension | Hub form |
| --- | --- |
| Typed handoffs | Work orders and JSON matrices built by deterministic planners — artifact, evidence, caps, and identity, never "done, looks good" |
| Shared state model | `_data/*.yml` + labels, read per-task — not a shared conversation |
| Routing policy | Each loop's plan step; severity ranking; per-tier caps |
| Independent verifier | The producing agent never judges its own PR: CI, the drift gate, and a human review every merge (`never_merge`) |
| Escalation protocol | Brake labels, fallback issues, deduped markers |

## Operating it

```bash
tools/dash harness            # compute the scorecard + wires now, from committed data
tools/dash config show harness  # the thresholds in force
python3 .github/scripts/dash-gen/test_harness.py   # the invariants
```

The daily refresh rides `fleet-pulse.yml`'s `pulse` job; thresholds are tuned in `_data/fleet.yml` `harness:` (a wire that is always on is noise — prune or retune it the way guide rules are pruned).
