---
schema: "0.1"
coverage: listed
---

# SCHEMA — tools/jev/missions

> The five stage prompts of a Propose–Probe–Compose refinement step, one `.prompt.txt` each, loaded and rendered by `../refine.py` under the loop-step prompt rules (data only; adapted from Harness², Apache-2.0).

## Conventions

- A mission is `<stage>.prompt.txt`: UTF-8, LF, exactly one final newline, no trailing whitespace, no `${{`, only the `{{TOKEN}}`s `refine.MISSION_INPUTS` declares for it. Never `.md` (the prose gates reflow Markdown).
- Adding a mission is a code change too: its name in `refine.MISSIONS`, its tokens in `refine.MISSION_INPUTS`, a row here and in README.md, and a case in `tools/test_jev_refine.py`.

## Structure

| entry | kind | purpose | rules |
| --- | --- | --- | --- |
| `README.md` | file | What the missions are, their tokens, the rules they carry and the attribution | required |
| `propose-invariant.prompt.txt` | file | The INV editor's mission | required |
| `propose-domain.prompt.txt` | file | The DOM editor's mission | required |
| `compose.prompt.txt` | file | The composer's mission (parallel aggregation and sequential checkpoints) | required |
| `select.prompt.txt` | file | The blind selector's mission | required |
| `reflect.prompt.txt` | file | The experience reflector's mission | required |

## Placement

- New stage → `<stage>.prompt.txt` here plus its `MISSION_INPUTS` row in `../refine.py`.
- Anything unrouted → propose an entry in this table first, then create it.

## Forbidden

- No `${{ }}` expression, no secret, no `.md` prompt, no rendered mission committed here.
- No mission that names a score, a rubric or a grader, or that lets an agent edit a step spec's hard rules.
