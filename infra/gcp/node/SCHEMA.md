---
schema: '0.1'
coverage: listed
---

# SCHEMA — infra/gcp/node

> The platform's machine as a root module: one virtual machine that is a fleet node, with what outlives a container on it.

## Conventions

- Reads `_data/hosting.yml` for the machine's shape and its switches: `node:` by default, `dev:` when `instance` is `dev`. With the machine's `enabled: false` every resource has a count of zero.
- A machine that is not `durable` (the development instance) gets no data disk, no snapshots, no backups bucket and no deletion protection, so it can be removed by a plan.
- The data disk and the backups bucket carry `prevent_destroy`: a plan that would delete either fails.
- SSH comes in only from the provider's identity-aware tunnel, and the operator signs in as themselves. No SSH key is created.

## Structure

| entry | kind | purpose | rules |
| --- | --- | --- | --- |
| `versions.tf` | file | The OpenTofu and provider floors, the local backend and the provider | required |
| `variables.tf` | file | What comes from the environment: the project, and which machine of `_data/hosting.yml` this state describes (`node` or `dev`) | required |
| `main.tf` | file | The network and its two firewall rules, the address, the machine's identity and its three roles, the data disk and its snapshot schedule, the backups bucket, and the machine | required |
| `outputs.tf` | file | The machine's name and address, the backups bucket, and whether the front door is open | required |

## Placement

- A new way into the machine → a firewall rule in `main.tf` behind a switch in `_data/hosting.yml`, never an always-on rule.
- Anything unrouted → propose an entry in this table first, then create it.

## Forbidden

- No rule that lets the internet reach port 22.
- No startup script that installs software: bashOS and Ansible configure the machine (ADR 0003), this module only creates it.
