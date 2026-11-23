# templates/pr-review — the fleet's one PR comment

> A thin caller of the hub's reusable `pr-review.yml`, which summarizes every CI failure on a pull request in one sticky comment, so nobody has to open a log to learn why a check failed, adds an AI analysis of each failed run to that comment, and posts each repo check's findings inline on the diff, once.

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

While something is failing, the sticky also counts the findings on the head commit's diff, by severity.

## AI analysis (§ 19.11)

Under the deterministic summary, each failed run also gets an AI analysis in the same comment: what most likely went wrong, whether the pull request caused it, the one log line that shows it, a confidence, and the smallest fix with commands to verify it. The summary reads the log with patterns; the analysis reads the log, the workflow file and the pull request's diff together, so it can say *why*.

| What | How |
| --- | --- |
| When | Once per failed run attempt. Every time a workflow on the PR finishes, `ci-failure` counts the failed runs on the head commit that have no analysis yet; the `ai-analysis` job starts only when there is one. A re-run is a new attempt and gets a new analysis. A run held for approval gets none: the summary already says what to do |
| What the model sees | Per failed run: the fleet's own reading of each failed job (step, reason, class, whether it fails on the default branch), the failed step's last 160 log lines, and the workflow file at the head commit; then the PR's changed files and a diff excerpt. Everything from the PR is fenced as untrusted data, and the whole prompt stays under 90 KB |
| The model | `claude-sonnet-5-5` through the hub's `claude-run` action, OAuth only, **no tools, one turn** (`max-turns: 1`, `permission-mode: default`), capped at $1 per pass (`budget.call_sites` `pr-review.yml:ai-analysis`). One turn means a tool call a log talks it into can never feed a result back into the answer |
| Its answer | One JSON object per pass, validated field by field (an unknown run id is dropped, a value outside its set falls back to the cautious one, every string is bounded). Every string is scrubbed of token shapes and escaped, so nothing renders as a link, image, mention or HTML; a URL shows as code. Commands go in a fenced block that the answer cannot close |
| Who gets one | A pull request from an `OWNER`, `MEMBER` or `COLLABORATOR`, from a bot in `_data/fleet.yml` `pr_review.ai_analysis.trusted_bots` (Dependabot, `github-actions[bot]`, …), or one carrying the `ai-analysis` label. Anyone else's gets a note that it waits for that label; in the hub, adding the label starts a pass at once |
| When it cannot run | The block says why: no `CLAUDE_CODE_OAUTH_TOKEN` reached the job, the call failed (a spent usage window, an outage), or the answer broke the contract. It is tried again on the next pass, at most `max_tries` (2) times per run attempt |
| What it never does | Fail a check, approve, review code beyond the log and diff, or run anything from the PR. Each block ends by saying it was written by AI and can be wrong |

Each block is keyed by a hidden `<!-- fleet:ai-analysis {"run":…,"attempt":…,"status":…} -->` header inside one `<!-- fleet:ai-analyses -->` region. `pr_review.py` rebuilds the comment from scratch as runs finish and carries each block whose run still fails at the same attempt; a fixed or re-run workflow drops its block. Only a comment a bot wrote is read for blocks, so a person's comment that starts with the marker cannot stop an analysis or pass for one. The `ai-analysis` job runs after `ci-failure` and `readiness` in the same concurrency group, so the comment is never edited twice at once, and each pass analyses every failed run that still has no block, so a pass the group cancelled loses nothing. The job summary keeps every block whole.

Turn it off in one repo with the variable `PR_AI_ANALYSIS_ENABLED` set to `false`; `PR_REVIEW_ENABLED=false` still stops everything. The same pass runs from a workstation, through `dash ai run` and its ledger, capped by the same call site (§ 10.9):

```bash
python3 .github/scripts/dash-gen/pr_ai_analysis.py local --repo bamr87/<repo> --pr <n>          # prints the blocks
python3 .github/scripts/dash-gen/pr_ai_analysis.py local --repo bamr87/<repo> --pr <n> --post   # and writes them
```

A fleet repo needs kit 0.3.0, whose stub passes `CLAUDE_CODE_OAUTH_TOKEN` (and nothing else) to the reusable workflow. **Seed 0.3.0 only after the `v2` tag carries the `ai-analysis` job:** an older reusable workflow does not declare that secret, and a caller that passes an undeclared secret does not start. A 0.2.0 stub keeps working and gets the "no credential" note. The `ai-analysis` label trigger is in the hub only, like the readiness events, until a later stub adds `pull_request_target`.

## Findings: how a repo check reports

A repo-specific check (a docs warden, a content-quality or docs-quality check, a linter) does not comment on the PR itself (§ 19.1). It writes its findings to a file and uploads it as an artifact named exactly `fleet-findings`; `pr-review.yml` reads it when the check's workflow finishes and posts each finding as an inline comment (§ 19.3).

```yaml
      - name: Report findings to pr-review
        if: ${{ !cancelled() }}
        uses: actions/upload-artifact@v7
        with:
          name: fleet-findings
          path: fleet-findings.jsonl
          retention-days: 7
```

The file is UTF-8 JSON lines, one finding per line, each line ended by `\n` (a `\r\n` ending is fine; a raw U+2028 or NEL inside a string is not a line break), with exactly these six keys:

| Key | Value |
| --- | --- |
| `path` | The file, relative to the repository root (no leading `/`, no `..`) |
| `line` | The line in the PR's version of the file, a positive integer (a `\n`-ended line, as git counts them) |
| `rule` | The check's rule id: letters, digits and `. _ : / -`, at most 80 characters |
| `severity` | `error`, `warning` or `note` |
| `message` | What is wrong, plain text, 1 to 1,000 characters (markdown is escaped) |
| `kind` | `code`, `content` or `docs` |

