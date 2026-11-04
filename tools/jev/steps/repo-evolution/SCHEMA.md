---
schema: "0.1"
coverage: listed
---

# SCHEMA — tools/jev/steps/repo-evolution

> The step spec of the evolution agent: job `evolve`, step `evolve` of `.github/workflows/repo-evolution.yml`, a prompt with four matrix tokens that the workflow carries inline as matrix expressions, byte-equal, and the local loop runner renders from the spec (`python3 -m tools.jev steps render repo-evolution evolve --set NWO=… --set REPO_NAME=… --set BRANCH=… --set BRIEF=…`).

## Conventions

- The two files change together: an edit to either updates the `evolve` step's `JEV_STEP_SHA256` in `.github/workflows/repo-evolution.yml`, a prompt edit also updates the workflow's inline copy (parity holds them byte-equal) and the pinned hashes in `tools/test_jev_spec.py`, in the same PR.
- The target repository is the checkout (`workspace.cwd: target`); the brief directory `.evolution/` holds the planner's brief and, locally, the engine's own files (TMPDIR, the context pack).

## Structure

| entry | kind | purpose | rules |
| --- | --- | --- | --- |
| `evolve.yml` | file | The spec: the four `{{TOKEN}}` inputs (`NWO`, `REPO_NAME`, `BRANCH`, `BRIEF`), `fleet.yml` references for model/turns/dollars (`evolution.*`), the allowlist, timeout, the `cwd: target` / `fleet-read` workspace contract, risk, and the `local:` block (`targets` planner, `evolve-file` filer, `harvest: patch`, `on_budget_hit: publish-flagged`) | required |
| `evolve.prompt.txt` | file | The evolution agent's hard-rules prompt, byte-pinned to the inline prompt it replaced (rendered with the matrix expressions); LF, one final newline | required |

## Placement

- Anything unrouted → propose an entry in this table first, then create it.

## Forbidden

- No other file here: the briefs are the planner's output (`dash-gen targets`), never committed, and rendered prompts are never committed.
