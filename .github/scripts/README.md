# Scripts

Helper scripts in this directory must be reusable and configured through arguments or environment variables. Keep scripts here only when they are called by active workflows or documented as copyable workflow helpers.

## dash-gen/

The registry generator — the only part of this directory called by live workflows (`build-dash.yml`, `refresh-dash.yml`, `fleet-pulse.yml`, `reconcile-registry.yml`, and the drift gate via `tools/`). Fronted by the [`tools/dash-gen`](../../tools/dash-gen) wrapper; subcommands: `health`, `readme`, `ai`, `ai-usage`, `actions`, `daily`, `triage`, `remediate`, `reconcile`, `estimate`, `ledger`, `all`. See [dash-gen/README.md](dash-gen/README.md).

## Copyable workflow helpers

Not referenced by any live workflow here; candidates to seed into submodules or delete.

| Script | Purpose |
| --- | --- |

## Rules

- Do not hardcode repository names, personal accounts, or secret values.
- Document required and optional environment variables at the top of each script.
- Prefer exiting successfully when optional provider secrets are not configured.
