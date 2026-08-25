---
schema: '0.1'
coverage: listed
---

# SCHEMA — {{directory_name}}

> {{One sentence: what this directory is for. If you cannot write this sentence, the directory should not exist.}}

## Conventions

- {{Only what this level defines or OVERRIDES. Ancestors' conventions inherit automatically — do not repeat them.}}

## Structure

| entry | kind | purpose | rules |
| --- | --- | --- | --- |
| {{`name/`}} | dir | {{why it exists}} | {{required \| terminal \| generated}} |
| {{`name.ext`}} | file | {{why it exists}} | {{required}} |
| {{`*.ext`}} | pattern | {{naming rule + what one of these is}} |  |

## Placement

- {{New X}} → {{`where/`}}
- Anything unrouted → propose an entry in this table first, then create it.

## Forbidden

- {{What must never appear or happen here.}}

<!--
Propagation checklist (delete after filling in):
[ ] Registered this directory in the PARENT's Structure table
[ ] Replaced every {{placeholder}}
[ ] `schema_lint.py check` passes from repo root
-->
