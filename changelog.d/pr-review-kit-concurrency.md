### Fixed

- `templates/pr-review/` 0.2.0: the seeded stub declares a workflow-level `concurrency` group, `pr-review-caller-<head sha>` with `cancel-in-progress: false`, so a repo whose own tests require a concurrency group on every workflow accepts it (githubai's `test_every_workflow_has_concurrency` failed on the 0.1.0 stub). The key matches the reusable `pr-review.yml`'s group, but the name differs, because GitHub cancels a run whose caller and called workflow hold the same group. `archive/` keeps the 0.1.0 stub, so `tools/fanout.sh --kit pr-review --upgrade` moves untouched copies.
