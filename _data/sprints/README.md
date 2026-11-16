# _data/sprints/ — the live expedite-sprint records

One committed state document per expedite sprint, modelled on the SRE live incident document: what was declared, which gates have passed and who passed them, where the sprint is, what it has spent against its ceiling, which trip wires fired, and what the retro learned. The standard is [`docs/EXPEDITE-SPRINTS.md`](../../docs/EXPEDITE-SPRINTS.md) (constitution § 27, amendment [0025](../../docs/amendments/0025-expedite-sprints.md)); this directory is § 27.7's live record, issue [#691](https://github.com/bamr87/bamr87/issues/691) under epic [#687](https://github.com/bamr87/bamr87/issues/687).

The directory holds no record until the first sprint is declared. The console's **Sprints** page (`/sprints`, Harnesses → Sprints) renders every record here and says so plainly while there is none.

## How a record moves

1. **Gate A, declaration.** Amr commits the item to `_data/work_queue.yml` `order:` with its appetite. The pull request that does it adds `<slug>.yml` here with `state: active`, `phase: 1` and the `declaration` gate filled in.
2. **Gate B, spec approval.** The spec's approval is recorded in `gates.spec`; only then may `phase` reach 2 (build).
3. **Gate C, merge.** The merge through the review gate (§ 12) is recorded in `gates.merge`; only then may `phase` reach 4 (deploy).
4. **Every change** (phase, items, spend, a tripped wire) is a pull request that edits the record. Nothing writes it on its own: the console only reads it.
5. **The end.** At the cap or the end of the time box the circuit breaker stops the sprint: `state: stopped` with a `stop:` record (`reason: cap` or `time-box`) and the drafts it filed. A finished sprint is `state: done` in phase 6 with its `retro:`. A demoted one is `state: demoted` with `stop.reason: demoted`.

## The format — `sprint/v1`

| Field | Required | What it holds |
| --- | --- | --- |
| `schema` | yes | `sprint/v1` |
| `slug` | yes | the file name without `.yml`: lowercase letters, digits and dashes |
| `title` | yes | what the sprint delivers, in one line |
| `item` | yes | the expedited issue, `owner/repo#n`; while the sprint is active, `issue:<item>` is in `_data/work_queue.yml` `order:` |
| `target_repo` | — | `owner/repo` the sprint changes |
| `state` | yes | `proposed` (no gate yet), `active` (at most one), `stopped`, `demoted` or `done` |
| `phase` | yes | 0 intake, 1 scope, 2 build, 3 test (3b conflicts included), 4 deploy, 5 monitor, 6 retro — the phases of the standard |
| `appetite` | yes | `{hours, usd, label, ends_at}`: the ceiling, never an estimate; `usd` is API-equivalent (estimate) |
| `gates` | yes | `declaration`, `spec`, `merge`, each `null` until it passes, then `{by, at, ref}`: the maintainer's login, an ISO 8601 time, and the commit, issue or pull request that is the evidence |
| `spend` | yes | `{usd, cap_usd, label, updated_at, source}`; `cap_usd` equals `appetite.usd` and, once `_data/fleet.yml` `budget.sprints.<slug>` exists (#689), that ceiling too |
| `items` | — | the issues and pull requests, each `{ref, kind: issue or pr, title, state, phase}` |
| `trip_wires` | — | `{id, rule, state: armed, tripped or cleared, at}`; a tripped wire records when |
| `dora` | — | `null` until the DORA projection lands (#690), then its snapshot for the target repo: a guide, never a target |
| `retro` | — | `{lessons, debt}`: what the sprint learned and the debt issues it filed; required when `state: done` |
| `stop` | — | `{at, reason, by, filed, note}`: the circuit breaker's stop record; required when stopped or demoted |
| `updated_at`, `notes` | — | when the record last changed, and free text |

Every dollar figure sits in a mapping that carries `label: API-equivalent (estimate)`, and a dollar figure written in prose says the same. No field holds a secret: the lint refuses a credential-shaped value or a key that names one, and the console withholds that record whole.

## Commands

```bash
python3 tools/sprint_record.py lint          # drift check (q): every rule above, plus WIP 1 across records
python3 tools/sprint_record.py show          # the /api/sprints document the console page reads
python3 tools/test_sprint_record.py          # the fixture tests (tools/test_sprint_record_fixture.yml)
```
