# templates/pr-review — the fleet's one PR comment

> A thin caller of the hub's reusable `pr-review.yml`, which summarizes every CI failure on a pull request in one sticky comment, so nobody has to open a log to learn why a check failed.

| File | Purpose |
| --- | --- |
| `pr-review.yml` | The per-repo stub: a `workflow_run` of every workflow, calling `bamr87/bamr87/.github/workflows/pr-review.yml` |
| `VERSION` | Kit provenance and changelog |
| `archive/` | Byte-exact earlier stubs (`pr-review-<version>.yml`), so `--upgrade` recognises an untouched seed |

## What the comment says

For each failed job: the failed step, the reason taken from its log, what kind of failure it is, whether the PR probably caused it, and what to do next. A short log excerpt sits behind a fold.

- **Why** comes from the failed step's own output: a traceback's exception, a failing test's line, or an error annotation. If the step printed no clear error, the comment says so instead of guessing.
- **Caused by this PR?** compares the same job on the default branch. If it also failed there, the PR probably isn't the cause.
- **Runs that never started** are covered too: a PR from `github-actions[bot]` held for approval, or a workflow GitHub refused.

A failed push to the default branch is reported on the PR that merged it, so a broken `main` reaches whoever merged.

## How it behaves

This follows constitution § 19: one comment per PR, found by its marker and edited in place, deleted when nothing is failing, ending in the fleet signature, and posted as `github-actions[bot]`. It never approves, merges or changes code. It reads only `GITHUB_TOKEN`-visible data and spends about a dozen API calls per failure.

It uses a `workflow_run` trigger because that is the only event that sees every workflow. GitHub fires no `check_run` or `check_suite` event for a check Actions created.

`workflow_run` runs from the default branch, so the stub takes effect once merged. To turn it off in one repo, set the repository variable `PR_REVIEW_ENABLED` to `false`.

Since 0.2.0 the stub declares its own workflow-level `concurrency` group, `pr-review-caller-<head sha>`, with `cancel-in-progress: false`: one review per head commit at a time, and a later completion queues rather than cancels, so no update is dropped. Some repos require a concurrency group on every workflow (githubai's `tests/test_workflows.py`). The key matches the reusable workflow's `pr-review-<head sha>` group, but the name must differ: GitHub cancels a run whose caller and called workflow hold the same group, reporting a deadlock.

## Merge readiness

With the repository variable `PR_READINESS_ENABLED` set to `true`, the same comment also says what is left before the pull request merges ([ADR 0012](../../docs/adr/0012-merge-readiness.md)). It is off by default.

| The pull request | What appears on it |
| --- | --- |
| has work left: a failing check, a conflict, a draft, a gated change with no `needs-amr` label, unticked tasks, unresolved review threads, requested changes | The one comment, with the failed runs first and a table of what is left under them: each item, and who moves it. The items that are done sit behind a fold |
| is waiting on a running check or a required review | The same comment, saying so |
| has nothing left | The comment is deleted, and one review is posted on that head commit: "Ready to merge", every item, and who merges it (the maintainer for a gated pull request, an agent under § 12.2 otherwise). A later commit that is ready gets its own |

The review is a comment. It never approves, never counts as a required review (§ 19.5), and says in its first line that no code was reviewed: it records the fleet's mechanical checks, which is stage A of the ADR.

`.github/scripts/dash-gen/pr_readiness.py` writes it: it calls `pr_review.py` for everything about a failed run and adds the rest. The items come from the PR queue's model, read for that one pull request with a single query, so the comment, `tools/dash prs ready --pr` and the console agree ([docs/PR-QUEUE.md](../../docs/PR-QUEUE.md#merge-readiness)). Every string that comes from the pull request (a task's words, a file path, a check's name) is escaped before it reaches the comment.

In the hub the workflow also runs on the pull-request events that start no workflow of their own: opened, reopened, marked ready, converted to a draft, pushed to, labelled, unlabelled and edited. It takes them through `pull_request_target`, under the rule the failure summary already follows: it checks out the hub's tooling, never the pull request. The stub in this kit does not have that trigger yet, so a fleet repo that sets the variable gets the readiness section when a workflow finishes and not when a pull request is only marked ready; kit 0.3.0 adds the trigger.

## Seeding

```bash
tools/fanout.sh --kit pr-review --target <name|all>                       # dry run
tools/fanout.sh --kit pr-review --target <name|all> --apply               # one PR per repo
tools/fanout.sh --kit pr-review --target <name|all> --upgrade --apply     # refresh untouched older stubs
```

The stub calls the hub at `@v2`, so a repo adopts it after the tag that carries `pr-review.yml`.

`--upgrade` replaces a repo's stub only when it is byte-identical to the current template or to a shape in `archive/`; a hand-edited copy is left alone. Snapshot the outgoing stub into `archive/pr-review-<version>.yml` (with `__KIT_VERSION__` rendered) before changing the template. To refresh a stub that was appended to an open PR rather than merged, set `FANOUT_BRANCH` and `FANOUT_BASE_BRANCH` to that PR's head branch and `FANOUT_PR_APPEND=1`.
