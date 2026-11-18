---
schema: "0.1"
coverage: listed
---

# SCHEMA — _data/sprints

> The live expedite-sprint records: one committed state document per sprint (`sprint/v1`), the incident-style record constitution § 27.7 asks for, linted by `tools/sprint_record.py` (drift check (r)) and rendered by the console's `/sprints` page.

## Conventions

- One sprint per file, named `<slug>.yml`, its `slug:` equal to the file name.
- At most one record is `state: active` (WIP 1, § 27.1); the lint refuses a second.
- Every gate (declaration, spec, merge) records who passed it, when and where (`by`, `at`, `ref`), in that order, and only the maintainer passes one (§ 27.2).
- Every dollar figure sits in a mapping labelled `label: API-equivalent (estimate)` (§ 10.7).
- A record changes only by a reviewed pull request: no console route, loop or tool writes here.

## Structure

| entry | kind | purpose | rules |
| --- | --- | --- | --- |
| `README.md` | file | The `sprint/v1` format, field by field, and how a record moves through a sprint | required |
| `*.yml` | pattern | One sprint's live record, named `<slug>.yml` | |

## Placement

- A new sprint → `<slug>.yml` here, opened by the pull request that records its declaration.
- A fixture or an example → `tools/test_sprint_record_fixture.yml`, never here: every file here is a real sprint.
- Anything unrouted → propose an entry in this table first, then create it.

## Forbidden

- No secrets, tokens or credential-named keys: this is public site data, and the lint withholds a record that holds one.
- No unlabelled USD figure, and no number that is not finite.
- No hand-picked second active sprint.
