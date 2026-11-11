# PRD — Red-main resolver

> **Status: Draft / proposed.** A harness command and a loop that find every red default branch in the fleet, name what blocks each one, resolve what the fleet's rules let an agent resolve, tell the maintainer exactly what is left, and re-read each branch to say whether it ended green. Design only. This pull request implements nothing: no workflow, schedule, script, setting or secret. Accepted when the maintainer merges it.
> Features: `HUB-NEW` slugs `red-main-resolver` and `red-main-workflow-review` (the CI review loop, § 20) in [`features/features.d/`](../../features/features.d/). Numbers are assigned at merge ([amendment 0002](../amendments/0002-conflict-free-numbering.md)).
> Requirements: `FR-NEW:red-main-detect`, `FR-NEW:red-main-classify`, `FR-NEW:red-main-resolve`, `FR-NEW:red-main-report`, `FR-NEW:red-main-ci-review` and `NFR-NEW:red-main-guardrails`, declared on those fragments and numbered at merge. The resolver also serves `FR42` (agent merge only of a mergeable pull request).
> Governing rules: [`docs/constitution.md`](../constitution.md) § 10, § 11, § 12 ([amendment 0009](../amendments/0009-agent-merge-review-gate.md)), § 13, § 17, § 19, § 26, § 28 and § 29. No constitution section is opened here. One follow-up amendment is named in § 17 and is not written in this pull request.

## 1. Problem

A default branch that stays red hides the next failure, blocks every pull request behind a strict required check, and teaches people to ignore the mark. On 11 November 2026 one GraphQL query over the fleet's 42 repositories found 8 red default branches, 30 green and 4 with no checks. Seven of the eight were then diagnosed by hand, read-only. The eighth is the hub itself (`CodeQL / Analyze (swift)`).

