---
description: Run the hub's own gates — drift, the SCHEMA pyramid, the workflow lint, the fleet graph, the harness surface and the fixture tests ($0)
argument-hint: '[all | drift | schema | workflows | graph | surface | tests]'
disable-model-invocation: true
allowed-tools: Bash(tools/dash ops run drift *), Bash(tools/dash ops run schema-lint *), Bash(tools/dash ops run workflows-lint *), Bash(tools/dash ops run graph-check *), Bash(tools/dash ops run refine-surface *), Bash(tools/dash ops run tests *)
metadata:
  ops: [drift, schema-lint, workflows-lint, graph-check, refine-surface, tests]
---

# /harness:gates — the hub's gates, one or all

Gate: $ARGUMENTS (blank means `all`)

| Gate | Runs |
| --- | --- |
| `drift` | `tools/dash ops run drift`: registry and `.gitmodules` parity, generated files, SCHEMA, action manifests |
| `schema` | `tools/dash ops run schema-lint`: the SCHEMA.md pyramid; warnings fail too |
| `workflows` | `tools/dash ops run workflows-lint`: the hub's workflows and actions against the README standards and the standing rules |
| `graph` | `tools/dash ops run graph-check`: the fleet graph's checks; only an error fails |
| `surface` | `tools/dash ops run refine-surface`: the harness surface (context files, skills, slash commands, agents, hooks, MCP) |
| `tests` | `tools/dash ops run tests`: every dash-gen and console fixture test on a bare interpreter (minutes) |

`all` runs the first five, then `tests`. Every gate is $0 and local. Report each gate as pass or fail; for a failure, the finding and the fix it names (the `drift-report` skill explains drift in detail). On macOS a drift run that marks every `action.yml` as failed with a syntax error is the stock bash 3.2, not the change: say so and point at the CI run.

## Rules every /harness:, /loops: and /console: command follows

- **Front door only.** A stage runs through `tools/dash ops run <op> key=value …`, the console's operation allowlist: the same validation and confirm gate as the Operations page, and when the console is running for this checkout the job shows there too. The only other commands are the read-only `tools/dash` ones this file names. No second implementation, no ad-hoc script.
- **Ask before a write or spend.** Exit 3 means the call writes to GitHub, destroys local data or spends Claude budget. Show the person what `--explain` prints, ask with AskUserQuestion, and add `--confirm` only after a yes. That yes covers that one call, not another stage, target or run id.
- **Run each command plainly.** One command per call, exactly as written here, with no pipe, redirect, `;` or `&&`: a pre-approved pattern matches only the plain command, so anything added is prompted for or refused. The output is short enough to read whole.
- **Say what happened.** Name the operation run (and the console job id when the console ran it), what it found, and the next stage. Never report a stage you did not run. Claude cost is an API-equivalent estimate.
