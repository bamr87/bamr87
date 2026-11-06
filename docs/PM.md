# The PM review

> A daily, read-only review that keeps three records in line with what GitHub actually holds: the Fleet project, the roadmap and each repo's release train. It reports what has drifted and plans the fix; a person applies it.

The fleet's work is spread over about forty repositories. The [Fleet project](https://github.com/users/bamr87/projects/14) is its system of record (constitution § 9, § 10), [`_data/roadmap.yml`](../_data/roadmap.yml) holds the cross-repo initiatives, and each repo releases through release-please or, for the hub, hand-cut tags ([RELEASES.md](RELEASES.md)). Nothing kept those three in step with the issues, pull requests, comments and workflow runs they describe, so they fell behind as soon as they were written. The PM review is the routine that reads everything once a day and says where each record is wrong. It implements the backlog item [#588](https://github.com/bamr87/bamr87/issues/588) and rollout phase 2 ("sync") of [PROJECTS-FRAMEWORK.md](PROJECTS-FRAMEWORK.md).

| | |
| --- | --- |
| **Tool** | [`tools/pm_review.py`](../tools/pm_review.py) (`tools/dash pm`) |
| **Loop** | [`.github/workflows/fleet-pm.yml`](../.github/workflows/fleet-pm.yml), daily 07:07 UTC, off until `vars.FLEET_PM_ENABLED` is `true` |
| **Config** | [`_data/fleet.yml`](../_data/fleet.yml) `pm:` (lanes, thresholds, option aliases) and `schedule.fleet_pm` |
| **Board rules** | [`_data/projects_backfill.yml`](../_data/projects_backfill.yml) `board:` on top of [`templates/projects/framework.yml`](../templates/projects/framework.yml): the reviewed rules, not a second copy |
| **Snapshot** | [`_data/pm_review.yml`](../_data/pm_review.yml) (`pm-review/v1`), public; local files under `.fleet/pm/` (gitignored) |
| **Writes to GitHub** | none. The Fleet project ops it plans are applied by `tools/dash projects apply`, through the § 11 service |
| **AI cost** | $0: no model is called |
| **Tests** | `python3 tools/test_pm_review.py` |

## What one run does

1. **Gather.** For the hub and every registry repo a fleet owner holds (`hub.owners`; upstream mirrors and archived repos are left out): every open issue and pull request, each pull request's draft, mergeable, review and CI state and the issues it closes, the comments of the last two days, the latest release or tag with the commits since, the open release PR, and each epic's sub-issues. Then every item of the Fleet project with its field values, the roadmap, and the failing workflows per repo from the committed triage snapshot. Every call is a `GET` or a GraphQL query. A repo the token cannot read is reported as unreachable, never read as empty or deleted.
2. **Align.** Four lanes of rules compare what was read with what each record says (the tables below). Each mismatch is a finding with its evidence and a proposal.
3. **Plan.** Findings a rule can settle without judgement become Fleet project ops, batched 50 at a time into a preview with the § 11 service's own plan ids, and roadmap status edits. Everything else is reported for a person.
4. **Report.** A Markdown report, the plan preview, and the public snapshot with a 30-run history, so coverage and the finding count can be followed over time.

A full review of the fleet takes about 35 seconds and a few hundred API reads.

## Commands

```bash
tools/dash pm                      # the review: gather, align, plan, report (reads GitHub, writes .fleet/pm/ only)
tools/dash pm review --repo bamr87/zer0-mistakes   # one repo (never written to the snapshot)
tools/dash pm review --from .fleet/pm/model.json   # replay a saved gather, no network
tools/dash pm plan                 # the Fleet project ops as before → after, with plan ids
tools/dash pm roadmap [--write]    # the roadmap status edits; --write edits the working tree, never commits
tools/dash pm releases             # the release train
tools/dash pm status               # the committed snapshot's headline
```

To apply what a review planned, after reading `tools/dash pm plan`:

```bash
HARNESS_PROJECTS_WRITES=1 tools/dash projects apply .fleet/pm/board-plan.json --confirm [--batch N]
```

