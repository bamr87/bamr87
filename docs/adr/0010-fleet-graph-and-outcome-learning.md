# ADR 0010 — The fleet graph and outcome learning: one model of what the control plane manages, and a shadow estimate of where each loop's work lands

- **Status**: proposed
- **Date**: 2026-11-10
- **Deciders**: proposed by an agent at the maintainer's request (2026-11-10: a continuously operating, efficient and harmonized agentic loop harness with graph and reinforcement-learning components that span the repos, and a console that carries every capability a person or an agent needs to operate it, over MCP or the API); the maintainer accepts or rejects it by merging the PR that adds it
- **Related**: constitution § 10.6 (read-only tools), § 10.7 (honest cost), § 10.8 (prior art first), § 10.9 (local first), § 11 (write-back), § 12.3 (gated changes), § 13.7 (earned autonomy), § 13.9 (no agent changes its own tier), § 17 (loop switches), § 29 (the efficacy contract); [ADR 0004](0004-recursive-harness-refinement.md) (Harness²), [ADR 0007](0007-workflow-studio.md) (one read model on every surface), [ADR 0009](0009-agentic-efficacy-model.md) (accepted outcomes and the five KPIs); epic #773 phase E3 (#777, outcome tracking) and E5 (#779, the Agents view), epic #737 phase A7 (#748, flow control); [docs/FLEET-GRAPH.md](../FLEET-GRAPH.md), [docs/LEARNING.md](../LEARNING.md)

<!-- Accepted in and Completed are added by the post-merge ratify job when the maintainer merges this ADR's PR and when the maintainer closes the Tracking issue as completed (docs/adr/README.md#lifecycle). Never write them by hand. A PR that adds or changes an ADR is gated (constitution § 12.3). -->

## Context

### Needs assessment

The review of 2026-11-09 and 2026-11-10 found the loops running and their output piling up. Three needs came out of it.

