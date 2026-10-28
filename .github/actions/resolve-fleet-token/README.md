# `resolve-fleet-token`

Pick the first GitHub token that **works**, not the first one that happens to be non-empty, and export it as `GH_TOKEN` for the rest of the job.

## Why

The common pattern for token selection is a presence chain:

```yaml
env:
  GH_TOKEN: ${{ secrets.FLEET_TOKEN || github.token }}
```

`||` selects the first non-empty operand and performs no validity check. An **expired or revoked PAT** is still a non-empty string, so it wins the chain and then returns `401` on the first real API call — which is how, on 2026-09-27, every fleet-pulse gather step got 401 on all 43 repos, wrote zeros, and the run went green (#280). Every loop then grew its own inline probe loop; this action is that loop, written once (CLAUDE.md standing rule: *probe, never presence-check*).

## Contract

- Each PAT candidate (`fleet-token`, then `fallback-token`) is probed with an idempotent `GET /user`, which a PAT answers and the job-scoped `GITHUB_TOKEN` cannot. The first `200` wins.
- `default-token` (normally `github.token`) is **never probed**: it is the unprobed last resort that still reads this repo and public repos, so a degraded run is partial rather than blind. When it is used after a PAT was rejected, the step emits an `::error::` annotation naming the fix; the output `pat` is `false`.
- The winner is exported to `$GITHUB_ENV` as `GH_TOKEN` (configurable via `export`), so `gh` and every later step just work. The `token` output carries the same value for steps that need it as an input.
- Every candidate is masked before use, so a rejected one cannot leak.
- With no `default-token` and no working PAT the step fails (`fail-on-no-valid-token: 'false'` to branch on `valid` instead).

## Usage

```yaml
- id: token
  uses: ./.github/actions/resolve-fleet-token
  with:
    fleet-token: ${{ secrets.FLEET_TOKEN }}
    default-token: ${{ github.token }}

- run: gh api repos/bamr87/some-private-repo      # GH_TOKEN is already exported

- if: steps.token.outputs.pat != 'true'
  run: echo "::warning::degraded — cross-repo writes are off this run"
```

Require a working PAT (a loop that cannot deliver without one should fail before spending anything):

```yaml
- uses: ./.github/actions/resolve-fleet-token
  with:
    fleet-token: ${{ secrets.FLEET_TOKEN }}       # no default-token: a dead PAT fails here
```

## Inputs

| Input | Default | Description |
| --- | --- | --- |
| `fleet-token` | `''` | Primary PAT candidate (probed) |
| `fleet-token-name` | `FLEET_TOKEN` | Reported in `source` when it wins |
| `fallback-token` | `''` | Second PAT candidate (probed) |
| `fallback-token-name` | `FALLBACK_TOKEN` | Reported in `source` when it wins |
| `default-token` | `''` | Unprobed last resort; empty = a working PAT is required |
| `default-token-name` | `GITHUB_TOKEN` | Reported in `source` when it is used |
| `export` | `GH_TOKEN` | Env var the winner is exported to; empty = none |
| `fail-on-no-valid-token` | `'true'` | Fail when nothing can be used |

## Outputs

| Output | Description |
| --- | --- |
| `token` | The winning value (masked), or empty |
| `source` | The winning candidate's name, or empty |
| `valid` | `'true'` when any token is in use |
| `pat` | `'true'` when a probed PAT won |
