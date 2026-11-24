# tools/

Development environment setup and maintenance utilities for the **bamr87 monorepo**.

## Overview

This directory contains cross-platform scripts for bootstrapping, configuring, and maintaining the development environment. The primary entrypoint is `setup.sh`, which reads package definitions from the central manifest `devtools.conf` and installs them using the platform-native package manager.

## Files

| File | Purpose |
| --- | --- |
| `devtools.conf` | **Central manifest** — declares all tools, packages, and env vars by platform |
| `devtools-env.sh` | Shell environment loader — exports vars, PATH, and aliases from the manifest |
| `Brewfile` | macOS Homebrew bundle — native `brew bundle` format (derived from manifest) |
| `setup.sh` | **Primary entrypoint** — cross-platform dev environment setup; on macOS its last step is `setup-terminal.sh` (`--skip-terminal` to opt out) |
| `setup-terminal.sh` | macOS-only: bootstraps the [bashOS `chui/`](https://github.com/bamr87/bashos/tree/main/chui) terminal (Oh My Zsh, Powerlevel10k, MesloLGS Nerd Font), registers the font with CoreText via `macos-register-nerd-fonts.swift`, applies it to Apple Terminal, and wires `~/.config/chui/local.zsh` to source `devtools-env.sh`. `--dry-run`/`--verbose`; no-ops on non-macOS |
| `macos-register-nerd-fonts.swift` | One-shot CoreText helper for `setup-terminal.sh` — registers the MesloLGS Nerd Font `.ttf`s with the user's font registry so Terminal.app can see them without a logout/login |
| `update-submodules.sh` | Refresh `projects/` — bring each submodule onto its declared branch at the remote tip (safe by default) and record moved pointers |
| `install-conflict-sweep.sh` | Installs the `com.bamr87.conflict-sweep` LaunchAgent (macOS), which runs `tools/dash conflicts sweep --scheduled` every few hours, so merge conflicts resolve in a local session. Run it yourself: it changes this Mac. |
| `install-harness-review.sh` | Installs the `com.bamr87.harness-review` LaunchAgent (macOS): daily, off the hour, it imports this machine's Claude Code sessions into the lake (`dash-gen lake sessions --days 2`), reads the console assistant's page audit and AI-ledger rows into it (`lake assist --days 7`), syncs the last two days of CI agent runs (`lake sync --days 2 --jobs ai --logs ai`), writes `lake review --days 7 --json` to `.fleet/refine/review-latest.json`, and runs the incident reflector `tools/dash refine reflect --scheduled` — guarded: skipped while `refine reflect` is not in the checkout or `harness_refinement.enabled` is not true. The reflector itself waits `reflect.every_days` (weekly), previews and notifies, and never files ([docs/HARNESS-REFINEMENT.md](../docs/HARNESS-REFINEMENT.md)). `--root PATH`, `--at HH:MM`, `--print-job`, `--print-plist`, `--uninstall`. Run it yourself: it changes this Mac. |
| `install-workspace-sync.sh` | Installs the `com.bamr87.workspace-sync` LaunchAgent (macOS) that runs `update-submodules.sh --no-commit --no-push` daily and at login, keeping the local clone on `main` everywhere — pointer recording stays with the `update-submodules.yml` PR (`--uninstall` removes it) |
| `install-prose-hook.sh` | Installs a **global** git `pre-commit` hook (`~/.git-hooks`, `core.hooksPath`) that runs `unwrap-prose.py` over the staged markdown and restages it, so a commit is born passing the `markdown-oneline` gate and the CI run it would have cost never happens; other hook names forward to each repo's own `.git/hooks`/`.husky` hooks. `PROSE_HOOK_SKIP=1` skips once, `--uninstall` removes it |
| `audit-git-hooks.sh` | Read-only diagnostic for the "Husky vs. pre-commit" question — reports which hook manager is actually live in a clone. Husky sets `core.hooksPath` to `.husky`, which makes git ignore the `.git/hooks` shim `pre-commit install` writes, so only one can be in effect and whichever installer ran last wins. Never installs or rewrites config, and always exits 0 |
| `fleet-dev.sh` | **The fleet dev stack's entry point** (`dash dev`) — launch, debug and work on any submodule from the hub. Drives each project as its OWN compose project joined by the external `fleet-net`, layering the hub's generated port override over the submodule's untouched compose file; `--debug` adds the repo's own debugpy layer. `up|down|ps|logs|exec|build|config|ports|list`, `--all` for everything. See [docs/FLEET-COMPOSE.md](../docs/FLEET-COMPOSE.md) |
| `fleet-compose.py` | Projects [`_data/ports.yml`](../_data/ports.yml) onto that stack — generates `compose/fleet.env`, `compose/overrides/*.yml` and `compose/fleet.yml`, and gates the allocation (bands, collisions, staleness) as drift check (m). `check --audit` also reports which submodules still hardcode a published port |
| `fleet_smoke.py` | **The monorepo smoke test** (`dash dev smoke`) — connects to every running fleet container and exercises it for real (HTTP GET, TCP connect, a `select` through the container's own `psql`, `redis-cli PING`, and an `exec` that records which user the process runs as), writes the whole observation to `_data/smoke.yml`, and `check` re-probes and fails on any move away from that baseline. Topology comes from `_data/ports.yml`, so a new service is probed automatically |
| `test_fleet_dev.py` | Tests for `fleet-dev.sh` and `fleet_smoke.py`, each one something a local deploy of the fleet workspace found on 2026-11-17: `dash dev up zer0-cms` selected no service because every one is behind a compose profile, the smoke test looked for the hub under `fleet-hub` and called a healthy console absent, a `docker run` copy of the console replaced the real one's health, and a check with only the core up reported every project nobody had started as a regression. Runs the launcher against a stub `docker`; PyYAML only. |
| `docker_harmonize.py` | The **fleet Docker standard** (`dash docker`) — brings a repo's Dockerfiles and compose files to it from ONE version registry (`_data/fleet.yml` `images:`): variant kept, never lowered, deliberate pins respected, Postgres 18 mount, loopback env-overridable ports, no `container_name`, `127.0.0.1` healthchecks. Line edits that preserve comments; idempotent. `tools/fanout.sh --kit docker` delivers it as PRs. See [docs/DOCKER.md](../docs/DOCKER.md) |
| `docker_view.py` | The **consolidated Docker view** (`dash docker view --write`) — joins the port registry, the image contract, the smoke recording, the launch/attach configurations and the read-only harmonizer audit into `_data/docker.yml`, rendered at `/docker/`: what to open, what is running, which image each service is on, and where that drifts from the contract (a deliberate pin, an `image_overrides:` ceiling and a floating tag are counted apart from real drift). Local-first — two of its inputs only exist where the containers and submodules are. |
| `test_docker_view.py` | Tests for `docker_view.py` — each one a mistake it actually made before it shipped: comparing majors instead of the contract's precision (which reported five repos on Python 3.11/3.12 as conforming to 3.14), counting a deliberate pin or an `image_overrides:` ceiling as drift, taking a multi-stage `FROM base` for an image, and reporting a repo with no checkout as clean. Run by drift check (n). |
| `pg-major-upgrade.sh` | Upgrade a compose service's Postgres across a MAJOR without losing data (`dash dev db-upgrade`; `--check` is the `dash up` and `dash dev up` preflight): backs up the raw volume, dumps, verifies, recreates on the new layout, restores. Dry run without `--yes` |
| `dash` | Unified dash CLI (`status`, `monitor`, `dev`, `serve`, `sync`, `ai`, `gen`, `harnesses`, `console`, `lake`, …) — see [docs/DASH.md](../docs/DASH.md); `dash lake sync|status|export` is the local data lake + Phoenix trace export of the local stack ([docs/HARNESS-OPS.md](../docs/HARNESS-OPS.md)) |
| `console/` | The **Harness Console** — the local control plane's front end: a FastAPI service (`tools/dash console`, or `docker compose up -d console` → http://127.0.0.1:4001) that renders every committed fleet signal (harness inventory, schedules, throughput, cost trends, triage, credentials by age), runs the **allowlisted** `dash` operations as jobs with live logs (dry-run by default; GitHub-writing operations confirm-gated and serialized), dispatches control-plane workflows, and edits the `harnesses:` contract in `fleet.yml` with comments preserved — never commits, never merges. Its **Traces** tab is the window onto the rest of the local stack: the data lake (`dash lake`, `.dash-lake/`) and the Phoenix trace store (compose service `phoenix`, :6006). See [docs/HARNESS-OPS.md](../docs/HARNESS-OPS.md) |
| `dash` | Unified dash CLI (`status`, `monitor`, `serve`, `sync`, `ai`, `gen`, `harnesses`, `console`, `lake`, `observe`, …) — see [docs/DASH.md](../docs/DASH.md); `dash lake sync|status|export` is the local data lake + Phoenix trace export, and `dash observe up|ship|status` the log plane beside it ([docs/HARNESS-OPS.md](../docs/HARNESS-OPS.md), [docs/OBSERVABILITY.md](../docs/OBSERVABILITY.md)) |
| `console/` | The **Harness Console** — the local control plane's front end: a FastAPI service (`tools/dash console`, or `docker compose up -d console` → http://127.0.0.1:4001) that renders every committed fleet signal (harness inventory, schedules, throughput, cost trends, triage, credentials by age), runs the **allowlisted** `dash` operations as jobs with live logs (dry-run by default; GitHub-writing operations confirm-gated and serialized), dispatches control-plane workflows, and edits the `harnesses:` contract in `fleet.yml` with comments preserved — never commits, never merges. Its **Observe** tab is the window onto the rest of the local stack, one pane per plane: **Logs** (Elasticsearch/Kibana, embedded), **Metrics** (Grafana) and **Traces** (the data lake `dash lake`, `.dash-lake/`, plus the Phoenix trace store on :6006) — all three joined by one `trace.id`. See [docs/HARNESS-OPS.md](../docs/HARNESS-OPS.md) and [docs/OBSERVABILITY.md](../docs/OBSERVABILITY.md) |
| `observability/` | The local **log plane's** configuration — the Logstash pipelines (two inputs, one shared ECS-mapping and redaction path), the label-gated Filebeat shipper, and the Elasticsearch ILM policies, index templates and Kibana/Grafana dashboards **rendered** from `_data/fleet.yml` `observability:` by `dash observe verify --write`. `bootstrap.sh` installs them into a running stack; `docker compose --profile elk up -d` starts it. Local-only: loopback ports, Docker volumes, never in CI. See [docs/OBSERVABILITY.md](../docs/OBSERVABILITY.md) |
| `dash-gen` | Wrapper for the registry generator (`health`, `readme`, `ai`, `ai-usage`, `actions`, `daily`, `triage`, `remediate`, `reconcile`, `vendor`, `estimate`, `ledger`, `all`) in [.github/scripts/dash-gen/](../.github/scripts/dash-gen/) |
| `fleet-config.py` | Reads [`_data/fleet.yml`](../_data/fleet.yml), the fleet's central config. `audit` (= `dash secrets`) prints the per-repo matrix of declared secrets/variables vs what GitHub actually has; `sync --apply` (= `dash config sync`) projects the canonical repo **variables** onto every fleet repo; `show [dotted.key]` reads a value; `rotate` (= `dash secrets rotate`) runs the weekly credential loop — audit each repo's secret AGE from GitHub's `updated_at`, re-mint via the optional OAuth refresh grant, propagate hub-first to missing/stale copies — and `rotation-plan` (= `dash secrets plan`) is its read-only half. `keys` (= `dash keys [status|verify|rotate|watch]`) manages the Anthropic API keys per Console workspace (`api_keys:`) through the Admin API (`CLAUDE_CONSOLE_TOKEN`, with the `anthropic` SDK). The API cannot create keys, so new Console keys come from `.env`. It matches each to its Console record by the partial hint, runs one cheap test call, writes hub-first to the workspace's repos, and disables the replaced key. The ledger is `_data/api_keys.yml`. `auth` (= `dash config auth [sync --apply]`) resolves the per-repo AI auth order (`ai_auth:`: `repos:` > `groups:` > `default:`), shows what each repo holds, and projects `CLAUDE_AUTH_ORDER`. Every secret writer honours that order. `push` (= `dash secrets push`) is the operator's rotation path: it parses the hub's `.env` (never sources it), takes only the token contract's names, writes the hub first and then fans the `scope: fleet` ones out — the Harness Console's Auth tab runs the same command. A multi-line secret is named by path (`NAME_FILE=…`, how the release app's PEM key gets in), and a value that is not shaped like its credential stops the push before anything is written. Secret *values* are never read or stored: `gh` returns names only, and a value to be written comes from the environment and goes straight to `gh secret set`'s stdin. See [`docs/TOKEN-ROTATION.md`](../docs/TOKEN-ROTATION.md). |
| `check-drift.sh` | **Hard drift gate** — registry/`.gitmodules` parity, README freshness, schema pyramid, and advisory checks: GitHub reality, and (q) that every hub pin in `templates/` resolves at its ref (CI + `dash status`) |
| `audit-standards.sh` | Standardization conformance matrix across the submodule fleet (wrapped by `dash audit`) |
| `run-all-tests.sh` | Aggregate verification — root lint, **the control plane's own `dash-gen` tests**, and each project's own checks (wrapped by `dash test`) |
| `adopt-release.sh` | Scaffolds the release-please pipeline into a repo and opens a PR (wrapped by `dash adopt-release`) |
| `protect-branch.sh` | Wrapper of `branch_policy.py protect` / `check` (wrapped by `dash protect`): plans the fleet ruleset on a repo's default branch, writes it with `--apply` |
| `branch_policy.py` | The branch model as code ([docs/BRANCHING.md](../docs/BRANCHING.md), `_data/fleet.yml` `branches:`): `classify` a branch name; `protect` plans one ruleset, `fleet-default-branch` (merge commits only per § 12.2, the CI gate named as its check run reports, no required approval, no linear history), and writes it only with `--apply`; `check` audits what GitHub enforces on the branch from every source, read-only (tests: `test_branch_policy.py`) |
| `fanout.sh` | Shared fan-out engine — clone→branch→seed→commit→PR loop with dry-run and external-upstream guard, called by `.github/workflows/fanout.yml` (one dispatch for every kit) and by `dash harnesses deploy` / `dash verify deploy`. Targets resolve through `.gitmodules` **or**, for a registered repo that is not mounted as a submodule, through `_data/projects.yml` — the engine clones the target either way, so a mount was never what made a repo reachable. A **pre-flight** resolves the hub pins in the kit's caller templates (`.github/scripts/dash-gen/hub_refs.py`) before any target is cloned: the dry run names an unresolved one and `--apply` refuses until it resolves (tests: `test_fanout_preflight.py`). `--upgrade` replaces a kit copy only when it is byte-identical to an archived shape, rendering a placeholder archive with its own filename version first (tests: `test_fanout_upgrade.py`). The assistant arm (`--kit assist`) takes a repo's platform from the planner (`dash apps assist`, the registry's `frontend.framework`) instead of the files at its root, seeds into the app's own folder, vendors nothing into a zer0-mistakes consumer, and keeps the copy a repo already has wherever it was moved to (tests: `test_fanout_assist.py`) |
| `issue-evidence.sh` | Builds one issue's **evidence bundle** in an isolated virtual environment — fresh clone, own toolchain (`venv`/`node_modules`/`vendor/bundle`), the project's own lint/test/build, screenshots, and issue-term-ranked candidate files. Tier 1 of the [issue pipeline](../docs/ISSUE-PIPELINE.md); `dash evidence <owner/repo> <n>`. Never executes commands found in an issue body, and scrubs credentials from every log it writes |
| `projects_backfill.py` | The issue-triage and **Fleet board backfill** pass (constitution § 10 / § 11; `dash projects`). `inventory` counts open issues and PRs per registry repo (the committed triage snapshot, or `--live`); `plan [--board]` compiles the reviewed decisions in [`_data/projects_backfill.yml`](../_data/projects_backfill.yml) (closes, label edits, sub-issue links; Status / Priority / Area for every open item on the Fleet project) into the § 11 service's ops, reads the current state and previews every batch as before → after with a deterministic plan id under `.fleet/backfill/`; the board targets widen with `--repos registry` (every registry repo), `--closed-since` / `--closed-before` YYYY-MM-DD (closed items as *Done*, minus the 2026-10-03 `not_planned` cleanup) and `--closed-only`, and the project is read up to `--max-items` (default 20000) so dedupe holds past the console's 500 (#453); `apply FILE --confirm` writes through `tools/console/gh_projects_write.py`, only with `HARNESS_PROJECTS_WRITES=1`, 50 ops a batch, audited. Issues and PRs go through REST (`gh api`); the board needs GraphQL, which is skipped and named where it is not reachable (a Claude Code cloud session, a token without `read:project`). Never merges, deletes, creates a label or prints a token |
| `test_projects_backfill.py` | Offline tests for `projects_backfill.py` — decisions validation and compilation, the 50-op batching, the REST state reader and executor against a recording fake `gh`, the flag + confirm refusals, board add-then-fields planning, Status / Priority / Area precedence, registry-wide and closed-window targets, the cleanup exclusion, dedupe on a project past 500 items, the applied ledger (run by `run-all-tests.sh`) |
| `pm_review.py` | The **routine PM review** (`dash pm`; [docs/PM.md](../docs/PM.md)). `review` reads every open issue and pull request of the registry repos, their pull-request state, recent comments and releases, and the Fleet project, then reports what is out of line with the project, the roadmap and each release train; `plan` prints the Fleet project ops it planned as before → after (applied by `dash projects apply`); `roadmap [--write]` the status edits for `_data/roadmap.yml`; `releases` the release train; `status` the committed snapshot. Read-only on GitHub: GETs and GraphQL queries only. |
| `check_rollup.py` | One rule for reading a commit's checks, shared by `weekly/closeout.py` (`checks_green`), `console/decision_index.py` and `pm_review.py`: a CANCELLED check run is set aside when a later run of the same check (workflow and name) on the same commit exists, so a label burst under `cancel-in-progress` does not read as red; `corrected_state` takes back GitHub's own FAILURE only when it can prove that, and `ROLLUP_FIELDS` is the GraphQL selection it needs. Pure functions; it reads nothing. |
| `test_check_rollup.py` | Offline tests for `check_rollup.py`: both rollup shapes (`gh pr view` and GraphQL), same-second ordering, a run not yet started, unreadable times, only a cancellation set aside, and `corrected_state` never turning anything red or green it cannot prove |
| [`weekly/`](weekly/README.md) | The **weekly routine** (`dash weekly`; [docs/WEEKLY.md](../docs/WEEKLY.md)), one stage a day. `close` (Friday) saves everything that exists only on this Mac, refreshes to main, and gives every open pull request and issue in the fleet one disposition, with one capped Claude Code session ruling on the stale ones. `prepare` (Saturday) checks that each activity scheduled for next week can run. `plan` (Sunday) builds the plan, the week day by day and the Monday brief. `confirm --apply` is the only external write (`wip/` pushes, Fleet project ops, the weekly PR) and never merges or closes; `brief <stage>` prints the Grok bot's half. |
| `test_weekly.py`, `test_weekly_dispositions.py`, `test_weekly_harness.py`, `test_weekly_stages.py` | Offline tests for the weekly routine: git on real throwaway repositories; `gh`, `docker`, `launchctl` and the model call as functions the tests supply. |
| `install-weekly.sh` | Installs the weekly routine's LaunchAgent (`com.bamr87.weekly`: Friday, Saturday and Sunday slots from `weekly.schedule`, each running `tools/dash weekly auto --scheduled`): the § 10.5 deploy step. `--print-plist` and `--print-job` show it, `--uninstall` removes it. |
| `test_pm_review.py` | Offline tests for `pm_review.py`: the scope, the gather against a recording fake `gh` that would see a write, each lane's rules, the preview the § 11 service accepts, the roadmap editor, private repos kept out of the snapshot, and the workflow's never-apply guard. |
| `uplift.py` | **Fleet uplift**, the hub's inbound arc (`dash uplift`; [docs/UPLIFT.md](../docs/UPLIFT.md)). Reads every fleet repo's default branch from the local submodule checkouts (and the hub's own) and compares file contents: a repo that changed a file other repos still hold in an earlier version, byte for byte, is a candidate, with exactly the repos behind and its route (`kit` when the earlier version is a hub source or carries a kit stamp, else `patch`); content that is the hub's own, came in on a fan-out branch (read from `fanout.sh`), carries a newer kit stamp or is held by `rollout_min` repos is a rollout in flight; a seed several repos filled in differently is a fork. A second lane lists the features each repo declared or shipped. `show` is one entry with its diff, `brief` the work order a session reads, `file` a previewed hub issue that `--apply` files byte for byte (never from a repo less visible than the hub, never twice, inside `uplift.file` caps), and `verify` re-derives who is behind a second way (the blob each shared path held at every commit of the window) and exits 1 when the scan lists a repo that method does not find, or misses one with no documented exclusion. No GitHub read, no model; writes `.fleet/uplift/`. |
| `test_uplift.py` | Offline tests for `uplift.py` against real git repositories built in a temp dir and a stubbed `gh`: each class of change, the chain of edits, what proves nothing (empty files, renames, reverts, a file added and deleted again, ignored paths and bots), unread and stale repos, the feature lane, every filing rule (previewed bytes only, visibility, credential shapes, the marker, the caps), the shown diff really applied with `git apply` to what each repo behind holds, and `verify` agreeing with the scan and catching a scan that is wrong. |
| `unpin-deps.sh` | Converts one repo to the fleet's **always-latest** dependency policy — strips exact pins, deletes + gitignores lockfiles, adapts CI installs (idempotent; the `deps-latest` fan-out kit runs it per clone). Run on the hub, it leaves the hub-only sanctioned runtimes of `specs/QUALITY.contract.yml` `sanctioned_lockfiles` alone (UPS-QA-40/41; tested by `test_quality_contract.py`) — see [docs/DEPENDENCIES.md](../docs/DEPENDENCIES.md) |
| `sanctioned_lockfiles.py` | The one parser of the hub-only lockfile exception (UPS-QA-40/41, UPS-REPO-07) in `specs/QUALITY.contract.yml`: who counts as the hub (origin `bamr87/bamr87`), which lockfiles it covers, and the drift checks. Imported by `conformance.py` and `check-drift.sh` (j); `unpin-deps.sh` runs `sanctioned_lockfiles.py paths <checkout>`. Malformed YAML/JSON becomes a one-line message (exit 2), never a traceback |
| `schema_lint.py` | Vendored Pyramid Schema linter (`check` + `init`) — provenance in [templates/schema/VERSION](../templates/schema/VERSION) |
| `gen-projects-schema.py` | Regenerates `projects/SCHEMA.md` from `.gitmodules` + the registry (`--check` gates staleness) |
| `render-diagrams.sh` | Validates every `diagrams/*.json` archify IR file and delivers the standalone HTML beside it |
| `unwrap-prose.py` | Liquid-safe one-paragraph-per-line unwrapper for markdown prose and list items (`--check`/`--diff`/`--write`); vendored into the fleet by the prose kit |
| `test_unwrap_prose.py` | Fixture tests for `unwrap-prose.py` — structure untouched, list items joined without leaving their list, idempotence (run by `run-all-tests.sh`) |
| `docs_index.py` | **The generated docs index** (specs/DOCS.md UPS-DOC-02/03): writes the `AUTO:docs-index` span in a repo's `docs/README.md` from each document's own summary line (front-matter `description:` or the `>` line under its H1); `--check` gates freshness, `--lint` lists documents with no summary or several H1s. Vendored byte-identical into every repo's `tools/` (drift check (i)); `conformance.py` imports this copy for UPS-DOC-02/03 |
| `test_docs_index.py` | Fixture tests for `docs_index.py` — run by `run-all-tests.sh` |
| `evals.py` | **The eval runner** (constitution § 13.1–13.2, [docs/EVALS.md](../docs/EVALS.md)): `list`, and `run <role>|--all [--json] [--dry-run] [--model ID] [--cases PATH]` over the sets in [`evals/`](../evals/README.md). Deterministic roles (`jev-classify`) import the code under test and run offline; model roles validate offline under `--dry-run` and otherwise ask a model from `_data/fleet.yml` `ai_models.allowed`, capped by `budget.local_usd`: `t1-intake` one prompt a case, `console-assist` the console's assistant against a recorded page (`tools/console/assist_eval_console.py`), whose model run must name its cases (`--canary`, `--all-cases`, `--case ID`; `--out DIR` keeps its files). Any failed case exits 1; `tools/test_evals.py`, run by the `python-tests` workflow, is the eval-regression check |
| `test_evals.py` | Tests for `evals.py`: the committed sets pass, the JSON shape, and a deliberately wrong expectation, a missing field, a duplicate id or too few cases each exit non-zero; the model path is tested with a stubbed `claude` (pinned id, budget cap). Run by `run-all-tests.sh` and the evals check |
| `test_conformance_instance.py` | **The two roots of the checker** ([ADR 0011](../docs/adr/0011-one-framework-many-instances.md), phase P0): `conformance.py --instance DIR` (default `$FLEET_HOME`, else `--hub`) grades the fleet of another control plane from this checkout. `--hub` stays the framework (spec, contracts, kits, tools); the instance supplies `_data/projects.yml` and `projects/`, and its own `standards.yml` and issue-type labels when it has them. The tests build a throwaway instance for a made-up owner that carries only its registry. |
| `test_vscode_launch.py` | The editor-is-a-front-door gate (constitution § 20, [`.vscode/README.md`](../.vscode/README.md)): the four `.vscode/` files parse, every `preLaunchTask`, `dependsOn`, compound member and `${input:…}` resolves, each picker equals its registry, every `:NNNN` an entry names is a port its plane publishes (devenv's workspace block, `_data/ports.yml` for `dash dev` projects, debugpy attach allocations), and no entry calls `fleet-dev.sh` directly or starts `fleet-hub` / `--all`; also fixture tests for `conformance.py` UPS-REPO-40 — run by `run-all-tests.sh` |
| `features_index.py` | **The fleet features index** (`dash features`): `check <repo>` validates a `features/features.yml` (schema `features/v1`; the legacy zer0/it-journey shape is accepted as-is — bad/duplicate ids fail, dangling paths warn, `{na: reason}` waives), `coverage <repo>` grades every feature's tests / user scenarios / evidence / `verified:` stamp **from files on disk**, `fleet --write` aggregates every checked-out submodule + the hub → `_data/features_index.yml` (the `/features/` page, refreshed weekly by `fleet-snapshots.yml`) with per-repo gaps and a ranked attention list. Feeds `fanout.yml` (kit `verify`)'s `gaps` target and `conformance.py`'s UPS-QA-50..53. Doc: [docs/VERIFICATION.md](../docs/VERIFICATION.md) |
| `test_features_index.py` | Fixture tests for `features_index.py` — run by `run-all-tests.sh` |
| `fleet_snapshots.py` | **The shrink guard of the weekly fleet snapshots** (#775). `.github/workflows/fleet-snapshots.yml` checks out every registry submodule its probed token can read, regenerates `_data/conformance.yml` (`dash spec fleet --write`) and `_data/features_index.yml` (`dash features fleet --write`), and runs `fleet_snapshots.py --before <copies of the committed files>` before it publishes: a scan that lost more than `--tolerance` (default 2) repos the committed snapshot read and the registry still lists, or that read no submodule at all, exits 1 with `::error::` and nothing is published. A repo that left the registry, is archived or is skipped by tier is excused; every submodule with no checkout is listed in the job summary (`--summary`). Tests: `test_fleet_snapshots.py` (also the workflow's shape) |
| `frontend_registry.py` | **The § 18 frontend registry**: `lint` validates every `_data/projects.yml` `frontend:` block (type, tier, framework, surfaces, token_version, entry_url, shell, enforce; drift check (o)), `launcher` prints the shell launcher manifest generated from it, `table` the registry table. Tests: `test_frontend_registry.py`; the UPS-FE-70..73 rows in `conformance.py` read the same block (`test_conformance_frontend.py`). Doc: [docs/FRONTEND-PLATFORM.md](../docs/FRONTEND-PLATFORM.md) |
| `sprint_record.py` | **The live expedite-sprint record** (constitution § 27.7): `lint` holds every `_data/sprints/<slug>.yml` (`sprint/v1`) to the standard — at most one active sprint, the three gates in order and passed by the maintainer, the phase behind its gate, no secret-looking value, every USD figure finite and labelled API-equivalent (estimate), an active sprint declared in `_data/work_queue.yml` and under its cap (drift check (r)); `show` prints the document the console's `/sprints` page reads. Read-only: a record changes only by pull request. Tests: `test_sprint_record.py` on `test_sprint_record_fixture.yml`. Docs: [_data/sprints/README.md](../_data/sprints/README.md), [docs/EXPEDITE-SPRINTS.md](../docs/EXPEDITE-SPRINTS.md) |
| `conformance.py` | **Executable Universal Project Standard checker** (`dash spec`): `check [path]` runs the machine-checkable rows of `_data/specs.yml` against one repo (kinds detected from the tree or `--kinds`; `--gate` fails on MUST; facts not visible offline are listed as `unverified`; `retired` spec rows are skipped; results are pass / **warn** / fail / unverified, and warnings never gate: a rule marked `rollout: warn` in `specs/WORK.contract.yml` reports its failures as warnings until Fleet Ops deletes the marker (except the rule's `hard_fail:` cases, such as UPS-REPO-21 `double_release`, which always fail), and a rule's own `warn:` clause (a deprecated-but-accepted shape) warns too; the UPS-WORK, UPS-AGENT-07/08/09 and UPS-REPO-21 rows are keyed to `specs/WORK.contract.yml` and fixture-tested in `test_conformance_work.py`; UPS-BE-10/11 (/healthz, /version) bind to `api, app (server-rendered)`, so an `app` repo with no server side, such as a browser-only SPA, a game or firmware, passes them as N/A, while kind `api`, a `manage.py`, `Dockerfile` or `Procfile`, a server framework dependency or a stdlib, asyncio or net/http server keeps them checked (`test_conformance_backend.py`)); `fleet --write` snapshots every submodule → `_data/conformance.yml` (the repo-evolution brief's adoption lane), carrying the file's `security:` block over byte for byte; the reusable `fleet-conformance.yml` runs the same checker in each repo's CI |
| `test_template_pins.py` | **Pins resolve** (#457): every `bamr87/bamr87` or `bamr87/.github` workflow or action that a caller pins at a tag or a full SHA exists at that ref. It reads the `uses:` values UPS-WORK-10 reads (the contract's `uses_keys`, `fleet_uses_value_re` and `pinned_ref_re`) in the seeded templates (`templates/`, minus `archive/` and `fixtures/`) and in the hub's own pin_scope, fetches each repo's `v*` tags as GitHub serves them into a scratch repository (depth 1, no blobs; the checkout is never touched), and fails on a pin whose ref lacks the workflow file or the action's `action.yml`/`action.yaml`. Offline, that check reports `skip`; the fixture tests need no network. Step 4 of a release in [docs/WORKFLOW-VERSIONING.md](../docs/WORKFLOW-VERSIONING.md#cutting-a-release); run by `run-all-tests.sh` and `python-tests.yml` |
| `test_claude_run.py` | **claude-run logs what it installed** (#499): the `claude-run` action prints `claude-run: Claude Code <version> on Node <version>` after the install, and warns, naming `$RUNNER_TEMP/npm-install.log`, when an install that exited 0 left no `claude` on PATH. Static checks plus the install span executed with stubbed `npm`/`node`; run by `run-all-tests.sh` |
| `scorecard_snapshot.py` | **The security-posture snapshot** (#513): `targets` lists the registry repos the weekly read-only `scorecard-sweep.yml` scans with the OpenSSF Scorecard CLI; `ingest DIR` folds its JSON into the raw cache `_data/scorecard.yml`; `--write` renders the `security:` block of `_data/conformance.yml` (seven checks; Pinned-Dependencies excluded: always-latest) and `--check` fails on a hand edit (drift check (f)). The dash's Projects `scorecard` column reads the block through `fleetcore.fleet.attach_security`. Tests: `test_scorecard_snapshot.py`. Doc: [docs/SECURITY-POSTURE.md](../docs/SECURITY-POSTURE.md) |
| `link_check.py` | **The fleet link check** (`tools/dash links`, weekly `link-check.yml`): finds every link the fleet publishes — each owned repo's tracked Markdown/HTML (fenced and inline code, comments and placeholders skipped; a relative link to a file resolved against the repo's tracked files, case-sensitively, the way GitHub does), the URL values of the data the profile README is generated from (`_data/projects.yml`, `_data/portfolio.yml`), and every live site of the registry and the portfolio crawled from its sitemap — and checks each unique link once: github.com and raw.githubusercontent.com through the GraphQL API in batches (repository, file at a ref, issue or pull request, commit, release tag, workflow badge; a repository GraphQL cannot see is retried over REST, which follows renames), everything else HTTP HEAD then GET. Reports `broken` · `error` · `moved` grouped by the repo or site that publishes the link, with `file:line`; `unverified` (a host that refuses robots) on `--show`. `url URL…` checks single links, `targets` lists what a scan reads. Read-only; a local cache of `ok` answers in `.fleet/links/`; settings in `_data/fleet.yml` `links:`. Tests: `test_link_check.py`. Doc: [docs/LINK-CHECK.md](../docs/LINK-CHECK.md) |
| `stargazer.py` | **The open-source radar** (`tools/dash stars`, daily `stargazer.yml`): reads the account's public GitHub stars and star lists, every fleet repo's topics, the repos rising this week, this month and in the fleet's topics, and one search per fleet project; writes `_data/stars.json` + `_data/stars_history.json` through the model in `fleetcore/stars.py` (categories, matches with the reason, star velocity, star-farming flags, a review list per project, the feed), and prints the slices, the session brief and the user-level hook install. `review --yes` is the AI pass (capped, tool-less sessions through `dash-gen ai-run` → `_data/stars_ai.json`), `metrics --push` feeds the Grafana dashboard `fleet-stars` through the OTel collector, `grafana --write` renders it. Read-only on GitHub; only `review --yes` spends ([docs/STARGAZER.md](../docs/STARGAZER.md)) |
| `architecture.py` | **The structure contract** ([docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md), ADR 0016): `check` holds the hub's own code to `_data/architecture.yml` — the import layers (generators < core < engines < surfaces), which non-test modules change `sys.path`, source files past 1,500 lines and committed `_data` files past 512 KB; `report [--json]` prints the measurements; `ledger --write` records a reduction (it lowers and drops entries, adds one only with `--accept-new`, never raises one). Runs on every pull request through `test_architecture.py` |
| `focus.py` | **The checks a change owes** ([docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md#the-checks-a-change-owes)): `python3 tools/focus.py` lists, and `--run [--keep-going]` runs, only the gates and tests the change against `origin/main` touched, from the registry `_data/checks.yml` plus the test beside each changed module. Every entry is an existing gate; a check whose `needs:` is missing here is reported as not run, never as passed |
| `gen-catalog.py` | Regenerates the root `CATALOG.md` — the master index of specs, kits, references, registries, tools, workflows, AI layer, docs, dash surfaces, diagrams — from disk + each directory's README/SCHEMA tables (`--check` gates staleness) |
| `gen-specs-data.py` | Regenerates `_data/specs.yml` (the machine-readable Universal Project Standard) from the requirement tables in `specs/*.md` (`--check` gates staleness) |
| `seed-schema.sh` | Seeds the schema kit into one repo (dry-run default) — see [docs/SCHEMA-FRAMEWORK.md](../docs/SCHEMA-FRAMEWORK.md) |
| `forge-ci.sh` / `forge_ci.py` | **Forge CI node** — invoke a checkout's fast GitHub workflows with `act` on forge and post commit status `forge/ci`. `dash host ci`, `forge ci`. Doc: [docs/FORGE-CI.md](../docs/FORGE-CI.md) |
| `test_forge_ci.py` | Fixture tests for `forge_ci.py` (allowlist, reusable inlining) — run by `run-all-tests.sh` |

## Architecture

```
bamr87/
├── .devcontainer/             # VS Code dev container config + image
├── .env.example               # Environment variable template
├── docker-compose.yml         # All services (dev, wiki, db, etc.)
└── tools/                     # This directory — the Files table above is authoritative
    ├── environment setup      #   devtools.conf, devtools-env.sh, Brewfile, setup.sh
    ├── dash CLI + gates       #   dash, dash-gen, check-drift.sh, audit-standards.sh, run-all-tests.sh
    ├── fleet operations       #   update-submodules.sh, adopt-release.sh, protect-branch.sh, fanout.sh
    └── schema tooling         #   schema_lint.py, gen-projects-schema.py, seed-schema.sh
```

## Central Tool Manifest — `devtools.conf`

All tools and packages are defined in a single file instead of being hardcoded in scripts. To add or remove a tool, edit `devtools.conf`:

```conf
# Sections group related packages
[core]
git                             # Available on all platforms
jq                              # JSON processor

[languages]
@brew    node                   # macOS only (via Homebrew)
@apt     python3                # Linux only (via apt)
@winget  OpenJS.NodeJS.LTS      # Windows only (via winget)
@custom  node-linux             # Requires special install logic

[devtools]
@pip     pre-commit             # Installed via pip on all platforms
@cask    visual-studio-code     # Homebrew cask (macOS GUI app)

[env]
BAMR87_HOME=~/bamr87            # Exported to shell environment
```

**Prefix reference:**

| Prefix    | Package Manager           | Platform          |
| --------- | ------------------------- | ----------------- |
| _(none)_  | Generic (brew/apt/winget) | All               |
| `@brew`   | Homebrew formula          | macOS             |
| `@cask`   | Homebrew cask             | macOS             |
| `@apt`    | apt-get                   | Ubuntu/Debian/WSL |
| `@winget` | winget                    | Windows           |
| `@pip`    | pip3                      | All (Python)      |
| `@npm`    | npm                       | All (Node.js)     |
| `@custom` | Custom install logic      | Platform-specific |

After editing `devtools.conf`, also update `Brewfile` to stay in sync for macOS users who prefer native `brew bundle`.

## Quick Start

### First-time Setup

```bash
# Clone the repo
git clone --recurse-submodules https://github.com/bamr87/bamr87.git
cd bamr87

# Run the setup script (auto-detects your OS)
./tools/setup.sh
```

### Setup Modes

```bash
# Full setup (local + Docker)
./tools/setup.sh

# Docker/dev container only
./tools/setup.sh --docker

# Local development only (no Docker)
./tools/setup.sh --local

# Specific components only
./tools/setup.sh --local cv docs

# Preview without making changes
./tools/setup.sh --dry-run --verbose

# Skip OS package installation (if you already have deps)
./tools/setup.sh --skip-deps
```

### macOS terminal (CHUI)

On Darwin, `setup.sh` also runs `setup-terminal.sh` unless you pass `--skip-terminal`. That clone-and-install path is [bashOS `chui/`](https://github.com/bamr87/bashos/tree/main/chui) (merged from bamr87/chui in 2026-10):

```bash
./tools/setup-terminal.sh            # clone ~/github/bashos, install chui/, register Meslo
./tools/setup.sh --skip-terminal     # hub tools only
```

Copying a Nerd Font into `~/Library/Fonts` is not enough — Apple Terminal keeps SF Mono until CoreText has registered the family. `macos-register-nerd-fonts.swift` does that, then CHUI's `macos-font.sh` sets profile **Clear Dark** to **MesloLGS Nerd Font**. If `ls` still prints `?`, run `ls` again in that window (or quit Terminal.app once).

bamr87 PATH/aliases live in `~/.config/chui/local.zsh` so they survive CHUI's `~/.zshrc` symlink. Do not append to that symlink from `setup.sh`.

### Shell Environment

The `.zprofile` (and CHUI `local.zsh`) source `tools/devtools-env.sh`, which:

- Reads the `[env]` section from `devtools.conf` and exports variables
- Adds `tools/` and `projects/scripts/` to `PATH`
- Registers convenience aliases

```bash
# Available after sourcing (or opening a new terminal):
bamr87-setup           # Run tools/setup.sh
bamr87-update          # Run tools/update-submodules.sh
bamr87-cv              # cd projects/cv-pro/app && npm run dev
bamr87-dash            # Run tools/dash (unified dash CLI)
bamr87-docs            # tools/dash serve — Jekyll dash via docker (:4000)
bamr87-dc              # docker compose (from project root)
```

To load manually in any shell:

```bash
source ~/bamr87/tools/devtools-env.sh
```

### macOS — Brewfile

macOS users can also install tools directly with Homebrew's native bundle:

```bash
brew bundle --file=tools/Brewfile
brew bundle check --file=tools/Brewfile   # Check what's missing
```

### Dev Container (VS Code)

1. Open the repo in VS Code
2. When prompted, click **"Reopen in Container"**
3. VS Code builds the dev container with all tools pre-installed
4. The `postCreateCommand` runs `setup.sh` automatically

### Docker Compose

```bash
cp .env.example .env                       # Configure
docker compose up -d                       # Start all services
docker compose exec devenv bash            # Dev shell
docker compose --profile admin up -d       # Include pgAdmin
docker compose logs -f                     # View logs
docker compose down                        # Stop
```

## Platform Support

| Platform           | Package Manager   | Status        |
| ------------------ | ----------------- | ------------- |
| macOS              | Homebrew (`brew`) | Full support  |
| Ubuntu/Debian      | APT (`apt-get`)   | Full support  |
| WSL (Windows)      | APT + winget      | Full support  |
| Windows (Git Bash) | winget            | Basic support |

## Adding a New Tool

1. Edit [tools/devtools.conf](devtools.conf) — add the package to the appropriate section
2. If macOS: also add to [tools/Brewfile](Brewfile)
3. If custom install logic is needed: add a case to `install_custom()` in [tools/setup.sh](setup.sh)
4. Test: `./tools/setup.sh --dry-run --verbose`

## Submodule Management

`update-submodules.sh` refreshes the `projects/` folder so every submodule sits **on its declared branch** (from `.gitmodules`) at the latest remote commit, then records the moved pointers in the root repo. It is safe by default: a submodule with uncommitted changes, unpushed commits, or a diverged history is skipped with a warning instead of being reset — pass `--force` to re-align those, or `--detach` for the legacy detached-HEAD behaviour.

```bash
./tools/update-submodules.sh --status      # Show declared vs. checked-out branch
./tools/update-submodules.sh --check       # List available updates (no changes)
./tools/update-submodules.sh               # Refresh all onto their declared branch
./tools/update-submodules.sh cv            # Refresh one (path, short name, or .gitmodules name)
./tools/update-submodules.sh --no-commit   # Refresh but leave pointer changes staged
./tools/update-submodules.sh --force       # Also re-align dirty/diverged submodules
```

Wrapped by `tools/dash sync` (which also regenerates dash data) and the `bamr87-update` alias.

## Troubleshooting

**Docker not starting:**

- macOS: Ensure Docker Desktop is running
- Linux: `sudo systemctl start docker`

**Port conflicts:** Edit `.env` to change ports, check with `lsof -i :5000`

**Submodule issues:** `git submodule sync --recursive && git submodule update --init --recursive --force`

**Permission denied on scripts:** `chmod +x tools/*.sh projects/scripts/*.sh`

**Python venv errors:** `rm -rf .venv-docs projects/README/.venv && ./tools/setup.sh --local docs`

**Terminal icons are `?`:** `./tools/setup-terminal.sh` (registers MesloLGS with CoreText). Then `ls` again.

**`pip3 install --user` fails (PEP 668):** expected on Homebrew Python. `setup.sh` uses `pipx` (`brew install pipx`).

---

**Version:** 2.3.0 | **Last Modified:** 2026-09-20

## JEV

[`jev/`](jev/) is the harness-level agent logic engine: the assign-at-merge numbering compiler (`python3 -m tools.jev number`), the tiered pull-request conflict triage and resolution engine (`python3 -m tools.jev conflicts`), and the loop step specs (`python3 -m tools.jev steps check|render`) — one file pair per agent step that CI and the local engine render the same prompt from — `headless.py`, the isolated, sandboxed headless Claude Code layer that `tools/dash ai run` executes local loop attempts through, and the local loop runner (`python3 -m tools.jev loop`, also `tools/dash loop`: `list`, `doctor [--live]`, `plan`, `run [--rehearse|--apply]`, `publish`, `show`, `budget`) with its hardened throwaway workspaces and per-loop adapters. It never merges a pull request and never uses `--admin`. Doc: [docs/JEV.md](../docs/JEV.md).