That is the same command, flag, confirmation, stale-plan refusal, caps (50 ops a plan, 200 an hour) and audit log as the backfill pass ([PROJECTS-FRAMEWORK.md § 3b](PROJECTS-FRAMEWORK.md)). A plan whose targets changed since the review is refused; run the review again. Items are added first and their fields are set by the next review, because an item id exists only once the item does. A PM plan is recorded in the audit log only; the `applied:` ledger in `_data/projects_backfill.yml` stays the reviewed pass's own.

## The project lane

Rules for the Fleet project. "Planned" means the review writes an op for it; the rest are reported.

| Finding | When | Planned |
| --- | --- | --- |
| `untracked` | an open issue or pull request is not on the project (§ 10.1) | add the item |
| `status_missing`, `priority_missing` | on the project with an empty Status or Priority (§ 10.4) | set it from the board rules; a Priority with no `P0`–`P3` label is the rules' default, and the plan says so |
| `gate_not_mirrored` | labelled `needs-amr` and the project does not say *Needs Amr* (§ 12.4) | Status → Needs Amr |
| `closed_not_done` | closed or merged on GitHub, any other Status on the project | Status → Done |
| `status_behind` | a pull request's Status differs from its state (draft → In progress, ready → In review), or an issue still in an early Status has an open pull request that closes it | set the Status |
| `pr_state_not_mirrored` | the project's CI or Merge state field differs from the pull request's | set the field |
| `priority_conflict` | the `P` label and the project disagree | no: the project wins (§ 9), so the proposal is to relabel |
| `done_but_open` | Done on the project, open on GitHub | no |
| `stale_in_progress` | In progress with no activity for 14 days | no |
| `epic_complete` | an open epic whose sub-issues are all closed | no: closing an epic is the maintainer's (§ 12.3) |
| `option_missing` | a derived value the project has no option for, and no alias | no |
| `board_unregistered` | an item on the project from a repo outside the registry | no: the write service refuses a repo it does not know |
| `board_unreadable` | the project could not be read (no token with `read:project`, or no GraphQL) | nothing is planned for the project; the other lanes still run |

A Status a person set on purpose is never planned over: *Needs Amr*, *Hold*, *Blocked* and *Won't do* hold an open item where it is (`pm.board.held`). The framework's option names are mapped to the live project's where they differ (`pm.board.aliases`: *Triaged* → *Triage*, *Blocked* → *Hold*). Ops are ordered gates first, then closed items, then field sets, then adds, the hub before the rest. The report also carries the project's queues: open items per Status and per Owner agent, and the *Needs Amr* list.

## The roadmap lane

| Finding | When | Planned |
| --- | --- | --- |
| `roadmap_shipped` | an entry that is not shipped names an issue closed as completed | `status: shipped` |
| `roadmap_started` | an `approved` or `backlog` entry whose issue has an open pull request against it, carries `agent:in-pr`, or is In progress or In review on the project | `status: in-progress` |
| `roadmap_declined` | the issue was closed as not planned | no: a person writes the reason |
| `roadmap_unlinked` | an `approved`, `backlog` or `in-progress` entry with no `issue_url`, so it is not an item on the project | no |
| `roadmap_untracked_epic` | an open epic labelled `roadmap` with no entry | no: `/future-features` drafts one, and nothing lands in the roadmap without approval |
| `roadmap_priority_drift` | the entry's priority and its issue's `P` label disagree | no |
| `roadmap_proposed_aging` | `proposed` entries older than 30 days | no |

`tools/dash pm roadmap --write` makes the planned edits with the Work board's own editor ([WORK-BOARD.md](WORK-BOARD.md)): it changes the `status:` lines and keeps every other byte. The file is edited in the working tree and never committed; the commit is the approval, as the roadmap's header requires.

## The release lane

