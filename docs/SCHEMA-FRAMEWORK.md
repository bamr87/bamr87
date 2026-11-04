# SCHEMA-FRAMEWORK — Pyramid Schema across the fleet

> The Pyramid Schema — `SCHEMA.md` structural contracts across the fleet, and how to follow, propagate and verify them.

How the dash carries, enforces, and propagates `SCHEMA.md` structural contracts — and how fleet experience flows back into the framework.

**One sentence:** every directory carries a small, lintable `SCHEMA.md` describing its contents one level deep, so stateless agents _look up_ structure instead of re-exploring it; the hub seeds that discipline into every submodule and gates it in CI.

## The four layers

```
┌ upstream ────────────────────────────────────────────────────────┐
│ pyramid-schema package (github.com/bamr87/SCHEMA): spec, linter,  │
│ template, protocol, scenario tests, token benchmark              │
└──────────────────┬───────────────────────────────────────────────┘
                   │ vendor (templates/schema/VERSION records commit)
┌ hub ─────────────▼───────────────────────────────────────────────┐
│ bamr87/bamr87: tools/schema_lint.py + templates/schema/ seed kit │
│ + the hub's own pyramid + drift-gate check (h)                   │
└──────────────────┬───────────────────────────────────────────────┘
                   │ seed (tools/seed-schema.sh · fanout.yml (kit: schema) PRs
                   │       · agent_fill via Claude Code OAuth)
┌ fleet ───────────▼───────────────────────────────────────────────┐
│ each submodule: own SCHEMA.md pyramid, vendored linter,          │
│ schema-check CI, protocol in CLAUDE.md                           │
└──────────────────┬───────────────────────────────────────────────┘
                   │ feedback (schema-check failures, registry schema:
                   │           status, drift signals → evolution loop)
                   └────────────► reinvest: fix upstream, re-vendor, re-seed
```

- **Upstream** owns the paradigm. Improvements discovered anywhere in the fleet are fixed there first (it has the 54-scenario test suite), then re-vendored here — bump `templates/schema/VERSION` in the same commit.
- **The hub** is both carrier and adopter: its own pyramid starts at [`../SCHEMA.md`](../SCHEMA.md) and lints in the drift gate at the strictest posture — **errors and warnings both gate** — so the machinery that seeds the fleet is itself under contract. Gitignored ephemera (`_data/project_health.yml`, `_data/ai_activity.yml`, build output) are registered `generated`, which tolerates absence, so clean checkouts and working trees lint identically.
- **The fleet** adopts via PRs, never pushes: each submodule gets its own self-contained pyramid (vendored linter, no dependency on the hub at runtime) and gates itself with `schema-check.yml`.
- **Feedback** closes the loop: adoption status lives in the registry (`schema:` sub-key per project), schema-check failures surface on the monitor board like any other CI signal, and recurring pain patterns go upstream.

## Commands

```bash
python3 tools/schema_lint.py check .        # lint the hub pyramid (drift gate check (h) — warnings gate too)
python3 tools/schema_lint.py check . --fix  # remediate mechanical drift: register strays, prune stale rows
python3 tools/gen-projects-schema.py        # regenerate projects/SCHEMA.md from the registry
tools/seed-schema.sh <name>                 # DRY RUN: what adoption would add to projects/<name>
tools/seed-schema.sh <name> --apply         # seed a local submodule worktree
tools/check-drift.sh                        # full gate, including (h)
```

Seeding is idempotent and additive-only: existing files are never overwritten, existing `SCHEMA.md` files are never touched, the protocol snippet is appended once. External submodules (e.g. `projects/skills` → microsoft/skills) are refused without `--force-external`.

## Propagation via GitHub Actions

**`fanout.yml` (kit `schema`)** (dispatch-only, dry-run by default) is the fleet rollout mechanism, mirroring `fanout.yml` (kit `standardize`):

