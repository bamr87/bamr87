# The weekly routine

> Friday closes the week, Saturday checks that next week's schedule can run, Sunday plans it. Each stage reads and reports; one confirm from the maintainer is the only thing that writes to GitHub, and it never merges or closes.

Work piles up where GitHub cannot see it (local branches, worktrees, stashes, uncommitted files) and where nobody looks (open pull requests nobody has ruled on, loops that will fail on Monday for a reason known on Saturday). This routine spends the weekend on both, so the week starts from a clean slate with one page to read.

| | |
| --- | --- |
| **Tool** | [`tools/weekly/`](../tools/weekly/README.md) (`tools/dash weekly`) |
| **Schedule** | One LaunchAgent, `com.bamr87.weekly` ([`tools/install-weekly.sh`](../tools/install-weekly.sh)), with three local slots: Friday 22:37, Saturday 10:37, Sunday 16:37. Not a workflow, because the work Friday saves exists only on this Mac |
| **Config** | [`_data/fleet.yml`](../_data/fleet.yml) `weekly:` |
| **Switch** | `weekly.enabled`, and `hub/weekly` in `switches:` (constitution § 17); a run started by hand bypasses it |
| **Local files** | `.fleet/weekly/<run>/` (reports, inventory, lists, draft posts; gitignored) and `~/bamr87-archive/weekly/<run>/` (bundles and snapshots) |
| **Public record** | [`_data/weekly_plan.yml`](../_data/weekly_plan.yml) (`weekly-plan/v1`) and the posts in `pages/posts/`, through the weekly pull request |
| **AI cost** | Friday: one session, capped at $2. Saturday and Sunday: $0, no model. At most $10 a month, inside `budget.loops`; every figure is API-equivalent (estimate) |
| **Tests** | `python3 tools/test_weekly.py`, `test_weekly_dispositions.py`, `test_weekly_harness.py`, `test_weekly_stages.py` |

## The weekend at a glance

The work is split the way constitution § 26 splits all work: Claude Code executes, Grok bots set direction. Each day has both halves.

| Day | Stage | Claude Code executes | Grok bots direct | You get |
| --- | --- | --- | --- | --- |
| Friday 22:37 | `close` | Saves everything local, returns the checkouts to `main`, gives every open pull request and issue one disposition, and has one capped session propose what to do with the stale ones | Reviews ready pull requests for direction, checks the roadmap against what shipped, assesses the week | A close-out report: what would be removed, what is ready to merge, what waits on you |
| Saturday 10:37 | `prepare` | Checks every activity scheduled for next week: switch, last result, credentials, budget, data freshness, this Mac | Names three to five outcomes for the week and hands the software work off as issues | A readiness report: what to fix before Monday |
| Sunday 16:37 | `plan` | Ranks the open work with the handoffs lifted in, lays the week out day by day, writes the Monday brief | Checks the plan against the direction and writes Monday's asks | The Monday brief: one page |

Then, whenever you are ready, usually Monday morning: `tools/dash weekly confirm`, read it, and `--apply`.

## Commands

```bash
tools/dash weekly                          # the latest run of each stage
tools/dash weekly close                    # Friday as a preview: saves locally, reports, changes no repo
tools/dash weekly close --agent            # ... and run the close-out agent (one session, capped)
tools/dash weekly close --apply            # refresh and tidy now, typed by the maintainer
tools/dash weekly prepare                  # Saturday: can next week's schedule run
tools/dash weekly plan                     # Sunday: the plan, the week day by day, the Monday brief
tools/dash weekly confirm                  # dry run: every external write it would make
tools/dash weekly confirm --apply          # the maintainer's yes: wip/ pushes, board ops, the weekly PR
tools/dash weekly tidy                     # the folders beside the hub (~/bamr87-*): what each is, what is removable
tools/dash weekly tidy --apply             # save, then remove the worktrees among them proven safe (branches stay)
tools/dash weekly brief close              # the Grok bot's brief for a stage: close, prepare or plan
tools/dash weekly inventory                # read-only: what the close-out sees on this machine
tools/install-weekly.sh --print-plist      # show the LaunchAgent; running it bare installs it
```