| Repo | Red check on the default branch | Cause | Blocking item | Class |
| --- | --- | --- | --- | --- |
| `bamr87/law-ai` | `CI / Backend Tests + Coverage` | Test-order settings pollution (`AttributeError: <LazySettings "None"> has no attribute 'AUDIT_PATH'`) | Draft [law-ai#214](https://github.com/bamr87/law-ai/pull/214), green and up to date with `main` | merge, by the maintainer |
| `bamr87/fredgar-ai` | `Release / publish / 🐍 PyPI`; `Verify` cancelled | PyPI trusted publishing refused from a reusable workflow, no publisher on PyPI; verify kit 0.1.0 cancel | [fredgar-ai#130](https://github.com/bamr87/fredgar-ai/pull/130); PyPI; `bamr87/.github` `publish.yml` | merge + settings + fix |
| `bamr87/bashcrawl` | `Verify` cancelled | A label event on the merged release PR shares the push run's concurrency group and cancels it | None filed | fix |
| `bamr87/scripts` | `Verify` cancelled | The same | None filed | fix |
| `year-of-ai/year-of-ai.github.io` | `Release / release-please` | No credential may open the release PR, and the `v2` tag predates the hub's guard | Hub [#456](https://github.com/bamr87/bamr87/issues/456) | settings |
| `bash-365/bash-365.com` | `Release / release-please` | The same | Hub [#456](https://github.com/bamr87/bamr87/issues/456) | settings |
| `bash-365/bash-365-apex` | `Release / release-please` | The same | Hub [#456](https://github.com/bamr87/bamr87/issues/456) | settings |

Three things stand out. Most of the fixes already existed: a green pull request nobody had merged, a kit version the hub had already published, a setting the hub had already documented. Finding that took on the order of a hundred API reads across the seven, by hand. And none of the seven could have been merged by an agent under today's rules: six of the seven repos have not ratified agent merge in their own constitution (five still say an agent may not merge its own pull requests, and `law-ai` forbids auto-merge as an invariant), and the one that has (`bash-365.com`) had no pull request that fixes its red check. A resolver has to be exact about that, or it merges where it may not.

Nothing in the fleet closes this loop. Fleet pulse ranks failing workflows over a window, the PM review reports pull-request state, the issue pipeline implements issues, JEV resolves conflicts. None of them starts from "this default branch is red" and ends at "it is green, or here is what the maintainer has to do".

## 2. Goals and non-goals

**Goals**

- Detect every red default branch in the fleet in one batched GraphQL query of `statusCheckRollup`.
- For each one, name the failing checks, the root cause with its evidence, and the pull request or issue that blocks it, and classify the fix as `merge`, `fix` or `settings`.
- Resolve without a person only what the constitution lets an agent do, exactly as it says: merge a mergeable pull request the review gate does not hold, with a merge commit, never with `--admin`, after re-reading live state; mark a draft ready only when its checks pass and the pull request says that is intended.
- Route every code fix to Claude Code as a handoff issue (constitution § 26).
- Tell the maintainer what only he can do, with exact steps: settings, secrets, tag cuts, external services such as PyPI.
- Re-read each default branch after a resolution and report the final state as green, red or pending.
- Review the CI itself behind each failed run: trace the workflow and what it calls, judge whether it was right to run and right to fail, and propose the minimal fix as a diff (§ 20).
- Be a dry run by default, bounded in time and API use, audited, and stoppable with one switch.

**Non-goals**

- Building the command, the loop, a console page, a workflow or a schedule in this pull request.
- A general auto-merger. The resolver merges only the pull request it identified as the blocker of a red default branch, and never more than one per repo per run.
- Writing code fixes or editing a workflow. The resolver and the CI review loop propose and file the handoff. Claude Code implements it.
- Making a red check pass by weakening it. The CI review loop never proposes `continue-on-error`, a lowered threshold, a deleted test or a skipped job for a failure it has not shown to be a non-issue.
- Changing a repository or organisation setting, a secret, branch protection, a ruleset, a tag or an external service. Those are reported, never done.
- Reverting a commit, force-pushing, updating a pull request's branch, or resolving a conflict. Conflicts stay with JEV ([JEV.md](../JEV.md)).
- Replacing fleet pulse, the doctor, the PM review or the issue pipeline.
- Hand-assigning `HUB-NNN`, `FRn` or `NFRn`.

## 3. How this sits beside what the fleet already has

| Existing piece | What it already owns | What the resolver asks of it |
| --- | --- | --- |
| Fleet triage (`tools/dash triage`, `_data/fleet_triage.yml`) | Each workflow's latest conclusion on the registry's branch, once a day, and `repos_red`. It treats a cancelled run as noise. | The resolver reads the commit's own rollup instead, so a head that is red only because a run was cancelled is seen. It follows the same rule that the registry's branch wins over GitHub's default. |
| Fleet pulse and the doctor, `HUB-012`, [DAILY-ANALYSIS.md](../DAILY-ANALYSIS.md) | The ranked queue of failing and expensive workflows, and the `fleet-doctor` issues and fix pull requests. | An open `fleet-doctor` issue that names the repo and workflow is the blocking item. The resolver links it and files nothing beside it. |
| The PM review, `HUB-077`, [PM.md](../PM.md) | A batched read of every open pull request's draft, mergeable, review and CI state, and the release train. | The resolver reuses that gather for the pull-request side. It does not keep a second reader. |
| The issue pipeline, `HUB-004`, [ISSUE-PIPELINE.md](../ISSUE-PIPELINE.md) | Intake with an evidence bundle, implementation as a draft pull request, completion. Tier 3 marks a completed pull request ready unless `human-review` is set. It never merges. | A routed fix enters here as a labelled issue. A pipeline draft is left for tier 3 to mark ready. |
| JEV conflicts, `HUB-035`, [JEV.md](../JEV.md) | Conflict resolution on open pull requests, the trusted-author list, tiers, caps and the ledger. | A conflicting blocker is reported as waiting on JEV. The resolver reuses `jev.allowed_authors` as its trusted-author list. |
| JEV ratify, `HUB-061` | A sanctioned merge by a job: `gh pr merge --merge --match-head-commit`, behind a guard. | The merge step copies that shape: the head it planned is the head it merges, or nothing is merged. |
| The review gate, `HUB-045`, constitution § 12 | The definition of mergeable, the gated categories, and `needs-amr`. | The resolver enforces it and relaxes nothing. Where § 7 is stricter, it holds more, never less. |
| The § 11 write-back service (`tools/console/gh_projects_write.py`) | Allowlisted edits to projects, issues and pull requests, including `pr.draft.set`, as a plan a person confirms. It never merges. | Marking a draft ready goes through it. |
| The OPS remote-write path, constitution § 11.8 | Confirmed, one-at-a-time remote operations: `dispatch`, the loop filers. It never merges and refuses `--scheduled`. | A re-run and a handoff issue go through it. |
| The fleet PR review, constitution § 19.10 | The sticky comment that explains each failed check, including a failed push to the default branch on the pull request that merged it. | The resolver reads that explanation when it exists. It does not post a second comment. |
| The workflow atlas, `HUB-034`, [WORKFLOW-ATLAS.md](../WORKFLOW-ATLAS.md) | The hub's own workflows and actions as one model, linted against the standards, with failure classes from the lake. | The resolver reuses a class where a signature matches one, and keeps the table in § 6 only for what they lack. The CI review loop (§ 20) applies the same kind of reading to a fleet repo's workflow and to the shared workflows it calls. |
| Actions usage analytics, `HUB-017`, and the doctor's queue | Per-workflow cost and waste over a 14-day window: `slow`, `flaky`, `cancel-heavy`, `cron-heavy`, `high-cost-low-value`. The doctor has already filed this way for the verify kit's cancels (hub #649, #822). | A cost flag is evidence for a CI review finding, and an open doctor issue for the same workflow is linked, not duplicated. The CI review loop starts from a failed run on a red head, not from a ranked cost, and ends in a line-anchored diff. |
| Loop switches, `HUB-057`, constitution § 17 | One map of kill switches in `_data/fleet.yml` `switches:`. | The loop's switch is one entry in that map. |

## 4. User stories

Stories are for Amr, for Claude Code as the executor, and for a fleet repo whose own constitution governs what may be merged into it.

| Id | As a… | I want… | So that… | Requirement |
| --- | --- | --- | --- | --- |
| US1 | fleet operator (Amr) | every red default branch found in one read, with unreachable, pending and no-checks repos named as such | I know the real count without opening forty repos, and a repo that could not be read is not counted as green | `FR-NEW:red-main-detect` |
| US2 | fleet operator | for each red branch the failing check, the cause with the log line it was read from, and the pull request or issue that blocks it | I can act on it without reading a run log myself | `FR-NEW:red-main-classify` |
| US3 | fleet operator | a green, mergeable blocker that the review gate does not hold merged for me, exactly as § 12 says | routine fixes stop waiting on me, and nothing gated is ever merged around me | `FR-NEW:red-main-resolve`, `FR42` |
| US4 | fleet operator | a draft marked ready only when its checks pass and the pull request says that is intended | a finished draft moves on, and a work-in-progress draft is left alone | `FR-NEW:red-main-resolve` |
| US5 | Claude Code, as executor | a handoff issue that states the red check, the evidence, the acceptance criteria and the governing requirement | I can implement the fix under § 26 and § 28 without re-diagnosing it | `FR-NEW:red-main-resolve` |
| US6 | fleet operator | a list of what only I can do, with the exact place, command and check for each | a settings flip, a secret or a PyPI publisher takes me a minute, not a search | `FR-NEW:red-main-report` |
| US7 | fleet operator | each default branch re-read after a resolution, and a final green, red or pending | I am told what happened, not what was attempted | `FR-NEW:red-main-report` |
| US8 | fleet operator | a dry run by default, a time and rate budget, an audit record of every action and one switch that stops it | I can leave it running and stop it at once | `NFR-NEW:red-main-guardrails` |
| US9 | a fleet repo that has not ratified agent merge | the resolver never to merge into me | my constitution decides who merges here, not the hub's loop | `FR-NEW:red-main-resolve` |
| US10 | fleet operator | each failed run on a red default branch traced to the workflow that ran it and to everything that workflow calls, with the file and line of each fact | I can see why the CI ran and why it failed without opening six files in three repos | `FR-NEW:red-main-ci-review` |
| US11 | fleet operator | the CI flagged as over-broad, under-selective, misconfigured or ok | I can tell a real defect from CI that ran when it should not have, or failed on something that is not a defect | `FR-NEW:red-main-ci-review` |
| US12 | Claude Code, as executor | the minimal fix as a diff against the reviewed commit, with its evidence, in a handoff issue | I implement a reviewed change, not a guess, and nothing that weakens a real check | `FR-NEW:red-main-ci-review` |
| US13 | fleet operator | any proposed fix that touches a setting, a secret, branch protection or a tag sent to me and never to an agent | CI is not made green by changing what only I may change | `FR-NEW:red-main-ci-review`, `NFR-NEW:red-main-guardrails` |

## 5. Detect — `FR-NEW:red-main-detect`

Scope is the hub and every registry repo whose owner is in `_data/fleet.yml` `hub.owners`, archived repos left out. Upstream mirrors are never read or written.

One GraphQL document carries one alias per repo and asks for the head commit of the registry's branch (`ref(qualifiedName:)`, because the registry's branch wins over GitHub's default, as in fleet triage), its `statusCheckRollup { state }`, `defaultBranchRef { name }`, `isArchived` and `rateLimit { cost remaining resetAt }`. A trial of that query on 11 November 2026, through `defaultBranchRef`, read 42 repos in 3.7 seconds for 1 of the hour's 5,000 points. A second batched query reads the check contexts of the red repos only.

| Rollup | State | What the resolver does |
| --- | --- | --- |
| `SUCCESS` | green | Nothing. |
| `FAILURE`, `ERROR` | red | Diagnoses it (§ 6). A head whose only non-success is a cancelled run is `red (cancelled-only)`, because GitHub reports it red and a required check reads it as not passed. |
| `PENDING`, `EXPECTED` | pending | Not red. Read again on the next pass. |
| no rollup | no-checks | Listed. Not red, not green. |
| the repo or the branch could not be read | unreachable | Listed with the error. Never counted as green. |
| the registry's branch is not GitHub's default | branch-mismatch | A note on the row. The registry's branch is the one judged. |

Detection runs on a schedule or on demand. It never runs on a pull-request or push check, because a fleet-wide read on every push spends the shared token quota ([WORKFLOW-OPTIMIZATION.md](../WORKFLOW-OPTIMIZATION.md)).

## 6. Diagnose and classify — `FR-NEW:red-main-classify`

Diagnosis reads only the red repos, with bounded REST calls: the failing run, its failed job and step, and a capped, redacted tail of that step's log. The cause is matched against a signature table. The first rows come from the seven repos in § 1.

| Signature | Cause | Class |
| --- | --- | --- |
| `GitHub Actions is not permitted to create or approve pull requests` | No credential may open the release PR | settings |
| `invalid-publisher` from PyPI trusted publishing | The publisher on PyPI does not match the workflow that uploads | settings (external service) |
| A run concluded `cancelled`, and a run of the same workflow in the same concurrency group started seconds later | A concurrency cancel, not a failure | fix (re-run now, kit upgrade for the cause) |
| `startup_failure`, or `workflow was not found` | A caller pins a ref where the reusable workflow does not exist | settings (a tag cut on the hub) or fix (the caller's pin) |
| Test or lint failures in a build step | A defect in code, a test or a workflow | merge if an open pull request greens the check, else fix |

A cause that matches no signature is `unclassified`. It is reported with its evidence and nothing is done about it. The resolver does not guess, and a log it could not read is said to be unread.

The blocking item is searched for in this order, and the first hit is kept with the reason it was chosen:

1. An open pull request in the repo on whose head the red check is green, and whose head contains the default branch's head. This is the only evidence that makes a pull request a `merge` candidate.
2. An open pull request or issue in the repo that names the failing run, workflow or check.
3. An open hub issue labelled `fleet-doctor` that names the repo and the workflow.
4. A known fleet-wide cause mapped to its hub issue (for example the release credential and hub #456).
5. Nothing. The finding is `no-item`, and the resolver proposes one issue, because every task is an item (constitution § 10.1).

| Class | Meaning | Who acts |
| --- | --- | --- |
| `merge` | An open pull request greens the red check. Its state is `auto`, `ready-first` or `needs-amr`, with the reason. | The resolver for `auto` and `ready-first` (§ 7). The maintainer for `needs-amr`. |
| `fix` | No open pull request fixes it. The route is `rerun` (nothing to change for this commit), `kit` (a fan-out kit upgrade) or `issue` (a handoff). | Claude Code, through the handoff (constitution § 26.4, § 28.1). A fan-out stays a dry run by default. |
| `settings` | A repository or organisation setting, a secret, branch protection, a tag on the hub's public interface, or an external service. | The maintainer, always. |

A repo can carry several findings. `fredgar-ai` carried three. Each is listed, and the repo's headline class is the most restrictive one still open: `settings`, then `fix`, then `merge`.

## 7. Resolve — `FR-NEW:red-main-resolve`

The resolver acts only on the rows of this table. Every condition is re-read from GitHub immediately before the action, never taken from the plan.

| Action | Rule that allows it | Conditions, all of them | Path |
| --- | --- | --- | --- |
| Merge the blocking pull request | Constitution § 12.1 and § 12.2, `FR42` | The repo is on the merge allowlist (§ 9). The pull request is open, not a draft, and its author is trusted. It is `MERGEABLE` and `CLEAN`. Every check on its head is green and every required review is satisfied. It carries no gate label (`needs-amr`, `agent:hold`, `blocked`, `human-review`, `jev:needs-human`) and touches no gated path (§ 12.3). It is not a release PR. Its head is the commit that was planned. The repo allows merge commits. | `gh pr merge <n> --merge --match-head-commit <sha>`. Never `--admin`, `--squash`, `--rebase` or `--auto`, and never a force-push. |
| Mark a draft ready | Constitution § 11.1 (`pr.draft.set`) | Every check on its head is green. The pull request states that ready-for-review is intended. It carries no gate label. | The § 11 write-back service: plan, confirm, apply, audited. |
| Re-run a cancelled run | Constitution § 11.8 (a remote operation, like `dispatch`) | The head is `red (cancelled-only)`. The run has not been re-run by the resolver before. | The OPS remote-write path, with its confirmation. Refused when scheduled. |
| File or update a handoff issue | Constitution § 11.8 (a loop filer), § 26.4 | The finding is `no-item`: no open pull request or issue, in the repo or on the hub, already covers the repo and signature. | The OPS remote-write path, as `scout-file` and `doctor-file` do. Refused when scheduled, until § 13.7 says otherwise. |
| Anything in class `settings` | None | None | Reported with exact steps (§ 8). Never done. |

**A draft is not marked ready and merged in one pass.** Marking a draft ready can start the AI review that `ready_for_review` triggers (constitution § 19.7) and any check that listens for it. The pull request becomes a merge candidate only on a later pass, when it is mergeable in its own right.

**Ready intent.** "The pull request says ready-for-review is intended" means the pull request states it, in its body or by a label. Proposed: a body line `Ready-for-review: intended`, or the label `ready-when-green`. A draft opened by the issue pipeline is left to tier 3, which already marks a completed pull request ready unless `human-review` is set; the resolver reports it as waiting on tier 3. A draft that says nothing is reported to the maintainer as green and silent.

**Gated paths.** A pull request is held when it touches the constitution, an amendment, a fleet standard or an ADR; secrets, tokens, budgets or billing; settings, branch protection, rulesets or permissions; security-sensitive code or configuration; a deploy or release path; or when it deletes data (§ 12.3). The resolver is deliberately stricter in three places: it also holds a pull request that touches a workflow or a composite action, because a workflow can change permissions and what a secret reaches; it holds every release PR, because merging one publishes; and it holds the two labels the loops use to ask for a person, `human-review` and `jev:needs-human`. When the resolver cannot tell, the pull request is held.

**Risk tiers (constitution § 13.6).** A merge reaches a default branch and can start a deploy or a release, so it is tagged `external` and starts at tier high: each merge waits for the maintainer's yes on the plan that shows it. It earns a lower tier only as § 13.7 says, after 25 consecutive clean approvals, and any rejection resets it. Marking ready and re-running are reversible and run at tier medium, with an audit record.

## 8. Report and re-check — `FR-NEW:red-main-report`

Every run writes one report with these sections: resolved, needs the maintainer, routed to Claude Code, unclassified, and still pending. An item that needs the maintainer carries:

- what is wrong and the evidence it was read from;
- where to change it, as a settings path or a URL;
- the command, when there is one, written so that a secret is typed at a prompt and never passed as an argument;
- how to verify it, as a command and the result to expect;
- what happens next, for example which re-run then turns the branch green.

After any applied action the run records the head it expects to change, then reads that branch's rollup again until every check has completed or the time budget ends. The final state of each repo is one of:

| Final state | Meaning |
| --- | --- |
| `green` | The rollup of the current head was read as `SUCCESS`. |
| `red` | It was read as red. The checks still failing are listed. A branch that a merge turned red in a new way is `red (new)`. |
| `pending` | Checks were still running at the deadline. The report names the command that reads it again. |
| `unchanged` | Nothing was applied, because the run was a dry run or every action was refused. |

Green is never inferred from an action having succeeded. Only a rollup that was read counts.

The report is a local file and the job summary. A public snapshot carries the counts and the public repos' rows, and nothing from a private repo. Nothing is posted under the maintainer's account (constitution § 19.5).

## 9. Merge authority is per repo

Constitution § 12.6 asks every repo's constitution to conform to § 12 or to say how it differs. Until a repo has done that, its own constitution still governs it. On 11 November 2026, of the seven repos in § 1, one (`bash-365.com`) had ratified the merge-authority section. Five still say an agent may not merge its own pull requests, and `law-ai` says "No auto-merge" as an invariant.

So the resolver merges only in a repo on an allowlist, proposed as `_data/fleet.yml` `red_main.merge.repos`, empty by default. A repo is added by a gated pull request once its own constitution carries the ratified section, and a check holds each entry to that record. Everywhere else a `merge` finding is `needs-amr` and goes to the maintainer's list. An empty allowlist means the resolver merges nothing, and still detects, classifies, reports and re-checks.

## 10. The command (proposed)

```bash
tools/dash red-main                    # scan: the fleet's default branches, one query; writes nothing to GitHub
tools/dash red-main plan               # diagnose and classify the red ones; print the plan and its plan_id
tools/dash red-main plan --repo bamr87/bashcrawl   # one repo
tools/dash red-main resolve            # the same plan, as a dry run: what would be done, nothing done
tools/dash red-main resolve --apply --plan <plan_id>   # apply that plan, each action re-checked first
tools/dash red-main recheck [<run_id>] # read the branches a run acted on; final green, red or pending
tools/dash red-main ci-review          # the CI review loop (§ 20) over the red heads' failed runs; read-only, prints findings and diffs
tools/dash red-main ci-review --repo bamr87/bashcrawl --sample-prs 3   # one repo, plus a sample of its failed pull-request runs
tools/dash red-main status             # the committed snapshot's headline
```

The local entry point ships first (constitution § 10.9). The implementation pull request that adds the subcommand also adds its editor entry (§ 20), its `tools/dash` reference line, a read tool on the fleet MCP server and the console view, so that an agent can read what a person can (`NFR20`).

## 11. The loop (proposed)

A scheduled workflow runs the read-only half once a day: detect, diagnose, classify, report, and publish the snapshot through `publish-data`. It never merges, marks nothing ready, re-runs nothing and files nothing: the fleet doctor already files an issue for a failing workflow, and the resolver links that issue instead of filing beside it. The proposed slot is 06:07 UTC, after fleet pulse has refreshed the triage snapshot and the doctor's issues; the implementation declares it in `_data/fleet.yml` `schedule:`, off the hour.

The loop is new, so it is off until `vars.RED_MAIN_ENABLED` is `true`, its switch is one entry in `_data/fleet.yml` `switches:`, and a manual dispatch bypasses it. Reads use `FLEET_TOKEN`, probed with `gh api user`, because the repos span four owners and one `GITHUB_TOKEN` quota is shared by every run in the hub.

The apply half runs in a local session: the maintainer at a terminal, or a Claude Code session, with `--apply` on a plan that was shown first. § 16 says why it is not in CI.

## 12. Guardrails — `NFR-NEW:red-main-guardrails`

| Guardrail | Rule |
| --- | --- |
| Dry run by default | `scan`, `plan` and `resolve` write nothing to GitHub. `--apply` takes a `plan_id` and applies only that plan. A plan whose targets changed since it was shown is refused. |
| Time budget | A run has a wall clock, proposed at 15 minutes, with a cap per repo for diagnosis and a cap on the wait for re-check (proposed 30 minutes for a local `--apply --wait`, otherwise the next pass). At the deadline the run stops and the report is marked partial. |
| Rate limits | Detection is one query. Diagnosis is capped per red repo and per run, and repos beyond the cap are listed as not diagnosed. The run stops, with a partial report, when `rateLimit.remaining` falls under a floor. A `403` or `429` is retried at most twice, honouring `Retry-After`. Writes are serialized and spaced. |
| Action caps | Per run, proposed: 3 merges and at most 1 per repo, 5 drafts marked ready, 5 re-runs and one re-run ever per run id, 5 issues. |
| Circuit breaker | A repo whose branch is still red after a merge the resolver made gets no further merge until a person clears it. Two such merges in a row stop every merge in the fleet. |
| Audit trail | One append-only JSONL record per planned and per applied action: who, when, run, plan, repo, pull request, head commit, before, after, result. Token values are redacted. The run record sits under `.fleet/runs/<run_id>/`. |
| Kill switch | The central switch (constitution § 17) stops the loop and the local apply alike. A switch that cannot be read is treated as off. Apply has its own switch, off until a gated pull request turns it on. |
| Secrets | The resolver never reads, prints or changes a secret value. It reads secret names only to explain a `settings` finding. Log tails are redacted before they are stored. |
| Hands off the Mac | Nothing here changes the maintainer's machines (constitution § 10.5). |
| One run at a time | A second run refuses to apply while one holds the remote lock. |

## 13. Design for Failure

| Failure | Detection | Behaviour | Recovery | What is learned |
| --- | --- | --- | --- | --- |
| The detection query fails, or one repo in it errors | A GraphQL error, or a null alias | That repo is `unreachable`. The others are still judged. | The next pass. | A repo that was not read is never green. |
| The rate-limit floor is reached | `rateLimit.remaining` under the floor | The run stops and reports what it has, marked partial. | The next pass, after the reset the report names. | The resolver never spends the quota other loops need. |
| A run log cannot be read | A `404`, a `502`, an expired log | The cause is `unclassified (log unread)`. Two retries, then no more. | A person opens the run, or the next pass reads it. | A missing log is not a guessed cause. |
| The cause matches no signature | The table has no row | `unclassified`, with the evidence. No action. | A row is added to the table by a reviewed change. | The table grows from real misses (§ 15). |
| A pull request changed between plan and apply | The live re-read differs: a new push, a new label, back to draft, a moved base | That action is refused. The others continue. | Plan again. | The plan is a preview, not an authority. |
| GitHub has not computed mergeability | `mergeable: UNKNOWN` | A bounded wait, then the action is skipped. | The next pass. | Unknown is not mergeable. |
| GitHub refuses the merge | A `405` or `409`, a required check missing, branch protection | Nothing is bypassed. The finding becomes `needs-amr` with GitHub's message. | The maintainer. | `--admin` is never the answer. |
| The repo does not allow merge commits | The repo's merge settings | Not merged. A `settings` finding. | The maintainer. | The resolver never falls back to squash or rebase. |
| The merge lands and the branch is still red, or red in a new way | The re-check | `red` or `red (new)`. No revert. A handoff issue. The circuit breaker trips for that repo. | Claude Code, through the handoff. | A merge that did not help is evidence the diagnosis was wrong. |
| A draft marked ready then fails its checks | The next pass | It is not a merge candidate. Reported. | Its author. | Ready is a state, not a verdict. |
| A re-run is cancelled again | The re-run's conclusion | Never re-run a second time. The route becomes `kit` or `issue`. | The kit upgrade. | A repeat cancel is a cause, not bad luck. |
| The list of open issues cannot be read | The filer's dedupe read fails | Nothing is filed. | The next pass. | No duplicate issues (constitution § 11.8). |
| The token lacks a scope a read needs | A `403` that names the scope | The read is reported as refused, with the scope. The resolver never changes auth and never asks for a wider token. | The maintainer decides. | An unread setting is said to be unread. |
| A secret-shaped string is in a log tail | The shared redaction patterns | It is dropped before storage. | Rotate it if it was already exposed. | Redaction happens before the write. |
| The time budget ends mid-run | The wall clock | The run stops between actions. Each action is atomic and already recorded. | The next run plans from live state; a merge that already landed is a no-op. | No half-applied plan. |
| The kill switch is off or unreadable | The switch map | Nothing is done. | The maintainer flips it. | Unreadable is off. |
| Two runs overlap | The remote lock | The second refuses to apply. | It runs again later. | One writer. |
| Claude Code is unavailable or out of budget | The handoff issue sits | The fix waits. Nothing else implements it. | The maintainer decides the path (constitution § 26.5, § 28.6). | The resolver does not become the executor. |

Risk tier (constitution § 13): detecting, diagnosing and reporting are low. Marking ready and re-running are medium. Merging is high, as § 7 says. Changing a setting or a secret is not an action the resolver has.

## 14. Prior art and build-vs-adopt

Needs assessment (constitution § 10.8): the fleet has 42 repos and one maintainer. On the day this was written 8 default branches were red, most with a fix that already existed and had not been applied, and each diagnosis was a run log, a pull-request list and a settings read, by hand. The need is a routine that finds them, applies what the rules allow, and hands the rest to the right actor with the steps written out.

| Option | Fit |
| --- | --- |
| Fleet triage and fleet pulse, `HUB-012` | The right daily signal for failing workflows. Wrong shape for a commit's own rollup, for cancelled-only heads, and for ending at a resolution. Read their issues as blocking items. |
| The PM review, `HUB-077` | The right batched reader of pull-request state. It reports and plans project edits. Reuse the reader. |
| The issue pipeline, `HUB-004` | The right executor for a routed fix. It never merges. Hand off to it. |
| JEV ratify's merge guard, `HUB-061` | The right shape for a guarded merge. Copy the shape. |
| GitHub auto-merge | Merges when the branch's requirements are met. It knows nothing of the gated categories, the per-repo constitution or § 12.2's live re-check, and it uses whatever merge method the repo allows. Do not adopt as the executor. |
| GitHub merge queue | Prevents one class of red branch. It needs branch protection, which only the maintainer changes, and it resolves nothing that is already red. Complementary, and a settings decision. |
| Mergify, Kodiak, bors | A third-party service with write access to every repo and its own rule language beside § 12. Do not adopt. |
| Prow Tide and a tree-status bot | The closed-tree idea is worth keeping: while a default branch is red, the blocker is the only thing the resolver considers. The machinery is far too large for this fleet. Adopt the idea. |
| Dependabot or Renovate auto-merge | Dependency pull requests only. Not a resolver. |

Decision (proposed): build a small command on the readers the hub already has, with GitHub's own rollup as the definition of red and the constitution's § 12 as the only merge rule. Adopt the PM review's gather, JEV's trusted-author list and merge-guard shape, the § 11 service for the draft state, and the OPS remote-write path for re-runs and issues. Adopt no outside merge bot.

For the CI review loop (§ 20) the need is narrower: six of the seven red heads were the CI's own doing, and seeing that meant reading a caller, the shared workflow it calls and the action that workflow calls, in three repos.

| Option | Fit |
| --- | --- |
| `actionlint`, already a hub gate | The right check of a workflow's syntax and expressions. It reads one file and no run, so it cannot say a workflow ran when it should not have. Keep it as the gate. Run it on every proposed diff. |
| The workflow atlas lint (`tools/dash workflows lint`), `HUB-034` | The right standards for the hub's own workflows. It does not read a fleet repo's caller or a run. Reuse its rules where they apply. |
| Actions usage flags and the doctor, `HUB-017`, `HUB-012` | The right signal that a workflow is `cancel-heavy` or `flaky` over two weeks, and the doctor already turns it into issues. It ranks by cost, does not follow a call into another repo and does not anchor a fix to a line. Link its issues. Use its flags as evidence. |
| A static security linter for workflows, such as zizmor | The right reading for permissions and injection. A different question from selectivity. Not adopted here. |
| A hosted flaky-test or CI-insight service | A third party with read access to every repo and its logs. Not adopted. The one idea kept is that flaky needs a passing re-run as proof. |

Decision (proposed): build the trace and the rule table as the read-only `ci-review` subcommand on the resolver's readers, adopt `actionlint` as the check on every diff it proposes, and adopt the doctor's issues as the dedupe list.

## 15. Eval set

Constitution § 13.1 asks each loop to keep about 20 real past tasks. The seven repos of § 1, as they stood on 11 November 2026, are the first seven: the input is each repo's rollup, failing contexts and log signature; the expected output is the class, the blocking item and the next step recorded in the pull request that added this document. A miss in production becomes a case, and a row in the signature table. The CI review loop keeps its own cases beside them: the findings of § 20.8, each a workflow at a commit with the flag, the evidence lines and the diff that were expected.

## 16. Phases

P0 is this pull request. Later phases are implementation, which constitution § 26 sends to Claude Code after the maintainer accepts this PRD, as sub-issues of one epic on the Fleet project (§ 10.2). This pull request files none of them.

| Phase | What lands | Acceptance |
| --- | --- | --- |
| P0, this pull request | This sub-PRD and two feature fragments | Schema, governance and numbering checks pass. No workflow, schedule, script, setting or secret is touched. |
| P1, read-only command | `scan`, `plan`, `ci-review`, the report and the eval sets, local first, no model | The seven cases of § 15 classify as recorded, and the findings of § 20.8 come out with the same flags and lines. An unreachable repo, a pending head and a no-checks head are each reported as such. Nothing is written to GitHub. |
| P2, the loop and the surfaces | The scheduled read-only workflow with its switch, the snapshot, the console view, the MCP read tool and the editor entry | The loop is off by default, runs inside its time and rate budget, and publishes through `publish-data`. A person and an agent read the same rows. |
| P3, confirmed writes | Marking ready through the § 11 service; re-runs and handoff issues, including the CI review's diffs, through the OPS remote-write path | Each write is a plan first, applied only on confirmation, audited, and refused when scheduled. A duplicate issue is never filed, and a kit defect is one hub issue, not one per repo. |
| P4, merge in a local session | The guarded merge of § 7, at tier high, with the allowlist of § 9 empty | A merge happens only for an allowlisted repo, a mergeable ungated blocker and a confirmed plan, with `--merge --match-head-commit`. Every refusal case in § 13 has a test. The re-check reports the final state. |
| P5, unattended merge | Only if the amendment in § 17 is ratified | Out of scope until then. |

Verification of P0 is `skip-evidence`: a document and two catalog fragments, with nothing a user can exercise ([VERIFICATION.md](../VERIFICATION.md)).

## 17. Governance fit, and the follow-up amendment (not written, not ratified)

Everything through P4 fits the rules as they stand. Reads are read-only tools (§ 10.6). Marking ready is on the § 11.1 allowlist. Re-runs and issues use the § 11.8 path. A merge in a local session is the agent's own merge under § 12.2, made by the maintainer or by Claude Code, which is the executor under § 26.1, on a plan the maintainer confirmed.

One thing does not fit, and this PRD does not do it. § 11.2 says the console's write-back never merges, and § 11.8 says the OPS remote-write path never merges and refuses scheduled runs. Amendment 0009 left § 11.2 unchanged. § 13.6 starts a merge at tier high, which waits for the maintainer's yes, and a scheduled job has nobody to ask. So a console job, an MCP tool or a scheduled workflow may not perform the merge, and the loop in § 11 does not. Letting one do so is a change to the constitution, proposed with `**Number:** NEW` and ratified only when the maintainer merges it.

Proposed slug, for a later pull request, and only if unattended merge is wanted: `red-main-unattended-merge`. It would say which job may merge the blocker of a red default branch, under which guard, at which § 13 tier, and with what audit, in the way `ratification-records` did for `jev ratify`. `Affects` would name § 11, § 12, § 13, `FR-NEW:red-main-resolve` and `HUB-NEW:red-main-resolver`. Until the maintainer merges it, no unattended job merges.

## 18. Cost

| Tier | What | Cost |
| --- | --- | --- |
| 0 | Detection, diagnosis by signature, classification, the report, the re-check, and the CI review's trace, rules and diffs | No model. One GraphQL point for detection, and bounded REST reads for the red repos. Actions minutes for the daily job are read from the billing meter once it runs. |
| 1, optional, later | A capped model reading of an `unclassified` failure, in a local session | API-equivalent (estimate), inside `_data/fleet.yml` `budget:`, off unless a person runs it. Its reading is advice in the report. It starts no action. If it is added, the step is registered in `_data/agents.yml` with its KPIs (constitution § 29). |

## 19. Open questions

- The ready-intent marker. Proposed: the body line `Ready-for-review: intended` or the label `ready-when-green`. The alternative is to leave every draft to its author and to tier 3.
- Where the merge allowlist lives. Proposed: `_data/fleet.yml` `red_main.merge.repos`. The alternative is a field on the registry row.
- Whether a cancelled-only head is shown as red on the public snapshot, or as its own state. Proposed: its own state, counted with red.
- Whether the re-run belongs here or to the fleet doctor. Proposed: here, because it is the resolution of a red head and not of a failing workflow.
- The schedule slot. Proposed: 06:07 UTC daily.
- Whether the hub's own default branch is in scope. Proposed: yes, as a row like any other, with every hub pull request that touches a gated path held.
- Whether the CI review samples failed pull-request runs by default. Proposed: no in the scheduled loop, to spare the quota, and three per repo on demand.
- How a rejected CI review finding is remembered. Proposed: a ledger entry keyed on repo, file, lines and rule, so the same finding is not raised again until the file changes.

## 20. The CI review loop — `FR-NEW:red-main-ci-review`

§ 6 asks why a run failed. The CI review loop asks a second question about the same run: was the CI right to run, and right to fail? A red default branch is often the CI's own doing. Of the seven repos in § 1, one failed on a real defect. The other six were red because of how a workflow was triggered, grouped or guarded (§ 20.8).

The loop is read-only from end to end. Its product is findings and diff suggestions. It edits no workflow, script, setting or secret, in any repo. Feature `HUB-NEW:red-main-workflow-review`.

### 20.1 Inputs

- Each failed or cancelled run behind a red default branch that § 5 found.
- Optionally, a capped sample of failed pull-request runs in the same repos (`--sample-prs N`, newest first). A pull request that reads as failing for a reason that is not a defect is the same waste in another place, and it stops the resolver from marking a draft ready (§ 7).

### 20.2 What one pass does

1. **Investigate.** The failed jobs and steps of the run and the failed step's own log lines, read as `gh run view --log-failed` reads them, with the run's event, actor, head ref and attempt, and the sibling runs of the same workflow on the same ref within a short window, which is where cancels and duplicates show. Log lines are taken by step, never from the tail of the job: a service container's teardown log follows the failed step and buries it. In `law-ai`'s failed run the test summary starts at line 12,741 of 13,680.
2. **Trace.** The workflow file is read at the run's own commit, not at the branch's current head. The loop reads `on:` (events, activity types, `branches`, `paths`, `paths-ignore`), `concurrency`, `permissions`, each job's `if`, `needs`, `strategy.matrix`, `timeout-minutes` and `continue-on-error`, and each step's `if`. It follows every `uses:` the fleet owns: a reusable workflow at the ref the caller names, in the hub or in `bamr87/.github`; a composite action's `action.yml`; and a script in the repo that a `run:` step calls. Depth and file count are capped. A third-party action is named and not followed. The result is a call graph in which every fact has a file and a line.
3. **Judge.** The rules of § 20.3 give each run's workflow one or more flags: `over-broad`, `under-selective`, `misconfigured`, or `ok`.
4. **Propose.** For every flag but `ok`, the minimal fix as a unified diff against the file at the reviewed commit: a condition, a path filter or a change of logic. One finding, one diff. The patched file is checked with `actionlint` in a scratch copy before the diff is printed. The diff is text in the output and is never applied. § 20.4 says where it goes.

### 20.3 The rules

| Flag | Rule | Fires when | Evidence it must cite |
| --- | --- | --- | --- |
| `over-broad` | event breadth | A `pull_request` trigger lists an activity type (`labeled`, `unlabeled`, `edited`) that no job condition narrows, so every such event starts a full run. | The `types:` line and the runs it started. |
| `over-broad` | bot runs | The run's actor or head branch is a bot's (Dependabot, release-please, the Actions bot) and the workflow has no condition for it, where the job needs a secret such a run cannot read, or is a content or docs check that constitution § 19.6 says to skip. | The run's actor and the trigger or job block that lacks the condition. |
| `over-broad` | path breadth | A costly job (service containers, a matrix, a long runtime) ran for a change whose files it does not read, and the workflow has no `paths`, `paths-ignore` or in-workflow filter. | The changed files and the trigger block. |
| `over-broad` | detection breadth | A job runs because a file exists, not because the repo opted in. | The detecting line and the job's `if`. |
| `under-selective` | optional credential | The step failed for want of a secret, a permission or an outside registration that the workflow documents as optional, or that a fork or a bot run cannot have. | The failing log line and the line that documents it optional. |
| `under-selective` | flaky infrastructure | The failure is a network, registry or runner signature, and a re-run of the same commit passed. Without that proof the rule does not fire. | Both runs. |
| `under-selective` | generated files | A lint or format step failed on a path the repo marks generated (`.gitattributes`, a `CHANGELOG.md` that release-please owns). | The failing path and the line that marks it. |
| `under-selective` | strict up-to-date | Branch protection requires a branch to be up to date, and green pull requests sit `BEHIND` after every merge. This is a settings finding. | The protection read and the pull requests. |
| `misconfigured` | concurrency | A workflow that can run twice for one ref has no `concurrency`; two different events share one group; or `cancel-in-progress` can cancel a default-branch or release run. | The `concurrency` block, or its absence, and a cancelled run. |
| `misconfigured` | duplicate runs | The same workflow ran more than once for one commit within seconds. | The runs and the events that started them. |
| `misconfigured` | dead job | A job's `if` cannot be true under the workflow's triggers, or the job was skipped in every run of the window. | The `if` line and the trigger block. |
| `misconfigured` | wrong reference | A `uses:` names a ref where the file does not exist (a run with zero jobs), or a branch where UPS-WORK-10 requires a tag or a full SHA. | The `uses:` line and the read of that ref. |
| `misconfigured` | error noise | A step or a service writes an error line on every run, failed or not, which buries the real failure. | The line that causes it and a count from the log. |
| `ok` | none | No rule fired. The CI ran for a relevant change and failed on a real defect. The fix is in the code, and § 6 has already routed it. | The filter that selected the job and the failing lines. |

The rules are deterministic and cost no model. A condition the loop cannot evaluate statically is quoted, its rule is skipped, and the finding is marked advisory. An optional model reading (§ 18, local, capped) may explain a finding. It adds no flag by itself.

**The loop never proposes weakening a check.** `continue-on-error`, a lowered threshold, a removed test or a wider skip is never the proposed fix for a failure that no rule has shown to be a non-issue. A real defect is flagged `ok` and left to § 6.

### 20.4 Where a proposal goes

| The fix touches | Route | Who acts |
| --- | --- | --- |
| A workflow, a composite action or a script in one repo | A handoff issue carrying the finding, its evidence and the diff, filed through the filing row of § 7 | Claude Code implements it (constitution § 26.4). The pull request touches a workflow, so § 7 holds it and the maintainer merges it. |
| A file a kit seeds, byte-identical in several repos | One hub issue against the kit, with the repos listed, and a fan-out proposal that stays a dry run by default | Claude Code changes the kit. The fan-out opens the pull requests. |
| A shared workflow or action in the hub or in `bamr87/.github` | One issue in the repo that owns it | Claude Code. If callers get the change only through a tag, cutting that tag is the maintainer's. |
| A setting, a secret, branch protection, a ruleset, a tag or an external service | The maintainer's list (§ 8), with exact steps | The maintainer, always. Never an agent. |
| Something an open issue already covers, a `fleet-doctor` issue included | The issue is linked. Nothing is filed. | Whoever holds that issue. |

### 20.5 Output format

One record per finding, kept under `.fleet/runs/<run_id>/ci-review.json` and rendered as a Markdown table with the columns of § 20.8.

```yaml
- repo: bamr87/bashcrawl
  workflow: .github/workflows/verify.yml
  run: 42773085298                 # the failed or cancelled run that was reviewed
  commit: 51a332c7                 # the workflow was read at this commit
  flag: misconfigured              # over-broad | under-selective | misconfigured | ok
  rule: concurrency
  confidence: rule                 # rule | advisory
  evidence:
    - {file: .github/workflows/verify.yml, lines: "41-43", fact: "one group for every event on a ref, cancel-in-progress"}
    - {run: 42773111397, fact: "a label event on merged PR 139 started three seconds before the cancel"}
  fix:
    touches: kit                   # workflow | action | script | kit | shared | settings
    route: claude-code             # claude-code | maintainer | linked
    covered_by: null               # an open issue that already covers it
    diff: |
      -  group: verify-${{ github.ref }}
      +  group: verify-${{ github.ref }}${{ (github.event.action == 'labeled' && github.event.label.name != 'verify') && format('-{0}', github.run_id) || '' }}
```

A pass also prints its totals: runs reviewed, runs not reviewed and why, findings per flag, and the reads it spent.

### 20.6 Guardrails

These add to § 12. Where both speak, the stricter one holds.

| Guardrail | Rule |
| --- | --- |
| Read-only, dry run by default | There is no `--apply` for a diff. The loop reads and prints. The only write it can lead to is a handoff issue, which is a plan first and is filed only on confirmation (§ 7). |
| Time budget | Proposed: 10 minutes a pass, 90 seconds a run, a trace depth of 3 and 40 files a run. At a limit the pass stops and lists the runs it did not review. |
| Rate limits | Proposed: at most 30 reads per reviewed run and 3 sampled pull-request runs per repo. A file whose blob was already read is not fetched again, so a kit file shared by seven repos is read once. The loop shares the resolver's floor on `rateLimit.remaining` and its `Retry-After` rule, and it never runs on a pull-request or push check. |
| Audit trail | One append-only record per reviewed run and per finding: the run, the workflow path, the commit, the blob of every file read, the rule, the flag, a hash of the diff, where it was routed, and the issue if one was filed. Token values are redacted. |
| Kill switch | The resolver's central switch stops the review too. The review also has its own entry in the same map, so it can be paused while detection continues. A switch that cannot be read is treated as off. |
| Secrets | The loop reads secret names as they appear in workflow text and never a value. A presence test such as `secrets.X != ''` is read as text and is not evaluated. Log lines are redacted before they are stored. |
| Untrusted input | A log, a workflow comment or a pull-request title from a fork is data. Nothing in it is executed or followed as an instruction, and the sampled pull-request path sends nothing outside the hub (constitution § 13.8). |

### 20.7 Design for Failure

| Failure | Detection | Behaviour | Recovery | What is learned |
| --- | --- | --- | --- | --- |
| The workflow cannot be read at the run's commit | A `404`, or a private repo the token cannot read | The finding is `untraced`. No flag. | The next pass, or a person. | A workflow that was not read is not judged. |
| A called workflow's ref moved after the run, or names nothing | The ref resolves to another commit than the run used, or to a `404` | The commit it resolves to now is recorded, and the finding says the ref may have moved. A file missing at the ref is itself a wrong-reference finding. | A tag cut, by the maintainer. | Tags move. The run's own commit is the record. |
| A third-party action is in the chain | A `uses:` outside the fleet's owners | Named, not followed, not judged. | None needed. | The scope is the fleet's own CI. |
| A condition cannot be evaluated statically | The expression reads a runtime output or builds a matrix from one | The condition is quoted, the rule is skipped, the finding is advisory. | A person reads it. | No guessed truth value. |
| The failed step's lines cannot be isolated | The log has no step boundary | The cause is `log unread`. The tail is not used in its place. | The next pass. | A tail is service noise as often as it is evidence. |
| A rule fires on a deliberate design | The maintainer rejects the finding | It is recorded as rejected with the reason, and is not raised again until the file changes. | None needed. | The ledger is the loop's memory. |
| The diff no longer applies | The file changed after the reviewed commit | The diff is rebuilt at the new commit or dropped. It is never applied loosely. | The next pass. | A diff belongs to one blob. |
| The proposed diff is not a valid workflow | `actionlint` fails on the patched scratch copy | The diff is dropped. The finding is kept without a fix and says why. | A person writes the fix. | A suggestion that does not parse is worse than none. |
| One defect sits in a kit file in many repos | The same blob in several repos | One finding against the kit, with the repos listed. | A kit change and one fan-out. | One issue, not seven. |
| A failure looks flaky and is not proven | No passing re-run of the same commit | The rule does not fire. The flag stays `ok` or the cause stays `unclassified`. | A re-run under § 7, then the next pass. | Flaky needs proof. |
| The minimal fix would weaken a real check | The proposal skips, lowers or removes a check on a finding no rule cleared | The proposal is dropped. The finding stays `ok` and goes to § 6. | The code fix. | The loop makes CI more exact, never more lenient. |
| The fix touches a setting, a secret, protection or a tag | The route table of § 20.4 | It goes to the maintainer's list with exact steps, never to an agent. | The maintainer. | Constitution § 12.3. |
| The rate floor or the time budget is reached | The counters | The pass stops with a partial result and lists what it did not review. | The next pass. | The review never spends what the other loops need. |
| An issue already covers the finding, or the issue list cannot be read | The dedupe read | Covered: linked, nothing filed. Unreadable: nothing filed. | The next pass. | No duplicate issues. |
| The kill switch is off or unreadable | The switch map | Nothing is done. | The maintainer flips it. | Unreadable is off. |
| Claude Code is unavailable or out of budget | The handoff issue sits | The diff waits in the issue. Nothing else implements it. | The maintainer decides (constitution § 26.5, § 28.6). | The loop proposes. It does not execute. |

Risk tier (constitution § 13): the whole loop is low. It has no write of its own.

### 20.8 First application: the seven red default branches, 11 November 2026

Applied by hand, read-only, to the failed runs of § 1, with two failed pull-request runs sampled in `fredgar-ai`. Line numbers are those of each file at the red head. These rows are the loop's first eval cases (§ 15).

| Repo | Workflow | Flag | Evidence | Minimal fix proposed |
| --- | --- | --- | --- | --- |
| `bamr87/law-ai` | `ci.yml`, job `Backend Tests + Coverage` | `ok` | `ci.yml:31-37` filters paths inside the workflow, `:248` runs the job only when `backend/**` or `ci.yml` changed, `:293` runs `pytest`. The run was started by an edit to `ci.yml:83` and failed on 666 real test failures and errors. | None in CI. The defect is in a test, and [law-ai#214](https://github.com/bamr87/law-ai/pull/214) fixes it. |
| `bamr87/law-ai` | `ci.yml`, the call to `spec-gate.yml` | `misconfigured` (wrong reference) | `ci.yml:83` named `spec-gate.yml@v2`, a ref where that file does not exist. All ten CI runs on `main` from 2026-10-30 to 2026-11-10 had zero jobs, so no test ran there for twelve days, and the first run that did start, on 2026-11-11, failed. The line is now pinned to a hub commit as a workaround. | The maintainer cuts the hub tag so `v2` carries `spec-gate.yml` (hub [#457](https://github.com/bamr87/bamr87/issues/457)). Then one line, by Claude Code: the commit pin back to `@v2`. |
| `bamr87/law-ai` | `ci.yml`, the postgres service | `misconfigured` (error noise) | `ci.yml:264`: `--health-cmd pg_isready` probes as `root`, and 89 `FATAL: role "root" does not exist` lines follow the test summary in the failed log. | `--health-cmd pg_isready` becomes `--health-cmd "pg_isready -U postgres"`. |
| `bamr87/law-ai` | required checks | `misconfigured` (settings) | `.github/rulesets/main-required-checks.json:30-38` names four required checks. The API lists no ruleset and no branch protection, so a pull request can merge while CI is red or cannot start. | The maintainer decides whether to import that ruleset. Never an agent. |
| `bamr87/fredgar-ai` | `release.yml`, into `bamr87/.github` `publish.yml@v1`, job `PyPI` | `over-broad` (detection breadth) | `publish.yml:135` runs the upload whenever `actions/detect-stack/action.yml:51` finds a `pyproject.toml`, and this repo's holds a project name, tool settings and no build system. The RubyGems and npm jobs test a credential first (`publish.yml:85-89`, `:120-124`). The PyPI job has no test and no opt-out. | In `bamr87/.github`: a boolean input `pypi`, default `true`, and `if: inputs.pypi && needs.detect.outputs.python == 'true'` at `publish.yml:135`. Then `pypi: false` under `with:` at `release.yml:29-31` here. [fredgar-ai#130](https://github.com/bamr87/fredgar-ai/pull/130) describes the same change. |
| `bamr87/fredgar-ai` | `release.yml` | `misconfigured` (concurrency, wrong reference) | `release.yml:7-16` has no `concurrency` block, where the fleet's caller has one. `publish.yml:57` calls `detect-stack@main` and `:149` calls `pypa/gh-action-pypi-publish@release/v1`: branch refs inside a tagged workflow. | Add `concurrency: {group: "release-${{ github.ref }}", cancel-in-progress: false}`. Pin the two refs to a tag or a SHA. |
| `bamr87/fredgar-ai`, `bamr87/bashcrawl`, `bamr87/scripts` | `verify.yml` (verify kit 0.1.0, the same bytes in all seven repos) | `misconfigured` (concurrency, duplicate runs) and `over-broad` (event breadth) | `verify.yml:41-43`: one group for every event on a ref, with `cancel-in-progress`. `:24`: `labeled` starts a full run for any label, though only `verify` matters (`:54`). `:25-26`: a push run that a label event on a merged pull request then cancels. `:47`: `@main`, a branch ref. Sampled pull requests: `fredgar-ai` drafts 131 and 132 read `FAILURE` only because the `automation` label, one second after opening, started a duplicate run that was cancelled. | Kit 0.2.0, already in the hub (`templates/verify/verify.yml:32-35`, `:53-55`, `:59`): no push trigger, a group of its own for a label that is not `verify`, and a job `if` that skips it. One kit fan-out, not three issues. Hub [#649](https://github.com/bamr87/bamr87/issues/649) covers `law-ai`. |
| `year-of-ai/year-of-ai.github.io`, `bash-365/bash-365.com`, `bash-365/bash-365-apex` | `release.yml`, into the hub's `release-please.yml@v2` | `under-selective` (optional credential) | `release.yml:28` pins `@v2`. `release-please.yml@v2:103-106` is one step with `token: secrets.RELEASE_PLEASE_TOKEN \|\| github.token` and no guard, and `:58-63` documents that secret as optional. The guarded version is on the hub's `main` only. | The maintainer moves `v2`. Or, by Claude Code through the SDLC kit, the gate `bamr87/scripts` already has at `release.yml:45-77`: a `preflight` job that outputs `armed`, and `needs: preflight` with `if: needs.preflight.outputs.armed == 'true' \|\| github.event_name == 'workflow_dispatch'` on `release`. Releases resume only with a credential, which is the settings step of § 1. |
| `bamr87/bashcrawl` | branch protection | `under-selective` (strict up-to-date) | The protection read gives `required_status_checks.strict: true`, and three green pull requests are `BEHIND`. `Verify` is not a required check, so its cancelled run blocks no merge. | The maintainer's choice: keep strict and accept one branch update per pull request, or turn strict off. Never an agent. |
