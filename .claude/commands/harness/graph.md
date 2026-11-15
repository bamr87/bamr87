---
description: The fleet graph — repos, workflows, loops, switches, agents, sources, features and the operator surfaces as one model; check it, or ask what depends on a node ($0, read-only)
argument-hint: '[check | summary | find <text> | show <node> | impact <node> | lineage <node> | path <a> <b>]'
disable-model-invocation: true
allowed-tools: Bash(tools/dash ops run graph-check *), Bash(tools/dash graph *)
metadata:
  ops: [graph-check]
---

# /harness:graph — one model of the whole harness

Query: $ARGUMENTS (blank means `check`)

- `check`: `tools/dash ops run graph-check`, the findings: dangling edges (an error), sources nobody writes, scheduled workflows with no switch entry, and the surface-parity notes (an API route no MCP tool reaches, a `dash` command no console operation runs).
- `summary`, `find <text>`, `show <node>`, `impact <node>`, `lineage <node>`, `path <a> <b>`: `tools/dash graph <query>`. A node is `<kind>:<key>` or any unique tail of one; `find` lists them.

Everything is read from the checkout: no network, no model, no write (docs/FLEET-GRAPH.md). For `impact`, say what would break or need regenerating if the node changed; for `check`, group the findings by rule with the fix the rule names.

## Rules every /harness:, /loops: and /console: command follows

- **Front door only.** A stage runs through `tools/dash ops run <op> key=value …`, the console's operation allowlist: the same validation and confirm gate as the Operations page, and when the console is running for this checkout the job shows there too. The only other commands are the read-only `tools/dash` ones this file names. No second implementation, no ad-hoc script.
- **Ask before a write or spend.** Exit 3 means the call writes to GitHub, destroys local data or spends Claude budget. Show the person what `--explain` prints, ask with AskUserQuestion, and add `--confirm` only after a yes. That yes covers that one call, not another stage, target or run id.
- **Run each command plainly.** One command per call, exactly as written here, with no pipe, redirect, `;` or `&&`: a pre-approved pattern matches only the plain command, so anything added is prompted for or refused. The output is short enough to read whole.
- **Say what happened.** Name the operation run (and the console job id when the console ran it), what it found, and the next stage. Never report a stage you did not run. Claude cost is an API-equivalent estimate.
