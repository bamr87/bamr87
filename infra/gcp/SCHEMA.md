---
schema: '0.1'
coverage: listed
---

# SCHEMA — infra/gcp

> OpenTofu root modules for the platform on Google Cloud: the landing zone and the machine the platform runs on, each planned and applied by the maintainer and only validated in CI (ADR 0020).

## Conventions

- OpenTofu, as for the fleet's nodes (ADR 0018: Google Cloud and AWS use OpenTofu; Azure stays on Bicep).
- One directory per root module, one level below this one. `.github/workflows/infra.yml` formats, initialises and validates each.
- A module reads what to create from `_data/hosting.yml` itself. Nothing is passed in a hand-written variables file.
- The project id, the billing account and every credential come from the environment at apply time. None is written in the repo.
- `deploy.sh` plans by default and applies only with `--apply`, from the plan the last run saved.
- Every resource that takes labels carries `project`, `env`, `managed-by` and `source` (ADR 0018, decision 6). Google Cloud labels cannot hold a slash or a space, so `source` is written `<owner>_<repo>--<path with underscores>`.

## Structure

| entry | kind | purpose | rules |
| --- | --- | --- | --- |
| `README.md` | file | What this layer is, the order to apply it in, and what is yours to do | required |
| `deploy.sh` | file | Plan one target (`foundation`, `node` or `dev`), and with `--apply` apply the saved plan; `dev --destroy` plans the development instance's removal; state lives outside every checkout | required |
| `foundation/` | dir | The landing zone: the APIs the platform uses, the keyless sign-in for GitHub Actions, the pull-through of ghcr.io and an optional budget alert | required |
| `node/` | dir | The platform's machine: its network and the two ways into it, the machine and its address, a data disk with daily snapshots and a backups bucket; plans nothing while `_data/hosting.yml` `node.enabled` is false. The same module is the development instance (`dev:`), with its own state and nothing durable | required |
| `dev/` | dir | The scripts that bring a service's development stack up on the development instance and forward it to the operator's loopback; they create no cloud resource | required |

## Placement

- A resource every hosted service shares → `foundation/`.
- A resource of the machine the platform runs on → `node/`.
- A managed service that replaces something the machine runs (a database, a bucket for media, a cluster) → a new root module directory here with its `SCHEMA.md` and a row in this table, in the change that adopts it (ADR 0020, G7).
- Anything unrouted → propose an entry in this table first, then create it.

## Forbidden

- No state, plan or lock file, and no hand-written `*.tfvars`.
- No project id, project number, billing account, address or credential in any file.
- No service account key: a job signs in through Workload Identity Federation, and a person as themselves.
- No rule that opens a port to the internet other than the one `node.public` controls.
