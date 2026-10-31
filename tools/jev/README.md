# tools/jev/ — JEV

> The fleet's harness-level AI agent logic engine: conflict-free numbering (ids assigned at merge, never in a pull request), tiered pull-request conflict triage and resolution, and loop step specs that CI and a local run render alike.

JEV is the fleet's planned agent logic layer ([bamr87/it-journey](https://github.com/bamr87/it-journey) `PRD.md`, Roadmap 2027 Q1). This directory holds its first two working capabilities, and the headless executor layer the second one's local runner is built on. The first answers one question the fleet asks several times a week: **a pull request says `This branch has conflicts that must be resolved` — now what?**

The second, [loop step specs](#loop-step-specs), gives each agent step one spec that CI and a local run render the same bytes from. The first capability's answer has two halves. The first removes the conflicts that should never have existed (numbering). The second resolves what is left, at the cheapest tier that can finish the job (the conflict engine). Full operator doc: [`docs/JEV.md`](../../docs/JEV.md). The rules it is held to: [amendment 0002](../../docs/amendments/0002-conflict-free-numbering.md).

## Quick reference

```bash
python3 -m tools.jev number next                        # the next free id in every series
python3 -m tools.jev number plan                        # what the pending fragments would be assigned
python3 -m tools.jev number apply                       # assign, compile, consume the fragments
python3 -m tools.jev number lint --base origin/main     # reject a hand-picked next number

python3 -m tools.jev conflicts scan                     # every CONFLICTING open PR in the fleet
python3 -m tools.jev conflicts scan --repo bamr87/bamr87
python3 -m tools.jev conflicts triage  --pr bamr87/bamr87#437
python3 -m tools.jev conflicts resolve --pr bamr87/bamr87#437 --dry-run
python3 -m tools.jev conflicts budget  --scheduled      # month to date against the cap

python3 -m tools.jev steps check                        # every step spec against its workflow and fleet.yml
python3 -m tools.jev steps render repo-scout scout --set NWO=bamr87/beta --set REPO_NAME=beta \
    --set BRANCH=main --set BRIEF=scout-workorder-beta.md   # the exact prompt bytes one leg gets
```

Run from the repository root — `tools.jev` is imported as a package, so `python3 tools/jev/conflicts.py` will not work.

## Loop step specs

[`spec.py`](spec.py) loads the specs under [`steps/`](steps/README.md): one `<step>.yml` plus its `<step>.prompt.txt` per agent step a loop workflow runs. The spec holds what has no other home — the hard-rules prompt, the caller-filled `{{TOKEN}}` inputs, the tool allowlist, the wall clock, the workspace contract and the § 13.6 risk tags — and **references** `_data/fleet.yml` for the model, the turn cap and the call-site dollar cap. The model must resolve to an exact id in `ai_models.allowed`; an alias is refused. `steps check` holds every literal the workflow still carries (`--max-turns`, `--max-budget-usd`, the cost step's `budget-usd`, `timeout-minutes`, `--allowedTools`, the artifact paths, no GitHub token in the agent step's effective env — workflow, job and step — its `github_token` input or an earlier `$GITHUB_ENV` export) equal to the resolved spec, requires the agent step's `JEV_STEP_SHA256` to equal the spec pair's content hash, reports each declared `workspace.exceptions` gap (claude-code-action's own OIDC App token is outside the step's env, so it is declared there until the ADR 0002 follow-up closes it), and fails when the prompt orders a tool the allowlist does not grant. `steps render` prints the prompt byte-exact, rendered in one pass. Decision record: [ADR 0002](../../docs/adr/0002-agent-step-specs-and-local-runner.md).

## The headless executor

[`headless.py`](headless.py) is the layer a local loop attempt runs headless Claude Code through (jev conflicts' tiers 1–2 still build their own argv; they move onto it before either tier is enabled). It is P1's first slice ([ADR 0002](../../docs/adr/0002-agent-step-specs-and-local-runner.md#p1--the-headless-executor-and-its--138-posture)): the executor is dash-gen's `tools/dash ai run`, extended rather than forked, and it imports this module lazily — this directory never imports dash-gen.

- **Session isolation** (`claude_flags`): `--restricted` (no user, project or local settings file is read, so a target repo's hooks, `env` block and permission rules never load), `--safe-mode` (no CLAUDE.md, memory, skills, plugins, mods or hooks), `--tools` limited to the spec's tool families, `--permission-mode dontAsk --permission-prompts none`, the spec's allowlist verbatim plus `DENY_TOOLS`, an empty strict MCP config, no slash commands, no session persistence, the `LOCAL_RUNNER_NOTE` appended to the system prompt and a debug file.
- **The sandbox** (`settings_doc`): Seatbelt for Bash and its children, `failIfUnavailable`, no unsandboxed escape, no auto-approval, `allowedDomains: []` with `strictAllowlist`, reads fenced to the working directories, and every credential variable and file denied. `Posture("reduced")` (no Bash at all; PR-B exposes it as `loop run --posture reduced`) is the only fallback.
- **The environment** (`agent_env`): built from scratch — PATH, HOME, the locale and offline git/npm/pip settings, and at most ONE Claude credential, chosen by `choose_auth` in `CLAUDE_AUTH_ORDER` (env → stored login → hub `.env`, the first present wins, no in-run fallback). `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB` is deliberately absent: on 2.1.308 it forces the permission mode to `default`, overriding `dontAsk`.
- **The run** (`stream`, `classify`): a process group read line by line, a redacted and size-capped trace, a SIGINT-first wall clock, and an outcome in claude-cost's order — `budget_hit`, then `timeout` and `interrupted` (a cancel is never read as a rejected credential), `usage_limit`, `credential_rejected`, then the rest — where a run that may have spent but left no figure is charged at its cap as `estimated`. `init_problems` is the per-run posture check on a session's init record (exact toolset, `dontAsk`, no MCP, no skill).
- **Proof before trust** (`preflight_parse`, `probe_isolation`): $0 checks against the installed CLI, both in `probe_env` — the run's own environment with no credential and a scratch, logged-out `CLAUDE_CONFIG_DIR`, refused if it is logged in. The preflight runs the real argv (`run_prefix` + `claude_flags`) with stdin `/dev/null` and must get "Input must be provided", which proves every flag parses, and its debug log must show the `--settings` document loaded; which settings keys the CLI honours only the canary proves. The probe runs in a fixture that plants a hook, an `env` block, an output style, an MCP server, a skill, a CLAUDE.md and an AGENTS.md, once plain (the control, which must show the hook, the server, the output style and the skill, or the detector is stale) and once isolated (which must pass `init_problems`, run no hook or server, apply no planted env, and log the flag rules and "project memory is off"). Memory content and user-scope settings have no $0 check; they rest on the documented flags and the canary. `posture_template_sha` is the cache key a probe or canary pass is stored under. Both are code here; running them against the real CLI is the maintainer's deploy step (§ 10.5), not a test.

```bash
tools/dash ai run --call-site repo-scout.yml:scout --stream --timeout 1800 --isolate \
    --cwd <clone> --prompt-file <prompt.txt> --trace <trace.jsonl> --result-file <result.json> \
    --outcome-file <outcome.json> --usage-limit skip -- <headless.claude_flags(…)>
```

## The merge driver

`.gitattributes` marks every generated file `merge=jev-regen`. Git cannot install a merge driver from `.gitattributes` (by design: a repository must not be able to run a program on your machine just because you cloned it), so each clone opts in once:

```bash
git config merge.jev-regen.name   "keep ours, regenerate"
git config merge.jev-regen.driver "tools/jev/merge-regen.sh %O %A %B %P"
```

**GitHub ignores this driver.** Its mergeability check runs its own merge, so a driver only helps a local clone. That is why `CATALOG.md` and `docs/README.md` are also marked `jev-main-only`: pull requests do not edit them at all — `.github/workflows/jev-number.yml` regenerates and commits them on `main` after every push, and `drift-check.yml` fails a pull request that edits one:

```bash
python3 -m tools.jev generated list                       # main-only files and generated spans
python3 -m tools.jev generated guard --base origin/main   # what CI runs on a pull request
python3 -m tools.jev generated regen                      # what the post-merge job runs on main
```

If the guard fails your branch: `git checkout origin/main -- CATALOG.md docs/README.md`, commit, and change the generator's source instead. Generated **spans** in hand-written files (PRD feature block, README `AUTO:projects`, the `docs/DASH.md` CLI reference) are regenerated by the same job; on a pull request their drift checks only warn (`JEV_SPANS_ADVISORY=1`). Option (a), gitignoring the files and building them in CI, was rejected because they are linked and browsed on GitHub. Full rationale: [`docs/JEV.md`](../../docs/JEV.md#main-only-generated-files). For a main-only file the driver takes **main's** copy (theirs, when main is merged into your branch).

With it configured, a conflict in any other generated file resolves to **ours**, and the path is appended to `.git/jev-regen-pending` — your to-do list for the regeneration that actually decides the content. Without it, git falls back to its default text merge: safe, but it gives you back the hand-merge the driver exists to avoid. Either way a wrong generated file never reaches `main`: main-only files and spans are rewritten there after merge, and every other generated file still fails CI on drift.

`merge=union` is set on two append-only files — `docs/amendments/README.md` (the index table) and `_data/jev_resolutions.yml` (the ledger's record list). Union takes **both** sides of a conflicting hunk, in order, and does not deduplicate, so it is correct only where a repeated or reordered line is harmless and nothing is read positionally. Do not extend it to a file with front matter, a header block, or a list whose order means something.

## The tier ladder

Tiers are decided by `classify.py` from the trial merge alone — conflicted files, their kinds, hunk and line counts, and how many attempts have already failed. The same pull request always triages the same way, and the reason is printable without a transcript.

| Tier | Cost | What it handles | How |
| --- | --- | --- | --- |
| 0 | $0, no model | Every conflicted file is generated, a fragment, union-safe, or an id collision | regenerate · union · renumber via `number.py` |
| 1 | ≤ $0.25/attempt, Haiku 4.5 | ≤ 3 files, ≤ 40 conflicted lines, nothing under `.github/workflows/`, no auth/secret, migration or lockfile | a capped headless `claude -p` |
| 2 | ≤ $1.50/attempt, Sonnet | ≤ 15 files **or** ≤ 400 conflicted lines, or tier 1 failed | the same, with a stronger model |
| 3 | $0 | Anything larger; binary or lockfile; a workflow/secret semantic conflict; a squash-only repo; two failed attempts; the monthly cap | label `jev:needs-human` + the triage report as a comment |

Every tier resolves the same way: **merge the base into the head** with a merge commit, then validate by running whichever of the repository's own checks it carries (`check-drift.sh`, `schema_lint.py`, `governance_lint.py`, `docs_index.py --check`, `run-all-tests.sh`) plus a clean `git diff --check` and a sweep for leftover conflict markers. A failed validation is discarded — `git merge --abort` — and the next tier starts from the same clean trial merge. Nothing half-resolved is ever pushed.

## What JEV will not do

- **Never merges a pull request.** `common.assert_no_admin` refuses `gh pr merge` and any `--admin` at the one place every GitHub call goes through.
- **Never force-pushes and never rebases.** The pull request's history belongs to whoever opened it; a force-push would detach review comments from their commits.
- **Never touches settings, secrets or branch protection.**
- **Only same-repo branches, only listed authors.** A fork's branch and a human collaborator's branch are tier 3 by policy (`jev.allowed_authors`), because JEV pushes to the head branch.
- **Runs only the tiers it is given.** `jev.auto_tiers` (today `[tier0]`) — anything above is labelled `jev:needs-human` rather than sent to a model.
- **Stops at the money.** `budget.jev.monthly_usd` is the ceiling; a scheduled run stops at `scheduled_stop_pct` of it so a human's manual run still has budget on the 28th.

## Cost

Each attempt is appended to `_data/jev_resolutions.yml` with its tier, model, outcome and `cost_usd`, and whether that figure was **reported** by the CLI (`total_cost_usd`) or **estimated** — the ledger reports the estimated share separately rather than presenting a measured half as a whole (the lesson of HUB-032 / NFR10). The same records carry `call_site: jev-conflicts` so the fleet's wider Claude accounting can read them.

Swapping the model is a one-line change in `_data/fleet.yml` `jev.tiers.<tier>.model`; [`docs/JEV.md`](../../docs/JEV.md) lists the alternatives that fit each tier's envelope, including local inference.

## Tests

```bash
python3 tools/test_jev_number.py      # the compiler: assignment, slug refs, consumption, the lint
python3 tools/test_jev_classify.py    # the tier ladder and the file-kind rules
python3 tools/test_jev_conflicts.py   # eligibility, validation, the no-merge/no-admin guard
python3 tools/test_jev_ledger.py      # the ledger and the monthly cap
python3 tools/test_jev_generated.py   # the main-only guard and the tier-0 main-only resolution
python3 tools/test_jev_spec.py        # step specs: byte identity, parity, the #89 lint, loader refusals
python3 tools/test_jev_headless.py    # the isolation argv, sandbox settings, agent env, auth choice, classifier, probes
```

They are standalone scripts — no pytest, no network, no `gh` — and `tools/run-all-tests.sh` and `.github/workflows/python-tests.yml` pick them up automatically.
