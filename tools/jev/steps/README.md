# tools/jev/steps/ — loop step specs

> One spec per agent step a loop runs: the hard-rules prompt, its inputs, the tool allowlist, the wall clock, the workspace contract and the risk tags, in one reviewed file pair that CI and the local loop engine render the same bytes from.

This is JEV capability two ([bamr87/bamr87#485](https://github.com/bamr87/bamr87/issues/485), epic [#484](https://github.com/bamr87/bamr87/issues/484)). The decision, the survey of what was considered instead, and the governance trade-off are in [ADR 0002](../../../docs/adr/0002-agent-step-specs-and-local-runner.md); the loader is [`../spec.py`](../spec.py); the operator doc is [`docs/JEV.md`](../../../docs/JEV.md#capability-two--loop-step-specs).

## Layout

`steps/<loop>/<step>.yml` + `steps/<loop>/<step>.prompt.txt`. `<loop>` is the workflow's file stem (`repo-scout` for `.github/workflows/repo-scout.yml`); the console's `LOOPS` id (`repo_scout`) joins it through its `workflow` field. `<step>` is the job the agent step runs in.

## Review gate

Any change under `tools/jev/steps/**` is security-sensitive config under constitution § 12.3: the pull request is gated (the `needs-amr` label and *Needs Amr* on the Fleet project, § 12.4 — the label is not created yet, HUB-045), so no agent merges it under § 12.2, and the maintainer's review is the control that decides it.

## The keys (`schema: loop-step/v1`)

| Key | What it holds |
| --- | --- |
| `loop`, `step` | equal to the directory and the file stem |
| `call_site` | `<workflow>.yml:<job>`, the key of `_data/fleet.yml` `budget.call_sites` — the dollar cap |
| `step_id` | the `id:` of the `anthropics/claude-code-action` step in that job |
| `prompt` | `<step>.prompt.txt`, beside the spec |
| `inputs` | `{{TOKEN}}` → the caller's row key that fills it (for scout, a `plan.json` `include[]` key) |
| `model_from`, `max_turns_from` | dotted `_data/fleet.yml` keys; the model must resolve to an exact id in `ai_models.allowed` (constitution § 13.3) |
| `timeout_minutes` | the job's `timeout-minutes`, and the local engine's wall clock |
| `allowed_tools` | the `--allowedTools` grant, in order |
| `workspace` | `cwd`, `brief_dir`, `outputs`, `github_credential` — what a runner must reproduce; optional `exceptions` names a gap CI still leaves open (`app-token`, `setting-sources`) with the reason, which `steps check` reports instead of hiding |
| `risk` (optional) | per action: `what`, `tags` from reversible / external / money, `tier` low / medium / high; an irreversible, external or money action starts high (§ 13.6) |
| `evals` (optional) | the eval set's hub-relative path, or `null` during the § 13.1 grace period |
| `local` (optional) | how `python3 -m tools.jev loop` runs the step on a workstation: `adapter` (a key of `tools/jev/adapters` `REGISTRY`), `switch {config, variable, default}` (a `_data/fleet.yml` bool honoured on every run, and the repo variable a `--scheduled` run reads; `steps check` holds it equal to the workflow's gating `if:` — default `'off'` needs `vars.<VARIABLE> == 'true'`, `'on'` needs `!= 'false'`), `planner {argv, flags}` and `publish {argv, apply_flag, risk}` (`tools/dash-gen` argv templates with `{plan_dir}` `{nwo}` `{name}` `{branch}` `{item_dir}` `{bodies_dir}` (the publish phase's own directory) `{validated}` (the adapter's validated file) `{run_ref}` placeholders, filled in one pass; `risk` names the `risk.<action>` whose tier gates the write) and `on_budget_hit` (`discard`). CI ignores it ([docs/JEV.md](../../../docs/JEV.md#the-loop-runner-p1)) |

`loop-step/v1` evolves the way `harness-registry/v1` does: an optional key added together with its loader support keeps v1; removing or renaming a key, making an optional key required, or changing a key's meaning bumps to `loop-step/v2`. The loader stays strict — an older loader refuses a newer spec rather than ignoring what it does not know — and every consumer reads specs through `tools/jev/spec.py`, never by parsing the YAML itself.

A spec carries **no literal model, turn cap or dollar cap**: those already live in `_data/fleet.yml`, and the spec references them (AGENTS.md, central configuration). The workflow still carries its caps as literals in `claude_args`, because `harness_registry`, the workflow atlas and `test_ai_budget.py` read literals; `python3 -m tools.jev steps check` holds every one of them equal to what the spec resolves to.

## Placeholders

A prompt uses `{{UPPER_SNAKE}}` tokens, the same syntax the brief templates use, and every token is filled by the caller. Rendering is a single pass: a value is never scanned again for tokens, an undeclared, missing or empty value is refused, and so is a value with a line break. A prompt never contains `${{` — Actions does not re-evaluate an expression's result, so one would reach the agent verbatim.

## Why `.prompt.txt`

The fleet's Markdown gates rewrite `*.md` to one paragraph per line; a `.md` prompt would be reflowed from 60 lines to 28 and pushed back by CI. `.txt` is outside those gates. The whitespace hooks still touch it, so the loader requires the state they produce — LF only, no trailing whitespace, exactly one final newline — and `.gitattributes` pins `eol=lf`.

## Who renders it

For scout, the plan job: `dash-gen scout` (`repo_scout.build_plan`) loads `repo-scout/scout.yml` once, renders the prompt for every leg from that leg's `plan.json` row (`include[].prompt`, the row's last key), and the workflow's agent step reads `prompt: ${{ matrix.prompt }}`. The plan fails before any spend when the spec does not load or a leg has no prompt. Locally, `python3 -m tools.jev steps render <loop> <step> --set TOKEN=value …` prints the same bytes, and the loop runner (`python3 -m tools.jev loop`) renders from the same spec and refuses a plan row whose prompt differs from its own render by a byte. While a workflow still carries its prompt inline, `steps check` accepts that inline text only when it is byte-equal to the spec rendered with the matrix expressions (`${{ matrix.<key> }}`), so a move is proven before the workflow changes.

## Changing a prompt, a grant or a cap

1. Edit the `.prompt.txt` or the spec. A prompt that orders a tool by name ("with the Read tool") needs that tool in `allowed_tools` — the check fails otherwise (bamr87/bamr87#89, where a prompt ordered a Read it was never granted).
2. A cap or model change is made in `_data/fleet.yml`, and the workflow's literal is changed to match.
3. Set the agent step's `env: JEV_STEP_SHA256` in the workflow to the spec pair's new content hash (`steps check` prints it). Any edit to `<step>.yml` or `<step>.prompt.txt` therefore touches the workflow file, which keeps GitHub's `workflow`-scope barrier over the hard rules ([ADR 0002](../../../docs/adr/0002-agent-step-specs-and-local-runner.md#governance-trade-off)).
4. Update the pinned hashes in `tools/test_jev_spec.py` (and `.github/scripts/dash-gen/test_scout.py` for scout) in the same PR. That speed bump is deliberate, but it is not a barrier: the same PR re-pins them.
5. Run `python3 -m tools.jev steps check` and `python3 tools/test_jev_spec.py`.
