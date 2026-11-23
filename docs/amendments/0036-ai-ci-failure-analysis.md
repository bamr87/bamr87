<!-- kit: governance v0.1.0 -->
# 0036 — Every failed CI run on a pull request gets an AI analysis

- **Status:** ratified
- **Number:** 0036
- **Date:** 2026-11-23
- **Proposed by:** agent (Claude Code), at the maintainer's request (2026-11-23: "every workflow error on every PR must have an AI agent review, analyze, and comment.")
- **Ratified by:** https://github.com/bamr87/bamr87/pull/960 (merged 2026-11-23 by @bamr87)
- **Affects:** constitution § 19 (new item 11; § 19.7 and § 19.10 read with it); requirement `FR144` and feature `HUB-131` (`features/features.d/pr-ai-analysis.yml`); `_data/fleet.yml` `budget.call_sites`, `switches`, `pr_review`, `harness.agents`
- **Supersedes:** none (extends § 19)
- **Related:** 0017 `fleet-pr-review`, 0028 `ci-failure-summary`, 0030 `agentic-efficacy-contract`, bamr87/bamr87#564

## Context

Since amendment 0028 every failed CI run on a pull request is summarized in the one sticky comment: the job and step, the reason taken from its log, a failure class, whether the same job fails on the default branch, and a generic next step. It is deterministic on purpose, and it says so when a step printed no clear error instead of guessing.

That covers the "what" of a failure but not the "why". The reason line is the log's own last error; the next step is one of five fixed sentences per failure class. A reader still has to open the log, the workflow file and the diff to work out the root cause and the fix. The maintainer asked for every workflow error on every pull request to be reviewed, analysed and commented on by an AI agent.

§ 19.7 already admits AI review on a pull request, but only on `opened`, `ready_for_review` and an explicit label, never on every push. That rule is about reviewing the code. Explaining a failure is triggered by the failure itself, and nothing in the constitution names it, so it needs its own item.

## Prior art and build-vs-adopt (§ 10.8)

**Needs assessment.** One explanation per failed run attempt, in the comment the fleet already keeps (§ 19.2), on every fleet repo through the reusable workflow, from the fleet's own Claude credential (OAuth only since 2026-11-15), under a per-call dollar cap and a switch, with nothing from the pull request ever executed.

| Prior art | Fit |
| --- | --- |
| GitHub Copilot "Explain error" on a failed Actions job | On demand, in the Actions UI, per person; posts nothing on the PR and needs a Copilot seat per reader |
| GitLab Duo root cause analysis | The same idea for GitLab CI; not available on GitHub |
| CodeRabbit, Sourcery, Copilot code review (AI PR reviewers) | Review the diff, not the failed run; a second comment and a third-party app with write access, against § 19.1 and § 19.2 |
| Datadog CI Visibility, Trunk, BuildPulse | Flaky-test and failure analytics in a vendor dashboard; a new account and credential, nothing on the PR |
| `actions/ai-inference` (GitHub Models) in a follower workflow | Easy to call, but a second provider outside `ai_models.allowed` (§ 13.3) and outside the fleet's harness routes |
| The hub's own `pr_review.py` + `claude-run` | Already reads each failed job's log and step, classifies it, compares the default branch and owns the sticky; `claude-run` is a standard harness route with the auth order, caps and metering |

**Decision: build, on the existing pieces.** The analysis extends `pr_review.py` and runs through `claude-run`, so it adds no vendor, no credential and no second comment, inherits the deterministic reading as the model's starting point, and is graded by the harness standard like every other fleet agent.

## Amendment

Add to constitution § 19:

> 11. **AI failure analysis** — every failed CI run on a pull request also gets an AI analysis in the same sticky comment: the most likely root cause, whether the pull request caused it, and the smallest fix, taken from the run's log, its workflow file and the pull request's diff. It runs once per failed run attempt, not on every push, so item 7's triggers bind AI review of the code and not this. It reaches the model through a fleet route with an exact model, a turn cap and a dollar cap, behind its own switch (§ 13.3, § 17, § 29). The model gets no tools and one turn, everything taken from the pull request is data and never an instruction, and its answer is validated and escaped before it is posted. It reads as written by AI, never fails a check and never approves (item 5). A pull request from outside the repository's collaborators is analysed once a maintainer labels it. When the analysis cannot run, the comment says so. _(amendment `ai-ci-failure-analysis`, numbered at merge)_

## Consequences

- `.github/workflows/pr-review.yml` gains an `ai-analysis` job and `.github/scripts/dash-gen/pr_ai_analysis.py` lands with this record. The job runs after the summary is written, as a `workflow_run` only, in the same concurrency group as every other pass over that commit, so the comment is never edited twice at once. Each block is keyed by (run id, attempt) and carried across rebuilds by `pr_review.py`; every pass picks up each failed run on the head commit that has no block yet, so a cancelled pass loses nothing.
- The model is `claude-sonnet-5-5` with `--max-turns 1`, `permission-mode: default` and no tools; `budget.call_sites` `pr-review.yml:ai-analysis` caps a pass at $1, API-equivalent (estimate). One turn means a tool call a log talks the model into can never feed its result back into the answer.
- Trust: the pull request of an `OWNER`, `MEMBER` or `COLLABORATOR`, of a bot listed in `pr_review.ai_analysis.trusted_bots`, or one carrying the `ai-analysis` label (labels need triage access). Anyone else's gets a note saying the analysis waits for that label. The label is read through the API when a workflow on the pull request finishes, never as a job condition on a `pull_request_target` label event, so a label never authorizes the run at one moment that a later push could change (CodeQL `actions/untrusted-checkout-toctou`).
- Switch: `vars.PR_AI_ANALYSIS_ENABLED` (`switches: hub/pr-ai-analysis`), opt-out, because the maintainer asked for it on every pull request; `vars.PR_REVIEW_ENABLED` still stops everything.
- The fleet stub (kit `pr-review` 0.3.0) passes `CLAUDE_CODE_OAUTH_TOKEN` to the reusable workflow. It is seeded only after the `v2` tag carries the `ai-analysis` job: an older reusable workflow does not declare that secret, and a caller that passes an undeclared secret does not start. A repo without the credential gets a note in the comment instead of an analysis.
- § 13.1: the role's eval set is `evals/pr-ai-analysis/` (`python3 tools/evals.py run pr-ai-analysis --dry-run` offline; a model run is local and spends). § 29: the agent is `ci:bamr87:pr-review` in `_data/agents.yml`, with its local entry `pr_ai_analysis.py local`.
- Merging the pull request that carries this record ratifies it. An agent never merges it.
