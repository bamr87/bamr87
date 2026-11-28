# ADR 0019 — AI providers are switchable without regression: a class binds a kind of work to a model in one place, every other place that names a model is counted down to zero, and a switch needs its evals recorded on the target

- **Status**: proposed
- **Date**: 2026-11-28
- **Deciders**: proposed by an agent at the maintainer's request (2026-11-28: "AI Agnostic means that providors can be easily switched without any regression")
- **Related**: constitution § 12.3, § 13.1–13.4 (eval sets, pinned models, "cheaper only if green"), § 26, § 28 and § 30.3 (who executes); [docs/AI-MODELS.md](../AI-MODELS.md), [docs/EVALS.md](../EVALS.md), [docs/AI-INTEGRATION.md](../AI-INTEGRATION.md); [docs/prd/HARNESS-PROTOCOL.md](../prd/HARNESS-PROTOCOL.md) and epic #632 (the agent-loop contract); [ADR 0009](0009-agentic-efficacy-model.md) (the agent inventory), [ADR 0011](0011-one-framework-many-instances.md), [ADR 0018](0018-clouds-as-fleet-targets.md) (the same idea for clouds: the vendor in data, never in code); pull request #963 (a second route, OpenAI through the Codex CLI); `HUB-NEW:ai-model-switch`

<!-- Accepted in and Completed are added by the post-merge ratify job when the maintainer merges this ADR's PR and when the maintainer closes the Tracking issue as completed (docs/adr/README.md#lifecycle). Never write them by hand. A PR that adds or changes an ADR is gated (constitution § 12.3). -->

## Context

### Needs assessment

**Who needs what.** The maintainer defined the goal in one sentence: AI-agnostic means providers can be easily switched without any regression. That is two tests, and both can be measured. *Easily*: the model behind a kind of work is written once, so a switch is one edit. *Without regression*: nothing the work does, and nothing that measures or limits it, gets worse on the new provider.

**Evidence: a switch is not one edit.** Measured on 2026-11-28 by reading the hub and the 40 owned repos checked out beside it:

- A model is named in 118 places besides the allowlist. 14 are settings elsewhere in `_data/fleet.yml` (`weekly.agent.model`, `assistant.model`, `jev.tiers.tier2.model` and so on). 25 are literals in the hub: 15 in workflows, 4 in generators, 4 in tools, 1 in the `claude-run` action and 1 in the kit that seeds `claude.yml`. 79 are literals in the workflows of 39 fleet repos, 38 of them the kit's `claude.yml` line copied once per repo.
- By model: the one 74 agents run on is named in 98 places, the one 10 agents run on in 16, and the one 4 agents run on in 4.
- The settings already have a way to say "the model is written elsewhere": an agent or a step spec may carry `model_from: <key>` in place of a model, and the agent inventory resolves it. Nothing does the same one level up, so each of the 14 keys repeats an id.

**Evidence: nothing proves a switch is safe.** Constitution § 13.2 says an eval set reruns after any prompt, tool or model change, and § 13.4 that a step moves to a cheaper model only if its evals still pass.

- The runner already takes `--model`: `tools/evals.py run <role> --model <id>` holds a set to another allowed model.
- No result is kept. A run prints pass or fail and is gone, so no later reader can tell that a role passed on a model, on which set, or when.
- Coverage is thin. 87 of the 146 agents in `_data/agents.yml` run a model. Three are covered by a model-backed eval set (`console-assist`, `pr-ai-analysis`, `t1-intake`), and one of those sets tests only the first of its agent's three model steps. 84 have none.

**Evidence: the provider is not a dimension anywhere yet.** From the audit of 2026-11-27:

- Every agent call goes through the Claude Code CLI or `anthropics/claude-code-action`. Two files hold almost all of the CLI's flags, credentials and result parsing: `.github/actions/claude-run/run.sh` in CI and `tools/jev/headless.py` locally. Ten workflow steps use the vendor's action directly and two local callers (`tools/evals.py`, `tools/jev/conflicts.py`) build their own command, so neither seam is complete.
- `ai_models.allowed` is keyed by provider and every reader flattens it. No AI ledger and not the run-record contract has a provider field. Telemetry names are the CLI's own, and the collector stamps one provider as a constant.
- A second route is already on its way in pull request #963, and its description records that three of the harness standard's controls (`budget-cap`, `turn-cap`, `auth-ordered`) do not bind it. Under the maintainer's definition that is exactly the kind of regression a switch must not bring unnoticed.

