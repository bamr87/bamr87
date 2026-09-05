# Repo Evolution

The fleet's weekly **proactive** loop. The three loops it sits beside all *react* to a signal — [`fleet-pulse`](DAILY-ANALYSIS.md) fixes broken *workflows*, [`issue-pipeline`](ISSUE-PIPELINE.md) resolves filed *issues*, [`token-rotation`](TOKEN-ROTATION.md) keeps *credentials* current. This one improves what nobody filed a ticket for — documentation accuracy, onboarding, clarity, small correctness gaps — in each opted-in submodule's **own upstream repository**, delivered as a **draft pull request there**.

| | | |
| --- | --- | --- |
| **Workflow** | [`.github/workflows/repo-evolution.yml`](../.github/workflows/repo-evolution.yml) | weekly Mon 10:37 UTC + dispatch |
| **Planner** | [`.github/scripts/dash-gen/evolution.py`](../.github/scripts/dash-gen/evolution.py) | `dash-gen targets` / `dash gen targets` |
| **Brief material** | [`.github/evolution/`](../.github/evolution/) | goals + method template, category emphasis |
| **Config** | [`_data/fleet.yml`](../_data/fleet.yml) → `schedule.repo_evolution`, `evolution:` | cadence, caps, marker, backpressure |
| **Opt-in** | [`_data/projects.yml`](../_data/projects.yml) → `auto_evolve: true` | per project |
| **CLI** | `tools/dash evolve --repo <name>` · `--all` | dispatches the workflow |
| **Tests** | `python3 .github/scripts/dash-gen/test_evolution.py` | no network, no pytest |

> **Two evolution layers — don't confuse them.** `unified-evolution.yml` evolves the
> **monorepo itself** and is dispatch-only (`tools/dash evolve`). This loop evolves the
> **fleet**: one agent per opted-in submodule, one draft PR in that submodule's upstream.

## The loop

```text
          ┌──────────────────── weekly Mon 10:37 UTC · repo-evolution.yml ─────────────────────┐
          │                                                                                  │
          │  job: plan  (deterministic)                 job: evolve  (matrix, needs: plan)    │
          │  ┌──────────────────────────────────┐       ┌───────────────────────────────────┐ │
registry ─▶  │ 1. SELECT   auto_evolve: true    │       │ per repo:                         │ │
_data/    │  │             + submodule          │       │  · checkout its upstream          │ │
projects  │  │             + owned upstream     │       │    (FLEET_TOKEN, no persisted     │ │
.yml      │  │             + not archived       │       │     credentials)                  │ │
          │  │ 2. DEDUPE   skip if its previous │       │  · Opus Claude Code reads the     │ │
triage ───▶  │             pass is still open   │       │    brief, orients (README-First), │ │
_data/    │  │ 3. CAP      max_targets          │       │    makes a few surgical fixes,    │ │
fleet_    │  │ 4. BRIEF    facts + signals +    │──────▶│    verifies, reports              │ │
triage    │  │             focus + goals +      │artifact│  · workflow commits as the bot,   │ │
.yml      │  │             category emphasis    │       │    pushes ai-evolution/<date>-<n>, │ │
          │  └──────────────────────────────────┘       │    opens a DRAFT PR (marker first)│ │
          │        probes FLEET_TOKEN + Claude auth      └───────────────────────────────────┘ │
          │        FIRST — fails before any spend                                              │
          └──────────────────────────────────────────────────────────────────────────────────┘
                                                                        │
                                                  human reviews the draft in the target repo
```

### 1. Plan — deterministic

`dash-gen targets` runs before any model does, and everything selective happens there:

- **Select.** A registry entry qualifies only if it opted in (`auto_evolve: true`), is a
submodule, its upstream is owned by the hub's owner, and it is not `status: archived`. The owner guard is the same one [`tools/fanout.sh`](../tools/fanout.sh) applies — an external mirror such as `microsoft/skills` must never receive a pull request from us, whatever the registry says.
- **Dedupe.** A repo whose previous evolution PR is still open is skipped, recognised by the
`ai-evolution/` branch prefix **or** the hidden marker in its body (`<!-- repo-evolution key="owner/repo" -->`), so a renamed branch cannot fool it. One unreviewed draft is a proposal; a stack of them is noise. `force` overrides for one run.
- **Cap.** `evolution.max_targets` bounds the run; anything dropped is listed in the run
  summary, never silently truncated.
