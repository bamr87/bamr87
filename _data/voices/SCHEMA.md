---
schema: "0.1"
coverage: listed
---

# SCHEMA — _data/voices

> THE fleet voice model `voices/v1`: the canonical voices, styles, personas, topics and per-site assignment that lifehacker.dev and zer0-CMS read (constitution § 23 rule 6), with its JSON Schema beside it.

## Conventions

- Admin-edited by pull request; the console's Voices editor writes back here as a PR, never to a database copy (constitution § 23 rule 7).
- `python3 tools/voices.py check` is the gate (schema, enums, references); `--against <file>` reports drift in a consumer's copy.

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
