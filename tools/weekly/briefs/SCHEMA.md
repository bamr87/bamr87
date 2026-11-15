---
schema: "0.1"
coverage: listed
---

# SCHEMA — tools/weekly/briefs

> The weekly routine's standing briefs: what the close-out agent is told, and what a Grok bot runs for each stage (data only; rendered by `../harness.py`).

## Conventions

- `claude-<stage>.prompt.txt` is a headless Claude Code session's prompt: UTF-8, LF, exactly one final newline, no trailing whitespace, no `${{`, never `.md` (the prose gates reflow Markdown). Its `{{TOKEN}}`s are exactly the ones `harness.review` fills.
- `grok-<stage>.md` is a Grok bot's brief for a stage, one paragraph per line. Its tokens are `{{WEEK}}` and `{{HANDOFF_LABEL}}`. It names what the bot reads, what it does and the one place it writes, and it restates the § 26 boundary.
- `tools/test_weekly_harness.py` holds every file to these rules and fails on a token nothing fills.

## Structure

| entry | kind | purpose | rules |
| --- | --- | --- | --- |
| `claude-close.prompt.txt` | file | Friday's close-out agent: rule on the stale items, as proposals only | required |
| `grok-close.md` | file | Friday's Grok half: the direction close-out | required |
| `grok-prepare.md` | file | Saturday's Grok half: direction for the week and the handoffs | required |
| `grok-plan.md` | file | Sunday's Grok half: the plan sign-off and Monday's asks | required |

## Placement

- New stage → its `grok-<stage>.md` here and the stage in `harness.STAGES`.
- New model session → its `claude-<stage>.prompt.txt` here, filled in `../harness.py`.

## Forbidden

- No `${{ }}` expression, no secret, no rendered brief committed here.
- No brief that tells a Grok bot to open an implementation pull request, push a product commit, apply a console plan or merge (constitution § 26), and none that lets the close-out agent act on its own proposals.
