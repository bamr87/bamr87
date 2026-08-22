# Token precedence for CI and fleet automation

This page is the **canonical** statement of which credential our GitHub Actions
workflows use, in what order, and what happens when the preferred one is not
available. Workflow files should link here rather than re-explaining the rule at
each definition site.

## TL;DR

```yaml
# The canonical expression. Use this verbatim wherever a workflow needs a token.
token: ${{ secrets.FLEET_TOKEN || secrets.GITHUB_TOKEN }}
```

Precedence, highest first:

| # | Token | Where it comes from | Available when |
|---|-------|---------------------|----------------|
| 1 | `FLEET_TOKEN` | Configured secret (see "Verify" note below) | Runs in this repository triggered by a trusted event, and only for actors with access to the secret |
| 2 | `GITHUB_TOKEN` | Minted automatically by Actions for every job | Always — including forks, including `pull_request` runs from forks |

There is no third fallback. If neither resolves to a usable credential the job
should fail loudly rather than silently skip work.

> **Verify:** the exact secret name, its scope (organisation-level vs.
> repository-level), and whether it is a personal access token or a GitHub App
> installation token should be confirmed against the repository/organisation
> secret settings. This document assumes an organisation-level secret named
> `FLEET_TOKEN`; correct this section if that is not accurate.

## What each token is

### `GITHUB_TOKEN` — the ambient token

Every Actions job gets a `GITHUB_TOKEN` automatically. You do not configure it,
you cannot see its value, and it is revoked when the job ends. Its important
properties:

- **Scoped to a single repository.** It can only act on the repository that owns
  the workflow run. It cannot read a sibling repository, open an issue
  elsewhere, or push to another repo in the fleet.
- **Permissions are declared, not inherited.** What it may do is whatever the
  `permissions:` block on the workflow or job says (subject to the repository's
  default workflow permissions). Omitting `permissions:` does not mean "full
  access"; it means "whatever the repository default is", which is why every
  workflow should declare the minimum it needs explicitly.