```json
{"path": "docs/setup.md", "line": 12, "rule": "MD013", "severity": "warning", "message": "Line is 140 characters; the limit is 120.", "kind": "docs"}
```

What happens to each finding:

- **Only lines the PR adds** get a comment. A finding anywhere else, or in a file the PR does not touch, is listed in the job summary and not posted, so a repo-wide dump never reaches the PR.
- **Once per (path, line, rule).** Each comment carries a hidden key, `<!-- fleet:finding key=<sha1 of path:line:rule> -->`. A later push with the same finding posts nothing new; a finding that moves to another line is a new one. Only keys on comments posted by a bot count.
- **Severity first, signature last.** Each comment opens with its severity and rule and ends with `<!-- fleet:source=<check> trigger=<event> run=<run-url> -->`, where `<check>` is the uploading workflow's name. It is a single review comment, never a review, so it never approves (§ 19.5).
- **Scope (§ 19.6).** `content` and `docs` findings are dropped on a PR opened by `dependabot[bot]` or from a `release-please--*` branch. `code` findings still post.
- **Strict validation.** The artifact comes from the PR's own code. It is read in memory, never extracted or executed. A line that is not valid JSON (or JSON Python cannot hold, such as a 5,000-digit number), a missing or extra key, a value outside the table above, a string UTF-8 cannot hold (a `\ud800` escape decodes to a lone surrogate), a zip the reader cannot open (a member name flagged UTF-8 that is not), a zip over 1 MiB, more than 2 MiB of `.jsonl` or more than 500 findings rejects the whole artifact: nothing from it is posted, the CI-failure sticky is still written, and the job summary says why.
- **Caps.** At most 20 new inline comments per review, and a review stops posting once GitHub has refused 5 in a row (a locked conversation, a 403); the rest post on the next one. Each review re-reads every check's latest artifact for the head commit, so a review the concurrency group cancelled loses nothing.
- **Job summary.** Every finding and what happened to it (posted, already on the PR, not on a line the PR adds, skipped, waiting, refused) goes to the run's `$GITHUB_STEP_SUMMARY`. Cost, usage and test tables belong there too, never in a comment (§ 19.8).

A workflow with several jobs uploads one artifact per job under its own name, then merges them into one `fleet-findings` with `actions/upload-artifact/merge`. The check still decides its own pass or fail: findings say where, the check status says whether.

## How it behaves

This follows constitution § 19: one comment per PR, found by its marker and edited in place, deleted when nothing is failing, ending in the fleet signature, and posted as `github-actions[bot]`. It never approves, merges or changes code. It reads only `GITHUB_TOKEN`-visible data and spends about a dozen API calls per failure, plus one call per review to look for findings artifacts.

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

The findings channel lives in the reusable workflow, not the stub, so a seeded repo gets it with the next `v2` minor cut and no stub change.

## Moving the comment bots onto it

The workflow atlas rule `pr-comment` (warn) flags any workflow step that posts on a pull request by itself: `gh pr comment` or `gh pr review`, a `gh api` or `curl` write to a PR's comments or reviews, a sticky-comment action, or `github-script` creating a review or a PR comment. List a repo's sites with `tools/dash workflows lint --root projects/<repo>`.

The fan-out is one pull request per repo, each in that repo, and none is executed by the change that added the findings channel. Each replaces a check's own comment step with a `fleet-findings` upload (or, for a table, a job summary) and seeds the stub if the repo has none:

| Order | Repo | What moves | Why first |
| --- | --- | --- | --- |
| 1 | year-of-ai.github.io | `docs-warden.yml` writes its `--json` findings as `fleet-findings` (`kind: docs`) and drops `marocchino/sticky-pull-request-comment` | 16 of the audit's comments, 9 invalid, 6 on Dependabot PRs |
| 2 | it-journey | `content-quality.yml` `brand-gate` uploads findings (`kind: content`) instead of `gh pr comment`, which posted again on every push | Named in the audit |
| 3 | README | `docs-quality-check.yaml` uploads findings (`kind: docs`) instead of a `peter-evans/create-or-update-comment` dump; pr-review keeps only the lines the PR adds | It posted 40,038 repo-wide issues as one comment |
| 4 | lifehacker.dev | The `usage_report.rb` AI-usage meter writes to `$GITHUB_STEP_SUMMARY` (§ 19.8); no artifact | 29 meter comments, 25 as Amr |
| 5 | bamr87 (the hub) | `fleet-verify.yml`'s verify sticky and `jev-number.yml`'s ratify note | The two `pr-comment` warnings on the hub's own tree |

ai-world-view.github.io carries the same `docs-warden.yml` as year-of-ai and follows it. The rule stays a warning everywhere until a repo's fan-out PR lands (§ 19.9); turning it into a failure for a repo that has moved is a later change.

## Not built yet

- **AI review of the code (§ 19.7)** runs on `opened`, `ready_for_review` and an explicit label, never on every push, behind the § 17 switch and held to § 13. It is a different harness from the AI failure analysis above (which reads failed runs, not the diff as a review) and needs its own issue: a fleet route with an exact model, `--max-budget-usd` and a `budget.call_sites` entry, an `_data/agents.yml` entry with its KPIs, and a § 13.1 eval set before its findings can fail a build. Its findings would arrive through the same `fleet-findings` channel.
- **Identity (§ 19.5):** posting as the fleet app instead of `github-actions[bot]` is bamr87/bamr87#565.
