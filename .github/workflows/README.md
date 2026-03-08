# GitHub Actions Workflows

**Version**: 4.0.0
**Last Updated**: March 8, 2026

## Workflow Files

| File | Trigger | Purpose |
|------|---------|---------|
| `cicd.yml` | Push to `main`, PRs, manual | Lint, test, and build the CV Builder (Node.js), MkDocs documentation, and shell scripts |
| `build-docs.yml` | Push to `main` (docs paths), manual | Build and deploy MkDocs to GitHub Pages |
| `release.yml` | Tag push (`v*`), manual | Create GitHub Release with auto-generated changelog |
| `maintenance.yml` | Weekly (Mon 2 AM UTC), manual | Security audits, repo health checks, stale branch reporting |
| `submodule-sync.yml` | Daily (3 AM UTC), manual | Sync submodule pointers and open a PR with updates |
| `workflow-review.yml` | Weekly (Mon 6 AM UTC), manual | Collect workflow failures, generate a report, and create a GitHub issue for Copilot AI review |

## Architecture

```
cicd.yml            <- push / PR / manual        -- lint, test, build
build-docs.yml      <- push (docs paths) / manual -- MkDocs deploy
release.yml         <- tag push / manual          -- GitHub release + changelog
maintenance.yml     <- weekly / manual            -- security & health
submodule-sync.yml  <- daily / manual             -- submodule pointer updates
workflow-review.yml <- weekly / manual            -- AI failure review + issue
```

All workflows use `dorny/paths-filter` or path-scoped triggers to avoid unnecessary runs.

## Manual Triggers

```bash
# CI/CD
gh workflow run cicd.yml -f mode=full
gh workflow run cicd.yml -f mode=test-only
gh workflow run cicd.yml -f mode=lint-only

# Docs deploy
gh workflow run build-docs.yml

# Release (push a tag to trigger, or use manual)
gh workflow run release.yml -f draft=true

# Maintenance
gh workflow run maintenance.yml -f task=all
gh workflow run maintenance.yml -f task=security

# Submodule sync
gh workflow run submodule-sync.yml
gh workflow run submodule-sync.yml -f submodule=cv

# Workflow error review
gh workflow run workflow-review.yml -f lookback_days=14
```

## Required Secrets

| Secret | Used by | Purpose |
|--------|---------|---------|
| `GITHUB_TOKEN` | All | Default token (auto-provided) |


## Refactoring History

### v4.0.0 (March 2026) -- Simplification

**Removed:**

- `unified-evolution.yml` -- contained only stub print statements
- `workflow-dispatcher.yml` -- unnecessary meta-orchestrator; each workflow has its own triggers
- `update-submodule.yml` + `update-submodules.yml` -- redundant pair

**Added:**

- `submodule-sync.yml` -- single workflow replacing both submodule updaters
- `workflow-review.yml` -- periodic AI-powered failure analysis that creates GitHub issues

**Changed:**

- `unified-cicd.yml` renamed to `cicd.yml` -- rewritten with path-based change detection and real build steps (was referencing nonexistent composite actions)
- `unified-maintenance.yml` renamed to `maintenance.yml` -- simplified to security audits, health checks, and cleanup (was generic for 10+ languages)
- `unified-release.yml` renamed to `release.yml` -- simplified from 382-line multi-registry pipeline (npm/gem/docker/pypi/cargo) to focused GitHub Release workflow using `softprops/action-gh-release@v2`

**Result:** 8 files to 6 files, all functional with real steps matching the actual tech stack.