1. **One answer to a question that crosses two registries.** The hub keeps a dozen partial maps: the registry, the workflow atlas, the switches map, the agent inventory, the harness registry, the feature index, the roadmap, the decision logs and four operator surfaces. Each is correct about its own subject and silent about the others. Nothing can say what depends on a composite action, which agents read a file, or what a person can do in a terminal that an agent cannot do over MCP. The loops themselves are listed four ways: 10 hand-kept cards in `tools/console/core.py`, 41 entries in `_data/fleet.yml` `switches.loops`, 17 keys in `schedule:` and 73 agents in `_data/agents.yml`. The parity question was answered on 2026-11-10 by a person reading four files; two MCP tools the docs promise had been missing since the server merge and nothing had noticed (#810).
2. **Know what happened to a loop's output.** Every ranker in the hub is a fixed rule: the scout rotates through the repos by date, evolution takes every opted-in repo, the pipeline scores an issue from its labels, the conflict engine picks a tier from the size of the conflict. None reads what became of the last thing it filed. ADR 0009 defined an accepted outcome and deferred measuring it to E3 (#777). The lake could not have measured it: its `issues` table stored `closed` and neither why an issue closed nor whether a pull request merged.
3. **Stop filing faster than anyone can take up.** Measured on 2026-11-10 from GitHub, for output filed since 2026-09-10:

   | Loop | Filed | Landed | Rejected | Stale | Working | Young |
   | --- | --- | --- | --- | --- | --- | --- |
   | Scout (issues; first filed 2026-10-30) | 58 | 3 | 0 | 0 | 13 | 42 |
   | Doctor (issues) | 88 | 17 | 19 | 30 | 1 | 21 |
   | Doctor (fix pull requests) | 5 | 5 | 0 | 0 | 0 | 0 |
   | Evolution (pull requests) | 17 | 11 | 0 | 0 | 0 | 6 |
   | Pipeline (issues it took) | 36 | 31 | 1 | 0 | 4 | 0 |

   Landed means merged, or closed as completed. All 19 rejected doctor issues were closed as duplicates. The scout has 55 issues open and lands three every four weeks. Evolution has landed a pull request in two repos only (README and scripts). The fleet opened 419 issues in 14 days and closed 47. Flow control (#748) is specified and has no measure of what a loop's next slot is worth.

If nothing is decided, each new registry adds another partial map, each new loop adds another fixed rule, and the backlog keeps growing at the rate the caps allow.

### Prior art survey (§ 10.8)

- **Backstage's software catalog and system model** (backstage.io; Component, API, Resource, System, Domain, with relations). Fit: a small closed vocabulary of entity kinds and typed relations. Limits: the model is part of the core, and relations come from `catalog-info.yaml` files people write, so the graph says what someone last typed. The hub's facts are already in files a parser can read.
- **Port and Cortex** (commercial developer portals with custom models and scorecards). Fit: a model per organisation and checks over it. Limits: hosted products for teams. ADR 0007 already declined a vendor for the same reason, and the fleet has one maintainer.
- **Embedded graph databases.** Kùzu was archived in October 2025 and lives on as forks (RyuGraph). Neo4j needs a server. Fit: a query language over a property graph. Limits: 1,253 nodes and 1,752 edges build and answer in under a second from Python dictionaries; a store adds a dependency, a schema migration and a sync job for no faster answer.
- **Graphs already in the fleet.** zer0-CMS keeps a content graph (`content/graph/models.py`: Entity, Edge, Embedding, on pgvector) and law-ai a Neo4j knowledge graph. Fit: neither; both model their product's domain, not the control plane. Noted so the names do not collide: this ADR's graph is the control plane's.
- **The hub's own partial graphs.** `workflow_atlas.edges()` (workflow → action → published file), `_data/agents.yml` (`reads`, and each source's writer), `switches.loops`, `features.yml` (`prd`, `tests`, `scenarios`), `harness_registry.yml`. Fit: these are the inputs, read through their own parsers. Limits: each stops at its own border, which is the need.
- **Thompson sampling for model routing in production.** Ramp's gateway (Thompson sampling over latency and failure tracked with a moving average), `bayesian-router` (PyPI), RoBC (Thompson sampling per cluster), OrcaRouter (LinUCB with an offline warm-up; arXiv 2605.30736). Fit: a Beta estimate per arm, discounted over time, sampled to share traffic, is the working pattern when feedback is partial. Limits: they route requests between models and are rewarded within the request. The fleet's reward is a person merging or closing something days later, a few hundred times a quarter. No context model is warranted at that volume, and the libraries are young.
- **Open Bandit Pipeline** (Saito et al., NeurIPS 2021 datasets track; off-policy evaluation with inverse propensity and doubly robust estimators). Fit: judge a policy from logged data before it acts. Limits: the estimators need the logging policy's propensities, and the loops' rules are deterministic, so every propensity is 0 or 1. The replay in decision 5 keeps the idea (score the estimate on history before it steers anything) with a predictive test instead.
- **ADR 0004 (Harness²) and ADR 0009.** ADR 0004 improves how a step does its work, by editing a loop's tunable half and keeping what a blind selection prefers. ADR 0009 defines what an agent's work is worth. Fit: this ADR adds the third part, where a loop spends its slots, on the same outcome signal. Limits: neither chooses between targets.
- **§ 13.7, earned autonomy.** One tier down after 25 consecutive clean approvals, back to high on any rejection. Fit: the constitution already has a rule driven by recorded outcomes; this ADR measures the outcomes such a rule needs. Limits: it governs risk tiers, not allocation.

**Build versus adopt.** Adopt the vocabulary idea (kinds and typed relations), the Beta-and-Thompson pattern with time decay, and the rule that a policy is scored on history before it acts. Build both parts in `tools/fleetcore/` on the standard library: they must read the hub's own files offline, run on every surface from one implementation, and stay small enough to read (about 1,100 and 650 lines).

## Decision

1. **One graph, a read model.** `tools/fleetcore/graph.py` (`fleet-graph/v1`) builds one typed graph from the committed registries and the checkout: 22 kinds of node (repo, workflow, action, loop, variable, secret by name, file, source, agent, feature, requirement, roadmap entry, decision, amendment, command, operation, route, tool, page and three more) and 24 relations. It parses through the owners' parsers (the workflow atlas for `.github/`, the layer's source for MCP tools) and never keeps a second copy of a fact. It is built on demand and committed nowhere; the console caches it for 30 seconds.
2. **A relation says which end depends on the other.** `uses`, `reads`, `runs` and `gated_by` make the source of the edge the dependent; `publishes`, `writes`, `serves` and `affects` make the target the dependent; containment (`owns`, `manages`) carries no dependency. `impact` walks to what depends on a node, `lineage` to what it needs, `path` finds the shortest chain between two nodes.
3. **The graph's checks report; one of them fails.** `tools/dash graph check` reports a source an agent reads that nothing writes, a switched hub loop whose workflow is missing, a scheduled hub workflow with no entry in the switches map, a call to a hub action that does not exist, a feature that names a file not in the checkout, an API route that returns data and no MCP tool reaches, and a dash command no console operation runs. Only an edge to an undeclared node is an error, because it means a builder is wrong. The parity findings are notes, each exemption is one line in the module with its reason, and turning any of them into a gate is a gated change.
4. **Outcomes are read from the lake.** `issues` gains `state_reason` and `merged_at`, filled by the sync that already lists every issue (no extra request). `_data/fleet.yml` `learning.loops` attributes an issue or pull request to a loop by the labels the loop puts on its output. Each output is landed (merged, or closed as completed), rejected (closed unmerged, not planned, duplicate), stale (open past `horizon_days` with nobody working it), working, young or unread. A row synced before the columns existed is unread and is never counted as a rejection.
5. **One estimate per loop and per arm, and a test it must pass.** An arm is the repo a loop acted on. The estimate is Beta(prior + landed, prior + rejected + stale), each outcome weighted by its age with a half-life, the prior being the loop's own rate worth `prior_strength` observations. The plan shares the next slots by Thompson sampling: an arm's share is the probability that it is the best one, drawn with a seed made of the date, so one day has one plan. The replay walks the history in order and asks whether the arm's estimate predicted each outcome better than the loop's average did (Brier skill). Below `min_resolved` outcomes the answer is "not enough evidence".
6. **Shadow only, and a ladder to anything more.** `learning.mode` accepts `shadow` and nothing else: `tools/dash learn` prints, steers no loop and changes no cap. Three steps can follow, each a gated pull request for one loop:
   - **Advise:** the loop prints the plan in its run summary beside what it took.
   - **Steer:** the loop's queue builder orders its candidates by the plan, inside its existing caps.
   - **Propose:** the engine drafts a cap or share change as a pull request a person merges.

   A loop may take a step only after its replay shows skill above zero over at least `min_resolved` scored outputs. No step raises a cap, edits a step spec's hard half (ADR 0004 decision 5), or changes the engine's own thresholds (§ 13.9, § 29.8). A pin in `_data/work_queue.yml` always wins.