**Constraints.**

- § 13.3: models are exact versions from `ai_models.allowed`, never aliases, and changing the list is gated (§ 12.3).
- § 26, § 28 and § 30.3: Claude Code, with an allowed Anthropic model, is the executor for implementation and review. This record does not change that.
- § 10.7: every AI cost is labelled API-equivalent (estimate), and a model eval run spends.
- The hub's AI layer is being changed by an open pull request (#963); this change must not collide with it.

**If nothing is decided.** The count of places grows with every new loop. The first real switch, whether to a cheaper model, to the same models on another host, or to another vendor, is a hunt through workflows in 40 repos, made on trust because no eval result was kept. A second provider arrives with weaker controls and nobody is told.

### Prior art survey (§ 10.8)

| Candidate | Fit | Decision |
| --- | --- | --- |
| A model gateway (LiteLLM, OpenRouter) | One API for every model, so a switch is configuration | Rejected as the seam: fleet work is an agent session with tools, a sandbox and permissions, not a completion call, and a gateway adds a hop and a credential store. It can sit inside one runner later |
| Model groups or aliases in such gateways | One name that resolves to a model | **Adopted** as `classes`, resolved to an exact pinned id so § 13.3 holds |
| The Unified Harness Protocol and HarnessRouter | One API over several agent harnesses, with conformance tests | The harness-protocol PRD already keeps it as an optional adapter. **Borrowed**: a conformance suite a runner must pass |
| Claude Code's own host switches (Bedrock, Vertex AI, Foundry, a base URL) | The same harness and the same models from another host | The cheapest first switch. `tools/jev/headless.py` strips those variables from every run today on purpose; P2 decides when one is allowed |
| OpenCode | A provider-neutral agent engine; bashOS already runs on it | Candidate second runner (P5) |
| Eval frameworks with a provider matrix (promptfoo, Inspect, OpenAI Evals) | The same set run against several models, results kept | **Borrowed**: the matrix and the kept result. `tools/evals.py` already has an adapter per role; revisit a framework if adapters outgrow it |
| OpenTelemetry GenAI semantic conventions | Telemetry names no vendor owns | Already adopted by the harness-protocol PRD; P3 here |
| Shadow or canary runs | The same work on two providers, compared before a switch | **Adopted** for P5 |

**Build versus adopt.** Adopt the class as the single binding, the kept eval result and the conformance suite. Build two small things: a reader that finds every place a model is named and plans a switch, and one flag on the eval runner that keeps a run.

## Decision

1. **The definition is the test.** A switch is *easy* when it is one line, and *safe* when every agent it moves is proven on the target. `tools/dash ai switch <class> --to <model>` reports both, and says `READY` only when both hold.
2. **A class binds a kind of work to a model, once.** `_data/fleet.yml` `ai_models.classes` names each kind of work by what it needs (`deep`, `standard`, `fast`) and binds it to one exact id from `ai_models.allowed`. A class is not an alias: it resolves to a pinned model, and changing its line is the same gated change as changing the list. The names never say which vendor serves the work.
3. **Every other place that names a model is a binding, and the count only goes down.** [`tools/fleetcore/aimodels.py`](../../tools/fleetcore/aimodels.py) finds each one with its file and line: a setting elsewhere in the settings, a literal in a workflow, an action, a generator, a tool, a kit or a step spec, and a literal in a fleet repo's own workflows. The model an eval set is pinned to and a table that holds a row per model are listed apart, because a switch re-runs the one and adds a row to the other. New work names a class or a setting, never a model.
4. **Proof is a recorded run.** `tools/evals.py run <role> --model <id> --record` appends one row to `_data/eval_runs.yml`: the role, the model and its provider, the date, how many cases ran, passed and failed, and the hash of the set. The runner is the file's only writer. A row is proof only when the whole set ran, nothing failed, and the set in the tree is still the one that ran. A sample, a failure and a run on an older set each read as what they are.
5. **Coverage is declared, and a part is never read as the whole.** `ai_models.evals` maps each eval set to the agents it covers, and says when a set tests only part of an agent. An agent no set covers is `no-evals`, which is not a pass.
6. **A switch is a plan before it is a change.** The plan lists the edits the switch still owes and the state of every agent it moves. The pull request that changes a class line carries the plan and the recorded runs, so the evidence travels with the change.
7. **No regression covers the controls, not only the answers.** The program that reaches a provider (a runner: a CLI or an action) must give the same controls the harness standard holds today's to: a budget cap, a turn cap, a kill switch, a pinned model, a cost and usage record, usage-limit handling, a tool allowlist and a sandbox. A runner passes one conformance suite before any class is bound to a provider only it reaches (P2). A control a runner cannot give is declared and shown, never silently dropped.
8. **The code names no provider and no model.** Every id the reader looks for comes from `ai_models.allowed`, and a test fails if the module names one, as for clouds in ADR 0018.
9. **Who executes is unchanged.** § 26, § 28 and § 30.3 stand. Binding a class that executes software changes to a model that Claude Code does not run needs an amendment, and only the maintainer ratifies one. Everything up to that line is built here, so that the decision, when it comes, is one line and a set of green rows.

