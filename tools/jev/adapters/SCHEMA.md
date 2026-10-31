---
schema: "0.1"
coverage: listed
---

# SCHEMA — tools/jev/adapters

> The local loop engine's adapters: one module per loop that maps its deterministic planner's and filer's JSON onto the engine's items and verdicts and holds that loop's own decisions, registered by name so a step spec can name one but never cause an arbitrary import (ADR 0002, P1).

## Conventions

- An adapter only maps JSON and makes decisions. The engine (`../loop.py`) owns the workspace, the argv, the environment, the settings, the run record, the § 13.6 gate and running the spec-declared publish argv; an adapter can widen none of them.
- An adapter reads only harvested copies of the agent's outputs, never the workspace, and reaches GitHub only through the `execute` the engine hands to `publish`.

## Structure

| entry | kind | purpose | rules |
| --- | --- | --- | --- |
| `README.md` | file | The adapter contract on one page: the seven hooks, their defaults, what the engine owns | required |
| `__init__.py` | file | The contract: `REGISTRY` (name → module), `get`, the `Item` / `PlanResult` / `Tier0` / `Triage` / `Verdict` / `PublishPlan` data classes and the `Adapter` base class with its defaults | required |
| `repo_scout.py` | file | repo-scout's adapter: maps `dash-gen scout` and `dash-gen scout-file`, tier-0 reuse on the same HEAD and brief, the dedupe block on `--apply`, the privacy filter and the local-runner artefact flags | required |

## Placement

- New adapter → `<name>.py` exposing `ADAPTER`, a row in `REGISTRY`, a row here, `tools/test_jev_adapter_<name>.py`, and the step spec's `local.adapter: <name>`.
- Anything unrouted → propose an entry in this table first, then create it.

## Forbidden

- Any GitHub write except through the spec-declared publish argv the engine executes; `gh pr merge`, `--admin`, a force-push, an issue close or edit.
- Importing dash-gen (`.github/scripts/dash-gen/`): the planner and the filer run as `tools/dash-gen` subprocesses.
- Reading a credential, or putting a local path or the host name into anything that is published.
