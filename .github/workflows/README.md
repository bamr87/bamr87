# Workflows

GitHub Actions for the bamr87 dash. Two groups: the **control-plane** workflows
that keep the dash and its ~40 submodules aligned, and a **legacy** generic suite
kept dispatch-only.

## Control plane (live)

| Workflow | Triggers | Purpose |
| --- | --- | --- |
| `build-dash.yml` | push `main` (dash paths), 6h cron, dispatch | Builds the Jekyll dash + ephemeral health data; deploys to GitHub Pages. **The sole Pages surface.** |
| `drift-check.yml` | push `main`, PR, dispatch | Fast offline+API gate: registry↔`.gitmodules` parity, **stray/unregistered project dirs**, README AUTO freshness, missing top-level READMEs, **SCHEMA.md pyramid (h)**; advisory **GitHub-reality** (renames/deletions/branch) + **standardization**. Also runs `actionlint` over the live control-plane workflows (add new workflows to its list; legacy suite exempt). No Ruby/Jekyll build; the internal-link check is local-only (`--links`). |
| `refresh-dash.yml` | daily 04:00, dispatch | Regenerates the committable README `AUTO:projects` span + registry data; opens a PR. |
| `update-submodules.yml` | weekly Sun 03:00, dispatch | Bumps submodule pointers **up** into root (pointer-only staging); opens a PR. |
| `standardize-fanout.yml` | dispatch (per-repo or all) | Opens standardization PRs **down** into submodules via `tools/fanout.sh`, seeding `.editorconfig`, the reusable `standard-ci.yml` caller, and on request the **agent-context kit** (`CLAUDE.md` scaffold + `@claude` workflow). Dry-run default. |
| `schema-fanout.yml` | dispatch (per-repo or all) | Opens **Pyramid Schema** adoption PRs down into submodules via `tools/fanout.sh` (SCHEMA.md contracts + vendored linter + CI gate). Optional `agent_fill` runs a Claude Code pass that fills scaffold TODOs on the PR branch (single target only). Dry-run default. |
| `standard-ci.yml` | `workflow_call` | Reusable CI (detect stack → lint + test + build) that member repos adopt via a short caller. |
| `claude.yml` | `@claude` mention (issues/PRs) | Claude Code responds to `@claude` mentions in this repo. Same file the agent-context kit seeds into submodules. |
| `actions-usage.yml` | daily 05:00, dispatch | Queries the Actions API (PyGithub) for every registry repo; commits refreshed `_data/actions_usage.yml` (cost / effectiveness / waste per workflow) for the `/actions/` page. **Display name is load-bearing** — `actions-review.yml` triggers on it by string. |
| `actions-review.yml` | after `actions-usage.yml`, dispatch | Triages the worst workflows (failing / slow / high-cost) and runs an **Opus Claude Code reviewer** that deep-dives them and files ONE optimization **issue** per candidate (deduped by a hidden marker; capped per run). AI step self-skips when no Claude auth is provisioned. |

## Legacy / dispatch-only

`unified-cicd.yml`, `unified-release.yml`, `unified-maintenance.yml`,
`unified-evolution.yml`, and `workflow-dispatcher.yml` are a generic single-app
template. They only ever ran against the **root** tree (which has no app code —
the projects are submodules), so their scheduled triggers are removed; they
remain **`workflow_dispatch`-only** for reference and manual use. Prefer the
control-plane workflows above. `unified-evolution.yml` still powers the manual AI
evolution pass (trigger via `tools/dash evolve`).

## Standards

- One workflow per durable responsibility; propagate shared CI via the
  `workflow_call` template, not by copying near-duplicate workflows.
- Top-level `permissions: contents: read`; elevate per-job only where needed.
- Every job sets `timeout-minutes`; every write-capable schedulable workflow
  has a `concurrency:` group.
- **Claude auth (house convention):** every `anthropics/claude-code-action@v1`
  call site is OAuth-first —
  `claude_code_oauth_token: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}` with
  `anthropic_api_key: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN == '' && secrets.ANTHROPIC_API_KEY || '' }}`
  as the fallback. Provisioning: [`docs/AI-INTEGRATION.md`](../../docs/AI-INTEGRATION.md).
- **Bot identity:** automated commits use
  `bamr87-bot <10567847+bamr87@users.noreply.github.com>` (the noreply form is
  required by email-privacy push protection).
- Fan-outs go through `tools/fanout.sh` (dry-run default, PRs only,
  external-upstream guard) — don't inline new clone→seed→PR loops.
- Avoid scheduled write-capable workflows unless the owner confirmed perms/secrets.
- Update this README when adding, removing, or renaming workflows.

## Validation

`actionlint` runs in CI (drift-check.yml) and locally: `actionlint` from the
repo root. Also check that referenced local actions/scripts exist.
