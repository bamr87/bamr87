# PRD — Common harness protocol and platform

> **Status: Draft / proposed.** Design only; nothing here is implemented yet.
> Feature: `HUB-NEW` (slug `harness-protocol`) in [`features/features.d/harness-protocol.yml`](../../features/features.d/harness-protocol.yml). The number is assigned at merge.
> Roadmap: `FF-0038` in [`_data/roadmap.yml`](../../_data/roadmap.yml). Epic: [#632](https://github.com/bamr87/bamr87/issues/632), with phases [#626](https://github.com/bamr87/bamr87/issues/626)–[#631](https://github.com/bamr87/bamr87/issues/631).
> Requirements: FR26, FR46, FR54, FR56, FR59, FR60, FR63, NFR9 and NFR11 in the root [`PRD.md`](../../PRD.md), plus the new `FR-NEW:harness-loop-contract`, `FR-NEW:harness-task-trace`, `FR-NEW:harness-adapters` and `NFR-NEW:harness-protocol-portable`.
> Governing rules: [`docs/constitution.md`](../constitution.md) and [`docs/amendments/`](../amendments/).

## 1. Problem

The fleet runs agents through several harnesses:
- the Harness Console job API (FR60) and its MCP layer (FR26, with write tools in #472)
- the CI agent steps (#489)
- local headless Claude Code (FR56)
- the JEV tiers, with k8s research in #587
- the harness/loop registry (#586)

Each one describes a run, an approval, a budget and a trace in its own way. The activity-replay epic ([#624](https://github.com/bamr87/bamr87/issues/624); PRs #617 and #625) needs one event shape to replay. The `_data/fleet.yml` `harnesses:` contract only governs deployment, not runtime. Meanwhile, outside protocols (UHP, A2A, AG-UI, ACP) are changing monthly, and nothing gives them a single place to plug in.

## 2. Goals and non-goals

**Goals**
1. One agent-loop contract shared by every harness. Work runs as a **task**, inside one or more **sessions**, with a **typed event stream**. **Interrupts** pause for approval and resume. **Budgets** cap tokens, USD, wall clock and tool calls.
2. Keep **MCP** as the tool layer and **AGENTS.md** as the source of repo instructions.
3. Each task produces **one OTel GenAI span tree in Phoenix**: a root span for the task, with a child span per turn and per tool call.
4. Outside protocols connect only through **adapters**. The Unified Harness Protocol is optional. A2A is the later external interface; AG-UI and Zed's Agent Client Protocol are options.

**Non-goals:** replacing MCP or AGENTS.md; making UHP (or any pre-1.0, single-vendor spec) a dependency; changing repository settings or secrets; running anything on Amr's Mac without his yes (§ 10.5).

## 3. The contract

| Concept | Meaning | Maps today to |
| --- | --- | --- |
| Task | One unit of requested work, with an id, a requester, a repo, a risk tier and a budget | console job (FR60), loop run, CI agent step |
| Session | One agent context working on a task (model, harness, JEV tier) | Claude Code session, JEV tier attempt |
| Event | Typed, ordered by sequence, carries `trace_id`. Kinds: `task.*`, `turn.*`, `tool.*`, `interrupt.*`, `budget.*`, `artifact.*`, `error` | activity events (#624), job progress |
| Interrupt | A pause that waits for a human or policy decision, then resumes or cancels | FR46 high-tier approval, `needs-amr` |
| Budget | Hard caps checked before each turn and tool call | `harnesses.budget`, `ai_models`, JEV caps |
| Tool | An MCP tool call (read or write) with risk tags | MCP layer (FR26, #472) |

The schema is `schemas/harness-event-1.json`, delivered in P0. It is versioned, additive-only within a major version, and validated in tests.

### Protocol positioning

| Protocol | Role here | Why |
| --- | --- | --- |
| MCP | **Kept**: the tool layer | Already the fleet standard (FR26, NFR9) |
| AGENTS.md | **Kept**: repo instructions | Already the fleet standard |
| OTel GenAI semconv | **Adopted**: the trace shape | Vendor-neutral, and Phoenix is already wired in |
| [UHP 2026-10-19](https://unifiedharnessprotocol.org/spec/2026-10-19) | **Optional adapter** (P4) | Apache-2.0, but a single-vendor (HarnessRouter) draft that changes fast |
| [A2A](https://github.com/a2aproject/A2A) | **Later**: the external interface (P5) | Open governance under [AAIF](https://aaif.io/blog/a2a-joins-aaif); it is the subject of #543 |
| [AG-UI](https://github.com/ag-ui-protocol/ag-ui) | Option for the console front-end stream | Event model close to ours |
| [Agent Client Protocol](https://github.com/agentclientprotocol/agent-client-protocol) | Option for editor clients (FR63) | Zed's editor↔agent protocol |

## 4. User stories

- **US1:** As Amr, I see every agent run in the fleet, whether CI, local, console or a JEV tier, as the same task / session / event shape, so one view (`/replay`, #624) covers all of them.
- **US2:** As Amr, a high-risk action pauses as an interrupt that I approve or reject in one place. The run then resumes or stops cleanly.
- **US3:** As Amr, a runaway agent stops at its budget, and the stop shows up as an event and a span rather than a silent kill.
- **US4:** As a harness author, I add a new harness by writing one adapter to the contract, without touching the console or the trace plane.
- **US5:** As Amr, I can try UHP or A2A clients through an adapter and remove the adapter without breaking anything.
- **US6:** As a debugging agent, I open one Phoenix trace per task and see every turn and tool call in it.

## 5. Phases, milestones and acceptance criteria

| Phase | Issue | Milestone | Acceptance criteria |
| --- | --- | --- | --- |
| P0 Contract | [#626](https://github.com/bamr87/bamr87/issues/626) | M0: ADR plus schema | Fixture events validate; every existing harness maps to the schema with no unmapped field; Amr reviews the mapping |
| P1 Console core | [#627](https://github.com/bamr87/bamr87/issues/627) | M1: the task API | Task lifecycle, interrupt/resume, budget stop and cursor resume are tested; FR46 high-tier actions pause; the old job routes still pass |
| P2 Trace plane | [#628](https://github.com/bamr87/bamr87/issues/628) | M2: one tree per task | A fixture task produces the expected span tree in Phoenix; events and spans join by `trace_id`; redaction test passes (shared with #619) |
| P3 Harmonize | [#629](https://github.com/bamr87/bamr87/issues/629) | M3: every harness on the contract | Claude Code headless, the CI steps, the JEV tiers and the #586 registry emit conformant events, or are listed as gaps; the conformance check is a warning first |
| P4 UHP adapter | [#630](https://github.com/bamr87/bamr87/issues/630) | M4: optional adapter | Off by default; spec version pinned; core tests pass with the adapter removed; spec drift raises an attention item |
| P5 External | [#631](https://github.com/bamr87/bamr87/issues/631) | M5: A2A decision and fixture | #543 decided; A2A fixture passes against the contract; loopback plus bearer auth (NFR9); AG-UI and ACP evaluated |

Order: P0 comes first. P1 and P2 run in parallel. P3 needs P1. P4 and P5 each need P1. P5 also needs the #543 decision.

## 6. Design for Failure

| Failure | Behaviour |
| --- | --- |
| The event store or stream is down | The harness keeps running and spools events locally, then flushes them exactly once by `event_id` |
| Phoenix or the collector is down | Spans are dropped and counted; the task is never blocked |
| An interrupt is never answered | It times out to **cancel** (never to approve), and the timeout is logged as an event |
| A budget is exceeded mid-turn | The current tool call finishes or is cancelled, then a `budget.exceeded` event ends the task |
| The UHP spec changes or is withdrawn | The adapter is disabled by its kill switch (FR54); the core is unaffected |
| An adapter sends a malformed event | Schema rejection, counted; it can never bypass risk tiers, budgets or kill switches |
| A schema version is skewed | Readers accept additive fields and refuse a different major version with a clear error |

## 7. JEV tiers

| Tier | Work |
| --- | --- |
| Tier 1 (cheap model, mechanical) | Schema fixtures, mapping tables, adapter boilerplate, docs |
| Tier 2 (standard) | Console task API, OTel instrumentation, harness adapters |
| Tier 3 (frontier, plus Amr's review) | ADR, interrupt and budget semantics, the A2A and UHP decisions |

Risk tiers (§ 13.6): every write path stays PR-only, and high-tier actions wait for Amr (FR46, NFR11).

## 8. Dependencies

- The `_data/fleet.yml` `harnesses:` contract and `harness_registry.py`
- #586 harness/loop registry
- #587 JEV-tiered harness on k8s
- #472 MCP write tools
- #489 CI agent steps
- #624 activity replay, with PRs #617 and #625 (shared event envelope and trace plane; P2 here aligns with #619)
- FF-0032 fleet-shell, for the UI surfaces
- #536 and #543, for A2A

## 9. Risks and licenses

| Risk | Mitigation |
| --- | --- |
| **UHP churn and vendor governance (main risk).** It is a single-vendor, fast-moving draft. | Optional adapter only; spec version pinned; drift watch; exit plan; nothing in the core imports it |
| A2A, AG-UI and ACP are still evolving | Decide before building (#543); adapters only |
| Refactoring the job API breaks console or MCP clients | Keep a compatibility layer and run the old tests in P1 |
| Scope overlap with #624 and #586 | This epic owns the contract; #624 owns visualization; #586 owns inventory |

Licenses: UHP spec Apache-2.0; A2A Apache-2.0; AG-UI MIT; Agent Client Protocol Apache-2.0; OTel semconv Apache-2.0; Phoenix ELv2 (self-hosted, as today). Each license is to be confirmed in P0's license review.

## 10. Proposed amendment (not ratified)

**`harness-protocol-core`**: every fleet harness speaks the fleet agent-loop contract. External protocols connect only through removable, off-by-default adapters, and no single-vendor or pre-1.0 spec may become a core dependency. This is described in the PR for Amr to decide; nothing here ratifies it.
