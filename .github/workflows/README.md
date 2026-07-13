# Workflows

GitHub Actions for the bamr87 dash. Two groups: the **control-plane** workflows
that keep the dash and its ~40 submodules aligned, and a **legacy** generic suite
kept dispatch-only.

## Control plane (live)

| Workflow | Triggers | Purpose |
| --- | --- | --- |
| `build-dash.yml` | push `main` (dash paths), 6h cron, dispatch | Builds the Jekyll dash + ephemeral health data; deploys to GitHub Pages. **The sole Pages surface.** |
| `drift-check.yml` | push `main`, PR, dispatch | Fast offline+API gate: registry↔`.gitmodules` parity, **stray/unregistered project dirs**, README AUTO freshness, missing top-level READMEs; advisory **GitHub-reality** (renames/deletions/branch) + **standardization**. No Ruby/Jekyll build; the internal-link check is local-only (`--links`). |
| `refresh-dash.yml` | daily 04:00, dispatch | Regenerates the committable README `AUTO:projects` span + registry data; opens a PR. |
| `update-submodules.yml` | weekly Sun 03:00, dispatch | Bumps submodule pointers **up** into root; opens a PR. Pointer changes only. |
| `standardize-fanout.yml` | dispatch (per-repo or all) | Opens standardization PRs **down** into submodules, seeding the reusable `standard-ci.yml` caller + baseline config (`.editorconfig`, etc.). |
| `standard-ci.yml` | `workflow_call` | Reusable CI (detect stack → lint + test + build) that member repos adopt via a short caller. |
| `actions-usage.yml` | daily 05:00, dispatch | Queries the Actions API (PyGithub) for every registry repo; commits refreshed `_data/actions_usage.yml` (cost / effectiveness / waste per workflow) for the `/actions/` page. |
| `actions-review.yml` | after `actions-usage.yml`, dispatch | Triages the worst workflows (failing / slow / high-cost) and runs an **Opus Claude Code reviewer** that deep-dives them and files ONE optimization **issue** per candidate (deduped by a hidden marker; capped per run). Needs `ANTHROPIC_API_KEY`. |

## Legacy / dispatch-only

`unified-cicd.yml`, `unified-release.yml`, `unified-maintenance.yml`,
`unified-evolution.yml`, and `workflow-dispatcher.yml` are a generic single-app
template. They only ever ran against the **root** tree (which has no app code —
the projects are submodules), so their scheduled triggers are removed; they
remain **`workflow_dispatch`-only** for reference and manual use. Prefer the
control-plane workflows above. `unified-evolution.yml` still powers the manual AI
evolution pass (needs `ANTHROPIC_API_KEY`).

## Standards

- One workflow per durable responsibility; propagate shared CI via the
  `workflow_call` template, not by copying near-duplicate workflows.
- Top-level `permissions: contents: read`; elevate per-job only where needed.
- Add a `concurrency:` group to every write-capable schedulable workflow.
- Avoid scheduled write-capable workflows unless the owner confirmed perms/secrets.
- Update this README when adding, removing, or renaming workflows.

## Validation

Run `actionlint` after editing; check that referenced local actions/scripts exist.
