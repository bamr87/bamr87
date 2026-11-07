### Added

- `pr-review.yml`: a reusable workflow that summarizes every CI failure on a pull request in one sticky comment: the job, the reason from its log, whether the PR probably caused it, and what to do. The comment is deleted when nothing is failing. A fleet repo adopts it with the stub in `templates/pr-review/`.
