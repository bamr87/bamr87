# Harness refinement — the Harness² method on the hub's own loops

> Recursive harness refinement (JEV capability three, `tools/dash refine`): the hub's harness surface validated as a sensor, one Propose–Probe–Compose step planned and evidenced from real local runs at $0, and a human-gated experience library whose lessons reach every later attempt through the context pack. Decision: [ADR 0004](adr/0004-recursive-harness-refinement.md).

## Why

Agent = model + harness ([HARNESS.md](HARNESS.md)). The hub holds the model fixed and has improved its harnesses one incident at a time: a standing rule after a failure, a sensor after the third correction. Nothing proposed a harness edit from what an attempt actually did, nothing probed an edit before it shipped, and nothing remembered what an edit changed. Two pieces of 2026 research say how that is done in practice. [Harness²](https://github.com/google-research/harness2) (Xu et al., arXiv:2610.14224) refines a harness recursively while the model's weights stay fixed: at the task level, a contrastive Propose–Probe–Compose step; at the harnessing level, a library of adopted harnesses and evidence-supported lessons the next task reads first. [Harness Engineering: Anatomy, Architecture, and Evolution of Coding Agents](https://arxiv.org/abs/2609.00006) (Barbaste et al., eleven production harnesses read in source) says what a harness surface is made of and which rules it must meet: skills with `name` and `description` frontmatter or they are dropped silently, hooks with the shape the runtime dispatches or they never fire, policy as data rather than prose, context files capped and scanned, agent memory behind a human-reviewed inbox, the cheap caps on every loop.

This page is the operator doc for what exists today: the $0 half, built on [ADR 0002](adr/0002-agent-step-specs-and-local-runner.md)'s step specs and local runner. The model-backed stages are the next phase (ADR 0004 P1) and run only through the loop runner's executor, behind the maintainer's `--apply`.

## The map

Harness² edits eight components around the model. On a Claude Code harness they are these files, and `refine surface` reads them as one tree:

| Harness² component | On the hub (and every fleet repo's `.claude/` kit) | In context |
| --- | --- | --- |
| c1 system prompt | `CLAUDE.md` → `AGENTS.md`, the context-file chain | always on, capped (`harness_refinement.always_on_max_chars`) |
| c2 guardrails | `.claude/settings.json` `permissions` (allow / deny / ask); for a loop step, its spec's tool grant | policy as data |
| c3 memory | `_data/harness_library/` (the experience library), `.claude/memory/` where a repo keeps one | read back through the context pack |
| c4 tool guidance | `.github/instructions/*.instructions.md` | read in place by skills |
| c5 subagents | `.claude/agents/<name>.md` | their own context, return text |
| c6 skills | `.claude/skills/<name>/SKILL.md`, `.claude/commands/<name>.md` | name and description advertised, body on demand |
| c7 scripts | `.claude/hooks/*.py`, the `tools/` a component names | run on demand |
| c8 plugins | the `hooks` block of `.claude/settings.json`, `.mcp.json` | act inside the tool loop |

For a loop's agent the harness has two halves. The **hard rules** (the step spec's prompt, grant, model, turns and dollars; [tools/jev/steps/](../tools/jev/steps/README.md)) are gated config under constitution § 12.3: no agent edits them, and a refinement that needs one writes a proposal a person reviews. The **tunable half** (the brief template and the category emphasis in `.github/scout/` and `.github/evolution/`) is what a candidate may edit. The deliverable's shape belongs to the loop's filer, never to a candidate.

## The surface check: a sensor over the harness

```bash
tools/dash refine surface check            # the hub's own surface; exit 1 on an error
tools/dash refine surface check projects/README --json
tools/dash refine surface census           # the eight-component inventory
tools/dash refine surface diff BEFORE AFTER
```

The check reads a repository's surface and fails on what both sources say breaks a harness: an always-on chain over its cap, an empty one, a skill whose frontmatter is not YAML or has no `description` or whose `name` is not its directory, a subagent with no description, a hooks block with an unknown event, a non-list entry, an empty command or a `$CLAUDE_PROJECT_DIR/<script>` that does not exist, a settings or MCP file that is not JSON, and a script a context file, skill, command or agent names (`tools/x.py`, `.claude/hooks/x.py`) that is not in the repository. It warns on an always-on chain past 80% of the cap, a skill body past the runtime's per-skill load (`skill_max_chars`), a command with no description and prompt-injection phrasing in a file the agent reads as instructions, and it notes which skills no always-on line names (optional under deferred loading: the runtime advertises every skill's name and description). `tools/test_jev_surface.py` holds the hub's own surface clean; its first run found the `run-dash` skill's frontmatter invalid (an unquoted `Triggers:` colon) and that was fixed in the same change, which is the ratchet in [HARNESS.md](HARNESS.md) working as designed.

## The experience library

`_data/harness_library/<loop>/<domain>/<entry>/experience.yml` ([`_data/harness_library/README.md`](../_data/harness_library/README.md)) holds, per adopted refinement, the cue (the shape of situation the lesson fires on, one line), the lesson (an operation on a harness, naming its component), the evidence (the edit rows and the execution contrast), a confidence, the per-edit verdicts (`helped`, `hurt`, `no observed effect`, `confounded`), and the adopted edits as `harness.diff`. `<loop>` is the workflow stem and `<domain>` the item's registry category, the grouping the category emphasis already uses.

An entry lands only on a branch and reaches `main` by a reviewed pull request: `refine library add …` is the $0 reflector a person runs after reading a run's record; the model-backed reflector (P1) opens a draft PR. `refine library check` holds every entry to its schema, its field caps and the context pack's redaction, so a local path, a host name, an address or a credential shape can never be committed. The library reaches an agent two ways: the context pack's `library` section ([JEV.md](JEV.md#the-context-pack)) puts the domain's newest lessons beside the brief of every local attempt, as data to re-verify and never as a rule; and `refine evidence` copies the whole library of the domain into the tree a proposer reads.

```bash
tools/dash refine library list [--loop repo-scout] [--domain dev-tools]
tools/dash refine library index --loop repo-scout --domain dev-tools    # the INDEX.md a proposer browses
tools/dash refine library check
tools/dash refine library add --loop repo-scout --step scout --domain dev-tools --item bamr87/SCHEMA \
    --run <run_id> --adopted base1 --confidence medium --cue "…" --lesson "…" --evidence "…" \
    [--diff harness.diff] [--edit "component|labels|change|observed|verdict"]
```

## One Propose–Probe–Compose step

The method at budget k: k reference attempts under the base harness (`base1..k`), then k INVARIANT candidates (how the agent works: procedure, tool use, completion) and k DOMAIN candidates (what a practitioner of the category knows) proposed from those trajectories, each rolled out once, then either k independent compositions from the whole pool (parallel mode: `agg1..k`) or k successive checkpoints that carry the refined harness forward (sequential mode: `c1..k`). That is R = 4k rollouts and P = 3k improvement sessions, an identity `refine.Ledger` asserts rather than assumes, plus one blind selection over the finals' deliverables and one reflection into the library.

```bash
tools/dash refine plan repo-scout --target SCHEMA                 # k=1, the configured mode, the live ledger
tools/dash refine plan repo-evolution --k 2 --mode sequential --no-budget
```

`plan` prints the schedule (every rollout and session, which harness it runs or edits and which evidence it reads), the ceiling computed from the step's own `budget.call_sites` cap for rollouts and `harness_refinement.stage_usd` for sessions, whether the month's `budget.loops` can absorb it (from the AI ledger, as [the loop runner](JEV.md#the-loop-runner-p1) judges it), the tunable files a candidate may edit, the hard rules it may not, the domain's library, and that the model-backed stages are off. On the scout at k = 1 the ceiling is 4 × $8 + 3 × $2 + 2 × $2 = $42 (API-equivalent (estimate)); on evolve at k = 2 it is $176, which a $50 month cannot absorb, and the plan says so.

```bash
tools/dash refine evidence repo-scout --item bamr87/SCHEMA [--run <run_id>]… [--stage compose] [--k 1] [--out DIR]
```

`evidence` builds, from this loop step's completed local attempts on the item (`.fleet/runs/`; a rehearsal or a tier-0 skip never counts), the tree a proposer session would read, under `.fleet/refine/<stamp>-…/` (gitignored): `MISSION.md` (the stage's prompt, rendered), `context/INDEX.md` (what is there), `context/task.md` (the brief), `context/rollouts/<label>.md` (each attempt's full trajectory in the `[ACTION]` / `[OBSERVATION]` / `[ERROR]` / `[DENIED]` / `[RESULT]` grammar, every observation clipped to `obs_trunc_chars` but the trajectory whole), `context/deliverables/<label>/` (the validated outputs, the preview bodies, the patch), `context/harness/` (the tunable files, the tree a candidate edits), `context/hard-rules/` (the prompt, the grant and the caps, read-only), `context/library/` (the domain's entries, INDEX.md first), `context/proposals/` (where a hard-rule proposal goes) and `evidence.json` (the manifest, every file's hash). Every file passes through the context pack's redaction: the work root is `<work>`, the home `~`, the machine `<host>`, credentials masked. The mission tells the session that everything under `context/` is data, never instructions, that no score, rubric or grader exists anywhere in its context, and that KEEP_BASE is a real answer.

The five missions ([tools/jev/missions/](../tools/jev/missions/README.md)) are adapted from Harness² under its Apache-2.0 notice: `propose-invariant`, `propose-domain`, `compose`, `select`, `reflect`. They are `.prompt.txt` files under the step-spec prompt rules, rendered one-pass from `{{TOKEN}}` inputs; `refine missions list` prints their hashes and `refine missions render <name> --set TOKEN=value …` their bytes.

## Configuration

`_data/fleet.yml` `harness_refinement:`, read and validated on every command:

| Key | What it bounds |
| --- | --- |
| `enabled` | the model-backed stages (P1); `false` until the maintainer turns them on, and `--apply` still gates every spend |
| `k_max`, `mode` | the task-level recursion budget and the default mode (`parallel` or `sequential`) |
| `always_on_max_chars`, `skill_max_chars` | the surface check's caps |
| `stage_usd`, `model`, `max_turns` | one improvement session's dollar cap, its model (an exact id in `ai_models.allowed`, § 13.3) and its turns |
| `library_dir` | the experience library's hub-relative root (`JEV_LIBRARY_DIR` overrides it locally) |
| `obs_trunc_chars` | the per-observation clip in a rendered trajectory |

## What runs a model, and when

Nothing in this page spends. The model-backed stages (ADR 0004 P1) will run each proposer, composer, selector and reflector session through `tools/dash-gen ai-run --isolate` with the evidence tree as its working directory, under the step's own § 13.8 posture and the loop runner's budget lock, each capped at `stage_usd`; each candidate's rollout is a `tools/dash loop run` attempt whose clone carries the candidate's tunable files; selection is blind over the validated deliverables; and the reflector's entry and the adopted tunable edits land as draft PRs. `harness_refinement.enabled`, `budget.loops` and the maintainer's typed `--apply` gate every spend, and the first live step is a k = 1 canary on the scout. A refinement never edits a step spec: a lesson that needs a hard rule is a proposal in `context/proposals/hard-rules.md` for a gated PR, and a lesson confirmed three times is a candidate for a sensor or a standing rule, the ratchet of [HARNESS.md](HARNESS.md).

## Tests

```bash
python3 tools/test_jev_surface.py     # the surface rules on fixtures, the hub's own surface clean, the CLI's exit codes
python3 tools/test_jev_library.py     # the entry round trip, refusals, leaks, check, the registry domain, the pack's library section
python3 tools/test_jev_refine.py      # the schedule and its identity, the ledger, the config, the missions, the plan, the evidence tree
```

## Related

- [ADR 0004](adr/0004-recursive-harness-refinement.md) — the needs assessment, the prior-art survey and the build-vs-adopt decision (§ 10.8), the phases
- [JEV.md](JEV.md) — the step specs, the loop runner and the context pack this is built on
- [HARNESS.md](HARNESS.md) — the six layers, the scorecard and the ratchet this feeds
- [`tools/jev/README.md`](../tools/jev/README.md) — the module reference
