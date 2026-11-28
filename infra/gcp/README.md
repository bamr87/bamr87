# infra/gcp — the platform on Google Cloud

> OpenTofu for where the platform runs in the cloud: a landing zone, and one machine that is a fleet node. Nothing here has been applied; every step that creates something is the maintainer's.

The decision is [ADR 0020](../../docs/adr/0020-platform-on-google-cloud.md) and the operator page is [docs/HOSTING.md](../../docs/HOSTING.md). What is hosted, on what machine and entered from where is one file, [`_data/hosting.yml`](../../_data/hosting.yml), which each module reads itself.

| Module | What it creates | Billed while idle? |
| --- | --- | --- |
| [`foundation/`](foundation/SCHEMA.md) | the APIs, a keyless sign-in for GitHub Actions, a pull-through of ghcr.io, an optional budget alert | No |
| [`node/`](node/SCHEMA.md) | the machine, its network and address, a data disk with daily snapshots, a backups bucket; as `dev`, a smaller machine with nothing durable | Yes, once its `enabled` is true: the machine, its disks and its address |
| [`dev/`](dev/SCHEMA.md) | nothing in the cloud: the scripts that start a service's development stack on the development instance | — |

## Run it

```bash
gcloud auth application-default login      # once, as yourself
export GCP_PROJECT_ID=<the project>        # never committed
infra/gcp/deploy.sh foundation             # the plan: what would change
infra/gcp/deploy.sh foundation --apply     # apply exactly that plan
infra/gcp/deploy.sh node                   # plans nothing while node.enabled is false
```

`deploy.sh` needs OpenTofu (`brew install opentofu`). It plans by default. `--apply` applies the plan the last run saved and refuses when the module or `_data/hosting.yml` changed after it. State lives outside every checkout, in `~/.local/state/bamr87-infra/`. Set `GCP_BILLING_ACCOUNT` (and `GCP_BUDGET_USD`, default 50) to have `foundation` create a budget alert; it warns and does not cap.

## A development instance

For review and validation, beside the platform's machine and before it: `_data/hosting.yml` `dev:` is the same machine module with its own state. It is never public, it has nothing durable, and one apply removes it.

```bash
infra/gcp/deploy.sh foundation && infra/gcp/deploy.sh foundation --apply   # once per project
infra/gcp/deploy.sh dev                  # the plan: one machine, its network and address
infra/gcp/deploy.sh dev --apply          # create it; it is billed from here
infra/gcp/dev/up.sh                      # zer0-CMS's development stack on it
infra/gcp/dev/up.sh --tunnel             # then open http://127.0.0.1:8000/studio/
infra/gcp/dev/up.sh --account            # make the first account
infra/gcp/dev/up.sh --codes              # the sign-in code the app logged
infra/gcp/deploy.sh dev --destroy && infra/gcp/deploy.sh dev --apply       # remove it
```

## The order, and what is yours

1. Choose the project, link billing, and apply `foundation`.
2. Set `node.enabled: true` in `_data/hosting.yml` in a pull request, then plan and apply `node`. The machine exists; nothing reaches it from the internet.
3. Reach it as yourself: `gcloud compute ssh <name> --tunnel-through-iap`. Install bashOS and enrol it as a node ([docs/PLATFORM.md](../../docs/PLATFORM.md)).
4. Bring up a service on it, add its DNS record, then set `node.public: true` and apply `node` again to open ports 80 and 443.
5. Set the service's `enabled: true` once it answers, and the main site offers it.

## Rules

- **CI validates, the maintainer applies.** `.github/workflows/infra.yml` runs `tofu fmt -check`, `init -backend=false` and `validate` on each module. It holds no cloud credential.
- **No identifier in the repo.** The project id, its number, the billing account and the machine's address never appear in a tracked file (`tools/test_hosting.py` holds this for the files it can read).
- **No stored credential.** A workflow signs in through Workload Identity Federation; a person signs in as themselves.
- **Floors, no ceilings, no lock file** (docs/DEPENDENCIES.md).