1. For each bamr87-owned submodule (or one `target`): shallow-clone, run `tools/seed-schema.sh --apply`, commit to `chore/schema-adoption`, open a PR against the repo's default branch. Requires the **`FLEET_TOKEN`** secret (fine-grained PAT, contents + pull-requests + workflows write on targets).
2. With **`agent_fill`** (single target only): after seeding, a `anthropics/claude-code-action@v1` job authenticated by the **`CLAUDE_CODE_OAUTH_TOKEN`** secret (generate with `claude setup-token`) checks out the PR branch and replaces scaffold TODOs with real one-line purposes, converts enumerations to pattern rows, marks build output `generated`, and keeps the linter green — then pushes to the same PR.

Rollout playbook: dispatch with `target=all, dry_run=true` and read the logs; pick a pilot (`target=<name>, dry_run=false, agent_fill=true`); merge its PR and let `schema-check.yml` run in the submodule; then fan out the rest in batches, setting `schema: {status: pending, pr: …}` → `adopted` in `_data/projects.yml` as PRs open and merge.

## Run it locally

The agent pass of either kit runs on a workstation through the JEV loop runner ([JEV.md](JEV.md#the-loop-runner-p1); epic [#484](https://github.com/bamr87/bamr87/issues/484), [#488](https://github.com/bamr87/bamr87/issues/488)) from the same specs CI's prompts are held to — [`tools/jev/steps/fanout/agent-fill-schema.yml`](../tools/jev/steps/fanout/agent-fill-schema.yml) + `agent-fill-schema.prompt.txt` and the `standardize` pair beside it; `python3 -m tools.jev steps check` holds each kit's inline prompt in `fanout.yml` byte-equal to its spec. One claude-code-action step per kit, gated on the dispatch's kit, replaced the shell `case` over two heredocs: a step spec holds one prompt. The target repository at the kit's PR branch is the workspace, exactly as in CI, so a local run needs the fan-out to have pushed that branch first (`fanout.yml` with `dry_run=false`); the planner checks it, and skips a target whose branch is missing or already carries the `(Claude agent pass)` commit CI's dedupe reads.

```bash
tools/dash loop doctor fanout                                        # $0 host checks for both kit steps
tools/dash loop plan fanout agent-fill-schema --target <name>        # the target at chore/schema-adoption: branch state, dedupe, prompt sha
tools/dash loop run fanout agent-fill-schema --target <name> --rehearse --offline   # the prompt, settings and argv, $0, no clone
tools/dash loop run fanout agent-fill-standardize --target <name>    # one capped attempt ($10, the call-site cap): the CLAUDE.md patch previewed
tools/dash loop show --latest                                        # items/<dir>/outputs/changes.patch, agent-fill.validated.json, bodies/
```

The attempt's output is the patch the engine harvests from the clone, held to the kit's brief (only `CLAUDE.md` for `standardize`, only `SCHEMA.md` files for `schema`; anything else withholds the whole attempt), then `dash-gen agent-fill-file` runs the structural rules and writes the exact patch and commit message CI's push step would make. `--apply` is **refused by the filer in this release**, naming #488: the publish step (the validated patch committed as the `(Claude agent pass)` commit and pushed to the kit's PR branch with `FLEET_TOKEN` probed by `gh api user`) lands with that issue's next pull request. Until then the preview is the deliverable, and nothing a local run does reaches GitHub.

## Adoption tracking

`_data/projects.yml` gains an optional per-project key (documented in the registry header):

```yaml
schema:
  status: adopted | pending | none
  pr: https://github.com/bamr87/<repo>/pull/<n>
```

## Why (measured)

The upstream package's benchmark, run against init-scaffolded copies of three fleet repos, measured orientation cost per placement task (schema chain vs full tree listing, ~4 chars/token, identical exclusions):

| repo           | dirs  | tree dump | mean chain | reduction  |
| -------------- | ----- | --------- | ---------- | ---------- |
| ai-seed        | 22    | 636       | 360        | +43%       |
| it-journey     | 161   | 14,100    | 1,036      | **+92.7%** |
| lifehacker.dev | 1,187 | 137,089   | 2,286      | **+98.3%** |

Below ~25 directories the dump is cheaper — small repos adopt for placement determinism and drift CI, not token savings. Full analysis: the upstream package's `docs/2026-07-15-effectiveness-report.md`.
