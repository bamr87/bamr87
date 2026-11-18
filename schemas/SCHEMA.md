---
schema: '0.1'
coverage: listed
---

# SCHEMA — schemas

> Versioned JSON Schemas for the events and contracts the hub's runtime pieces exchange, each with the fixtures that prove what it accepts and rejects.

## Conventions

- One file per major version: `<name>-<major>.json`, JSON Schema draft 2020-12, with a `schema` field whose `const` is `<name>/<major>` so every instance names its own major.
- Additive changes only within a major: a new optional field, a new enum value or a new kind. A removal, a rename or a changed meaning is a new file, `<name>-<major+1>.json`, and the old one stays until nothing writes it.
- Unknown top-level fields are rejected (`additionalProperties: false`), so a new field lands here before any producer writes it.
- Every schema has `fixtures/<name>-<major>/` and a test under `tools/` that validates them with `jsonschema` when it is installed and with a strict fallback that refuses keywords it does not implement.

## Structure

| entry | kind | purpose | rules |
| --- | --- | --- | --- |
| `README.md` | file | What each schema is for, who writes and reads it, and how to change one | required |
| `fleet-activity-1.json` | file | `fleet-activity/1`: the envelope of one event in the fleet activity store (HUB-072, FR66, FR69, NFR13); checked by `tools/test_activity_contract.py` | required |
| `fixtures/` | dir | One directory per schema version (`<name>-<major>/`) of example instances: `valid-*.json` must validate and `invalid-*.json` must fail, each for one named reason | terminal |

## Placement

- Versioned event or contract schema → `schemas/<name>-<major>.json`, a row here, its fixtures in `fixtures/<name>-<major>/` and a `tools/test_*.py` that loads both (named in the row)
- A config file's own schema that ships inside a kit → stays beside the kit (`templates/<kit>/<kit>.schema.json`), not here
- Anything unrouted → propose an entry in this table first, then create it.

## Forbidden

- No breaking change inside a major version.
- No real event data in a fixture: fixtures are written by hand with made-up ids. A fixture that must hold an unredacted secret uses an obvious placeholder in no provider's real format; provider-prefixed tokens are built at run time by the test.
