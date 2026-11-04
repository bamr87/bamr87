# tools/jev/adapters/ — loop adapters

> One adapter per loop the local loop runner can run: it maps that loop's planner and filer JSON onto the engine's items and verdicts and holds the loop's own decisions, while the engine keeps everything that touches safety.

The engine is [`../loop.py`](../loop.py) (`python3 -m tools.jev loop`, [docs/JEV.md](../../../docs/JEV.md#the-loop-runner-p1)); the decision is [ADR 0002, P1](../../../docs/adr/0002-agent-step-specs-and-local-runner.md#p1--the-headless-executor-and-its--138-posture). A step spec names its adapter with `local.adapter: <name>`, and the loader accepts only a key of `REGISTRY` in [`__init__.py`](__init__.py), so a spec can never make the engine import an arbitrary module.

## What the engine owns, and what an adapter may do

The engine owns the workspace, the argv, the agent's environment, the `--settings` document, sandbox verification, the ledger, the run record, the § 13.6 gate, and running the spec-declared publish argv. An adapter can widen none of these. It maps JSON and makes decisions, reads only the harvested copies of the agent's outputs, and reaches GitHub only through the `execute` the engine hands to `publish`.

## The hooks

| Hook | Default | What it decides |
| --- | --- | --- |
| `items(ctx, plan)` | required | the planner's stdout JSON → `Item`s (key, name, nwo, branch, the row, the brief) plus the skipped and dropped rows (a skipped row carries `key` where it can, so the attempts log has one identity per item); every row carries every `spec.inputs` key, because the engine renders the prompt from it with `spec.values_from` exactly as CI's plan does. Keys are distinct (the engine refuses a repeat) and need not be an nwo: `workspace.item_dirname(key)` names the item's directory. A brief must be a bare file name in the plan directory |
| `reuse_key(ctx, item, head_sha)` | `None` (never reuse) | what makes two attempts identical, for tier 0 |
| `tier0(ctx, item, head_sha)` | reuse an unpublished twin within `REUSE_DAYS`, skip a published one; `--fresh` bypasses | the $0 decision before any workspace exists |
| `classify(ctx, item)` | not blocked | loop-specific blocks, after the engine's own |
| `validate(ctx, item, harvested, outcome)` | every declared output present | whether the harvested outputs are publishable; names the validated copy to publish in `Verdict.publish_file` (the engine's `{validated}`), never the raw output |
| `publish(ctx, item, verdict, execute, *, apply)` | required when the spec declares `local.publish` | parses what the spec's publish argv printed, dry or applied, into rows, blockers and per-item failures; its bodies are in `ctx.bodies_dir(item, apply=apply)` (the spec's `{bodies_dir}`: the preview's and the apply's differ) |
| `recheck(ctx, item)` | `None` | a live re-read just before an applied write; a reason cancels the filing |
| `context_request(ctx, item)` | `ContextRequest(item.nwo, item.name)`, no queries | what the host-built context pack is for (`tools/jev/context.py`): the repository, its checkout name and up to three code-index queries of one line and at most 300 characters each (`ContextRequest` refuses more); `None` places no pack for the item. The engine sets the window from the spec's `local.context.days` |

`sources` lists the hub paths the adapter's behaviour depends on besides `tools/jev/`; the engine records whether they were dirty when a run started, and a later `--apply` refuses a dirty one without `--allow-dirty`.

## repo_scout

[`repo_scout.py`](repo_scout.py) maps `tools/dash-gen scout` (the plan job) and `tools/dash-gen scout-file` (the file job). Tier 0 reuses an attempt whose HEAD and brief are the same, the brief's per-run `Prepared …` line aside; the key is always computed from the plan's brief, never from the clone's copy that carries the context pack's pointer. `context_request` turns the brief into the pack's code-index queries: the registry description, the category and stack, then the operator focus or, with none, the first conformance gap, each read only inside its own `## ` section of the brief and clipped to one line of 300 characters. `classify` blocks `--apply` on a row whose open-issue dedupe was unavailable. `validate` withholds any proposal carrying a local path or the host name, flags (never rejects) a proposal citing a sandbox or offline denial, and runs the filer's own rules with `scout-file --offline`. `publish` turns the filer's "filing without the duplicate check" into a blocker, a body `--reviewed-bodies` withheld as not in the reviewed preview into a blocker too (the filing is then `partial`), and its `gh issue create failed` rows into failures, the way CI's file job fails on them.

## fleet_pulse_doctor

[`fleet_pulse_doctor.py`](fleet_pulse_doctor.py) maps `tools/dash-gen remediate --plan-dir` (CI's remediation queue, split into one item per candidate, each brief carrying the evidence Step 2 of the doctor's prompt would read with `gh` — fetched by the planner, because a local attempt's shell has no network) and `tools/dash-gen doctor-file` (a complete dry run; its `--apply` is refused naming bamr87/bamr87#488 until the publish step lands). Every item's clone is the HUB (`workspace.cwd: hub`), as CI's doctor works in the hub checkout; the candidate's own repository is the row's `repo`. The brief is placed at the clone root under the prompt's fixed name (`workspace.brief_file: remediation-workorder.md`). The step declares no outputs: with `local.harvest: patch` the engine diffs the clone against the fresh HEAD (the agent's own branch and commits are inside the tamper allowance) and hands the adapter `changes.patch`, and `validate` pairs it with the filing the agent attempted — its `gh pr create` or `gh issue create` call, refused by the permission layer and read back from the trace — into one document (`doctor.validated.json`, kind `pr` or `issue`, the MARKER line held first because CI dedupes on it, a derived `fix/fleet-doctor-<slug>` branch when the session named none). A hub fix with no filing call is synthesised from the result text and flagged; a submodule candidate yields only the issue the agent fell back to (Step 3c), never a hub PR for a submodule file; nothing to file is rejected. Tier 0 reuses an attempt on the same HEAD and brief, the signal stamps and the evidence capture time aside; `classify` blocks `--apply` on a row whose open-marker dedupe was unavailable; `recheck` re-runs the planner for the one key before an applied write. `context_request` queries the code index for the workflow path with its signals and the workflow's name.

## repo_evolution_evolve

[`repo_evolution_evolve.py`](repo_evolution_evolve.py) maps `tools/dash-gen targets` (CI's plan job: the opted-in submodules, one open pass per repository, the cap, one brief per target, every row carrying the spec's render; `--offline` marks the dedupe unavailable) and `tools/dash-gen evolve-file` (a complete dry run; its `--apply` is refused naming bamr87/bamr87#488). The target repository is the checkout (`workspace.cwd: target`) and the agent's edits are the output (`local.harvest: patch`): `validate` drops the lockfiles CI's publish step drops, takes the agent's final message as the draft PR body behind the brief's marker line with CI's footer, names the branch `<prefix>/<yyyymmdd>-local-<run>` and the publish remote `https://github.com/<nwo>` (#220), withholds a body or patch carrying a local path or the host name, flags a refused publishing command, and turns an empty pass into `kind: none` — valid, filing nothing, as CI's "No changes" summary line. A budget hit (`local.on_budget_hit: publish-flagged`) is previewed flagged PARTIAL with CI's warning block first. Tier 0 reuses an attempt whose HEAD and brief are the same, the brief's `Prepared …` stamp aside; `context_request` asks the code index for the operator's focus and the repository's category.
## fanout_agent_fill

[`fanout_agent_fill.py`](fanout_agent_fill.py) maps `tools/dash-gen agent-fill --kit <kit>` (the fan-out's own target list — bamr87-owned, non-archived registry repos — one item per repository at the kit's PR branch, the branch and the `(Claude agent pass)` dedupe checked online, no brief: the prompt is the whole work order) and `tools/dash-gen agent-fill-file` (a complete dry run of CI's push step: the exact patch and commit message; its `--apply` is refused until #488's publish step lands). Tier 0 reuses an attempt on the same HEAD for the same kit. Classify blocks a target whose kit branch is missing or already filled, and `--apply` without a live dedupe. Validate holds the engine's patch (`local.harvest: patch`) to the kit's brief — only `CLAUDE.md` for `standardize`, only `SCHEMA.md` files for `schema`, anything else withholds the whole attempt — refuses an empty patch and anything carrying this machine's paths or host name, writes `agent-fill.validated.json` + `agent-fill.patch`, and runs the filer's offline rules on the copy. The same adapter serves both kit specs: the step name says which kit, and a plan row of another kit is refused.

## Adding one

Write `<name>.py` exposing `ADAPTER`, add it to `REGISTRY`, add a row to [`SCHEMA.md`](SCHEMA.md), write `tools/test_jev_adapter_<name>.py`, and give the step spec a `local:` block.

## Tests

```bash
python3 tools/test_jev_adapter_repo_scout.py   # items from the real offline planner, tier 0, classify, validate, publish, the context queries, the source guard
python3 tools/test_jev_adapter_fleet_pulse_doctor.py   # the doctor: the real offline planner, the patch + filing document, the filer's dry run and its refused apply
python3 tools/test_jev_adapter_repo_evolution_evolve.py   # evolve: the real offline planner, the patch + report document (lockfile drop, PARTIAL, #220 remote), the filer's dry run and its refused apply
python3 tools/test_jev_adapter_fanout_agent_fill.py   # the agent fill: the real offline planner (no brief), the patch held to the kit's brief, the filer's dry run and its refused apply
```
