# Scripts

Helper scripts in this directory must be reusable and configured through arguments or environment variables. Keep scripts here only when they are called by active workflows or documented as copyable workflow helpers.

## dash-gen/

The registry generator — the only part of this directory called by live workflows (`build-dash.yml`, `refresh-dash.yml`, `actions-usage.yml`, `actions-review.yml`, and the drift gate via `tools/`). Fronted by the [`tools/dash-gen`](../../tools/dash-gen) wrapper; subcommands: `health`, `readme`, `ai`, `actions`, `actions-review`, `all`. See [dash-gen/README.md](dash-gen/README.md).

## Copyable workflow helpers

Not referenced by any live workflow here; candidates to seed into submodules or delete.

| Script | Purpose |
| --- | --- |
| `comment-pr-preview.js` | Posts or replaces a pull request comment for a preview deployment. |
| `trigger-vercel-preview.sh` | Triggers a Vercel preview deployment when Vercel environment variables are configured. |

## Rules

- Do not hardcode repository names, personal accounts, or secret values.
- Document required and optional environment variables at the top of each script.
- Prefer exiting successfully when optional provider secrets are not configured.
