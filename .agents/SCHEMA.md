---
schema: '0.1'
coverage: listed
---

# SCHEMA — .agents

> Project agent skills loaded from this worktree. Not a fleet generator output.

## Structure

| entry | kind | purpose | rules |
|---|---|---|---|
| `SCHEMA.md` | file | This contract | required |
| `skills/` | dir | One directory per skill (`SKILL.md` plus any supporting files) | required terminal |

## Placement

- A new skill is a directory under `skills/` with a `SKILL.md`. Do not add a second skills root.

## Forbidden

- No credentials, tokens, or machine-local paths that are not already public.
