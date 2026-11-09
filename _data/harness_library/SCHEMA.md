---
schema: "0.1"
coverage: listed
---

# SCHEMA — _data/harness_library

> The harness experience library: one directory per loop, one per domain under it, one per adopted refinement under that, each holding `experience.yml` (`jev-experience/v1`) and optionally `harness.diff`; read by the loop runner's context pack and `tools/jev/refine.py`, written by `tools/jev/library.py` on a branch (docs/HARNESS-REFINEMENT.md).

## Conventions

- `<loop>/` is a workflow stem (`repo-scout`); `<domain>/` is a registry category as `library.domain_dir` spells it; an entry directory is `<yyyymmdd>-<item slug>-<8 hex>`, the id `experience.yml` carries.
- Data only, committed, reviewed: an entry is added on a branch and reaches `main` by a merged pull request. `python3 -m tools.jev refine library check` is the gate (schema, field caps, the redaction leak check).

## Structure

| entry | kind | purpose | rules |
| --- | --- | --- | --- |
| `README.md` | file | What the library is, how an entry is written and read | required |
| `fleet-pulse/` | dir | The fleet-pulse doctor's lessons. Every doctor item is keyed to the hub, which the registry does not list, so they all sit under `unknown/` | terminal |
| `repo-evolution/` | dir | The repo-evolution evolve step's lessons, one `<domain>/` per registry category | terminal |
| `repo-scout/` | dir | The repo-scout scout step's lessons, one `<domain>/` per registry category | terminal |

## Placement

- New lesson → `python3 -m tools.jev refine library add …` (never by hand: the id, the caps and the leak check are the tool's).
- The first lesson for a new loop creates `<loop>/`: register it here in the same commit, as a `terminal` dir. `schema_lint` matches pattern rows against files only, so a `*/` row cannot cover a loop folder, and `terminal` keeps the walk out of the entries, where `refine library check` is the gate.
- Anything unrouted → propose an entry in this table first, then create it.

## Forbidden

- No file but `experience.yml` and `harness.diff` inside an entry; no entry outside `<loop>/<domain>/`.
- Nothing private: a local path, a host name, an address or a credential shape fails `refine library check`.
- No hand-edited id, and no entry written straight to `main`.
