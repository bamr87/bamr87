# Repo Scout

> The daily repo-scout loop — a sample of repos a day, an agent that proposes, a filer that opens issues for the issue pipeline.

The fleet's daily **proactive issue loop**. [`repo-evolution`](EVOLUTION.md) writes *code* (a weekly draft PR in opted-in repos); the scout writes *tickets*. Every day it visits a small sample of the fleet's repositories, has an agent read each one the way a new maintainer would, and files a few well-formed issues there — fixes, updates, features — for the [issue pipeline](ISSUE-PIPELINE.md) to triage, implement and complete. Together the two loops are the "find the next thing worth doing, then do it" cycle the user asked for: the scout proposes, the pipeline delivers, and a human reviews the draft PR at the end.

| | | |
| --- | --- | --- |
| **Workflow** | [`.github/workflows/repo-scout.yml`](../.github/workflows/repo-scout.yml) | daily 04:37 UTC + dispatch |
| **Planner + filer** | [`.github/scripts/dash-gen/repo_scout.py`](../.github/scripts/dash-gen/repo_scout.py) | `dash-gen scout` / `dash-gen scout-file` |
| **Brief material** | [`.github/scout/`](../.github/scout/) | goals + method template; category emphasis shared with the evolution loop |
| **Agent step spec** | [`tools/jev/steps/repo-scout/`](../tools/jev/steps/README.md) | the agent's hard-rules prompt, inputs, allowlist and workspace contract, with model and caps referenced from `fleet.yml`; rendered per leg by the plan, delivered as `matrix.prompt` |
| **Config** | [`_data/fleet.yml`](../_data/fleet.yml) → `schedule.repo_scout`, `scout:`, `budget.call_sites` | cadence, sample, caps, label, marker |
| **Opt-out** | [`_data/projects.yml`](../_data/projects.yml) → `scout: false` | per project (the read-only zer0-mistakes mirror opts out) |
| **Kill switch** | repo variable `REPO_SCOUT_ENABLED` | a NEW loop: the cron runs only while it is `true`; a dispatch always runs |
| **CLI** | `tools/dash scout plan` · `--repo <name>` · `--all` | plan locally, or dispatch |
| **Console** | Loops → *Repo scout*, Operations → *scout* | the plan as a job; the workflow as a dispatch |
| **Tests** | `python3 .github/scripts/dash-gen/test_scout.py` · `python3 tools/test_jev_spec.py` · `python3 -m tools.jev steps check` | no network, no pytest |

## The loop

```text
          ┌──────────────────── daily 04:37 UTC · repo-scout.yml ────────────────────────────┐
          │                                                                                │
          │ job: plan (deterministic)   job: scout (matrix, needs: plan)   job: file (hub)   │
          │ ┌────────────────────────┐  ┌───────────────────────────────┐ ┌───────────────┐ │
registry ─▶ │ 1. ELIGIBLE  owned,    │  │ per repo:                     │ │ per repo:     │ │
_data/    │ │    not archived, not   │  │  · checkout its upstream      │ │  · validate   │ │
projects  │ │    opted out, status   │  │    (FLEET_TOKEN, no persisted │ │  · dedupe vs  │ │
.yml      │ │    in scout.statuses   │  │     credentials)              │ │    open issues│ │
          │ │ 2. ROTATE  `sample` a  │  │  · Claude Code reads the      │ │  · cap        │ │
triage ───▶ │    day, fixed order    │  │    brief, orients (README-    │ │  · labels     │ │
conform-  │ │ 3. BACKPRESSURE  skip  │──▶│    First), tries the docs,   │─▶│  · gh issue   │ │
ance ─────▶ │    a repo with open   │art│    writes .scout/proposals.json│art│   create    │ │
          │ │    scout issues        │  │  · never edits, never files   │ │   (marker 1st)│ │
          │ │ 4. BRIEF  facts +      │  └───────────────────────────────┘ └───────────────┘ │
          │ │    signals + open      │        read-only allowlist + Write     FLEET_TOKEN    │
          │ │    issues + focus      │                                                      │
          │ └────────────────────────┘                                                      │
          │   probes FLEET_TOKEN + Claude auth FIRST — fails before any spend               │
          └────────────────────────────────────────────────────────────────────────────────┘
                                                        │
                        issue-pipeline.yml (07:37): intake → ready → implement (draft PR) → complete
```

### 1. Plan — deterministic

`dash-gen scout` runs before any model does, and everything selective happens there:

