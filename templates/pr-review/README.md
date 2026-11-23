# templates/pr-review — the fleet's one PR comment

> A thin caller of the hub's reusable `pr-review.yml`, which summarizes every CI failure on a pull request in one sticky comment, so nobody has to open a log to learn why a check failed, and posts each repo check's findings inline on the diff, once.

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

## AI review

A pull request that is marked ready is read once by a model, which comments with what it found and who does what next (constitution § 19.7; [ADR 0012](../../docs/adr/0012-merge-readiness.md), stage B). It runs in the hub today, from `.github/workflows/pr-ai-review.yml`; the fleet gets it with a later kit version (see [Not built yet](#not-built-yet)).

| When | What happens |
| --- | --- |
| A pull request is opened ready, or a draft is marked ready, by an author with write-level standing (owner, member, collaborator) | It is reviewed |
| Anyone with triage rights adds the `review` label | It is reviewed, whoever wrote it and whether or not it is a draft |
| A push, an edit, any other label | Nothing. A review is never repeated on a push (§ 19.7); add the label again after new commits |
| A Dependabot, release or bot pull request | Nothing, unless it is given the label (§ 19.6) |
| A commit that already has its review | Nothing: one review per head commit |
| The repo has used the day's reviews (`max_per_day`), a commit was pushed after the request, or the diff holds only generated, vendored or binary files | One line on the pull request saying so, and how to ask again |

### What it posts

Two things, both through `pr-review.yml`, both as `github-actions[bot]`:

- **Findings on the diff.** Each finding on a line the pull request adds is an inline comment with its severity and a rule id `ai-review/<category>` (correctness, security, rules, tests, docs, design). They travel through the `fleet-findings` channel described above, so they are deduplicated and capped like any check's.
- **One review per head commit.** It opens with a short summary, counts the findings, lists the ones that are not on an added line, and ends with the next actions. It is a comment: it never approves and never requests changes (§ 19.5), and it says its findings are advisory.

### Who does what next

The review names who moves each action, and gives the hand-off for it. The model chooses who; the hand-off text is fixed, so a diff cannot write a command into it.

| Who | Used for | The hand-off the review prints |
| --- | --- | --- |
| An agent | Mechanical work a coding agent can do from the findings alone: a fix, a missing test, a doc update | A maintainer comments `@claude address the AI review findings on this pull request`, which starts the repo's mention handler (`claude.yml`) |
| The author | A change only whoever opened the pull request can judge | Push the change to the branch |
| The maintainer | A decision: scope, risk, a rule being bent, anything touching governance, secrets, budgets, permissions or deploys | A decision, not work |

The review recommends and hands off. It starts nothing by itself: a bot's comment cannot trigger the mention handler, by design, so spending on a fix is still one comment from a person. Starting the fix without a person is stage C of ADR 0012.

### How it runs

| Job | Holds | Does |
| --- | --- | --- |
| `plan` in `pr-ai-review.yml` | A read-only token | `pr_ai_review.py plan` decides whether this pull request gets a review now and writes the brief: the diff with the new file's line number beside each line, the description, and what the PR queue already knows (so the reviewer does not report a failing check). Files past the size caps are named and left out |
| `review` in `pr-ai-review.yml` | The Claude credential, and a token that reads contents only and never reaches the agent | One session through the fleet route `claude-run`: an exact model, a turn cap and a dollar cap from `_data/fleet.yml` `pr_ai_review`. Read, Grep and Glob only. Then `pr_ai_review.py collect` holds the reply to the contract and uploads `fleet-findings` and `fleet-review` |
| `ci-failure` in `pr-review.yml` | The token that writes on pull requests | Its pass posts the findings inline and then, because the workflow that finished is the AI review, the review itself (`pr_review.ai_review_of`). No step was added for it |

The pull request's code is never checked out, on any job: every checkout takes the event's default ref, which on `pull_request_target` is the base branch. The reviewer's working directory holds the hub's tooling, the base branch (the code before the change) and the diff as text, so no `.claude/` settings, hook or `CLAUDE.md` from the pull request can load. The diff is still text someone else wrote, so the reply is treated as untrusted twice: `collect` keeps only what fits the contract (an item that does not is dropped and counted; a reply with no summary fails the job), and the posting pass validates the artifact again, believes it only from a `pull_request_target` run of `pr-ai-review.yml` (which always runs the base branch's file), and escapes every word before it reaches the review.

Which label was added is read by the script, never by a job condition. A label checked in an `if:` on `pull_request_target` authorizes a pull request at one moment, and code scanning reports any checkout after it as a check a later push can outrun. So every `labeled` event reaches the plan step, which turns away any label but `review`, and turns away a pull request whose head moved after the event.

A review that was attempted and failed (a spent usage window, a reply that is not a review) fails the `review` job, and the CI-failure comment explains it like any other failed check. Re-run the job, or add the label again.

### Switch, caps and settings

| Setting | Value | Where |
| --- | --- | --- |
| Kill switch | `vars.PR_AI_REVIEW_ENABLED` must be `true`: off until set, as every new loop is. `vars.PR_REVIEW_ENABLED` set to `false` stops it too, because nothing would post it | `_data/fleet.yml` `switches.loops` `hub/pr-ai-review` |
| Model, turns, dollars | `claude-sonnet-5-5`, 25 turns, $4 a review, API-equivalent (estimate) | `pr_ai_review`, `budget.call_sites` `pr-ai-review.yml:review` |
| Reviews a day | 30 for the repo, in one UTC day | `pr_ai_review.max_per_day` |
| Size | 80 files, 40 kB a file, 240 kB a review, 30 findings | `pr_ai_review` |
| Files never read | Lockfiles, build output, vendored trees, binaries, and the repo's generated files | The script's defaults, plus `pr_ai_review.skip_paths` |

```bash
gh variable set PR_AI_REVIEW_ENABLED -R bamr87/bamr87 --body true    # arm it
gh workflow run pr-ai-review.yml -R bamr87/bamr87 -f pr=123          # a dry run: the review is in the run's summary, nothing is posted
tools/dash prs review --pr bamr87/bamr87#123                         # the same review in a local session; prints, posts nothing
```

The dry run works with the switch off, so the loop can be tried before it is armed. The local run is a capped session through `dash-gen ai-run --isolate`, with its cost on the AI ledger (§ 10.9).

### The `fleet-review` artifact

One file, `fleet-review.json`, with `schema: fleet-review/v1`, the `repo`, `number` and `head_sha` it reviewed, and either `status: reviewed` (`model`, `summary`, `findings`, `actions`, `files_reviewed`, `files_total`, `dropped`) or `status: skipped` with a `reason` (`daily-cap`, `moved`, `nothing-to-review`). The posting pass rejects a document with a missing or extra key, a value outside its bounds, or a `repo`, `number` or `head_sha` that is not the run's own, and then posts nothing.

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

- **AI review in the fleet.** [AI review](#ai-review) runs in the hub. A fleet repo needs a stub that carries the `pull_request_target` trigger and passes `CLAUDE_CODE_OAUTH_TOKEN` to a reusable form of `pr-ai-review.yml`: a later kit version, a `v2` cut that carries it, and one fan-out pull request per repo.
- **An eval set for the reviewer (§ 13.1).** About 20 past pull requests with the findings a review must and must not report. Until it exists the findings are advisory: they never fail a build, and merge readiness does not count them. With it, an `error` finding becomes a `todo` item in the readiness list, as ADR 0012 stage B describes.
- **Handing work off without a person (ADR 0012, stage C).** The review names who does what and prints the hand-off. Starting the agent from an `error` finding, at most twice and then `needs-amr`, is the next stage; so is letting the PR queue's `address-review` task take a comment-only review as its brief.
- **The other two reviews.** The completeness review (§ 15.5, bamr87/bamr87#492) and the direction review (§ 28.3) are separate reviewers with their own markers; this one reviews the code.
- **Identity (§ 19.5):** posting as the fleet app instead of `github-actions[bot]` is bamr87/bamr87#565.
