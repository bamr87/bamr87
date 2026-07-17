# SCHEMA-FRAMEWORK — Pyramid Schema across the fleet

How the dash carries, enforces, and propagates `SCHEMA.md` structural contracts — and how fleet experience flows back into the framework.

**One sentence:** every directory carries a small, lintable `SCHEMA.md` describing its contents one level deep, so stateless agents _look up_ structure instead of re-exploring it; the hub seeds that discipline into every submodule and gates it in CI.

## The four layers

```
┌ upstream ────────────────────────────────────────────────────────┐
│ pyramid-schema package (~/github/SCHEMA): spec, linter, template, │
│ protocol, scenario tests, token benchmark                        │
└──────────────────┬───────────────────────────────────────────────┘
                   │ vendor (templates/schema/VERSION records commit)
┌ hub ─────────────▼───────────────────────────────────────────────┐
│ bamr87/bamr87: tools/schema_lint.py + templates/schema/ seed kit │
│ + the hub's own pyramid + drift-gate check (h)                   │
└──────────────────┬───────────────────────────────────────────────┘
                   │ seed (tools/seed-schema.sh · schema-fanout.yml PRs
                   │       · agent_fill via Claude Code OAuth)
┌ fleet ───────────▼───────────────────────────────────────────────┐
│ each submodule: own SCHEMA.md pyramid, vendored linter,          │
│ schema-check CI, protocol in CLAUDE.md                           │
└──────────────────┬───────────────────────────────────────────────┘
                   │ feedback (schema-check failures, registry schema:
                   │           status, drift signals → evolution loop)
                   └────────────► reinvest: fix upstream, re-vendor, re-seed
```

- **Upstream** owns the paradigm. Improvements discovered anywhere in the fleet are fixed there first (it has the 50-scenario test suite), then re-vendored here — bump `templates/schema/VERSION` in the same commit.
- **The hub** is both carrier and adopter: its own pyramid starts at [`../SCHEMA.md`](../SCHEMA.md) and lints in the drift gate, so the machinery that seeds the fleet is itself under contract.
- **The fleet** adopts via PRs, never pushes: each submodule gets its own self-contained pyramid (vendored linter, no dependency on the hub at runtime) and gates itself with `schema-check.yml`.
- **Feedback** closes the loop: adoption status lives in the registry (`schema:` sub-key per project), schema-check failures surface on the monitor board like any other CI signal, and recurring pain patterns go upstream.

## Commands

```bash
python3 tools/schema_lint.py check .        # lint the hub pyramid (drift gate check (h))
python3 tools/gen-projects-schema.py        # regenerate projects/SCHEMA.md from the registry
tools/seed-schema.sh <name>                 # DRY RUN: what adoption would add to projects/<name>
tools/seed-schema.sh <name> --apply         # seed a local submodule worktree
tools/check-drift.sh                        # full gate, including (h)
```

Seeding is idempotent and additive-only: existing files are never overwritten, existing `SCHEMA.md` files are never touched, the protocol snippet is appended once. External submodules (e.g. `projects/skills` → microsoft/skills) are refused without `--force-external`.

## Propagation via GitHub Actions

**`schema-fanout.yml`** (dispatch-only, dry-run by default) is the fleet rollout mechanism, mirroring `standardize-fanout.yml`:

1. For each bamr87-owned submodule (or one `target`): shallow-clone, run `tools/seed-schema.sh --apply`, commit to `chore/schema-adoption`, open a PR against the repo's default branch. Requires the **`FANOUT_TOKEN`** secret (fine-grained PAT, contents + pull-requests write on targets).
2. With **`agent_fill`** (single target only): after seeding, a `anthropics/claude-code-action@v1` job authenticated by the **`CLAUDE_CODE_OAUTH_TOKEN`** secret (generate with `claude setup-token`) checks out the PR branch and replaces scaffold TODOs with real one-line purposes, converts enumerations to pattern rows, marks build output `generated`, and keeps the linter green — then pushes to the same PR.

Rollout playbook: dispatch with `target=all, dry_run=true` and read the logs; pick a pilot (`target=<name>, dry_run=false, agent_fill=true`); merge its PR and let `schema-check.yml` run in the submodule; then fan out the rest in batches, setting `schema: {status: pending, pr: …}` → `adopted` in `_data/projects.yml` as PRs open and merge.

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