`confirm` is safe to repeat. Branches already saved are skipped, finished board batches are remembered, and a run more than 8 days old is refused. In a Claude Code session, `/weekly` runs a stage as a preview and walks through it.

## Friday: close

**Unattended, in this order:**

1. **Gate.** Stop if the switch is off.
2. **Inventory.** Read the hub and every submodule: branches, worktrees, stashes, uncommitted files, nested submodules, live sessions, running containers.
3. **Classify.** Prove what is merged; everything else is kept (see [What is safe to touch](#what-is-safe-to-touch)).
4. **Save.** Bundle every branch `main` does not contain, the stashes, and commits only a detached HEAD holds, and verify each bundle. Snapshot uncommitted work, including live sessions' work, without touching the working tree.
5. **Refresh and tidy.** Fast-forward the hub, move each submodule to its declared branch, remove proven-merged branches and clean dead worktrees. A checkout with a session or process in it, or on a feature branch, is left where it is and noted in the report. Skipped on the report-only runs.
6. **Review and rank.** Run the [PM review](PM.md), then rank every open item.
7. **Close out.** Give every open pull request and issue in the fleet one disposition (below).
8. **Rule on the stale.** One capped Claude Code session reads the stale items and proposes, for each, to close it, carry it or put it in front of you.
9. **Recap.** Draft a chronicle for each active day and the week's retro (constitution § 23).
10. **Report.** Write `report.md` and send a notification.

### The close-out

Every open pull request comes from the [decision index](DECISION-INDEX.md) (a handful of GraphQL queries, not a sweep of each repo) and every open issue from the PM review. Rules alone decide the disposition, most restrictive first, so a gated pull request is never offered for merging however green it is.

| Disposition | Meaning | Who moves it next |
| --- | --- | --- |
| **Ready to merge** | Mergeable, every check green, a trusted author, and nothing the review gate holds | You, or Claude Code when you ask; the routine never merges |
| **Awaiting ratification** | Changes the constitution, an amendment or an ADR | You: only the maintainer merges it (§ 8) |
| **Waiting on Amr** | A gate or hold label, a gated path, a release pull request, a Dependabot bump that is major or states no versions, an untrusted author, no check that succeeded, a base that is not the default branch, or a repo whose own rules keep merges with you | You |
| **Conflicting** | Conflicts with its base | JEV: `tools/dash conflicts sweep` (§ 12.7) |
| **Checks failing** | A check failed or was cancelled, or changes were requested | Carried into next week's Unblock lane |
| **Not settled** | Checks or merge state still computing | Nobody yet; Sunday reads it again |
| **Stale** | An issue untouched for 30 days with no priority above P2, a draft untouched for 14, a blocked pull request untouched for 30 | The close-out agent proposes; you decide and act |
| **Carried** | Open and moving | Sunday ranks it |

**Ready to merge is read, not assumed.** GitHub's "mergeable and green" says nothing about what a pull request changes, and constitution § 12.3 gates on exactly that. So the close-out reads each candidate from live GitHub once (its files, labels, author, base and head branches and every check) and moves the held ones to *Waiting on Amr* with the reason. On its first real run, 74 pull requests were mergeable and green and 1 was ready.

The gate holds a pull request that:

- **changes a gated path**, matched without regard to case: anything under `.github/`, `_data/fleet.yml` and the other registries that carry budgets, agents and roles, the constitution, amendments and ADRs, `AGENTS.md`, `CLAUDE.md`, `SECURITY.md` and `CODEOWNERS`, agent and MCP config, `.gitmodules`, infrastructure, compose files and Dockerfiles, `.env` files, the `tools/dash` entry points and every shell script in `tools/`, JEV, this routine's own code, and the kits and specs. The list is `gate_paths` in `tools/weekly/closeout.py`; `weekly.closeout.gate_paths` adds to it and cannot remove from it, and `repo_gate_paths` adds a repo's own content gate;
- **renames or copies a file**, because the path it came from cannot be read, or changes 100 files or more, past what one read returns;
- **comes from an author who is not trusted.** People and bots are kept apart: a name `jev.allowed_authors` lists as a bot is trusted only as a bot, so nobody can register a bot's name and borrow its standing;
- **is not provably green**: every check must have finished, none failed or been cancelled, and at least one succeeded. A pull request whose every check was skipped proves nothing;
- **targets a branch that is not the repo's default**, sits in a repo that does not allow merge commits (the routine merges no other way), or in a repo `never_merge` names.

The list is as good as the moment it was read. Whoever merges reads the pull request again first (§ 12.1): a label, a new commit or a failed check can arrive after Friday. One limit no read removes: a required check that has not started yet has no entry to read, so it cannot be seen as missing.

Each disposition that needs someone has a list file under the run's `lists/`, one `owner/repo number` a line, so a loop in your terminal can walk it.

### The close-out agent

The stale set is where a rule cannot tell an abandoned thing from a waiting one. One headless Claude Code session reads it and proposes `close`, `carry` or `decide` for each item, with a one-line reason.

- **It can only read.** Its tools are Read, Glob and Grep, in a throwaway copy of one JSON file. It runs in the sandbox the [incident reflector](HARNESS-REFINEMENT.md) runs in, through the same runner: no network, no GitHub credential, one model credential.
- **It is capped.** `weekly.agent.usd` a session ($2), inside `budget.loops`, with the budget lock held and the attempt recorded in the AI ledger as loop `weekly`, step `close-out`.
- **Nothing it says is trusted.** Titles are written by anyone, so the engine drops any proposal whose key is not in the stale set, whose action is not one of the three, or whose reason is not one short line of plain text, and reports how many it dropped. A reason with a mention, markup or a control character is dropped: a comment from the repo's owner is not inert here, and an `@claude` in one starts an agent run.
- **It sees nothing private.** A private repo's rows are left out of what it reads.
- **It is bought once a week.** If a later slot makes up a scheduled close-out that failed, the session already paid for is kept and checked again against that day's stale set, not run again.
- **Nothing it proposes is applied.** A proposal is a line in the report. The routine has no way to close anything.

It needs a cached probe and canary for its posture. Its model, turn limit and tool grant are the reflector's on purpose, so `tools/dash refine reflect doctor --live --yes` arms both (a paid canary of at most $0.10, yours to run). Until then, or when the month's ceiling is reached or the usage window is spent, the agent says why it did not run and the stale list stands as the rules left it. A bare `close` never runs it; a scheduled run and `close --agent` do.

### What is safe to touch

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

### Folders beside the hub

Work made for one task piles up next to the hub as `~/bamr87-<task>` folders: worktrees an agent made for a pull request, a clone, a folder whose worktree was pruned. Every Friday report lists each one in a table with what it is, its size, its state and what happens next, and the [`~/bamr87-archive`](#saving-work) the routine saves into is never one of them. The globs are `weekly.siblings` (by default the hub's own name with a suffix, beside it).

- A worktree git knows is classified as above, and only a `dead` one is removed: by Friday's active run, or now with `tools/dash weekly tidy --apply`.
- A folder git does not know (an orphaned worktree, a separate clone, a plain folder) is reported and never removed: nothing proves it safe. Check it, then move it into the archive by hand.

`tidy` is that one part of Friday on its own: the same inventory, the same save to the archive and the same checks at the moment of removal, scoped to the folders (`--path GLOB` for another scope), with no refresh, no PM review and nothing on GitHub. A removed worktree keeps its branch; `--branches` also removes merged branches no surviving worktree holds. On 2026-11-13 it found 25 folders and 2.3 GB, removed 18 dead worktrees and kept their 18 branches, and left 7: two with uncommitted changes, one with 39 initialized submodules, two touched that day and two in use.

### Saving work

Local-only **commits** go to `wip/mac/<branch>` on the repo's own origin, on confirm. These repos are public, so that publishes them: the report lists each branch first, and a branch that looks like it holds a secret is held back (the report names the file, never the value). The scan reads every commit message and every blob added, including binaries and merges, and anything it cannot read counts as a hit. It is pattern matching, so read the list before you confirm. Test fixtures can trip it: read what it found, and `--allow <repo>:<branch>` releases exactly that branch. The tip of each mirror is an empty `[skip ci]` commit, so the push wakes no workflow. The local branch is never changed, and a branch that moved since the report is skipped until the next run reviews it.

**Uncommitted work is never pushed.** It stays in the local archive, and the report flags it every week until it is committed or dropped. This also means it is not yet off the Mac: a lost disk loses it, which is why it keeps appearing.

Restore a branch from a bundle:

```bash
git fetch ~/bamr87-archive/weekly/<run>/<repo>.bundle refs/heads/<branch>:refs/heads/<branch>
```

## Saturday: prepare

Saturday answers one question: can each activity scheduled for next week run. It reads; it flips no switch, rotates no credential and loads no LaunchAgent. Each finding names the command that fixes it, and the command is yours to run (§ 10.5, § 17.3).

It first runs `weekly.prepare.refresh` (by default `tools/dash decisions refresh`; config can only choose from the tool's own short list of read-only refreshes, because a `tools/dash` subcommand can do anything), then checks:

| Check | Source | At risk when |
| --- | --- | --- |
| **Every scheduled workflow** in the fleet, with the times it fires in the week (UTC crons, shown in local time) | `switches.loops` for the hub, `_data/harness_registry.yml` `schedule` for the rest | Its last run failed, fewer than half its recent runs succeeded, or its repository variable disagrees with the switch map |
| **Its switch** | The global, group and loop levels of `switches:` (the most restrictive wins), then the gate: a `fleet.yml` key, or the repository variable read from GitHub | Reported as off, with the command that turns it on; unknown if the variable cannot be read |
| **Credentials** | `_data/token_rotation.yml` and `_data/api_keys.yml`, which hold names, ages and expiry dates and never a value | A token is missing in a repo, or passes its age limit before the week ends; an API key expires inside the week |
| **Budget** | The AI ledger against `budget.loops`' scheduled ceiling; the fleet's projected AI spend and Actions minutes | The ceiling leaves no room for one scheduled session; a fleet budget is in breach |
| **Data freshness** | Each source in `harness.sources` that promises a freshness (§ 29.4) | A source is older than it promises |
| **This Mac** | Disk, the Claude CLI, the Docker daemon, the GitHub login, and whether launchd has each local job loaded | Any of them is missing |

The report leads with *Fix before Monday*, then shows the hub's loops day by day with the rest of the fleet counted beside them.

## Sunday: plan

Sunday runs the PM review again, reads the pull requests again (so Friday's *Not settled* rows are current), and ranks every open item by rules, so the same input gives the same plan. The score adds the priority (the project field, then the `P` label, and your `_data/work_queue.yml` override above both), the lane, and up to 60 points of age. Your pins in `work_queue.yml` come first and keep their order. Items held on the board and epics are left out.

| Lane | What is in it | Slots | Day |
| --- | --- | --- | --- |
| **Decide** | Labelled `needs-amr`, or *Needs Amr* on the board | 5 | Monday |
| **Finish** | Open PRs ready for review | 5 | Tuesday |
| **Unblock** | Open PRs that conflict or fail CI | 3 | Wednesday |
| **Do** | Everything else | 5 | Thursday |

**What the Grok half handed off is lifted in.** An issue that the week's issue links under Saturday's heading, or that carries the handoff label, gets a lift that outranks every priority and no pin. The brief says which handoffs are in the plan, which are open but past the lane's slots, and which are not open at all.

The **Monday brief** is Sunday's report: what to do first (confirm, fix what Saturday found, decide), where the direction stands, the plan by lane, and the week day by day with each day's focus lane beside the loops scheduled on the hub. Friday closes the week again.

The Fleet project's Iteration field is 2 weeks, so the routine does not write it. The weekly plan lives in `work_queue.yml`, which the issue pipeline and repo-evolution already read, and reaches it only through the weekly pull request.

## Confirm

A scheduled stage makes no GitHub write: external actions start at high risk and wait for you (§ 13.6), Fleet project writes need a human who has seen the plan (§ 11.4), and every repo here is public. `tools/dash weekly confirm` shows every write first; `--apply` makes them.

1. **Save off the Mac.** Mirror each local-only branch to `wip/mac/<branch>` on its repo's origin.
2. **Update the projects.** Apply the Fleet project plan through the § 11 service, 4 batches a run (200 ops an hour is the cap). If the PM review ran again since, its batches start over; an op already applied is a no-op.
3. **Record it.** Open one weekly pull request, built on `origin/main` in a throwaway worktree, with the retro, the chronicles, the plan in `_data/work_queue.yml`, roadmap status edits and the `_data/weekly_plan.yml` snapshot. It never carries the checkout's uncommitted edits and never overwrites a post that has landed. The plan is Sunday's when Sunday has run. If you confirmed on Friday, a later confirm adds Sunday's plan to the same pull request as one more commit, and only to a file still exactly as the routine pushed it, so anything you edited on the branch stays as you left it.
Merging the weekly pull request is the last step. It publishes the writing and makes the plan the order the loops read. The routine never merges it.

**Confirm never merges and never closes.** What the close-out calls ready or stale stays a list. To act on the ready list yourself, after reading it:

```bash
while read -r repo number; do gh pr merge "$number" --repo "$repo" --merge; done < .fleet/weekly/<run>/lists/merge-prs.txt
```

Or ask Claude Code in a session, which rechecks each one live before it merges (§ 12.2). An automated `--merge` and `--close-proposed` were built for this routine and taken out again before it shipped; the [design record](#design-record-constitution--108) says why.

Each write is saved to the run's `confirm.json` as it happens, whole or not at all, under the same lock the stages take. If that file is ever unreadable, confirm says so and starts its record again: every write checks the remote before it acts, so nothing is repeated.

## The Grok half

A Grok bot runs off this machine and on its own schedule, so the routine does not start it. It gives each stage a standing brief ([`tools/weekly/briefs/`](../tools/weekly/briefs/), printed with the week filled in by `tools/dash weekly brief <stage>`), and reads back what the bot wrote.

| Stage | Brief | Run it | It writes |
| --- | --- | --- | --- |
| `close` | [`grok-close.md`](../tools/weekly/briefs/grok-close.md) | Friday after 23:00 | A direction verdict on each ready pull request (§ 28.3), and `## Friday: direction close-out` on the week's issue |
| `prepare` | [`grok-prepare.md`](../tools/weekly/briefs/grok-prepare.md) | Saturday midday | One handoff issue per piece of software work (§ 28.1), and `## Saturday: direction for the week` linking them |
| `plan` | [`grok-plan.md`](../tools/weekly/briefs/grok-plan.md) | Sunday after 17:00 | `## Sunday: plan sign-off` with Monday's asks, and the direction verdict on the weekly pull request |

**The week's issue is the only thing the two halves pass to each other.** It is one issue in the hub, titled `Week <year>-W<week> — close-out and plan` (`weekly.grok.issue_title`). Sunday's plan finds it by that exact title, sees which of the three sections exist, and takes the handoffs from Saturday's section only. The issue is public, so only words from the repo's owner, a login in `weekly.grok.authors`, or a comment GitHub marks as an owner's, member's or collaborator's are read; anyone else's are counted and ignored. If the issue is missing, the Monday brief says the Grok half has not set direction, and the plan is the rules' ranking alone.

Each brief restates the boundary: a Grok bot never opens an implementation pull request, pushes a product commit, applies a console plan or merges. To schedule the Grok half, give each of the three Grok routines one instruction: fetch that stage's brief from this repo and follow it. The routines themselves are configured in Grok, not here.

## Beside the console's weekly lanes

[PR #841](https://github.com/bamr87/bamr87/pull/841) adds the same three days as CI lanes the console dispatches (`weekly_closeout`, `weekly_gather`, `weekly_finalize`). The two are halves of one routine, not rivals.

| | The console's lanes (#841) | This routine |
| --- | --- | --- |
| Runs | In GitHub Actions, through `ai-lane.yml` | On this Mac, from one LaunchAgent |
| Friday | An agent repairs pull requests: fixes failing CI on the branch, merges the base into a conflicting branch | Saves the Mac, tidies local branches and worktrees, and gives every open item a disposition |
| Can see | GitHub only; it never touches `~/bamr87` | The checkouts, worktrees, sessions and containers GitHub cannot see |
| AI | Opus up to $20 on Friday, Sonnet up to $10 on Saturday and on Sunday | One Sonnet session up to $2 on Friday |
| Switch | Three repository variables, off until you set them | `weekly.enabled`; nothing runs until you install the LaunchAgent |

They meet on the week's issue: both use the same title, and each writes under its own headings. Run in the default order, the console's Friday lane (13:17) repairs what it can in the afternoon, and this routine's close-out (22:37) rules on what is left at night. #841 records that it has no local entry point yet (its `R6:no-local-entry` gap, constitution § 10.9); this routine is that entry point for the read-and-report half, and the repair half stays with JEV's conflict engine and the issue pipeline locally.

## Writing

The routine is the daily chronicle generator § 23 asked for, run weekly. It drafts `pages/posts/YYYY-MM-DD-chronicle.md` for each active day without one, and `YYYY-MM-DD-weekly-retro.md` for the week, with secret-shaped text redacted. Features lead each repo's list, and routine bot commits are left out.

Posts are drafts until reviewed (§ 23.4): they wait in the run folder, and `confirm --apply` is the review that publishes them. Read them first. The retro ends with an *In my own words* section for your notes; left empty, it is removed on publish. `--keep-drafts` lands the posts as drafts, and `--publish FILE` also publishes an older draft.

This is a recap from git, so it shows what landed, not why, and § 23.2's prompts and agent runs are not in it yet.

## Rollout

The first 2 scheduled Fridays are report-only, and a run with errors does not count. Read those reports: they show exactly what an active run would remove. `weekly.report_only_runs` sets the number. After them a scheduled close-out is active, whichever slot runs it: one made up on Saturday or on Monday morning refreshes and tidies just as Friday's would.

| Phase | Scope | Who |
| --- | --- | --- |
| **P1** | The three stages, the close-out agent, the Grok briefs, the switch, the editor entries, the `/weekly` command | This change |
| **P2** | Install the LaunchAgent (`tools/install-weekly.sh`), arm the agent's canary (`tools/dash refine reflect doctor --live --yes`), and read the 2 report-only runs | Amr (§ 10.5, § 10.7) |
| **P3** | Point the three Grok routines at their briefs | Amr, in Grok |
| **P4** | A console page and a read-only MCP tool for the latest run, so a Grok bot can read the report instead of rebuilding it; `confirm` behind the OPS path (§ 11.8) | Later |
| **P5** | An eval set for the close-out agent (§ 13.1) and its run records in the reflector's inputs (§ 29.5) | Later |
| **P6** | The review gate as one shared module the decision index, JEV and this routine all call; only then, if wanted, an automated merge of the ready list as its own reviewed change | Later |

## Design record (constitution § 10.8)

**Need.** A manual cleanup on 2026-11-06 found 221 local branches and 64 worktrees across the hub and its submodules, 17 branches with commits on no remote, 465 of 522 open items off the Fleet project, and no chronicle ever written. On 2026-11-13 the decision index reported 85 pull requests ready to merge; read against the review gate, 3 were. Each Monday also began with loops that had been failing since the week before for reasons a Saturday check would have shown. Nothing surfaced any of it in one place.

**Prior art.** From general knowledge of these tools; none was trialled.

| Tool | Fit |
| --- | --- |
| `tools/update-submodules.sh` | Adopted: moves every submodule to its declared branch and skips dirty repos |
| `tools/pm_review.py`, `tools/projects_backfill.py` | Adopted: gather every open item, then plan and apply through § 11 |
| `tools/console/decision_index.py` | Adopted: every open pull request with its merge state in a handful of queries. It keeps no file list, so the gate scan reads each candidate once |
| `tools/jev/reflect.py` `run_session` | Adopted for the close-out agent: the sandbox, the budget lock, `budget.loops` and the AI ledger were already built and proven for one read-only session |
| `harness_registry.parse_cron` | Adopted; the fire times in a week are new, because nothing in the hub computed when a cron next fires |
| `_data/work_queue.yml` | Adopted: already the order the loops read |
| `tools/install-harness-review.sh` | Adopted as the LaunchAgent pattern |
| `git bundle` | Adopted: full-fidelity local save of refs |
| GitHub auto-merge, merge queue | Merge when checks pass, per repo, with no notion of a content gate; auto-merge is also a setting only the maintainer changes |
| `actions/stale` | Closes by age alone, per repo, unattended; no fleet view and no human between the rule and the close |
| myrepos, gita, git-trim | Multi-repo status and merged-branch cleanup; no merge proof through a squash, no worktree or session awareness |
| Claude Code cloud routines | Run on a schedule in the cloud, so they cannot see this Mac's worktrees or sessions; right for the console's lanes, not for this |
| GitHub Projects iterations, Linear cycles | A cadence, not a save; the Fleet project's Iteration is 2 weeks |

**Decision.** Build a thin orchestrator over the hub's own tools. What is new is small and specific: the branch and worktree classifier, the disposition rules and the gate scan, the week's fire times, and the catch-up dispatcher. Everything else is called, not rebuilt.

**One LaunchAgent, not three.** The agent inventory reads one job per installer, and a job that picks its stage from the weekday would run Saturday's stage for a Friday slot missed while the Mac slept. So every slot runs `tools/dash weekly auto --scheduled`, which runs each stage that is due this weekend and has not run, in order, until 18 hours after Sunday's slot. The slots are wall-clock times, and so is the arithmetic, so the weekend the clocks change does not run a stage twice. A stage that crashes is reported and does not stop the next.

**Maintainer's decisions (2026-11-06).** Local-only commits go to `wip/` branches on each repo. Project writes are planned Friday and applied on confirm. Ranking is rules first, with a capped model later. The first 2 runs are report-only, then only proven-merged branches and clean dead worktrees are removed.

**Why the routine does not merge or close.** A `confirm --merge` and a `confirm --close-proposed` were built and reviewed twice by independent reviewers before this shipped. Each round found ways they could act wrongly: a model-written reason posted under the owner's name, where `@claude` or a slash command starts an agent run; files the path gate did not hold, this routine's own imports among them; a label gate read from Friday's saved file; private repos held only by Friday's rows. Every finding was fixable and most were fixed, but two rounds in a row is the signal that the gate should be one shared, separately reviewed module before anything merges on its word. On the day, 1 pull request in the fleet would have qualified. So the routine lists, and a person or a session they direct acts. The parked work is the local branch `parked/weekly-confirm-merge-close`.

**Open for the maintainer (2026-11-13).** Whether the close-out agent runs on the schedule from the first Friday or waits for the report-only runs. How this routine and the console's lanes (#841) share Friday once both are on. Whether an automated merge of the ready list is wanted at all once the gate is shared.