- **Brief.** One `evolution-workorders/evolution-workorder-<name>.md` per survivor, uploaded as
  the `evolution-workorders` artifact. See [Reading the brief](#reading-the-brief).

The plan job also **probes** `FLEET_TOKEN` with `gh api user` (a present-but-expired PAT has silently degraded this fleet before) and requires Claude auth, and fails *before* any agent runs when either is missing — a pass that cannot be delivered is money burned.

### 2. Evolve — one job per repo

Each matrix job checks the target repository out at its declared branch, downloads its brief into `.evolution/` (excluded from git, so it can never be committed there), and runs one Opus Claude Code agent with a prompt whose hard rules are fixed in the workflow:

- the brief's **Conformance gaps** section (from `_data/conformance.yml`, written by `dash spec fleet --write`) is the agent's adoption lane: failing Universal Project Standard rows, MUST first, each pointing at its spec file and a reference implementation in `_data/references.yml`;
- the agent reads the brief, then orients README-First (`README.md`, `CLAUDE.md`,
  `AGENTS.md`, `CONTRIBUTING.md`, `SCHEMA.md` — house rules there override the prompt);
- it makes a **small number** of high-leverage, obviously-correct changes in the brief's
priority order — documentation → clarity → functionality — verifies with the repo's own lint/tests, and leaves the tree clean;
- its **final message becomes the PR body** (what changed / why / verification / not done);
- it **never commits, pushes, or opens anything**. The checkout keeps no credentials, the
  allowlist grants only read/verify commands (`git status|diff|log`, `gh issue|pr view`, the
  test runners — no `git push`, no `gh pr create`), and publishing is the workflow's step.

Then the workflow — and only the workflow — commits as `bamr87-bot`, pushes `ai-evolution/<yyyymmdd>-<run id>`, and opens a **draft** PR in the target repo with the brief's marker as the first line of the body, the agent's report, and a link back to the run. It refuses to publish if the agent moved `HEAD` off the base branch, and it drops any lockfile a verify step produced ([always-latest policy](DEPENDENCIES.md)). No changes → no branch, no PR, one summary line.

**The publish step re-derives its own remote and never trusts `origin`.** `claude-code-action` resolves its repository from `github.repository` — the *hub*, not the checkout — and revokes its own installation token before the step ends, so it leaves the tree pointing at `bamr87/bamr87` with a dead credential. Run #1's `scripts` job checked out `bamr87/scripts` and pushed to `bamr87/bamr87.git`; the push failed on `Invalid username or token`, which was the lucky outcome — one that *succeeded* would have put a submodule's changes on the hub. So the step sets `origin` from `$NWO`, clears any `http.<server>/.extraheader` the agent step left behind, hard-fails with a named `::error::` if the remote is anything but `$NWO`, and pushes to the explicit URL rather than the remote name. `test_evolution.py` asserts all four ([#214](https://github.com/bamr87/bamr87/issues/214)).

**A finished agent is never thrown away for overshooting the cap.** `claude-code-action` fails the step when the turn count exceeds `--max-turns` *even when the agent reported success* — run #1's `README` job was billed $2.85 for completed work that `Open draft PR` then never saw, because a failed step skips the rest of the job. The `Salvage a successful overshoot` step reads the agent's own verdict out of `claude-execution-output.json` (`subtype == "success"` **and** `is_error == false`; a genuine turn exhaustion reports neither), warns, and lets the publish step run anyway. Raising `max_turns` makes the case rarer; only this makes it non-destructive.

### Lanes — why it does not collide with the other loops

The brief *tells* the agent about the repo's failing workflows and open issues and PRs, and the prompt *forbids* acting on them: a failing workflow belongs to the fleet doctor, an open issue to the issue pipeline, an open PR to whoever opened it. The signals are context — where the repo hurts — not work. What is left is exactly this loop's lane: the improvements nobody filed.

## Reading the brief

```text
<!-- repo-evolution key="bamr87/scripts" -->     ← dedupe marker; the workflow copies it into the PR body
# Evolution brief — scripts
## Repository (from the registry)                ← upstream, branch, category, stack, status, description
## Signals (the fleet's current view)            ← from _data/fleet_triage.yml: attention level + reasons,
                                                   failing workflows, open issues (bugs first), open PRs
## Focus for this run                            ← the dispatch `focus` input, or "none given"
## Goals / ## Method                             ← .github/evolution/evolve-prompt.md, rendered
## Category emphasis                             ← .github/evolution/categories/<category>.md
```

Preview the briefs the next run would write, offline:

```bash
tools/dash gen targets --no-dedupe            # plan as JSON on stdout; briefs in evolution-workorders/
tools/dash gen targets --target scripts --focus "the README's install section" --no-dedupe
```

## Adding or removing a repo

Edit **only** the registry, [`_data/projects.yml`](../_data/projects.yml):

```yaml
- name: scripts
  submodule_path: projects/scripts
  ...
  auto_evolve: true        # ← opt in / out here
```

The planner still refuses external upstreams and archived repos, so a stray opt-in is reported in the run summary rather than acted on. Today's opt-ins: `cv-builder-pro`, `README`, `scripts`.

## Running it by hand

```bash
tools/dash evolve --all                              # the weekly run, now
tools/dash evolve --repo scripts                     # one repo
tools/dash evolve --repo scripts -f dry_run=true     # run the agent, report the diff, push nothing
tools/dash evolve --repo scripts -f force=true       # even though its last pass is still open
tools/dash evolve --repo scripts -f focus='the README install section'
tools/dash evolve                                    # (unchanged) the hub's own dispatch-only pass
```

Or from the Actions tab: **🌿 Repo Evolution** → *Run workflow*.

## Configuration

All in [`_data/fleet.yml`](../_data/fleet.yml), read by the planner and wired into the workflow through the plan job's outputs so each number is stated once (`test_evolution.py` asserts the wiring):

| Key | Default | What it bounds |
| --- | --- | --- |
| `schedule.repo_evolution` | `0 9 * * 1` | the cron (the test asserts the workflow matches) |
| `evolution.enabled` | `true` | `false` → the plan is empty and says so |
| `evolution.skip_when_open_pr` | `true` | one open evolution PR per repo at a time |
| `evolution.branch_prefix` / `marker` / `label` | `ai-evolution` / `repo-evolution` / `ai-evolution` | how a pass is recognised and labelled |
| `evolution.max_targets` | `6` | repos per run |
| `evolution.max_parallel` | `2` | concurrent agents (the Claude loops share one OAuth account) |
| `evolution.max_turns` | `120` | per repo — orient, read, edit, verify, report. Run #1 (2026-08-31) measured that program at **46 / 61 / 63** turns (`scripts` / `cv-builder-pro` / `README`); the old cap of `60` sat at the median of real demand, so two of three targets were billed in full and produced no PR. Set above the observed ceiling, not at it. |
| `evolution.signals.max_issues` / `max_prs` | `8` / `5` | how much of the triage snapshot a brief quotes |

## Tokens

Both are part of the [token contract](../_data/fleet.yml) and already live on `bamr87/bamr87` (`tools/dash secrets` audits them):

| Secret | Role here |
| --- | --- |
| `CLAUDE_CODE_OAUTH_TOKEN` | Claude auth, OAuth-first at every call site; `ANTHROPIC_API_KEY` is the fallback ([AI-INTEGRATION.md](AI-INTEGRATION.md)). |
| `FLEET_TOKEN` | **Required.** Cross-repo checkout, push, labels, the draft PR — and the reason the PR gets CI: GitHub fires no workflow events for refs pushed with `GITHUB_TOKEN`. Probed, never presence-checked. |

The agent step receives `FLEET_TOKEN` only for read-only `gh` verbs (`issue view`, `pr view`, `run view`, …) so it can read a listed issue on a private target; the allowlist grants no writing verb.

## Where its output shows up

- The draft PRs, labelled `ai-evolution` + `automation`, in each target repository.
- Every run and every PR carrying the Claude marker is harvested into the fleet's
[`/ai-usage/`](https://bamr87.github.io/bamr87/ai-usage/) ledger by the daily pulse — no separate ledger is kept.
- The briefs, as the `evolution-workorders` artifact on the run (14 days).

## Safety model

- **Draft PRs only, opened by the workflow.** The agent has no credential to push with and no
  publishing command on its allowlist. Nothing merges automatically.
- **Signal-led, not speculative.** The brief is built from the committed triage snapshot;
the agent is told to prefer many precise fixes over one rewrite and that *no change* is a valid result.
- **Bounded.** Registry opt-in per repo, owner + archived guards, caps in `fleet.yml`, one
  open PR per repo, `fail-fast: false` so one repo's failure strands nothing else.
- **Observable.** The credential-rejected classifier (zero billed turns + empty
`modelUsage`) names the secret to rotate instead of reporting "Claude execution failed"; every exclusion the planner makes is listed in the run summary.
