---
schema: '0.1'
coverage: listed
---

# SCHEMA — infra/gcp/dev

> The scripts that bring a service's development stack up on the development instance, for review and validation, reached only through the identity-aware tunnel.

## Conventions

- The machine is created by `../deploy.sh dev`, from `_data/hosting.yml` `dev:`. Nothing here creates a cloud resource.
- `up.sh` runs on the operator's machine and reaches the instance only with `gcloud compute ssh --tunnel-through-iap`. One script per service runs on the instance itself.
- A stack is the service's own development compose, unchanged, bound to the instance's loopback. What is generated on the instance (a secret key, a database password) stays there.
- Development only: made-up content, no backup, sign-in codes printed to the app's log. Never client data.

## Structure

| entry | kind | purpose | rules |
| --- | --- | --- | --- |
| `up.sh` | file | From the operator's machine: send a service's script to the instance, forward the app to the operator's loopback (`--tunnel`), make the first account (`--account`), show logged sign-in codes (`--codes`) | required |
| `zer0-cms.sh` | file | On the instance: install Docker from the distribution's packages, clone zer0-CMS, generate its secrets once, start `docker compose --profile content`, wait for `/readyz` | required |

## Placement

- Another service's development stack → `<service>.sh` here, sent by `up.sh`, and a row in this table.
- Anything unrouted → propose an entry in this table first, then create it.

## Forbidden

- No port published to anything but the instance's loopback, and no rule or flag that opens the instance to the internet.
- No secret written in a script: what a stack needs is generated on the instance.
