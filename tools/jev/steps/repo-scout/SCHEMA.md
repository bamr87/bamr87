---
schema: "0.1"
coverage: listed
---

# SCHEMA — tools/jev/steps/repo-scout

> The step spec of repo-scout's agent: job `scout`, step `scout` of `.github/workflows/repo-scout.yml`, rendered per matrix leg by the plan job (`dash-gen scout`) and by `python3 -m tools.jev steps render repo-scout scout`.

## Conventions

- The two files change together: an edit to the prompt that names a tool needs that tool in `allowed_tools`, and any edit to either file updates the Scout step's `JEV_STEP_SHA256` in `.github/workflows/repo-scout.yml`, plus (for a prompt edit) the pinned hashes in `tools/test_jev_spec.py` and `.github/scripts/dash-gen/test_scout.py`, in the same PR.

## Structure

| entry | kind | purpose | rules |
| --- | --- | --- | --- |
| `scout.yml` | file | The spec: inputs, `fleet.yml` references for model/turns/dollars, allowlist, timeout, workspace contract, risk, evals | required |
| `scout.prompt.txt` | file | The scout's hard-rules prompt with `{{NWO}}` `{{REPO_NAME}}` `{{BRANCH}}` `{{BRIEF}}` tokens; LF, one final newline, byte-pinned | required |

## Placement

- Anything unrouted → propose an entry in this table first, then create it.

## Forbidden

- No other file here: the tunable brief stays in `.github/scout/`, and rendered prompts are never committed.
