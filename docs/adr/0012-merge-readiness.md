# ADR 0012 — Merge readiness: every pull request is checked, reviewed and adjusted before it merges, and says so in one place

- **Status**: accepted
- **Accepted in**: https://github.com/bamr87/bamr87/pull/917 (merged 2026-11-18 by @bamr87)
- **Date**: 2026-11-17
- **Deciders**: proposed by an agent at the maintainer's request (2026-11-17: redesign the commenting, analysis and review of each pull request after it is marked ready and after its CI results, so that every check, review and adjustment is done before a merge)
- **Related**: constitution § 12 (merge authority and the review gate), § 15 (evidence and the completeness review), § 19 (fleet PR review and comments), § 28.3 (direction review); HUB-117 (the PR queue); bamr87/bamr87#863 and #905 (who merges from the console), #880 (inline findings), #492 (QA Lead), #565 (bot identity)

<!-- Accepted in and Completed are added by the post-merge ratify job when the maintainer merges this ADR's PR and when the maintainer closes the Tracking issue as completed (docs/adr/README.md#lifecycle). -->

## Context

### Needs assessment

Measured on 2026-11-16 and 2026-11-17, across the 409 open pull requests of the hub and the registry repos:

- **§ 19 is ratified and one item of it is built.** `pr-review.yml` implements § 19.10, the summary of a failed CI run. § 19.7 says an AI review runs when a pull request is opened or marked ready; nothing implements it. No hub workflow runs at all when a pull request is marked ready: the CI workflows use the default event types, which leave `ready_for_review` out.
- **A finished pull request looks the same as one nobody looked at.** bamr87/bamr87#873 was green, gated and labelled for a day, with no comment, no review and no review request. Of the 35 pull requests in its batch none had a comment, and eight were merged with no review recorded. § 19.2 says the summary is deleted when every check is clean, so "clean" and "never examined" are both an empty page.
- **Three steps between opened and merged have no actor.** Nobody marks a finished draft ready (203 of 215 drafts were green; the issue pipeline's third tier does it for four of its own a run). Nobody reviews: a direction verdict (§ 28.3) was on 8 of 409, and the completeness reviewer of § 15.5 is not built (#492). Nobody merges an ungated pull request: no loop does, and the console's merge is off until #905 is decided.
- **What a pull request says about itself drifts.** 229 gated pull requests carried no `needs-amr` label; 266 had no next-action comment and the ones that did were written once, on 2026-11-15; 106 left a "CI is green" task unticked while every check passed.
- **The reviewer GitHub would ask is the author.** Agents open pull requests with the maintainer's token, so the code owner is the author: GitHub requests no review and sends no notification. 162 of 231 comments were posted under that login (#565).

### Prior art survey (§ 10.8)

- **Branch protection, required checks and the merge queue.** Fit: GitHub's own gate; a required status is the one thing that stops a merge. Limits: it says a check is missing, not why or who moves it, and its settings are the maintainer's alone.
- **Prow's Tide.** Fit: one status per pull request that states exactly what still blocks the merge ("needs lgtm, has do-not-merge"), computed from labels and checks. The closest match to the need. Limits: a server to run.
- **Danger.** Fit: rules as code that keep one sticky comment per pull request, rewritten on every run. Limits: it runs the pull request's own rule file, which a `pull_request_target` job must never do.
- **Reviewdog.** Fit: tools emit findings in one format; a poster places them inline and removes duplicates across pushes. This is what #880 builds for § 19.3.
- **Mergify and Bors.** Fit: merge by rule once conditions hold. Limits: a hosted service or a bot with merge rights, which § 11.2 and § 12 do not give.
- **AI reviewers (Copilot code review, CodeRabbit).** Fit: a summary and inline findings on open and on ready. Limits: hosted, no fleet budget or switch, and nothing that knows the review gate.
- **In the fleet.** `pr_review.py` (one sticky comment, untrusted text made safe, state held in the comment), the PR queue's model (checks collapsed, the gate, who moves it next, and since #914 the label, comment and task flags), the queue's capped agent (`fix-ci`, `address-review`) and JEV's conflict tiers.

**Build versus adopt.** Adopt Tide's idea of one place that says what is left, Danger's single rewritten comment and Reviewdog's findings format. Build on the queue's model, so the console, the terminal, the MCP tool and the comment on the pull request can never disagree.

## Decision

1. **One model.** Merge readiness is a function of the PR queue's row: an ordered list of items, each `done`, `todo`, `wait`, `held` or `note`, and one verdict, `ready`, `waiting` or `not-ready`. The review gate is `held`, never `todo`: it is the maintainer's decision and not work, so a gated pull request with nothing else left is ready, for the maintainer.
2. **One place on the pull request.** The § 19 comment carries the failed runs and, under them, what is left. It stays while anything is left. When nothing is, it is deleted as § 19.2 says, and one review per head commit records that the pull request is ready and who merges it. That review is a comment: it never approves and never counts as a required review (§ 19.5).
3. **Every event that changes the answer recomputes it.** A finished workflow (as today), and the pull-request events that start no workflow: opened, reopened, marked ready, converted to a draft, pushed to, labelled, unlabelled, edited. Those arrive through `pull_request_target`, which runs the default branch's file, checks out the hub's tooling only and reads the pull request through the API.
4. **Four stages, each with an actor and an exit.**

   | Stage | Runs when | Does | Exit |
   | --- | --- | --- | --- |
   | A. Readiness | every event above | computes the items from facts and writes the comment or the review; no model, $0 | the verdict |
   | B. Review | opened as ready, marked ready, or the `review` label, once CI is green (§ 19.7); once per head commit | a capped AI code review in a job that holds no GitHub credential and writes a findings file; a second job posts them inline with a severity (#880, § 19.3). The completeness (§ 15.5) and direction (§ 28.3) verdicts are items read by their markers, filled by the reviewers those sections name | findings of severity `error` are `todo` items; none is `done` |
   | C. Adjust | a `todo` a machine can move | a script first (update the branch, regenerate a generated file, add the label), then the queue's capped agent (`fix-ci`, `address-review`), at most two attempts, then `needs-amr` | the item is `done` or a person has it |
   | D. Merge | the verdict is `ready` | a `Merge readiness` status the maintainer may require in branch protection; an ungated pull request is an agent's to merge (§ 12.2), a gated one the maintainer's; the console's merge follows #905 | merged |

5. **Automation speaks as itself.** Every comment and review is posted by `github-actions[bot]` with the run's token (§ 19.5). Nothing in these stages posts as the maintainer.
6. **Switches and spend.** Stage A is behind `vars.PR_READINESS_ENABLED`, off until set to `true`. Stage B is a harness: it lands with its own switch, an exact model, a dollar cap, its `_data/agents.yml` entry and its KPIs (§ 29), skips Dependabot and release pull requests (§ 19.6), and never runs on a plain push.
7. **One comment, not two.** Once readiness is on across the fleet, the queue's `comment` action and the triage comments of 2026-11-15 are retired; a note from the maintainer stays possible as a line in the same comment.

### Phases

| Phase | Delivers | Done when |
| --- | --- | --- |
| P0, this pull request | Stage A in the hub: `readiness` on every queue row, `tools/dash prs ready --pr`, the comment section and the ready review in `pr_readiness.py` (beside `pr_review.py`, which it calls and does not change), the `pull_request_target` trigger, the switch | With the switch on, a hub pull request that is marked ready gets its comment or its review within a minute, and with it off nothing changes |
| P1 | The `Merge readiness` status and pr-review kit 0.3.0 (the stub gains the trigger and `statuses: write`); fan-out | A fleet repo's pull request carries the status, and the queue's `agent_merge` requires it |
| P2 | Stage B: the review harness and #880's poster | A pull request marked ready has a review with findings or "no findings" on its head commit, inside the cap |
| P3 | Stage C: script adjustments, then the agent, triggered by `todo` items | A failing check or an `error` finding on an ungated pull request is attempted without a person starting it |
| P4 | Stage D for ungated pull requests, after #905 | An ungated, ready pull request merges without the maintainer |

## Consequences

**Positive**

- A pull request always answers "what is left, and who has it": in the comment while there is work, in a review when there is none.
- The console, the terminal and the pull request read one model, so they cannot disagree.
- The gate label, the governance trace and the task list are checked on every event, so they stop drifting.
- P0 costs nothing to run and changes nothing until the switch is set.

**Negative**

- One more review entry on each pull request per head commit that reaches ready.
- `pull_request_target` holds a write token on pull requests from forks. The job never checks the pull request out and treats every string from it as untrusted, as the failure summary already does; the harness standard's check for a `pull_request_target` checkout of a head covers it.
- The readiness job checks out `tools/` and `_data/` beside the script, which is a larger sparse checkout on every run.
- Until P2, "ready" means the fleet's mechanical checks are done. The review says so in its first line ("no code was reviewed").
- § 19.2 is kept as written. A reader who expects a standing summary on a finished pull request finds a review instead.

## Alternatives considered

- **Keep posting nothing when everything is clean.** Rejected: it is why #873 and an unexamined pull request look alike.
- **Keep the comment forever and change § 19.2.** Deferred: it needs an amendment, and a review per ready head commit gives the same record inside the rule as ratified.
- **A second comment for readiness beside the failure summary.** Rejected: § 19.2 allows one, and two writers drift apart, as the triage comments did.
- **Require a human review on every pull request.** Rejected: the reviewer would be the author's own account, and 220 pull requests were opened on one day.
- **AI review on every push.** Rejected by § 19.7, and by the cost of 220 pull requests a day.
- **A hosted merge bot.** Rejected: § 11.2 and § 12 give no service merge rights.

## Supersedes / Superseded by

None.