7. **Every surface, one implementation.** `tools/dash graph` and `tools/dash learn`, `/api/graph` and `/api/learn`, the MCP tools `fleet_graph` and `fleet_learning`, and the console operations `graph-check`, `learn-status` and `learn-plan` all call `fleetcore`'s two `view` functions. The console's pages for both are the next phase.
8. **What this does not do.** It calls no model, reads GitHub nowhere, and writes nothing. It does not compute ADR 0009's five KPIs (E3 still owns the join from an output to the run that produced it; this ADR supplies the outcome and a loop-level cost floor). It does not set work-in-process limits (A7, #748). It does not look inside other repositories beyond what the committed scans hold.

## Consequences

**Positive**

- "What depends on this" has an answer: `tools/dash graph impact claude-cost --depth 2` names 7 workflows, 6 agents and 4 loops.
- The parity audit is a command. On 2026-11-10 it lists 20 dash commands with no console operation and 17 API routes no MCP tool reaches.
- The first run found drift nobody had reported: eleven features whose `docs:` still points at one of seven amendment records under `docs/amendments/proposed/` that numbering has since moved, four features naming test files that do not exist, and the `conformance` source with no writer.
- The backlog problem is measured per loop, with one word of advice (file, slow, hold) that flow control can read.
- A loop that wants to act on evidence has a defined path and a test to pass first.

**Negative**

- Two more modules and two more documents to keep current. A new registry or surface needs a builder, or the graph goes quiet about it.
- The graph reads other modules' shapes (`OPS`, `STATIC_ROUTES`, the layer's decorators) from source. A refactor of those can blind a builder; the hub's own test fails when an input reads as empty.
- Attribution is by label. A loop that stops labelling its output disappears from the estimate, and the pipeline's pull requests are counted through the issues they close, not by branch.
- The estimate is only as fresh as the lake. Rows older than the last sync window stay unread until a one-off backfill runs ([LEARNING.md](../LEARNING.md#run-it)).
- With one maintainer the outcome is one person's attention as much as an agent's quality. A stale output may be a good proposal nobody has read. The advice says so by naming the backlog, not the agent.

## Alternatives considered

- **A graph database or a committed graph snapshot.** Rejected for now: nothing reads the graph that cannot build it in a second, and a snapshot is another generated file to keep in step. The public site can get one when a page needs it.
- **Extending the workflow atlas or the agent inventory into the graph.** Rejected: each has a consumer and a gate tied to its own schema, and the need is the join between them.
- **A contextual bandit or a learned ranker over issue features.** Rejected: a few hundred outcomes a quarter cannot fit one, and its choices could not be read by the person who must trust them.
- **Letting the estimate steer the scout now.** Rejected: the scout has three resolved outputs. § 13.7 and ADR 0009 both start in shadow; so does this.
- **Counting an open issue as accepted, as ADR 0009 does for the scout.** Kept for ADR 0009's KPI and not used here: for allocation, an output nobody acted on within the horizon is the signal.
- **Reading GitHub directly for outcomes.** Rejected: the lake already lists every issue each day, and a second reader would spend the token quota a PR check must not touch.

## Supersedes / Superseded by

- Supersedes: none
- Superseded by: none
