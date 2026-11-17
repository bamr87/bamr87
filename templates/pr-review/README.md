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

## Seeding

```bash
tools/fanout.sh --kit pr-review --target <name|all>                       # dry run
tools/fanout.sh --kit pr-review --target <name|all> --apply               # one PR per repo
tools/fanout.sh --kit pr-review --target <name|all> --upgrade --apply     # refresh untouched older stubs
```

The stub calls the hub at `@v2`, so a repo adopts it after the tag that carries `pr-review.yml`.

`--upgrade` replaces a repo's stub only when it is byte-identical to the current template or to a shape in `archive/`; a hand-edited copy is left alone. Snapshot the outgoing stub into `archive/pr-review-<version>.yml` (with `__KIT_VERSION__` rendered) before changing the template. To refresh a stub that was appended to an open PR rather than merged, set `FANOUT_BRANCH` and `FANOUT_BASE_BRANCH` to that PR's head branch and `FANOUT_PR_APPEND=1`.
