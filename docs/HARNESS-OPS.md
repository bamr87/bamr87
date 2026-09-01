# Harness Operations — centrally managing the fleet's AI harnesses and schedules

> [`docs/HARNESS.md`](HARNESS.md) is the architecture: the six layers, the scorecard, the trip wires — the hub watching **itself**. This document is the operations counterpart: how the hub **manages the harnesses deployed across the fleet** — observe them, create them, mass-update them, bound their throughput, and forecast their cost — and how the read-only monitoring plane differs from the processing plane you run locally or in the cloud.

## The model in one paragraph

The contract lives in version control (`_data/fleet.yml` → `harnesses:`); observed reality is gathered daily into a committed inventory (`_data/harness_registry.yml`, by `dash-gen harnesses` inside `fleet-pulse.yml`); a static page renders it read-only on GitHub Pages ([`/harnesses/`](https://bamr87.github.io/bamr87/harnesses/)); and every finding names its **lever** — the fan-out that deploys/updates kit artifacts ([`harness-fanout.yml`](../.github/workflows/harness-fanout.yml)), the rotation loop that provisions credentials ([`token-rotation.yml`](../.github/workflows/token-rotation.yml)), or the doctor that fixes failures ([`fleet-pulse.yml`](../.github/workflows/fleet-pulse.yml)). Nothing on the observation path writes to a fleet repo; nothing on the write path skips a pull request. That is the same declare → observe → reconcile split the token contract and the registry already use, applied to the harnesses themselves.

```text
   DECLARE                    OBSERVE                      ACT (levers, all PR-gated)
_data/fleet.yml          dash-gen harnesses            harness-fanout.yml   (deploy/upgrade kit)
  harnesses:      ──►   _data/harness_registry.yml ──► token-rotation.yml  (secrets)
  (baseline,             (daily, committed)            fleet-pulse doctor  (failures)
   throughput,                 │                       a human retuning a cron or a cap
   budget)                     ▼
                        /harnesses/  (read-only, GitHub Pages)
```

## What is a "harness" here

The deployable unit is the **agent-context kit** ([`templates/agent-context/`](../templates/agent-context/)): the `@claude` mention workflow (`claude.yml`, OAuth-first), the `CLAUDE.md` scaffold, and the opt-in `.claude` artifacts (settings baseline, shared guardrails, agent auditor). A repo's harness *state* is what the inventory reads back: which claude-code-action workflows it carries (mention handler / scheduled agent / event agent), on which action ref and auth shape, with which kit version stamp, plus its agent-context file, its `CLAUDE_CODE_OAUTH_TOKEN` presence (from the rotation ledger — never a value), and every cron it schedules. Repos may additionally declare their lanes in a `fleet.manifest.yml` (the `fleet/v1` spec from bamr87/wtd); the inventory records the manifest's presence (📜 on the board).

## Observe (read-only, statically generated)

- **[`/harnesses/`](https://bamr87.github.io/bamr87/harnesses/)** — the board: attention queue (ranked, lever named), cost trends + monthly forecast vs budget, throughput vs caps, the per-repo deployment matrix, and the fleet-wide UTC schedule calendar. It is rendered by `build-dash.yml` from the **committed** `_data/harness_registry.yml`, so the published site needs no credentials, no API calls, and no server — the monitoring plane is a static artifact of the data plane, deliberately.
- **`tools/dash harnesses`** — rebuild the inventory on demand. With a GitHub token it re-scans the fleet; without one it **reuses the previous committed scan** and refreshes only the offline analytics (trends, throughput, grading), so the command is always safe to run.
- **`tools/dash config show harnesses`** — the contract in force.
- The hub's own health stays on [`/harness/`](https://bamr87.github.io/bamr87/harness/) (`dash harness`, singular) — the two boards deliberately share the daily `pulse` commit.

## Create (enrol a repo)

Enrolment is the existing registration path plus two levers — nothing new to remember:

1. Register the repo in `_data/projects.yml` (the `update-registry` / `new-project` skills, or by hand). The next daily pulse scans it and grades it against the baseline; its gaps appear on `/harnesses/` and in `dash harnesses gaps`.
2. Deploy the kit: dispatch **`harness-fanout.yml`** with `target: gaps` (or `tools/dash harnesses deploy --gaps`), review the dry-run, re-dispatch with `dry_run: false`. Each target gets one PR in its own repo — additive-only, never a default-branch push.
3. Credentials arrive on their own: the weekly `token-rotation.yml` writes `CLAUDE_CODE_OAUTH_TOKEN` to any registry repo missing it (`dash secrets rotate --apply` to not wait). A missing secret is **deliberately not** a fan-out target — files and credentials ride different loops with different blast-radius rules.

## Mass update / deploy

`harness-fanout.yml` is the third fan-out on the shared engine (`tools/fanout.sh`), so it inherits every guarantee: **dry-run by default, PRs only, external upstreams skipped, additive-only seeding**. What it adds is the plan step: `target: gaps` reads the committed inventory and opens PRs **only where the data says so** — repos missing a kit-deployable baseline artifact, or running a machine-seeded harness whose stamp is behind the current kit version.

- **Deploy** (`artifacts: claude`, the default; add `agent-context,claude-settings,claude-guardrails,claude-agent-auditor` as wanted): seeds what is absent, touches nothing that exists.
- **Update** (`upgrade: true`): refreshes an existing copy **only when it is byte-identical to the current template or an archived machine-seeded shape** — proof it was seeded and never touched. Hand-modified harnesses are never rewritten, stamp or no stamp. This is the safe half of "mass update"; the unsafe half (rewriting a hand-edited workflow) intentionally does not exist.
- **Version discipline**: bump [`templates/agent-context/VERSION`](../templates/agent-context/VERSION) and snapshot the outgoing shape into `archive/` **before** editing a template — skip that and `--upgrade` silently stops reaching the fleet (see the header of `tools/fanout.sh` for the incident).
- CLI equivalent: `tools/dash harnesses deploy [--gaps|--target <name>] [--artifacts csv] [--upgrade] [--apply]`.

Requires `FLEET_TOKEN` with contents + pull-requests + **workflows** write on the targets (GitHub refuses a push touching `.github/workflows/*` without it).

## Control throughput

Scheduled agent work is a **standing commitment** — it runs whether or not anyone asked that day — so it is the half the contract caps (`harnesses.throughput`):

| Knob | Meaning |
| --- | --- |
| `max_scheduled_ai_per_day_fleet` | Estimated cron-driven AI workflow runs/day, fleet-wide |
| `max_scheduled_ai_per_day_repo` | The same per repo, so one repo can't absorb the whole budget |
| `max_ai_crons_per_utc_hour` | AI crons sharing one UTC hour — the Claude loops share one OAuth account's rate limit, so adjacency is contention |

The estimate is cron arithmetic (hourly = 24/day, weekly ≈ 0.14/day; the approximations are documented on `cron_fires_per_day`), cross-checked against the **observed** rate from `ai_usage.yml` (which includes mention/PR traffic riding on top). A violation is an attention item naming the cron; the fix is a human retuning the cron or the cap — by design there is no automatic throttle, because silently skipping a scheduled loop is exactly the failure mode (`stale-data`) the harness watches for. Per-run depth stays where it always was: each loop's caps and `--max-turns` in `fleet.yml`, asserted by fixture tests.

## Estimate costs from trends

`harnesses.budget` declares the ceilings; the inventory computes, from the committed ledgers (never a live API):

- **Claude CI spend** (`ai_usage.yml` by-day): window total, last-7d vs prior-7d, week-over-week %, and **projected monthly** = last-7-day daily average × 30.44.
- **Actions minutes** (`actions_usage.yml` by-day): same math, in minutes.

Crossing a ceiling → a `budget-breach` attention item; growing faster than `trend_warn_pct` week-over-week → `cost-trend`. Caveats, stated because they matter: CI logs price only what claude-code-action reports (`unpriced_runs` are counted, not guessed); Actions minutes on public repos are free — the figure is a *load* shadow price, which is exactly what makes a runaway visible (a 3350% WoW minutes spike is what this wire caught on its first offline run). Deeper attribution lives on `/ai-usage/`, `/actions/`, and the engagement ledger (`docs/ESTIMATION.md`); mid-run dollar enforcement remains the roadmap item tracked in `docs/HARNESS.md`.

## The two planes — local, cloud, enterprise

**Read-only plane (anyone, no credentials).** GitHub Pages serves `/harnesses/` and the other boards as static HTML built from committed `_data/*.yml`. Nothing secret is in the data (the token ledger carries names and ages, never values), nothing is computed at view time, and an outage of every API leaves yesterday's board standing.

**Processing plane (credentialed, two equivalent homes):**

- **Cloud — the default.** GitHub Actions *is* the hosted control plane: the scheduled loops (pulse, issue pipeline, rotation, evolution) run in ephemeral runners with secrets held by GitHub, and every write lands as a PR. There is nothing to keep alive; "deploying the stack" is having the workflows and secrets in the repo.
- **Local — the maintenance bench, with a front end.** `docker compose up -d devenv console` gives the same toolchain in a container with the repo mounted at `/workspace`, plus the **Harness Console** on http://127.0.0.1:4001 ([`tools/console/`](../tools/console/README.md), also `tools/dash console` natively): one browser surface to **view** every committed signal (the harness matrix, schedules and UTC-hour load, throughput vs caps, cost trends vs budget, triage, credential ages), **manage** the contract (edit the `harnesses:` block with comments preserved and see the git diff), **orchestrate** the loops (run each one's local half as a job with a live log, or dispatch its workflow in CI), and **deploy** the kit (dry-run → confirm → apply, or dispatch `harness-fanout`). It runs only the allowlisted `tools/dash` operations — parameters validated into argv, never a shell string — gates every GitHub-writing operation behind a confirm and a single lock, and never commits: generated data lands in the working tree for you to review. The Jekyll dash (`tools/dash serve`, :4000) remains the read-only twin. Everything CI runs is a `tools/` entrypoint first, so local and cloud execute the same code — CI is just cron plus credentials around the CLI.

**Enterprise hardening (an org account, not a personal one, unlocks the rest):** move the fleet into a GitHub organization and the version-controlled substitutes here upgrade to platform features — org-level secrets/variables replace `dash config sync` projection; org rulesets replace per-repo protection; **Workload Identity Federation replaces the stored one-year OAuth token entirely** (the zero-rotation path documented in [`docs/TOKEN-ROTATION.md`](TOKEN-ROTATION.md), which needs the Anthropic org console); larger runners or self-hosted runner groups absorb the minutes budget; and the same committed-YAML surfaces keep working unchanged, because they never depended on the account type. The contract file stays valuable even then — it is the reviewable record of *intent* that org settings pages don't give you.

## Operate — the short card

```bash
tools/dash console                        # the front end: view / manage / orchestrate / deploy on :4001
tools/dash harnesses                      # rebuild the inventory (offline degrade without a token)
tools/dash harnesses gaps                 # what the fan-out would fix
tools/dash harnesses deploy --gaps        # dry-run the kit PRs
tools/dash harnesses deploy --gaps --apply --upgrade
tools/dash config show harnesses          # the contract
tools/dash secrets rotate --apply         # credentials now instead of Monday
python3 .github/scripts/dash-gen/test_harness_registry.py   # the invariants
```

Dispatch surface: `harness-fanout.yml` (`target: gaps|all|<name>`, `artifacts`, `dry_run`, `upgrade`). Daily refresh: `fleet-pulse.yml` → publish → `/harnesses/` after the 07:00 `build-dash` run. Thresholds: `_data/fleet.yml` `harnesses:` — tune them the way the trip wires are tuned: a cap that is always breached is noise, prune or raise it deliberately.
