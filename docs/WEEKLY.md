# The weekly routine

> Every Friday night the workspace regroups: everything that exists only on this Mac is saved, the checkouts return to `main`, the week is recapped and the next one is planned. One confirm then records it all globally.

Work piles up where GitHub cannot see it: local branches, worktrees, stashes, uncommitted files, idle sessions. The Fleet project and the writing section fall behind it. This routine closes that gap once a week, so a week never ends with its state living in one place on one disk.

| | |
| --- | --- |
| **Tool** | [`tools/weekly.py`](../tools/weekly.py) (`tools/dash weekly`) |
| **Schedule** | A LaunchAgent, Friday 22:37 local ([`tools/install-weekly.sh`](../tools/install-weekly.sh)); not a workflow, because the work it saves exists only on this Mac |
| **Config** | [`_data/fleet.yml`](../_data/fleet.yml) `weekly:` |
| **Switch** | `weekly.enabled`, and `hub/weekly` in `switches:` (constitution § 17); a run started by hand bypasses it |
| **Local files** | `.fleet/weekly/<run>/` (report, inventory, draft posts, gitignored) and `~/bamr87-archive/weekly/<run>/` (bundles and snapshots) |
| **Public record** | [`_data/weekly_plan.yml`](../_data/weekly_plan.yml) (`weekly-plan/v1`) and the posts in `pages/posts/`, through the weekly PR |
| **AI cost** | $0: no model is called |
| **Tests** | `python3 tools/test_weekly.py` |

## The shape of a week

The split is the design. External actions start at high risk and wait for the maintainer (constitution § 13.6), Fleet project writes need a human who has seen the plan (§ 11.4), and every repo here is public. So Friday night is local only, and one confirm covers every external write.

**Friday night, unattended:**

1. **Gate.** Stop if the switch is off.
2. **Inventory.** Read the hub and every submodule: branches, worktrees, stashes, uncommitted files, nested submodules, live sessions, running containers.
3. **Classify.** Prove what is merged; everything else is kept (see below).
4. **Save.** Bundle every branch `main` does not contain, the stashes, and commits only a detached HEAD holds, and verify each bundle. Snapshot uncommitted work, including live sessions' work, without touching the working tree.
5. **Refresh and tidy.** Fast-forward the hub, move each submodule to its declared branch, remove proven-merged branches and clean dead worktrees. A checkout with a session or process in it, or on a feature branch, is left where it is and noted in the report, and detached commits get a `weekly/detached-*` branch first. Idle sessions started in a submodule keep that repo from refreshing until they close. Skipped on the report-only runs.
6. **Review and rank.** Run the [PM review](PM.md), then rank every open item.
7. **Recap.** Draft a chronicle for each active day and the week's retro (constitution § 23).
8. **Report.** Write `report.md` and send a notification.

**`tools/dash weekly confirm --apply`, by the maintainer:**

1. **Save off the Mac.** Mirror each local-only branch to `wip/mac/<branch>` on its repo's origin.
2. **Update the projects.** Apply the Fleet project plan through the § 11 service, 4 batches a run (200 ops an hour is the cap).
3. **Record it.** Open one weekly PR, built on `origin/main` in a throwaway worktree, with the retro, the chronicles, the plan in `_data/work_queue.yml`, roadmap status edits and the `_data/weekly_plan.yml` snapshot. It never carries the checkout's uncommitted edits, skips posts that have already landed, and uses a branch unique to the run, so it never overwrites anything. If a weekly PR for that week is already open, it opens no second one.

Merging that PR is the last step. It publishes the writing and makes the plan the order the loops read. The routine never merges it.

## Commands

```bash
tools/dash weekly                  # the latest run's headline
tools/dash weekly inventory        # read-only: what the routine sees (--json for all of it)
tools/dash weekly run              # a preview: saves locally, drafts, reports, changes no repo
tools/dash weekly run --apply      # refresh and tidy now, typed by the maintainer
tools/dash weekly confirm          # dry run: every external write it would make
tools/dash weekly confirm --apply  # the maintainer's yes
tools/dash weekly confirm --apply --keep-drafts              # land the week's posts as drafts
tools/dash weekly confirm --apply --publish 2026-11-04-x.md  # also publish an older draft
tools/dash weekly confirm --apply --allow bashcrawl:fix/x    # push one held branch, after reading the hit
tools/install-weekly.sh --print    # show the LaunchAgent; running it bare installs it
```

