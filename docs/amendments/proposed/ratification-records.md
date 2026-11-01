<!-- kit: governance v0.1.0 -->
# NEW — The post-merge job records ratification, acceptance and completion, and merges that record itself

- **Status:** proposed
- **Number:** NEW
- **Date:** 2026-11-01
- **Proposed by:** agent (Claude Code, on a branch opened for bamr87 at the maintainer's request of 2026-11-01)
- **Ratified by:** the merged PR URL (leave blank until merged)
- **Affects:** constitution § 8.3; § 12.3 (ADRs join the gated list, and the ratification-record carve-out); § 10.1 (a record PR that merges is not a project item); § 13.6 (the job's merge action is tagged and tiered here); `docs/adr/README.md` (ADR acceptance by merge, completion by the tracking epic); `docs/amendments/SCHEMA.md`, `docs/amendments/proposed/SCHEMA.md` (status lines are recorded, not edited); `.github/workflows/jev-number.yml` (new job `ratify`, kill switch `vars.JEV_RATIFY_ENABLED`); feature `jev-ratify` (HUB-NEW:jev-ratify); requirement FR-NEW:ratification-records
- **Supersedes:** none (extends amendment 0002's post-merge job; leaves § 12.2 and § 12.5 as they are)
- **Related:** epic bamr87/bamr87#484 and ADR 0002 (the record that prompted it), amendment 0005 (the one correctly recorded ratification), 0008 `harness-prior-art-research`, 0009 `agent-merge-review-gate` (§ 12), bamr87/bamr87#501 and #505 (HUB-056, the governance records lint), `central-loop-switches` (its stale slug reference to its own requirement is resolved to FR54 in this PR, which unwedges numbering), [docs/JEV.md](../../JEV.md#ratification-records)

## Context

§ 8.3 says merging an amendment's pull request ratifies it and that the record then says `Status: ratified` and `Ratified by:` the PR. Nothing writes that. `tools/jev/number.py` numbers a record after the merge but copies its pre-merge `proposed`, so 11 of the 13 merged amendments (0002–0004, 0006–0013) and their index rows still read `proposed`; only 0005 was fixed by hand. ADRs have the same gap: ADR 0002 merged in #521 (header) and #523 (its P1 section) and still says `proposed` twice. Nothing says who accepts an ADR or when, and nothing records when the epic that delivers it is done.

On 2026-11-01 the maintainer ruled that merging the PR that adds an ADR means it is accepted, and asked for this to be automated: "a separate PR is automatically created and merged with all necessary information and triggers for ratification and/or completion."

As written, § 12.3 gates any PR that touches amendments, so a bot-made PR that only writes these status lines could never be merged by the job that opens it. The decision itself is already made by the maintainer's merge; the record of it is clerical. This amendment carves that one clerical change out of the gate, and nothing else.

## Prior art

Per 0008, existing fleet assets and external patterns come first.

**Fleet assets**

- **jev-number.yml and `tools/jev/number.py` (amendment 0002):** already runs serialized on `main` after every merge and already writes amendment records. Fit: the trigger and the serialization. Extend with a `needs:` job; leave the compiler's behaviour as it is.
- **publish-data:** pushes or falls back to a PR, but squash-auto-merges, which § 12.2 forbids. Not reused for this PR; its bot identity is.
- **resolve-fleet-token:** probes `FLEET_TOKEN`. Reuse: a PR made with `GITHUB_TOKEN` gets no CI, so it could never be proved.
- **JEV's guard (`common.assert_no_admin`):** the Python never merges. Keep: only the workflow step merges.

**External patterns**

- **EIP bot, Rust RFC merge procedure:** the record is stamped at the merge, in the merge pipeline. Adopted: the stamp follows the merge mechanically.
- **changesets, release-please:** derive the action from repository state, and keep one stable bot PR. Adopted: the plan is computed from `main`'s state, so it is idempotent and heals a missed run.
- **adr-check, KEP validator:** lifecycle fields are machine-maintained metadata and the body is immutable. Adopted: the diff is limited to status lines.
- **PEP Accepted vs Final, KEP implementable vs implemented:** decision and completion are separate events. Adopted: acceptance fires on the merge; completion fires when the tracking epic closes.
- **Not adopted:** GitHub's `--auto` merge. `main` has no required checks, so it would merge before CI; the job waits for the checks itself. A merge queue is not available here, and an FCP-style vote has nothing to count with one maintainer.

## Amendment

Replace constitution § 8.3 with:

> 3. **Ratify** — merging the PR ratifies it. The record says `Status: ratified` and `Ratified by:` the PR. A rejected or withdrawn PR keeps its record with that status; numbers are never reused. The post-merge job records it: `jev-number.yml`'s `ratify` job (`python3 -m tools.jev ratify`) sets `Status: ratified`, writes `Ratified by:` as the PR, its merge date and who merged it, and sets the index status cell, through a ratification-record PR (§ 12.3), only for a record whose PR the maintainer merged. Recording these lines is not an edit to a ratified rule. _(amendment `ratification-records`)_

In constitution § 12.3, add architecture decision records to the gated list, after "a fleet standard;":

> an architecture decision record (`docs/adr/`), whose merge accepts it;

and add to the end of § 12.3:

> A **ratification-record PR** is not gated. It is opened by the post-merge job from this repository's own `chore/jev-ratify` branch, and it changes only status lines, `Ratified by` / `Accepted in` / `Completed` lines and index status cells of records whose trigger PR the maintainer merged (not from an automation branch, not opened by a bot), or whose tracking issue the maintainer closed as completed with every sub-issue closed. That job merges it with a merge commit only when `python3 -m tools.jev ratify guard` says go: the head is one commit on the current tip of `main`, every check on that commit has passed, and the diff is exactly the plan it was built from, each of whose triggers still holds. It needs no Fleet project item (§ 10.1) unless the guard refuses it; then the job labels it `needs-amr` and sets its item to *Needs Amr* (item 4). Anything else on that branch, and any change to that guard or job, is gated. _(amendment `ratification-records`)_

Record the maintainer's ruling of 2026-11-01 in `docs/adr/README.md`:

> The maintainer's merge of the PR that adds an ADR, or adds a phase section with its own Status line, accepts it. Because that merge is the acceptance, a PR that adds or changes an ADR is gated (constitution § 12.3): no agent merges it. The post-merge job then sets `accepted`, adds `- **Accepted in**:` the PR, and updates the index row. An ADR may name `- **Tracking**: #N`; when the maintainer closes that issue as completed with every sub-issue closed, the job adds `- **Completed**: <date> (#N closed)`.

The mechanics, which the job must keep:

1. **Trigger, from state.** An amendment's trigger is the merged PR that added `docs/amendments/proposed/<slug>.md` on `main` before the numbering commit that created the record (a later re-proposal of the slug never names an older record), or, for a record numbered by hand, the PR that added the numbered file. An ADR Status line's trigger is the merged PR that introduced that exact line on `main` (`git blame`). A completion's trigger is the tracking issue, closed as completed by the maintainer, with every sub-issue closed. A PR counts only when it is merged into the default branch by the maintainer, did not come from one of the hub's automation branches (the stable `branch:` of a workflow, `chore/jev-ratify`, `wtd/*`, `dependabot/*`) and was not opened by a bot. A record whose `Ratified by` or `Accepted in` already names a different PR is not touched. Every record not recorded is listed as skipped with the reason; a GitHub read that failed skips only that record, says so, and the next run retries it.
2. **Only status lines.** The PR touches only `docs/amendments/NNNN-*.md`, `docs/amendments/README.md`, `docs/adr/NNNN-*.md` and `docs/adr/README.md`, and in them only the lines named in § 12.3, never inside a fenced code block. `ratify check-diff` compares bytes (a line ending counts) and refuses a file-mode change, an added or deleted file, and any other byte.
3. **Its information.** The PR body names, for every record, the trigger PR (number, title, merge date, who merged it, merge commit), the issues it linked, the records skipped and why, the tracking issues still open, the guard that will merge it, and the plan it was built from (its record keys and digest, in an HTML comment). It never carries a GitHub closing keyword before a reference, so its own merge closes nothing.
4. **The merge.** The job merges only on two "go" verdicts in a row from `python3 -m tools.jev ratify guard --pr N --sha SHA --plan F`: the PR is the job's own (this repository's `chore/jev-ratify`, opened by the maintainer's token, never a fork's branch of that name) and open; its head is `SHA`, one commit whose only parent is `main`'s live tip; it carries no `needs-amr`, `agent:hold` or `blocked`; every check run and commit status on `SHA` completed as success, skipped or neutral, and there is at least one; GitHub reports it mergeable; and the diff is exactly plan `F`, each of whose triggers still holds when re-read. Then `gh pr merge --merge --match-head-commit SHA`: a merge commit, never squash, `--admin`, `--auto` or a force-push. The guard's other answers: *not yet* (a check running, a GitHub read that failed) waits up to 30 minutes and then ends with a warning; *re-cut* (`main` moved) plans again from the new tip, at most three times in a run; *stop* (merged, closed or held by a person) leaves it. A record that became eligible while it waited is recorded by the next run and never fails the guard. Only *refuse* (the diff is not the plan, a trigger no longer holds, a check failed, the head moved) labels the PR `needs-amr`, comments the reason, sets its Fleet project #14 item to *Needs Amr* when the token has the project scope, and fails the run.
5. **Brakes.** `vars.JEV_RATIFY_ENABLED` turns the job off (`'false'`); a manual dispatch bypasses it, and a dispatch with `dry-run` only prints the plan and the PR body. A hold label on the open record PR stops it. A record PR the maintainer closes unmerged holds that same plan until a manual dispatch or a change to the plan; the job never reopens it.
6. **Risk tier (§ 13.6).** The job's merge is tagged *reversible: yes* (by a revert PR), *external: no* (it writes only this repository), *money: no*, and it is **medium**: it runs alone, with the PR, its body and the run log as the audit record. This amendment sets that tier, and ratifying it is the maintainer's yes; § 13.7's ladder applies to agent roles, and this is a deterministic job that runs no model. Changing the guard or the job is gated (§ 12.3, § 13.9).

## Consequences

- The first run after this merges records the 11 stale amendments, ADR 0002's header and P1 Status lines, and this amendment itself, each with its trigger PR. `tools/jev/number.py` still copies `proposed` when it numbers a record; the ratify job corrects it in the same workflow run.
- `governance_lint`'s planned check that a merged amendment says `ratified` (HUB-056, #505) can become an error once this job has run once.
- What a merge cannot tell: `merged_by` is `bamr87` for the maintainer's own merge and for a merge made with `FLEET_TOKEN` alike. This amendment closes that gap by rule, not by data: amendments and, from now on, ADRs are gated (§ 12.3), so no agent may merge the PR that decides them, and the planner also refuses a trigger from an automation branch or a bot. The residual, stated plainly: until a distinct bot identity exists, a `FLEET_TOKEN` merge of a gated PR would be indistinguishable from the maintainer's, and the job would record it; § 12.5 forbids that merge. A GitHub App identity for bots would make it checkable; that is the maintainer's to create.
- ADR PRs are now gated. An ADR still goes in the same PR as the change it justifies, so that PR waits for the maintainer's merge.
- This PR also changes one merged record outside the carve-out: `docs/amendments/proposed/central-loop-switches.md`'s `Affects` named its requirement by the `central-loop-switches` slug, which #527 had already compiled to FR54, and that unresolved slug reference wedged `jev-number.yml` (slug references resolve only within one run). It now names FR54. That is the substitution the compiler itself makes, not a change to the ratified rule.
- Not in scope: rewriting `numbered at merge` notes in the constitution, slug references left in compiled records, and feature-catalog status changes. Each needs its own rule.
- Merging the pull request that carries this record ratifies it. An agent never merges it.
