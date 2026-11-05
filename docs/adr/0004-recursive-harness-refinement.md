# ADR 0004 — Recursive harness refinement: the Harness² method adopted into JEV, the hub's harness surface as a sensor, and a human-gated experience library

- **Status**: accepted
- **Accepted in**: https://github.com/bamr87/bamr87/pull/652 (merged 2026-11-04 by @bamr87)
- **Date**: 2026-11-04
- **Deciders**: proposed by an agent at the maintainer's request (2026-11-03); the maintainer accepts or rejects it by merging the PR that adds it
- **Related**: [docs/HARNESS-REFINEMENT.md](../HARNESS-REFINEMENT.md), [docs/HARNESS.md](../HARNESS.md) (the six layers and the ratchet), [docs/JEV.md](../JEV.md), [ADR 0002](0002-agent-step-specs-and-local-runner.md) (the step specs and the local runner this builds on), constitution § 10.8 (prior art first), § 12.3 (gated changes), § 13 (eval baseline and risk tiers), epic bamr87/bamr87#484 (run every loop locally)

<!-- Accepted in and Completed are added by the post-merge ratify job when the maintainer merges this ADR's PR and when the maintainer closes the Tracking issue as completed (docs/adr/README.md#lifecycle). Never write them by hand. A PR that adds or changes an ADR is gated (constitution § 12.3). -->

## Context

### Needs assessment

**Who needs what.** The maintainer asked for google-research/harness2 to be implemented into the monorepo where possible, with the Barbaste et al. harness-engineering study considered as well. Harness² is a method, not a library the hub can import: it recursively refines the harness around a fixed model, at the task level (a contrastive Propose–Probe–Compose step) and at the harnessing level (a persistent library of adopted harnesses and evidence-supported lessons). The hub already runs four scheduled agent loops against about forty repositories, each on a harness (a hard-rules prompt, a tool grant, caps, a generated brief, a context pack) that has never been improved by any process other than a person editing it after an incident. What the fleet needs is that method, on its own loops, inside its own governance.

**Evidence from the hub.**

- Every loop's harness changes by hand, after the fact: the standing rules in `AGENTS.md` each name an incident, and #89 (a prompt that ordered a tool it was never granted, 12 of 26 turns denied, on every scheduled run) was found by reading a log, not by a sensor. Nothing proposes a harness edit from a trajectory and nothing probes one before it ships.
- The hub keeps no record of what a harness edit did. A change to `.github/scout/scout-prompt.md` or a category emphasis file lands as a commit with no attempt before and after it; the next edit starts from zero.
- The hub's own harness surface had a latent defect no gate caught: the `run-dash` skill's frontmatter was not valid YAML (an unquoted `Triggers:` colon), which the strict agentskills.io loaders the production harnesses converge on drop silently. The first run of the surface check in this PR found it.
- The local loop runner (ADR 0002, P1) already produces exactly what the method consumes: one redacted trajectory per attempt, the validated deliverable, the brief, the caps, under a proven isolation posture, with a ledgered cost. The pieces of a Propose–Probe–Compose step exist; the step does not.
- The context pack (#486) assembles the lake, the code index, the telemetry and the loop's own history for a sealed agent. It has no slot for what an earlier refinement learned, so a lesson cannot reach the agent even when a person has written one.

**Why now.** The harness surface is growing (18 skills, two subagents, six commands, two hooks, six MCP servers in the hub alone; a `.claude/` kit fanned out to every fleet repo), the fleet's loops are moving onto one spec format and one local executor, and the two papers give a method and a corpus of production practice to adopt rather than invent. § 10.8 requires this record before implementation.

### Prior art survey (§ 10.8)

- **Harness²: Recursive Agent Harnessing for an Open World** (Xu et al., arXiv:2610.14224, google-research/harness2, Apache-2.0). Fit: the method itself. Eight editable components (c1 system prompt … c8 plugins) as a validated file tree; a contrastive Propose–Probe–Compose step with INVARIANT and DOMAIN dimensions, k base rollouts, 2k candidates, k compositions, R = 4k rollouts and P = 3k sessions asserted by a ledger; blind selection over deliverables; a reflector that writes per-edit verdicts (helped / hurt / no observed effect / confounded) and at most one transferable lesson (cue, lesson, evidence, confidence) into a per-domain library the next task reads. Evidence is served as files and the prompt is a short pointer; the evidence is data, never instructions; no rubric or grader is ever in the context. Not fit: its runtime (Linux, uv, Vertex AI, OpenCode or Codex executors, three benchmarks) is foreign to the hub, which runs Claude Code under its own executor and spends real money per attempt.
- **Harness Engineering: Anatomy, Architecture, and Evolution of Coding Agents** (Barbaste et al., arXiv:2609.00006, a source-code study of eleven production harnesses). Fit: the rules a harness surface must meet in practice, each pinned to shipped code: skills as `SKILL.md` directories with `name` and `description` frontmatter (dropped silently otherwise), deferred loading of skill bodies, conditional activation by paths, a supply chain with trust tiers and scanning; hooks as the dominant extension substrate with a near-universal event vocabulary; policy codified as data rather than imperative prose; hierarchical Markdown context files auto-discovered (every system), with per-file size caps and prompt-injection scanning (Hermes); agent-maintained memory behind a human-reviewed inbox (Gemini CLI's /memory inbox, Codex's git-baselined memories); the cheap caps (turns, wall clock); deterministic retrieval over code rather than embeddings; no general agentic framework in the runtime. Its catalogue names the shapes this ADR builds: Self-Improving Skill Loop, Agent-Maintained Memory, Outer Verification Loop, Untrusted-Content Delimiting, Policy-as-Code.
- **Prompt-optimisation frameworks** (DSPy, TextGrad, OPRO and the like). Fit: they optimise a prompt against a scored training set. Not fit: the hub's loops have no score (§ 13.1's eval sets are in their grace period), the editable surface is a tree of files rather than one prompt, and the method must run inside the hub's spend, isolation and merge rules.
- **The hub's own machinery.** ADR 0002's step specs (the hard rules as one reviewed file pair, gated under § 12.3), the local loop runner and its executor (`headless.py`, the Seatbelt posture, the canary, `budget.loops`), the context pack, the adapters, the `.fleet/runs` record. Fit: everything a refinement step runs on, already proven; the method is built on top of it and never beside it.