### Phases

| Phase | Delivers | Spends or changes behaviour? |
| --- | --- | --- |
| P0, this pull request | This record; `ai_models.classes`, `ai_models.evals`; the reader; `tools/dash ai models`, `bindings` and `switch`; `--record` on the eval runner and the empty `_data/eval_runs.yml`; [docs/AI-MODELS.md](../AI-MODELS.md) | No. It reads; `--record` only writes when someone runs a model eval |
| P1, one place | The 14 settings and the 25 hub literals name a class; the kit seeds a class, so its 38 copies in the fleet fall as kit upgrades land; a check that refuses a new binding, in shadow first | No behaviour change: the same models, written once |
| P2, the runner seam | One adapter at the two existing seams, the ten vendor-action steps and two local callers moved onto it; the conformance suite; the controls each runner gives, declared | Yes: how every agent is started. Golden tests hold today's command byte for byte |
| P3, the provider in every record | A provider field in the run-record contract, the AI ledgers and the lake; telemetry in the GenAI names beside today's; a price table per provider | Additive |
| P4, coverage and the gate | Eval sets for the agents that have none, the most-run first; a baseline run of every set on today's models, recorded; the prompt under test in the hash; a check that a pull request changing a class line carries proof | Spends: each baseline is a capped model run the maintainer approves |
| P5, a second provider in shadow | The same work run on a second provider beside the first, compared and never used: the same models on another host, then another runner | Spends, behind its own kill switch |
| P6, the executor | The amendment that says which classes may be bound to which runners | The maintainer's decision |

Every phase after P0 is its own pull request under the tracking epic that follows acceptance.

## Consequences

**Positive**

- The goal has a number. Today a switch of the most-used model is 1 line plus 98 edits with 0 of 74 agents proven; each phase moves one of those figures, and anyone can read them.
- It uses what the constitution already requires. § 13 asked for evals on every model change; this keeps their results and reads them.
- A second provider cannot arrive with weaker controls unnoticed: the conformance suite and the declared controls say so before a class moves.
- The first slice changes no behaviour and adds no model, credential or provider.

**Negative**

- The day-one figures are poor and visible: 118 places, 3 of 87 agents covered, no run recorded.
- Proof costs money. A model eval run spends, so a baseline for every set is a real, capped expense, and a class line cannot move for free.
- A recorded run goes stale only when the set changes. A changed prompt with an unchanged set still reads as proven until P4 puts the prompt in the hash.
- `classes` is one more concept, and JEV already uses "tier" for its conflict tiers. The two are different things with similar words.
- Of the 79 literals in fleet repos, 38 fall as each repo takes a kit upgrade, one pull request per repo. The other 41 are in workflows each repo wrote itself, and are that repo's to change.
- Two classes bound to one model cannot be told apart while places name models: the reader says so and will not plan a switch for one of them.

## Alternatives considered

- **A gateway as the seam** — see the survey: it solves completion calls, and the fleet runs agent sessions.
- **Wait until a second provider is needed** — the count of places grows meanwhile, and a switch made in a hurry is the one made on trust.
- **Replace the 14 settings with class references in this change** — every reader of those keys would change at once, alongside an open pull request that edits the same block. It is P1.
- **Keep eval results in the local AI ledger** — it lives on one machine and is not committed, so the evidence could not travel with the pull request that needs it.
- **Treat the provider only as a route in the harness standard** — a route says how a step is started. It says nothing about which model a kind of work runs on, or whether moving it is safe.
- **One ADR for the agent-loop contract and this** — epic #632 owns how a run is described (tasks, sessions, events, the trace). This owns which model runs it and what proves a change of model. They meet at the session's provider field, and the name #632's schema adopts is the one P3 uses.

## Supersedes / Superseded by

- Supersedes: none
- Superseded by: none
