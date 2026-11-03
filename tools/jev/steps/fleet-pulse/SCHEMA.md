---
schema: "0.1"
coverage: listed
---

# SCHEMA — tools/jev/steps/fleet-pulse

> The step spec of the fleet doctor's agent: job `doctor`, step `fix` of `.github/workflows/fleet-pulse.yml`, a prompt with no caller-filled part that the workflow carries inline byte-equal and the local loop runner renders from the spec (`python3 -m tools.jev steps render fleet-pulse doctor`).

## Conventions

- The two files change together: an edit to either updates the `fix` step's `JEV_STEP_SHA256` in `.github/workflows/fleet-pulse.yml`, a prompt edit also updates the workflow's inline copy (parity holds them byte-equal) and the pinned hash in `tools/test_jev_spec.py`, in the same PR.
- The prompt reads its work order by a fixed name in the checkout root (`workspace.brief_file`); the brief directory `.doctor/` is the engine's own (TMPDIR, the context pack).

## Structure

| entry | kind | purpose | rules |
| --- | --- | --- | --- |
| `doctor.yml` | file | The spec: `inputs: {}`, `fleet.yml` references for model/turns/dollars (`remediation.*`), the allowlist, timeout, the `cwd: hub` / `brief_file` / `fleet-write` workspace contract, risk, and the `local:` block (`remediate` planner, `doctor-file` filer, `harvest: patch`) | required |
| `doctor.prompt.txt` | file | The doctor's hard-rules prompt, byte-pinned to the inline prompt it replaced; LF, one final newline, no token | required |

## Placement

- Anything unrouted → propose an entry in this table first, then create it.

## Forbidden

- No other file here: the work order is the planner's output (`dash-gen remediate`), never committed, and rendered prompts are never committed.
