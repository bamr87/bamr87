---
schema: '0.1'
coverage: listed
---

# SCHEMA — infra/node

> One fleet node's durable infrastructure, over its Docker endpoint (`ssh://<alias>`): the `fleet` network and the named volumes of the services placed on it.

## Conventions

- One resource per kind of thing compose takes as `external`; durable volumes and rebuildable volumes are separate resources because `prevent_destroy` must be a literal.
- Every resource carries the `com.bamr87.fleet.node` and `com.bamr87.fleet.managed-by=opentofu` labels.

## Structure

| entry | kind | purpose | rules |
| --- | --- | --- | --- |
| `versions.tf` | file | OpenTofu and provider floors, and the local backend whose path `dash infra` passes at init | required |
| `variables.tf` | file | The generated inputs: node, Docker endpoint (SSH or a local socket, never TCP), network, durable and rebuildable volume names | required |
| `main.tf` | file | The Docker provider over SSH, the network, and the two volume resources | required |
| `outputs.tf` | file | The network name and the volumes held, by kind | required |

## Placement

- A new piece of per-node infrastructure → a resource in `main.tf`, its input in `variables.tf`, its value from `tools/fleetcore/nodes.py` `tfvars()`.

## Forbidden

- No container resources — compose owns containers.
- No `prevent_destroy = false` override and no `-target` workarounds in docs or scripts.