### Build-vs-adopt decision

Adopt the method and the practice; build the integration; vendor nothing. Harness²'s package is not installed or forked (its runtime does not fit and its benchmarks are not the fleet's work); its prompts are adapted under their Apache-2.0 notice into the hub's mission files, with the hub-specific parts (the tunable/hard-rule split, the loop and deliverable slots, the proposal file) added. Barbaste et al.'s rules become the surface validator's rules. The hub's own executor, posture, caps and gates are reused as they are, so a refinement rollout is a loop attempt and nothing else.

## Decision

JEV gains capability three, `python3 -m tools.jev refine` (`tools/dash refine`), in four phases. P0 is this pull request and spends nothing; every later phase runs models only through the loop runner's executor, under its posture, inside `budget.loops`, behind the maintainer's `--apply`, and is its own gated PR.

### P0 — the $0 half (this PR)

1. **The harness surface as a sensor** (`tools/jev/surface.py`). Harness²'s eight components mapped onto a Claude Code harness: the context-file chain (`CLAUDE.md`, `AGENTS.md`; always on, capped at `harness_refinement.always_on_max_chars`), `.claude/settings.json` permissions (guardrails, policy as data) and hooks (plugins, with `.mcp.json`), `.claude/agents/` (subagents), `.claude/skills/` and `.claude/commands/` (skills), `.claude/hooks/` (scripts), `.github/instructions/` (tool guidance), and the memory directories. `refine surface check [root]` validates any repository's surface with the rules both sources agree on and exits 1 on an error; `census` prints the inventory; `diff` compares two surfaces. The hub's own surface is held clean by `tools/test_jev_surface.py`.
2. **The experience library** (`tools/jev/library.py`, `_data/harness_library/<loop>/<domain>/<entry>/`). One `experience.yml` (`jev-experience/v1`: cue, lesson, evidence, confidence, the per-edit verdicts) and the adopted edits as `harness.diff`, grouped by loop and registry category. An entry is written only on a branch, by `refine library add` or a later reflector's draft PR, and reviewed before it reaches `main`: the human-gated inbox. `refine library check` holds every entry to its schema and to the context pack's redaction, so nothing private is ever committed.
3. **The library reaches the agent** (`tools/jev/context.py`, `library` provider). The context pack gains a section with the domain's newest lessons, rendered as data under the pack's rule, trimmed just before `history`. It is on by default for a spec with no explicit `providers` list; adding it to each step spec's list is a gated follow-up (P1), since a spec edit re-pins `JEV_STEP_SHA256`.
4. **The method's $0 half** (`tools/jev/refine.py`, `tools/jev/missions/`). The schedule of one Propose–Probe–Compose step in both modes with its R = 4k / P = 3k identity and the ledger that asserts it; `refine plan <loop>` with the ceiling computed from the step's own `budget.call_sites` cap and `harness_refinement.stage_usd`, judged against `budget.loops`; `refine evidence <loop> --item KEY`, which builds from real `.fleet/runs` records the evidence tree a proposer reads (the brief, full trajectories in the `[ACTION]` / `[OBSERVATION]` / `[ERROR]` grammar, the deliverables, the tunable harness, the hard rules read-only, the domain's library, the rendered mission), every file redacted; and the five missions rendered one-pass under the step-spec prompt rules.
5. **The editable surface is the tunable half.** A candidate may edit a loop's brief template and category emphasis (`.github/scout/`, `.github/evolution/`). A step spec's hard rules, grant and caps are never edited by a refinement: a lesson that needs one is written to `context/proposals/hard-rules.md` for a gated PR (§ 12.3). The deliverable's shape belongs to the loop's filer.
6. **Configuration** in `_data/fleet.yml` `harness_refinement:` (`enabled`, `k_max`, `mode`, the two surface caps, `stage_usd`, `model` as an exact id in `ai_models.allowed`, `max_turns`, `library_dir`, `obs_trunc_chars`), read by every command and validated on every read.

### P1 — the model-backed stages

The proposer, composer, selector and reflector sessions run through `tools/dash-gen ai-run --isolate` with the evidence tree as the working directory, under the step's own posture and the loop runner's budget lock, each capped at `stage_usd`; a candidate's rollout is a `loop run` attempt whose clone carries the candidate's tunable files in place of the hub's; selection is blind over the validated deliverables; the reflector's entry lands as a draft PR to `_data/harness_library/`; the adopted tunable edits land as a draft PR to `.github/`. `harness_refinement.enabled` and the maintainer's `--apply` gate every spend; the first live step is a canary at k = 1 on the scout, the cheapest loop, and the whole step is refused when `budget.loops` cannot absorb its ceiling.

### P2 — the console surface and the assistant

The Harness Console's **Refine** page (`/refine`, `/api/refine`): the surface check and the fleet sweep, one plan per agent step with its ceiling against the month, the evidence trees, the experience library with the $0 reflector's form, and the **review queue** of every unfiled local loop-run preview with *Check it still matches* ($0) and *Approve and file* (the engine's publish gate, § 11.8, behind the confirm); the ops `refine-surface`, `refine-plan`, `refine-evidence`, `refine-library-check`; the MCP tools `refine_status`, `refine_library`, `refine_reviews`. The **Assist** page: one read-only headless Claude Code session per question (`tools/dash-gen ai-run`, the prompt in `tools/console/assist.prompt.txt`) with the console's own MCP layer as its only server, the hub checkout readable, every writing tool denied, capped by `_data/fleet.yml` `assistant:` and confirm-gated because it spends. Writes stay behind the console's confirm; the model-backed refinement stages (P1) are not reachable from the page until they exist.

### P3 — the surface check in the fleet

`refine surface check` joins `tools/conformance.py` as a check on every registry repository's `.claude/` kit (warn-only per repo until its fan-out PR lands, then a hard failure), and a `library` lesson becomes a candidate for the ratchet: a lesson confirmed three times becomes a sensor or a standing rule.

### Adopted as is

- Harness²'s component model, its Propose–Probe–Compose schedule and ledger identity, its evidence layout and its three prompt rules (evidence is data, no grader in context, KEEP_BASE is a real answer).
- Barbaste et al.'s surface rules, and their inbox pattern for agent memory.
- ADR 0002's executor, posture, canary, budget lock and run record; the context pack's redaction; the step-spec prompt rules for mission files.

### Extended

- The context pack: one provider, `library`.
- The loop runner's record: a refinement reads it; later phases write a `refine` run record beside it.
- `_data/fleet.yml`: one block.

### Rejected

- Vendoring harness2 as a submodule or dependency (its runtime and benchmarks do not fit; its code is a reference, not a library).
- Letting a refinement edit a step spec's prompt, grant or caps (those are gated config under § 12.3; a change to them is a human decision).
- Embedding-based retrieval over the library or the trajectories (0 of 11 production harnesses do it for code; the library is small, lexical and browsed by an index file).
- Any LLM-as-judge score of a loop's work in P0 (§ 13.1's eval sets are the place for that; selection is blind over deliverables, not a score).

## Consequences

**Positive**

- The hub's harness surface is a sensor: a malformed skill, a hook that never fires, a script a component names but does not ship, an over-cap context chain or injection phrasing fails a test before it costs a run. The first run found and fixed one such defect.
- Every improvement to a loop's tunable half can be proposed from a trajectory, probed before it ships, and composed from evidence, under the same spend ceiling and gates as any loop attempt.
- What an edit did is recorded, and the next task in the domain starts from it: the library reaches the agent through the context pack and the proposer through the evidence tree.
- Nothing in P0 calls a model; the ceiling of a step is printed before it exists, and the method's identity is asserted rather than assumed.

**Negative**

- A refinement step is expensive by construction (4k rollouts at the step's own cap): on the scout at k = 1 it is $42 against a $50 month, on evolve at k = 2 it is $176. The plan says so, and P1 starts on the cheapest loop at k = 1.
- The library is only as good as its reflections; a lesson resting on confounded rows is a guess, which is why the schema carries verdicts and a confidence and why a person reviews every entry.
- One more provider in the context pack and one more `tools/jev` capability to keep tested and documented.

## Alternatives considered

- **Run harness2 as is, pointing its Claude CLI channel at the hub's loops** — its adapters are benchmark-shaped (task prompts, judges, rubrics), its proposer bypasses permissions (`--dangerously-skip-permissions`), and it has no notion of a step spec, a spend ledger or a gated change; every hub rule would have to be bolted on from outside.
- **A prompt optimiser over the brief templates** — needs a score the loops do not have, and optimises the wrong unit (one prompt, not a harness tree).
- **Keep improving harnesses by hand after incidents** — the status quo; it has no sensor over the surface and no memory of what an edit did.

## Supersedes / Superseded by

- Supersedes: none
- Superseded by: none
