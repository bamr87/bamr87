---
schema: '0.1'
coverage: listed
---

# SCHEMA — infra/gcp/foundation

> The landing zone root module: what the platform's machine stands on, created once, with nothing that serves traffic and nothing billed while idle.

## Conventions

- Reads `_data/hosting.yml` for the region, the `project` label and each service's `deploy:` repository and environment.
- A deploy identity is created only for a service that names where it is deployed from, and it is given no role here.

## Structure

| entry | kind | purpose | rules |
| --- | --- | --- | --- |
| `versions.tf` | file | The OpenTofu and provider floors, the local backend and the provider | required |
| `variables.tf` | file | What comes from the environment: the project, the environment label, the billing account and the budget amount | required |
| `main.tf` | file | The APIs, the Workload Identity Federation pool and provider, a deploy identity per service that names one, the pull-through of ghcr.io and the optional budget alert | required |
| `outputs.tf` | file | The provider and identities a deploy workflow signs in with, the registry path and the region | required |

## Placement

- A new API the platform uses → the `apis` list in `main.tf`, in the change that first uses it.
- Anything unrouted → propose an entry in this table first, then create it.

## Forbidden

- No role granted to a deploy identity: the change that needs one grants it, scoped to one resource.
