---
schema: "0.1"
coverage: listed
---
# SCHEMA — tools/jev/steps/fanout

> The step specs of the fan-out agent fill: job `agent-fill` of `.github/workflows/fanout.yml`, one spec pair and one claude-code-action step per kit (`fill-standardize`, `fill-schema`), each a prompt with no caller-filled part that the workflow carries inline byte-equal and the local loop runner renders the same bytes from.

## Conventions

- A kit's two files change together: an edit to either updates that kit's step `JEV_STEP_SHA256` in `.github/workflows/fanout.yml`, and a prompt edit also updates the workflow's inline copy (parity holds them byte-equal).
- The prompt is the whole work order (`workspace.no_brief`): no brief is downloaded in CI or placed locally, and the context pack stays off; the brief directory `.fanout/` is the engine's own (TMPDIR).

## Structure

| entry | kind | purpose | rules |
| --- | --- | --- | --- |
| `agent-fill-standardize.yml` | file | The spec for kit `standardize` (step `fill-standardize`): `inputs: {}`, `fleet.yml` references for model/turns/dollars (`agent_fill.*`, `fanout.yml:agent-fill`), the allowlist, timeout, the `cwd: target` / `no_brief` / `none` workspace contract with both action gaps declared, the risk tags and the `local:` block (`fanout_agent_fill`, `dash-gen agent-fill --kit standardize`, `dash-gen agent-fill-file`, `harvest: patch`) | required |
| `agent-fill-standardize.prompt.txt` | file | The standardize kit's brief (fill the CLAUDE.md scaffold), byte-pinned to the heredoc it replaced; LF, one final newline, no token | required |
| `agent-fill-schema.yml` | file | The spec for kit `schema` (step `fill-schema`): the same contract with `--kit schema` | required |
| `agent-fill-schema.prompt.txt` | file | The schema kit's brief (fill the SCHEMA.md scaffold purposes), byte-pinned to the heredoc it replaced; LF, one final newline, no token | required |

## Placement

- A new kit with an agent pass → `agent-fill-<kit>.yml` + `agent-fill-<kit>.prompt.txt` here, a `fill-<kit>` step in `fanout.yml` gated on `inputs.kit`, and a row above.
- Anything unrouted → propose an entry in this table first, then create it.

## Forbidden

- No other file here: the plan is the planner's output (`dash-gen agent-fill`), never committed, and rendered prompts are never committed.