`confirm` is safe to repeat. Branches already saved are skipped, finished batches are remembered, and a run more than 8 days old is refused. With a large board plan, run it again after the hour for the next 200 ops.

## What is safe to touch

A branch is removed only with proof, and a missing upstream is not proof. These are the states, and each came from a real near-miss in the cleanup that started this routine.

| Branch state | Meaning | Removed? |
| --- | --- | --- |
| `merged` | An ancestor of `main`, `main` already holds all of it, or its tip is the head of (or is covered by) a PR merged into `main` | Yes, unless a worktree that survives still holds it |
| `open-pr` | An open PR has this head | No |
| `local-only` | Commits on no remote and no proof of merge | No: bundled, and pushed to `wip/` on confirm |
| `remote-held` | Unmerged, but every commit is on a remote | No |

A branch name that matches a merged PR proves nothing: a branch reused after its PR merged keeps its new commits. "`main` holds all of it" needs two tests to agree: merging it must change nothing, and every patch must already be on `main`. Patch-ids alone ignore whitespace, and the tree alone would call a commit-then-remove branch merged. A multi-commit squash fails this on purpose, so its merged PR is the proof.

| Worktree state | Meaning | Removed? |
| --- | --- | --- |
| `dead` | Clean, idle for 24 hours, unused | Yes; its branch stays unless that is merged too |
| `live` | A session, a process, a container mount or a compose project is using it | No |
| `dirty` | Uncommitted files | No: snapshotted |
| `has-submodules` | Initialized nested submodules, whose stashes and ignored files a removal would lose | No: remove it by hand |
| `holds-ignored` | Ignored files that are not regenerable, such as `.env` | No |
| `holds-worktree` | Another worktree lives inside it | No |
| `unique-commits` | Detached with commits no ref holds | No |
| `recent` | Touched in the last 24 hours | No |
| `foreign` | In another tool's pool (`weekly.foreign_roots`) | No |
| `missing` | The directory is gone; its commits are bundled | No: check it, then `git worktree prune` |
| `unknown` | A check could not be read | No |

Every removal is checked again at that moment, without `--force`, and a repo whose save did not verify removes nothing. Every check fails closed: if git fails behind a guard, the thing is kept, and if the routine cannot read what is in use, it removes nothing at all.

## Saving work

Local-only **commits** go to `wip/mac/<branch>` on the repo's own origin. These repos are public, so that publishes them: the report lists each branch first, and a branch that looks like it holds a secret is held back (the report names the file, never the value). The scan reads every commit message and every blob added, including binaries and merges, and anything it cannot read counts as a hit. It is pattern matching, so read the list before you confirm. Test fixtures can trip it: read what it found, and `--allow <repo>:<branch>` releases exactly that branch. A branch that could not be scanned cannot be released and stays local. The tip of each mirror is an empty `[skip ci]` commit, so the push wakes no workflow. The local branch is never changed, and a branch that moved since the report is skipped until the next run reviews it.

**Uncommitted work is never pushed.** It stays in the local archive, and the report flags it every week until it is committed or dropped. It is unreviewed by definition, and an unattended job should not publish it. This also means it is not yet off the Mac: a lost disk loses it, which is why it keeps appearing.

`wip/` branches are never deleted by this routine, so a mirror outlives its branch being merged. Clearing them is a manual job for now.

Restore a branch from a bundle:

```bash
git fetch ~/bamr87-archive/weekly/<run>/<repo>.bundle refs/heads/<branch>:refs/heads/<branch>
```

## Next week's plan

