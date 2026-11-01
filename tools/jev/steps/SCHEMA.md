---
schema: "0.1"
coverage: listed
---

# SCHEMA — tools/jev/steps

> Loop step specs, JEV capability two: one directory per loop workflow, holding one spec pair per agent step that loop runs — the hard-rules prompt, inputs, allowlist, workspace contract and risk tags, with model, turns and dollars referenced from `_data/fleet.yml` (`tools/jev/spec.py`; ADR 0002).

## Conventions

- A loop directory is named for its workflow's file stem (`repo-scout` for `.github/workflows/repo-scout.yml`); the console's `LOOPS` id joins it through its `workflow` field.
- Data only — no code here. The loader is `../spec.py`; `python3 -m tools.jev steps check` holds every spec equal to its workflow and `_data/fleet.yml`.

## Structure

| entry | kind | purpose | rules |
| --- | --- | --- | --- |
| `README.md` | file | What a step spec is, its keys, the placeholder rule, and how to change a prompt | required |
| `repo-scout/` | dir | The agent step of `.github/workflows/repo-scout.yml` (job `scout`); see its SCHEMA | |

## Placement

- New loop → a `<workflow stem>/` directory with its own `SCHEMA.md`, and a row here.
- New agent step → `<step>.yml` + `<step>.prompt.txt` in its loop's directory, with rows in that directory's `SCHEMA.md`.
- Anything unrouted → propose an entry in this table first, then create it.

## Forbidden

- No `${{ }}` expression in a prompt, no secret or secret value, no `.md` prompt (the prose gates reflow Markdown), and no rendered output committed here.
- No agent merges a change here: any change under `tools/jev/steps/**` is security-sensitive config under constitution § 12.3: the pull request is gated (the `needs-amr` label and *Needs Amr* on the Fleet project, § 12.4 — the label is not created yet, HUB-045), so no agent merges it under § 12.2, and the maintainer's review is the control that decides it.
