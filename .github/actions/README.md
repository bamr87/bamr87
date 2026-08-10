# Actions

Composite actions used by this hub's own workflows. Every action here is called by at least one workflow in `.github/workflows/` — that is the entry bar, not a nicety.

## Layout

| Path | Purpose | Called by |
| --- | --- | --- |
| `setup/dash-gen` | Install Python + the dash-gen generator's dependencies. | `fleet-pulse`, `build-dash`, `refresh-dash`, `reconcile-registry` |
| `setup/configure-git` | Configure Git identity and authentication for automation. | `fleet-pulse`, `refresh-dash`, `reconcile-registry` |
| `utilities/publish-data` | Commit generated `_data/` files, falling back to a PR when the branch is protected. | `fleet-pulse`, `reconcile-registry` |

## Rules

- Keep each action focused on one responsibility.
- Pass project-specific values as inputs or environment variables.
- Do not hardcode registry hosts, organization names, local paths, or product-specific services.
- Include an `action.yml` and a README for every action directory.
- **An action with no caller is deleted, not kept "for later."** Seven actions were removed on 2026-08-09 (`ci/run-checks`, `ci/run-tests`, `deployment/build-push-image`, `deployment/build-n-cache-image`, `setup/setup-ruby`, `utilities/get-pr-labels`, `run-backend-tests`) — 3,500 lines that every reader of this directory had to evaluate and no workflow ever ran. Two were actively misleading: `setup/setup-ruby` existed while every workflow called `ruby/setup-ruby@v1` directly. The fleet's shared CI lives in reusable *workflows* (`.github/workflows/standard-ci.yml` and `bamr87/.github`), which is where generic build/test logic belongs; local composite actions are for glue this hub alone needs.

## Usage

Reference local actions from workflows with:

```yaml
- uses: ./.github/actions/setup/dash-gen
```

A calling workflow must `actions/checkout` the repo first — a local `uses:` path resolves against the checked-out tree.
