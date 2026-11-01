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

`sources` lists the hub paths the adapter's behaviour depends on besides `tools/jev/`; the engine records whether they were dirty when a run started, and a later `--apply` refuses a dirty one without `--allow-dirty`.

## repo_scout

[`repo_scout.py`](repo_scout.py) maps `tools/dash-gen scout` (the plan job) and `tools/dash-gen scout-file` (the file job). Tier 0 reuses an attempt whose HEAD and brief are the same, the brief's per-run `Prepared …` line aside. `classify` blocks `--apply` on a row whose open-issue dedupe was unavailable. `validate` withholds any proposal carrying a local path or the host name, flags (never rejects) a proposal citing a sandbox or offline denial, and runs the filer's own rules with `scout-file --offline`. `publish` turns the filer's "filing without the duplicate check" into a blocker, a body `--reviewed-bodies` withheld as not in the reviewed preview into a blocker too (the filing is then `partial`), and its `gh issue create failed` rows into failures, the way CI's file job fails on them.

## Adding one

Write `<name>.py` exposing `ADAPTER`, add it to `REGISTRY`, add a row to [`SCHEMA.md`](SCHEMA.md), write `tools/test_jev_adapter_<name>.py`, and give the step spec a `local:` block.

## Tests

```bash
python3 tools/test_jev_adapter_repo_scout.py   # items from the real offline planner, tier 0, classify, validate, publish, the source guard
```