Every open item is ranked by rules, so the same input gives the same plan. The score adds the priority (the project field, then the `P` label, and your `_data/work_queue.yml` override above both), the lane, and up to 60 points of age. Your pins in `work_queue.yml` come first and keep their order. Items held on the board and epics are left out. All of it is listed by lane, and the week commits to a slice:

| Lane | What is in it | Slots |
| --- | --- | --- |
| **Decide** | Labelled `needs-amr`, or *Needs Amr* on the board | 5 |
| **Finish** | Open PRs ready for review | 5 |
| **Unblock** | Open PRs that conflict or fail CI | 3 |
| **Do** | Everything else | 5 |

The Fleet project's Iteration field is 2 weeks, so the routine does not write it. The weekly plan lives in `work_queue.yml`, which the issue pipeline and repo-evolution already read.

## Writing

The routine is the daily chronicle generator § 23 asked for, run weekly. It drafts `pages/posts/YYYY-MM-DD-chronicle.md` for each active day without one, and `YYYY-MM-DD-weekly-retro.md` for the week, with secret-shaped text redacted. Features lead each repo's list, and routine bot commits are left out.

Posts are drafts until reviewed (§ 23.4): they wait in the run folder, and `confirm --apply` is the review that publishes them. Read them first. The retro ends with an *In my own words* section for your notes; left empty, it is removed on publish. Older drafts are listed in the report and publish only when named with `--publish`.

This is a recap from git, so it is thin in two ways. It shows what landed, not why, and § 23.2's prompts and agent runs are not in it yet. Commit dates are when each commit was made, so a day's PR count can exceed its commits. Both are what the model pass in P4 is for.

## Rollout

The first 2 scheduled runs are report-only, and a run with errors does not count. Read those reports: they show exactly what an active run would remove. `weekly.report_only_runs` sets the number. Installing the LaunchAgent is a deploy step that waits for the maintainer's yes (§ 10.5).

| Phase | Scope |
| --- | --- |
| **P1** | This tool, the docs, the switch and the F5 entries |
| **P2** | Install the LaunchAgent and review the 2 report-only runs |
| **P3** | The console page and a read-only MCP tool, with `confirm` behind the OPS path (§ 11.8) |
| **P4** | A capped local model pass over the plan and the retro, through `tools/dash loop`; a spend decision (§ 10.7, § 10.9) |

## Design record (constitution § 10.8)

**Need.** A manual cleanup on 2026-11-06 found 221 local branches and 64 worktrees across the hub and its submodules, 17 branches with commits on no remote, `zer0-cms` local `main` diverged by 4 commits, a worktree holding the only copy of a running service's config, 465 of 522 open items off the Fleet project, and no chronicle ever written. Nothing surfaced any of it.

**Prior art.** From general knowledge of these tools; none was trialled.

| Tool | Fit |
| --- | --- |
| `tools/update-submodules.sh` | Adopted: moves every submodule to its declared branch and skips dirty repos |
| `tools/pm_review.py`, `tools/projects_backfill.py` | Adopted: gather every open item, then plan and apply through § 11 |
| `_data/work_queue.yml` | Adopted: already the order the loops read |
| `tools/install-workspace-sync.sh` | Adopted as the LaunchAgent pattern |
| `git bundle` | Adopted: full-fidelity local save of refs |
| myrepos, gita | Multi-repo status and bulk commands; no merge proof, no worktree or session awareness |
| git-trim, git-delete-merged-branches | Find merged branches; do not know PR heads, live sessions or nested submodules |
| restic, borg | Good file backup, but save bytes rather than git work a PR can pick up, and need a backup target |
| GitHub Projects iterations, Linear cycles | A cadence, not a save; the Fleet project's Iteration is 2 weeks |

**Decision.** Build a thin orchestrator over the hub's own tools. Only the classifier and the ranking are new, because no tool proves a branch merged through a squash or knows a worktree has a live session or a container behind it.

**Maintainer's decisions (2026-11-06).** Local-only commits go to `wip/` branches on each repo. Project writes are planned Friday and applied on confirm. Ranking is rules first, with a capped model later. The first 2 runs are report-only, then only proven-merged branches and clean dead worktrees are removed.