- **Eligible.** A registry entry qualifies when its upstream is a GitHub repository owned by the hub's owner (an external mirror such as `microsoft/skills` never receives our issues — the same guard `tools/fanout.sh` and the evolution loop apply), its `status` is in `scout.statuses` (archived never qualifies), and it did not set `scout: false`. Unlike the evolution loop it does not need to be a submodule — the scout reads a checkout of the upstream, not the hub's working tree.
- **Rotate.** The eligible list is sorted by name and walked `scout.sample` repos a day from an offset derived from the calendar day. No state file: the same day always yields the same repos, consecutive days take consecutive windows, and every repo is reached within `ceil(eligible / sample)` days (the plan summary prints the figure).
- **Backpressure.** A repo that still carries `scout.max_open_per_repo` open issues filed by this loop — recognised by the `ai-scout` label or the hidden marker — is skipped and the next repo in the rotation takes its place. A stack of unread proposals is noise; the way to get more is to close or implement the ones that are open.
- **Brief.** One `scout-workorders/scout-workorder-<name>.md` per survivor, plus `plan.json`, uploaded as the `scout-workorders` artifact. The brief carries the registry facts, the fleet's signals for the repo (`_data/fleet_triage.yml`), its Universal Project Standard gaps (`_data/conformance.yml`), the repo's **live open-issue list** so nothing is proposed twice, the proposals earlier visits filed that are still open, the operator's focus, and the goals in [`.github/scout/scout-prompt.md`](../.github/scout/scout-prompt.md).

The plan job also **probes** `FLEET_TOKEN` with `gh api user` and requires Claude auth, and fails *before* any agent runs when either is missing — a pass whose proposals cannot be filed is money burned.

### 2. Scout — one job per repo

The target repository is checked out with `persist-credentials: false`, the brief is downloaded into `.scout/` and git-excluded, and a Claude Code agent (model from `scout.model`, the exact id `claude-sonnet-5-5` — reading and writing, not implementing) is run with a **read-only allowlist plus `Write`**: it may run the repo's documented commands to see what fails, and write exactly one file, `.scout/proposals.json`. It cannot edit, commit, push, or create anything on GitHub, and a tracked file it touched anyway is discarded and reported. The step is given **no GitHub token**: the agent reads text anyone can write (open issue titles, the repository itself) and its allowlist includes interpreters that can read any environment variable, so `FLEET_TOKEN` stays in the checkout (not persisted) and the `file` job. The open issues and PRs it must not duplicate are already in the brief. One caveat, recorded as `workspace.exceptions` in the step spec until a follow-up closes it: claude-code-action itself still exports its OIDC App token to the agent's subprocesses, and loads the target checkout's `.claude/` settings because `claude_args` passes no `--setting-sources` ([ADR 0002](adr/0002-agent-step-specs-and-local-runner.md#consequences)). The proposals file travels to the next job as an artifact; an absent file is a valid "nothing worth filing".

The agent's prompt — the hard rules: propose-only, the lanes — is the JEV step spec [`tools/jev/steps/repo-scout/scout.prompt.txt`](../tools/jev/steps/README.md), not text in the workflow. The plan job renders it per leg from the hub at the run's commit (`include[].prompt` in `plan.json`), the matrix carries the exact bytes to the step as `prompt: ${{ matrix.prompt }}`, and the plan fails before any spend if a leg has no prompt. `python3 -m tools.jev steps render repo-scout scout --set …` prints the same bytes locally, and `steps check` holds the workflow's caps, allowlist, timeout, artifact paths and the step's `JEV_STEP_SHA256` content-hash pin equal to the spec ([ADR 0002](adr/0002-agent-step-specs-and-local-runner.md)).

Every run reports its spend in the job summary through the shared `claude-cost` action (the same step as the other loops): a budget abort and a rejected credential each fail the job loudly, and a spent Claude usage window (`usage-limit: skip`) is a warning, not a red run.

### 3. File — the only writer

Back on the hub, `dash-gen scout-file` runs per repo with `FLEET_TOKEN`: it validates each proposal (title and body length, a known `kind`, no credential-shaped string — a GitHub or Anthropic token or a private key block withholds the proposal), normalises its labels to the issue pipeline's taxonomy (`type` / `priority` / `size`, with `kind → type` fallbacks), **dedupes** against the repo's open issues (exact after normalisation, or word-overlap Jaccard ≥ 0.6 — within the batch too), **caps** at `scout.max_issues_per_repo`, creates the labels on demand from the pipeline's own colour catalogue, and files the survivors with the marker `<!-- repo-scout key="owner/repo" -->` as the first line of the body and a footer naming the run. A `dry_run` dispatch does everything but the filing and prints what it would have filed.

## What a filed issue looks like

```text
<!-- repo-scout key="bamr87/bashos" -->

## Problem
`README.md` says `bashos --help` lists every command; it exits 1 ("unknown flag") — bin/bashos:42 …
## Proposal
…
## Acceptance criteria
- [ ] `bashos --help` exits 0 and lists …
## Scope
bin/bashos, README.md. Out of scope: …
---
_Filed by the fleet's repo scout (<run url>; bamr87/bamr87 docs/SCOUT.md) as a **fix** proposal for the issue pipeline. Close it if it is wrong; label `agent:hold` to keep automation off it._
```

