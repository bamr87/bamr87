# `resolve-fleet-token`

Pick the first GitHub token that **works**, not the first one that happens to be
non-empty.

## Why

The common pattern for token selection is a three-way fallback:

```yaml
env:
  GH_TOKEN: ${{ secrets.FLEET_TOKEN || secrets.GH_PAT || github.token }}
```

`||` selects the first non-empty operand and performs no validity check. That is
fine when every candidate is equally capable, but it fails quietly in two common
situations:

- an **expired or revoked PAT** is still a non-empty string, so it wins the
  `||` chain and then returns `401` on the first real API call;
- the job-scoped **`GITHUB_TOKEN` is repo-scoped**, so against a *foreign*
  repository it returns `404 Not Found`, not `403 Forbidden`. The failure looks
  like "that repo/issue doesn't exist" rather than "you aren't allowed", which
  sends debugging in the wrong direction.

This action probes each candidate with an idempotent
`GET /repos/{owner}/{repo}` and hands back the first one that returns `200`.

## Usage

```yaml
- id: token
  uses: ./.github/actions/resolve-fleet-token
  with:
    fleet-token: ${{ secrets.FLEET_TOKEN }}
    fallback-token: ${{ secrets.GH_PAT }}
    default-token: ${{ github.token }}
    probe-repo: some-org/some-other-repo

- name: Do cross-repo work
  run: gh issue list --repo some-org/some-other-repo
  env:
    GH_TOKEN: ${{ steps.token.outputs.token }}
```

Set `probe-repo` to the repository the job actually intends to touch. Probing
the current repository proves nothing about cross-repo access.

To branch instead of failing:

```yaml
- id: token
  uses: ./.github/actions/resolve-fleet-token
  with:
    fleet-token: ${{ secrets.FLEET_TOKEN }}
    default-token: ${{ github.token }}
    probe-repo: some-org/some-other-repo
    fail-on-no-valid-token: 'false'

- if: steps.token.outputs.valid == 'true'
  run: ...
```

## Inputs

| Input | Default | Description |
| --- | --- | --- |
| `fleet-token` | `''` | Primary candidate. |
| `fleet-token-name` | `FLEET_TOKEN` | Name reported in `source`. |
| `fallback-token` | `''` | Second candidate. |
| `fallback-token-name` | `FALLBACK_TOKEN` | Name reported in `source`. |
| `default-token` | `''` | Last resort, normally `${{ github.token }}`. |
| `default-token-name` | `GITHUB_TOKEN` | Name reported in `source`. |
| `probe-repo` | `${{ github.repository }}` | `owner/repo` used for the probe. |
| `api-url` | `${{ github.api_url }}` | API base URL. |
| `fail-on-no-valid-token` | `'true'` | Fail the step when nothing validates. |

## Outputs

| Output | Description |
| --- | --- |
| `token` | The validated token, or empty when none validated. |
| `source` | Name of the secret the winning token came from. |
| `valid` | `'true'` or `'false'`. |

## When *not* to use it

For **same-repo** work, keep the plain `||` fallback. `GITHUB_TOKEN` is
genuinely sufficient there, and adding a network round-trip per job to confirm
something the platform already guarantees is not worth the latency.

## Safety notes

- Every non-empty candidate is `::add-mask::`ed *before* any probe runs, so even
  a rejected candidate cannot appear in logs.
- The probe is a read-only `GET`; re-running it has no side effects.
- Only the HTTP status code is captured; the response body goes to `/dev/null`.
- Tokens are passed to the script through `env:`, never interpolated into the
  script body.
