---
schema: "0.1"
coverage: listed
---

# SCHEMA — _data/voices

> THE fleet voice model `voices/v1`: the canonical voices, styles, personas, topics and per-site assignment that lifehacker.dev and zer0-CMS read (constitution § 23 rule 6), with its JSON Schema beside it.

## Conventions

- Admin-edited by pull request, or in the console's Voices editor (`/voices`), which files the edit back here as a draft PR through `tools/voices.py pr` — never to a database copy (constitution § 23 rule 7, tools/console/README.md).
- Keep the canonical layout (`python3 tools/voices.py render` reproduces the file byte for byte), so an editor's diff is only the edit.
- `python3 tools/voices.py check` is the gate (schema, enums, references, and assignment rules that can never be reached: one after the `default` rule, or one whose `activity` or `repos` is an empty list — leave the key out to match anything); `--against <file>` reports drift in a consumer's copy.

## Structure

| entry | kind | purpose | rules |
| --- | --- | --- | --- |
| `voices.yml` | file | The canonical voice config (`schema: voices/v1`): defaults, per-site profile, personas and assignment rules | required |
| `voices.schema.json` | file | JSON Schema for `voices.yml`, read structurally by `tools/voices.py` | required |

## Placement

- A new site, persona or assignment rule → `voices.yml`; a new field → `voices.schema.json` first, then `tools/voices.py`.
- Anything unrouted → propose an entry in this table first, then create it.

## Forbidden

- Secrets, tokens, credentials or private values of any kind.
- A second copy of the voice config elsewhere in the hub.