Labels: `ai-scout` + one of `bug / feature / docs / chore / ci / refactor / test / security` + `P0–P3` + `size:xs–xl`. No state label, so the issue enters the pipeline at **intake** on the next 07:37 run; the two human brakes (`agent:hold`, `human-review`) apply exactly as for any other issue.

## Lanes — why it does not collide with the other loops

- A **failing workflow** in the brief is the fleet doctor's ([`fleet-pulse`](DAILY-ANALYSIS.md)); the scout is told not to propose work for it.
- An **open issue** is the pipeline's; the brief lists them and the filer refuses a duplicate anyway.
- An **open PR** is someone's work in flight; the scout must not propose what it already does.
- The **evolution** loop changes code the scout may be looking at; both carry markers, and the pipeline's intake sees both.

## Running it by hand

```bash
tools/dash scout plan --offline --no-briefs          # today's sample, no GitHub reads
tools/dash scout plan --day 2026-11-01               # the sample for another day, with briefs
tools/dash scout --repo bashos -f dry_run=true       # dispatch: one repo, file nothing
tools/dash scout --all                               # dispatch today's sample for real
tools/dash-gen scout-file --nwo bamr87/bashos --proposals ./proposals.json   # rehearse the filer locally
python3 .github/scripts/dash-gen/test_scout.py
```

## Configuration

Everything lives in `_data/fleet.yml`:

| Key | Default | Meaning |
| --- | --- | --- |
| `schedule.repo_scout` | `37 4 * * *` | daily, before the pulse (05:37) and the pipeline (07:37) so the chain closes the same day |
| `scout.sample` | 2 | repos visited per day |
| `scout.max_issues_per_repo` | 3 | proposals filed per visit |
| `scout.max_open_per_repo` | 3 | backpressure threshold |
| `scout.max_parallel` / `max_turns` | 2 / 40 | concurrent agents; turns per repo (the workflow literal is asserted against it) |
| `scout.model` | `claude-sonnet-5-5` | an exact id from `ai_models.allowed`, never an alias (constitution § 13.3); the scout reads and writes, the implementer in the pipeline is the Opus spend |
| `scout.label` / `marker` | `ai-scout` / `repo-scout` | how the loop recognises its own issues |
| `scout.statuses` | active, maintenance, experiment | eligible registry statuses |
| `budget.call_sites."repo-scout.yml:scout"` | 8 | the dollar ceiling per matrix leg (`test_ai_budget.py`) |

Shadow cost at the defaults: two Sonnet passes a day, each a fraction of the \$8 cap — a few dollars a day at list price, and a throughput ceiling rather than an invoice under subscription auth. Raise `sample` with an eye on `harnesses.budget` in the same file.

## Tokens

| Secret | Why |
| --- | --- |
| `FLEET_TOKEN` | cross-repo checkout of private targets, and the issue + label writes in `file`. Probed with `gh api user` before anything runs. |
| `CLAUDE_CODE_OAUTH_TOKEN` / `ANTHROPIC_API_KEY` | the agent's credential, chosen by the repo's `CLAUDE_AUTH_ORDER` through the `claude-auth` action. |

## Safety model

- The agent **proposes**; the workflow **files**. The agent job holds no write credential and a read-only allowlist; the file job is the only GitHub writer and writes only issues and labels, only to the repo the plan named, never to the hub.
- Nothing merges, closes, or edits an existing issue. Ever.
- One open batch per repo is the backpressure; the sample, the per-repo cap and the dollar ceiling bound the day.
- The kill switch starts OFF for a new loop; `REPO_SCOUT_ENABLED=true` arms the cron, and a manual dispatch — including `dry_run` — works without it.
- Every issue it files still has to pass the pipeline's intake, its autonomy gates and, at the end, a human's review of the draft PR.
- The hard rules live in `tools/jev/steps/repo-scout/`, outside `.github/workflows/`. The `workflow`-scope barrier that `GITHUB_TOKEN` pushers and the Claude App token cannot cross still covers them through the Scout step's `JEV_STEP_SHA256` pin: `steps check` refuses a spec pair whose hash differs, so changing the rules changes the workflow file too. `FLEET_TOKEN` already holds `workflows:write`, so for it the maintainer's review is the only control, before and after the move; the byte pins in `tools/test_jev_spec.py` and `test_scout.py` make an edit visible but are re-pinned in the same PR, and `CODEOWNERS` is not enforced. A change there is security-sensitive config under constitution § 12.3, so no agent merges it (the `needs-amr` label is still to be created, HUB-045). The trade-off is recorded in [ADR 0002](adr/0002-agent-step-specs-and-local-runner.md#governance-trade-off).