For each repo the review finds the release engine (the registry's `release:` block, `pm.release.engines`, or a `release-please-config.json` in the repo), the latest release or tag, the commits since it counted by Conventional Commit type, the bump they imply and the open release PR. That is the release train:

| State | Meaning | Finding |
| --- | --- | --- |
| `blocked` | release-please is adopted and releasable commits have landed, but no release PR is open | `release_blocked` (high): see [RELEASES.md](RELEASES.md#when-the-release-pr-cannot-be-opened) |
| `release pr open` | a release PR is waiting | `release_pr_waiting` once it is 7 days old: merging it is the release, and that merge is the maintainer's |
| `unreleased` | no engine (or hand-cut tags) and at least 5 `feat`, `fix` or breaking commits since the last tag | `release_unreleased`: `tools/adopt-release.sh <repo>`, or the next hand-cut tag for the hub |
| `current` | nothing releasable since the last release | none |
| `never released` | no release and no tag | none |

A repo whose default branch has failing workflows says so on its row. The count of commits is whole; their types are read from the first 100, and the finding says when that is a sample. The review never cuts, tags or publishes anything.

## The hygiene lane

Reported only: pull requests with conflicts (`pr_conflicting`), failing checks (`pr_ci_red`), requested changes (`pr_changes_requested`) or 14 idle days while ready for review (`pr_idle`); an open item whose newest comment in the last two days is from someone outside the fleet and unanswered (`awaiting_reply`); per repo, the number of open issues with no type or no priority label (`unlabelled`, § 10.3); and repos the token could not read (`repo_unreachable`).

## The loop

`fleet-pm.yml` runs the review at 07:07 UTC, after `fleet-pulse` has refreshed the triage snapshot, and publishes `_data/pm_review.yml` through `publish-data`. It uploads the report and the plan preview as an artifact and writes the report to the job summary. It never applies a plan, edits the roadmap, merges, or touches an issue, a setting or a secret (`test_pm_review.py` holds that). A manual dispatch is a dry run by default: it uploads the artifact and publishes nothing.

- **Switch.** New loop, so the cron runs only while `vars.FLEET_PM_ENABLED` is `true`. A manual dispatch always runs.
- **Tokens.** `FLEET_TOKEN` is probed and reads the fleet; without it the job token reads the hub and public repos, and the run says the review is partial. The Fleet project is a user-level project that the job token cannot read: `PROJECTS_TOKEN` with `read:project` reads it (constitution § 11.7; only the maintainer provisions it). Without it the project lane reports `board_unreadable` and the other lanes still run.
- **Failure.** A token or API failure costs that lane for that run, never the run and never an item: the next run reads everything again from scratch, and nothing is carried between runs except the snapshot's history.
- **Privacy.** `_data/` is public site data, and so are the job summary and the artifact. Rows of private repos are counted and never listed in any of the three (`--public`). The full report exists only in a local run's `.fleet/pm/`.

## What it will not do

- Write to GitHub. The module holds no mutation and no call but a `GET` and a GraphQL query, and a test fails the build if one appears.
- Apply its own plan. Constitution § 11.4 asks that a person has seen a plan before it is applied; a scheduled run cannot satisfy that, so the loop stops at the preview.
- Close, merge, label, comment, tag or release.
- Plan over a Status a person set, or guess a field value the project has no option for.
- List a private repo's items anywhere public.
- Commit a roadmap edit.

## The first review (2026-11-04)

The first full run, read-only, against the live fleet: 41 repos, 522 open issues and pull requests, 57 of them on the Fleet project (10.9%) and 44 with Status and Priority. It planned 531 project ops in 11 batches (465 adds, 28 closed items still showing an open Status, 25 missing fields, 13 pull-request state fields) and one roadmap edit (FF-0005, whose issue closed as completed). Of 34 roadmap entries, 8 name an issue and 18 active ones name none. The release train showed 8 open release PRs (one of them 11 days old), 2 repos with unreleased work and no engine, 11 current and 20 never released. Nothing was applied.

## Phases

The work is tracked on [#588](https://github.com/bamr87/bamr87/issues/588). This document covers P0.

| Phase | What | Needs |
| --- | --- | --- |
| P0 | The deterministic review: `tools/dash pm`, `fleet-pm.yml` behind its switch, the snapshot, the tests | this PR |
| P1 | The first sync: apply the first plans, provision `PROJECTS_TOKEN`, set `FLEET_PM_ENABLED` | the maintainer |
| P2 | Surfaces: a console page and `fleet_pm` MCP tool over the snapshot, the *Needs Amr* queue in the console ([#586](https://github.com/bamr87/bamr87/issues/586)), the machine API | P0 |
| P3 | Unattended sync for a named class of board-only ops (adds, closed → Done, pull-request state), applied by the scheduled run under the caps, the audit log and the switch | an amendment to § 11.4, ratified by the maintainer; § 13.7 earned autonomy |
| P4 | The PM brief: a capped agent step (a JEV step spec) that proposes roadmap entries for unlinked work, drafts release notes and writes the weekly summary | § 13.1 eval set, a `budget.call_sites` entry |
| P5 | Roadmap entries mirrored to issues through the § 11.8 path; iterations (the project's Cycle field) and the registry's `release:` blocks kept current | P1 |
| P6 | The same loop as a standard githubai capability ([githubai#134](https://github.com/bamr87/githubai/issues/134)) | P3 |

Until P3 is ratified the project updates when a person runs the apply command; the review, the plan and the snapshot update every day on their own.

## Design record (constitution § 10.8)

**Needs assessment.** The maintainer asked for a project-management loop across the fleet (#588, 2026-11-02) and for it to cover the roadmap and release management as well (2026-11-04). The evidence is the first review above: nine in ten open items are not on the system of record, 28 finished items still show as open work, most roadmap entries are not tied to an issue, and release PRs wait unseen. Phase 2 of the ratified projects framework names this sync and was never built. Without it, § 10.1 and § 10.4 are rules nothing checks.

**Prior art.** One line each on fit:

- **GitHub Projects built-in workflows** (item closed → Done, pull request merged → Done, auto-archive, auto-add): adopt the first three on the project itself, which is a project setting and the maintainer's to change; auto-add watches one repository per workflow and the number of workflows is limited by plan, so it cannot be the intake for 41 repos, and none of them know a roadmap or a release.
- **`actions/add-to-project`**: adopt later as event-time intake (framework phase 1, #473); it adds items and nothing else, needs a caller and a token in every repo, and does not reconcile drift.
- **The project's Roadmap layout and iteration field**: adopt as the view; it draws dates and iterations someone sets and derives none.
- **Milestones**: not used; the framework's phase 5 retires them for iterations.
- **release-please**: already adopted and stays in charge of versions, changelogs and release PRs; it has no fleet view and stops quietly when it cannot open its PR, which is exactly what the release lane reads.
- **`github/issue-metrics`**: reports response and close times as an issue; no alignment and no plan. A possible input to the P4 brief.
- **`actions/stale`**: labels and closes idle items; the fleet's loops never close, so staleness is reported instead.
- **A separate tracker (Linear, Jira, ZenHub)**: a second system of record; § 9 names GitHub Projects.
- **In the hub**: `tools/projects_backfill.py` and the § 11 service (extended: the review reuses the board reader, the field rules, the batching and the apply path); the Work board (reused: its roadmap editor; its job is ordering work for the loops, not checking the records); `fleet-pulse`'s triage snapshot (reused for failing workflows); the issue pipeline (owns the `agent:*` state and is not replaced). The weekly fleet steward of PR #298 read the same items, but it was merged into a stacked branch that never reached `main`, and its orchestrate and develop jobs are what the issue pipeline and the doctor do now, so it is not revived.

**Build or adopt.** Build the alignment and adopt everything around it. No existing tool compares GitHub's state with a project, a roadmap file and a release train across many repos and turns the difference into a reviewable plan. The new code is one deterministic module with no model, no new dependency and no writer; writes go through the existing § 11 service, the rules are the reviewed ones, the roadmap is edited by the existing editor, releases stay with release-please and the views stay in GitHub Projects.

