# .claude/ — AI orchestration layer

Claude Code configuration that makes the dash self-managing.

## Contents

| Path | Purpose |
| --- | --- |
| `skills/update-registry/` | Reconcile `_data/projects.yml` with `.gitmodules` + repo metadata |
| `skills/refresh-portfolio/` | Regenerate monitoring data + README project list |
| `skills/sync-project-docs/` | Pull each project's current summary/status into the registry |
| `skills/sync-cv/` | Sync bamr87/cv's data/cv.json with the fleet via the `dash-gen cv` projection (`_data/cv_portfolio.json`) — curated merge PR, never a mechanical overwrite |
| `skills/drift-report/` | Explain drift-gate failures and the exact fix |
| `skills/standardize-audit/` | Audit the fleet against the tiered baseline (`dash audit`); explain each gap |
| `skills/standardize-project/` | Bring one submodule up to its tier baseline and open a PR |
| `skills/onboard-dir/` | Adopt or remove a stray/unregistered `projects/*/` dir the drift gate flagged |
| `skills/new-project/` | Scaffold + register a new project |
| `skills/triage-attention/` | Turn Monitor-board signals into prioritized actions |
| `skills/actions-triage/` | Explain the worst Actions workflows from `_data/actions_usage.yml`; drive a direct fix or dispatch `fleet-pulse.yml` (its `doctor` job is the AI fix pass) |
| `skills/issue-pipeline/` | Read the three-tier issue queues from `_data/issue_pipeline.yml`, build an issue's evidence bundle in an isolated virtual environment, and dispatch the intake/implement/complete tiers of `issue-pipeline.yml` |
| `skills/deep-dive-showcase/` | The Quest Log showcase for a repo the daily deep dive processed: the article and personal LinkedIn draft (bamr87.github.io), the company-page LinkedIn draft (bash-365.com), a presentation PR in the repo, then the ledger record (`tools/deep_dive.py record --article …`); drafts and PRs only, Amr merges ([`docs/SHOWCASE.md`](../docs/SHOWCASE.md)) |
| `skills/estimate-issue/` | Deep-analyze a GitHub issue into a client-engagement estimate in `_data/engagements.yml` (refines the `dash estimate` draft; approval stays human) |
| `skills/evolve-project/` | Focused per-project improvement pass (reads `.github/agents` personas as guidance; shares its goals file `.github/evolution/evolve-prompt.md` with the weekly `repo-evolution.yml` loop) |
| `skills/archify/` | Vendored [tt-a1i/archify](https://github.com/tt-a1i/archify) (MIT) — typed-JSON → validated HTML diagrams; the hub's harness/loop illustrations in `diagrams/` are authored with it and rendered by `tools/render-diagrams.sh` |
| `skills/verify-feature/` | **Agent verification**: prove a feature/change/fix works the way a user experiences it — read the feature index for context, run the app per `verify/verify.yml`, drive it in a real browser (Playwright MCP / `verify/runner.mjs`), capture evidence, link it back, report PASS/FAIL/NOT VERIFIED; plus the fleet view of `_data/features_index.yml` and `dash verify deploy` for seeding the kit ([`docs/VERIFICATION.md`](../docs/VERIFICATION.md)) |
| `agents/verifier.md` | sub-agent: the acceptance tester that follows `verify-feature` and never claims what it did not observe |
| `skills/run-dash/` | Orchestration hub: whole-repo project map + per-project "work order" (branch, stack, run cmd, context) for dispatching into a submodule; serve/screenshot the Jekyll dash. Driven by `driver.py` |
| `commands/harness/` | `/harness:status`, `:inventory`, `:health`, `:decisions`, `:graph`, `:gates`, `:refine`, `:learn`, `:lake` — observe and gate the harness ([below](#slash-commands-the-harness-and-its-loops-one-stage-at-a-time)) |
| `commands/loops/` | `/loops:list` and one command per loop (`:pulse`, `:issues`, `:conflicts`, `:pm`, `:credentials`, `:evolution`, `:scout`, `:fanout`, `:upkeep`) — run one stage of a loop ([below](#slash-commands-the-harness-and-its-loops-one-stage-at-a-time)) |
| `commands/console/` | `/console:ops`, `:run`, `:jobs` — the Harness Console's whole operation allowlist ([below](#slash-commands-the-harness-and-its-loops-one-stage-at-a-time)) |
| `commands/register-project.md` | `/register-project` — add/reconcile a project |
| `commands/adopt-release.md` | `/adopt-release <repo>` — adopt the standardized release-please pipeline (scaffold + PR) |
| `commands/adopt-schema.md` | `/adopt-schema <submodule>` — seed the Pyramid Schema kit into one submodule (preview → apply → PR) |
| `commands/future-features.md` | `/future-features <idea>` — draft a full feature spec + place it on the right repo's roadmap |
| `commands/weekly.md` | `/weekly [close\|prepare\|plan\|confirm]` — run a stage of the weekly routine as a preview and walk through it; `--apply` only on Amr's yes (docs/WEEKLY.md) |
| `agents/feature-scout.md` | sub-agent that scans the session thread for latent feature ideas and proposes roadmap-ready specs (review/approval before backlog) |
| `hooks/` | `SessionStart` + `Stop` hooks that make the Future-Features pipeline active in **every** session (see `hooks/README.md`) |
| `settings.json` | registers the hooks above |
| [`../.claude-plugin/marketplace.json`](../.claude-plugin/marketplace.json) | the **`bamr87` plugin marketplace**: kits under `templates/` published as Claude Code plugins a member repo enables from its own `.claude/settings.json` instead of vendoring. Today: `spec-driven` ([`templates/spec-driven/`](../templates/spec-driven/README.md), [`docs/SPEC-DRIVEN.md`](../docs/SPEC-DRIVEN.md)) — the `/spec-driven:specify … :evolve` skills, the `backlog-triager` agent, the spec/backlog gate hook |

The whole layer is the hub's **harness surface**: Harness²'s eight components (the context-file chain, the permission and hook blocks, agents, skills, commands, hook scripts, instructions, MCP) as `tools/dash refine surface check` reads them. It validates the rules the production harnesses converge on (a skill needs `name` and `description` frontmatter or it is dropped silently, a hooks block must have the runtime's shape, every script a component names must exist, the always-on chain is capped), and `tools/test_jev_surface.py` holds this directory clean ([docs/HARNESS-REFINEMENT.md](../docs/HARNESS-REFINEMENT.md)).

MCP servers (github, memory, sequentialthinking, context7, **playwright** — the browser the `verify-feature` skill drives, and **fleet** — the fleet console itself: the dashboards' views plus the Harness Console's allowlisted, confirm-gated jobs, [`tools/fleetcore/mcp_server.py`](../tools/fleetcore/README.md)) are configured in the repo-root [`.mcp.json`](../.mcp.json). The `github` server needs a `GITHUB_TOKEN` env var (referenced as `${GITHUB_TOKEN}` in `.mcp.json`).

> **Templates vs. subagents:** `.github/agents/`, `.github/instructions/`, and `.github/prompts/` are **Copilot-format reference templates** (per `.github/docs/toolkit-retention-map.md`) consumed in place by hub skills (e.g. `evolve-project` reads the agent personas) — nothing seeds them into submodules, and Claude Code cannot Task-launch them. Only `.claude/agents/` (feature-scout) are real subagents. For a working-diff review use the native `/code-review` skill.

## Slash commands: the harness and its loops, one stage at a time

Three namespaces, one per subdirectory of `commands/` (Claude Code types `commands/loops/scout.md` as `/loops:scout`). Each is a thin front door onto the Harness Console's operation allowlist, run from the terminal with [`tools/dash ops`](../tools/console/README.md#tools-dash-ops): the same operations, parameter validation and confirm gate as the console's Operations page, the terminal dash and the `fleet` MCP server. When the console is running for this checkout, a command's job is submitted to it and shows on its Jobs page; otherwise it runs in the terminal with the same argv. A command never carries a second implementation.

| Namespace | Commands | What they do |
| --- | --- | --- |
| `/harness:` | `status`, `inventory`, `health`, `decisions`, `graph`, `gates`, `refine`, `learn`, `lake` | Observe and gate the harness: the scorecard, the AI-workflow inventory against the standard, the agent contract, the decision queue, the fleet graph, the hub's gates, Harness² refinement, outcome learning and the data lake. All $0 but `refine reflect`, which asks first |
| `/loops:` | `list`, then one per loop: `pulse`, `issues`, `conflicts`, `pm`, `credentials`, `evolution`, `scout`, `fanout`, `upkeep` | Run ONE stage of a loop. The first argument is the stage, the rest its target: `/loops:scout plan`, `/loops:scout rehearse kvlite`, `/loops:scout run kvlite`, `/loops:scout publish <run_id>`, `/loops:scout ci` |
| `/console:` | `ops`, `run`, `jobs` | The whole allowlist: list or show operations, run any one with its parameters, and follow the console's jobs |

The stages every agent loop shares (`/loops:list` prints them):

| Stage | What it does | Cost and gate |
| --- | --- | --- |
| (none) | where the loop stands | $0 |
| `plan` | what the next run would do: the sample, the briefs, the queue | $0 |
| `rehearse` | everything up to the model call | $0 |
| `run` | the agent step here, one capped attempt per item, a reviewable preview under `.fleet/runs/` | Claude spend: asks first |
| `show`, `publish <run_id>` | read a run's preview; `publish` checks it, then with `apply` files it | filing writes to GitHub: asks first |
| `ci` | the loop's workflow in GitHub Actions, dry run unless told otherwise | runs in CI: asks first |

The rules each command carries, and `tools/console/test_ops_cli.py` holds:

- **Started by a person.** Every command sets `disable-model-invocation: true`: it is an operator entry point, Claude never loads one on its own, and none of their descriptions is in a session's context.
- **Nothing pre-approved writes or spends.** `allowed-tools` lists only `tools/dash` read paths and the operations that never write or spend; a gated operation appears only with `--explain` (prints, runs nothing) or as its dry run, never with `--confirm`. A gated stage exits 3; the command shows the explain output, asks with AskUserQuestion, and adds `--confirm` only after a yes.
- **One plain command per call.** No pipes, redirects or chains: a pre-approved pattern matches only the plain command (a compound one is prompted for or refused).
- **Equal to the console.** Each command declares the operations it runs in `metadata.ops` and, under `/loops:`, the console loops it drives in `metadata.loops`. The `/loops:` commands cover exactly the console's loops table (`core.LOOPS`, the Loops page), each with every local operation of its loop, a `run` stage where the loop has a local agent step, and a `ci` stage where it dispatches. `tools/dash ops loops` prints the join.

A new loop adds its row to `core.LOOPS` and its stages to a `/loops:` command in the same pull request; a new operation a command runs is added to `OPS` first. `/dash-status` and `/evolve` were folded into `/harness:status` and `/loops:evolution` (its `hub` stage is the old chain below).

## Standardization

`standardize-audit` (see what's off-standard, via `tools/dash audit` + [`_data/standards.yml`](../_data/standards.yml)) → `standardize-project` (fix one repo, PR into its own repo) → the `fanout.yml` (kit `standardize`) workflow (fleet-wide `.editorconfig` + reusable `standard-ci.yml` adoption, plus the `agent-context,claude` artifacts: `CLAUDE.md` scaffold, `@claude` mention workflow, and the minimal `.claude/settings.json` baseline from [`templates/agent-context/`](../templates/agent-context/)). The full standard lives in [`docs/STANDARDS.md`](../docs/STANDARDS.md).

## The Future-Features pipeline

Captures feature ideas before they're lost and routes them to the right repo's roadmap. The backlog is [`_data/roadmap.yml`](../_data/roadmap.yml) (source of truth; rendered at the dash **Roadmap** surface), targets come from [`_data/projects.yml`](../_data/projects.yml) (or `bamr87` for the monorepo).

- **Manual:** `/future-features <idea>` → drafts a full spec → review/approval → appends to `_data/roadmap.yml` (optionally opens a GitHub issue).
- **Automatic:** a `SessionStart` hook keeps the workflow active; a throttled `Stop` hook nudges the `feature-scout` sub-agent (once per session) when feature-signal language appears. The scout **proposes**; a human approves; nothing is backlogged without approval. Opt out with `FUTURE_FEATURES_AUTOSCOUT=0`.

## The self-evolution loop

`/loops:evolution hub` runs it: `triage-attention` (read Monitor signals) → `sync-project-docs` (update registry) → `evolve-project` (fix the top item) → `refresh-portfolio` (regen) → PR to `main` → drift + dash-build gates verify → human merges. There is no CI twin for the hub (its dispatch-only `unified-evolution.yml` was retired on 2026-10-27); the per-submodule CI pass is `repo-evolution.yml` (`tools/dash evolve --repo <name>`).
