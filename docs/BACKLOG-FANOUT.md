# Backlog fan-out

> Turns the hub's pending backlog into tracking PRs in each fleet repo an item applies to — dry run by default, PR-only and additive.

The backlog fan-out routine (HUB-027, PRD FR22 and FR23) turns the hub's pending backlog into tracking PRs in the fleet repos each item applies to. Engine: `tools/backlog_fanout.py`. Workflow: `.github/workflows/backlog-fanout.yml`. Config: `_data/backlog_fanout.yml`. Push and PR mechanics: `tools/fanout.sh --kit backlog` (FR6: kits reach fleet repos only as PRs opened by fanout.sh).

## What counts as pending

| Source | Item id | Pending when |
| --- | --- | --- |
| Open issues in bamr87/bamr87 | `issue-<n>` | open, and not labelled with a `skip_labels` entry (`agent:blocked`, `wontfix`, `hub-only`, `duplicate`) |
| PRD requirements (`PRD.md` § 5, ranges such as `FR7–FR15` expanded) | `req-<ID>` | no feature with `status: shipped` lists it in `prd:` |
| Catalog features (`features/features.yml`) | `feat-<ID>` | `status` is not `shipped` or `deprecated` |

## Mapping items to repos

Targets are the registry submodules (`_data/projects.yml`) owned by a fleet owner (`_data/fleet.yml` `hub.owners`), not archived. External upstreams are never targeted. The first rule that matches wins:

1. Issue label `repo:<name>` or `applies-to:<name>`.
2. Issue body line `applies_to: <name>, <name>` (or `all`).
3. Issue title whose first word (before `:` or a space) is a target name, such as `godotgo CI: …`.
4. Feature `applies_to: [<name>, …]` field in `features/features.yml`.
5. Requirement mapping in `_data/backlog_fanout.yml` `requirements:` (`FR3: [zer0-mistakes]`).

Items that match nothing are skipped as `unmapped` and listed in the summary, so the mapping gap is visible instead of silently guessed.

## Idempotency and conventions

Each (item, repo) pair has one stable branch, `backlog/<item-id>`. The PR seeds a single file, `.fleet/backlog/<item-id>.md`, with the item, its source link, the feature ids and the PRD requirements they serve. Re-running fast-forwards the same branch (fanout.sh `FANOUT_BASE_BRANCH`) and, when an open PR already exists, edits its title and body (`gh pr edit`) instead of opening a duplicate. The PR body starts `Automated by bamr87 (tools/fanout.sh --kit backlog): …`, as every fan-out PR does, and carries a feature-to-requirement table. The routine never merges, never pushes a default branch, and caps PRs per run (`max_prs_per_run`, 10).

## Cadence

The workflow fires daily at 08:27 UTC (`_data/fleet.yml` `schedule.backlog_fanout`). `cadence: daily` runs every time. `cadence: weekly` runs only on `weekly_day` and exits early with a "not due" summary on the other days. A dispatch can override with the `cadence` input, or force a run with `force`.

## Dry run and first scheduled behavior

Dry run is the default everywhere. The CLI needs `--apply` to push. A manual dispatch is a dry run unless `dry_run` is unchecked. A scheduled run is a dry run unless `_data/backlog_fanout.yml` has `apply: true`, and it ships `false`. The first scheduled run therefore only reads the backlog, plans, writes the job summary, and uploads the report and activity queue as the `backlog-fanout-<run_id>` artifact. It opens nothing. Turning it on is a reviewed one-line PR to `apply: true`.

## Token

Applying requires the `FLEET_TOKEN` repository secret: a fine-grained PAT for bamr87-bot with contents:write and pull-requests:write on the targets (workflows:write is not needed, since only `.fleet/backlog/` is written). FLEET_TOKEN has been dead before, so the workflow probes it with `gh api user` before an apply run and fails loudly without pushing if it is missing or expired. Dry runs fall back to the read-only `GITHUB_TOKEN`. This PR does not create or set the secret.

## Activity log

Every decision is emitted through `tools/fleet_activity.py`, a thin fire-and-forget client for the fleet activity log event schema proposed in the activity-log PRD, bamr87/bamr87#409 (HUB-024, dependency, not yet merged). Each event carries `event_id`, `ts`, `bot_id`, `repo`, `task_ref`, `run_id`, `event_type` (`start`, `finish`, `declined`, `retry`, `blocked_handoff`), `standard_version` (from the repo's AGENTS.md kit stamp), `standard_source`, `decision`, `outcome` and `dry_run`. Events are appended to a bounded local JSONL spool (`$FLEET_ACTIVITY_QUEUE`, default `$RUNNER_TEMP/fleet-activity/queue.jsonl`), redacted of token-looking strings, and uploaded with the run artifact. When `FLEET_ACTIVITY_ENDPOINT` is set and the run is not a dry run, the spool is flushed best-effort with a 3 second timeout. A dry run writes the local queue only. An unwritable queue or unreachable endpoint is counted in the summary and never blocks or fails the routine. When #409's store lands, point `FLEET_ACTIVITY_ENDPOINT` at its ingest and align field names if the final schema differs.

## Run locally

```sh
python3 tools/backlog_fanout.py --dry-run              # plan with the live backlog (needs gh auth)
python3 tools/backlog_fanout.py --dry-run --no-stamp   # skip AGENTS.md reads
python3 tools/test_backlog_fanout.py                   # offline tests
```