- **Read-only for pull requests from forks.** This is a platform rule, not a
  configuration choice. See [Fork behaviour](#fork-behaviour).
- **Does not trigger downstream workflows.** Commits, tags, and pull requests
  created using `GITHUB_TOKEN` deliberately do **not** start new workflow runs.
  This prevents infinite loops, and it is the single most common reason an
  automation-generated PR appears to have "no checks".
- **Acts as `github-actions[bot]`.** Commits and comments are attributed to the
  bot rather than to a named identity.

### `FLEET_TOKEN` — the elevated token

`FLEET_TOKEN` is a stored secret. It exists because a handful of things the
fleet automation needs to do are *structurally impossible* with the ambient
token, not merely inconvenient:

1. **Cross-repository work.** Fleet automation coordinates work across more than
   one repository (this repo tracks others — see `fleet.manifest.yml` and
   `.gitmodules`). Reading, dispatching to, or opening pull requests against
   another repository requires a credential whose scope is broader than one
   repository. `GITHUB_TOKEN` can never do this, at any permission level.
2. **Triggering downstream workflows.** When automation pushes a branch or opens
   a PR that is *supposed* to be validated by CI, the push must come from a
   non-`GITHUB_TOKEN` identity, or no checks will run.
3. **A stable, attributable identity.** Actions taken by the fleet are
   recognisable as the fleet rather than as generic CI, which matters for audit
   trails and for filtering notifications.

Everything else — checking out this repo, reading its contents, posting a status
— works perfectly well with the ambient token, and should not reach for
`FLEET_TOKEN`.

> **Verify:** list the concrete scopes/permissions granted to `FLEET_TOKEN` here
> once confirmed, so reviewers can reason about blast radius without opening
> the settings page.

## Why this fallback order is correct

The order looks like "most privileged first", which is the opposite of the usual
least-privilege instinct. It is correct here because **the fallback is about
availability, not about privilege**:

- `FLEET_TOKEN` is the *intended* credential for fleet workflows. When it is
  present, the run is happening in a trusted context (this repository, trusted
  event, actor with secret access) and the workflow should do its real job.
- `GITHUB_TOKEN` is the *degraded* mode. When `FLEET_TOKEN` is absent, the run is
  by definition happening in a less trusted context — a fork, a `pull_request`
  event, a freshly cloned repo with no secrets configured, or a local runner.
  In those contexts the ambient token is exactly the right amount of authority:
  enough to check out code, lint it, and run tests; not enough to mutate
  anything outside the run.

So the expression never *grants* more than the context deserves. It asks "am I
in the trusted context?" and, if not, falls back to the safe subset. Reversing
the order (`GITHUB_TOKEN || FLEET_TOKEN`) would be wrong: `GITHUB_TOKEN` is
always truthy, so the elevated token would never be used and cross-repo steps
would fail everywhere.

Omitting the fallback entirely (`${{ secrets.FLEET_TOKEN }}` alone) would also
be wrong: fork contributors would see an empty token and a confusing
authentication error instead of a clean read-only run.

## When each token applies

| Context | `FLEET_TOKEN` available? | Effective token | What works |
|---|---|---|---|
| `push` / `schedule` / `workflow_dispatch` on a branch in `bamr87/bamr87` | Yes | `FLEET_TOKEN` | Everything, including cross-repo and downstream-triggering steps |
| `pull_request` from a branch **in this repository** | Yes (secrets are exposed to same-repo PRs) | `FLEET_TOKEN` | Everything |
| `pull_request` from a **fork** | **No** | `GITHUB_TOKEN` (read-only) | Checkout, build, lint, test. No writes, no cross-repo access |
| Workflows running in **someone else's fork** of this repo (their own schedule/push) | No | Their repo's `GITHUB_TOKEN` | Read/write within *their* fork only |
| Local runs (e.g. `act`) or a clone with no secrets configured | No | Empty or whatever you supply | Read-only work; token-requiring steps should be skipped or expected to fail |

### Fork behaviour

GitHub does **not** pass repository or organisation secrets to workflow runs
triggered by `pull_request` from a fork, and it downgrades the ambient
`GITHUB_TOKEN` to read-only for those runs. This is a deliberate platform
protection: a pull request can change workflow code, so a fork PR must not be
able to obtain write credentials.

Concretely, if you are contributing from a fork:

- `secrets.FLEET_TOKEN` evaluates to the **empty string** — not an error, not
  `null`. The `||` therefore falls through to `GITHUB_TOKEN`.
- Read-only jobs (build, lint, test, link-check, docs generation) run normally
  and their results are meaningful.
- Any step that writes — pushing a commit, labelling, commenting, creating a
  release, dispatching to another repo — will fail, typically with
  `403 Resource not accessible by integration` or `Bad credentials`.
- **This is expected and is not something you need to fix in your PR.** A
  maintainer will re-run or complete the write-side work from a branch in this
  repository after review.

Do **not** "fix" a fork permission error by switching a workflow to
`pull_request_target`. That event runs the base repository's workflow with
secrets available while checking out untrusted head code, and is the standard
way repositories leak credentials to attackers. If a workflow genuinely needs
write access to fork PRs, raise it for discussion rather than changing the
trigger.

## Checklist for a new workflow

- [ ] Use `${{ secrets.FLEET_TOKEN || secrets.GITHUB_TOKEN }}` — do not invent a
      new precedence, and do not hardcode either token alone.
- [ ] Declare an explicit `permissions:` block with the minimum required.
- [ ] Ask whether the job actually needs `FLEET_TOKEN`. Single-repo read/write
      work does not; only cross-repo access and downstream-triggering pushes do.
- [ ] If the job cannot work without `FLEET_TOKEN`, guard it so fork PRs skip it
      cleanly instead of failing with an opaque auth error.
- [ ] Link to this file from the workflow where the token is resolved.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `403 Resource not accessible by integration` | Running with the ambient token (fork PR), or the job's `permissions:` block is missing the scope you need |
| `Bad credentials` / `401` | The secret is missing or misnamed in this repository/organisation, and the fallback also failed |
| Automation opened a PR but no checks ran | The push used `GITHUB_TOKEN`; commits made with it do not trigger workflows. Use `FLEET_TOKEN` for that step |
| Step tries to reach another repository and 404s | The ambient token is repo-scoped; a 404 (not 403) is GitHub hiding a resource you cannot see |

## See also

- [`CONTRIBUTING.md`](../CONTRIBUTING.md) — general contribution workflow
- [`AGENTS.md`](../AGENTS.md) / [`CLAUDE.md`](../CLAUDE.md) — automation conventions
- [`fleet.manifest.yml`](../fleet.manifest.yml) — repositories the fleet operates on
