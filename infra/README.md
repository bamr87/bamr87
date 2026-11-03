# infra — the fleet's infrastructure as code

> OpenTofu root modules for what outlives a container: each fleet node's network and data volumes today, clusters and other infrastructure later (ADR 0003).

Each kind of resource has one owner. **Ansible** bootstraps a node's operating system and runs every ordered deploy step on it, and **Salt** then keeps that configuration steady (ADR 0003 § 5); **bashOS** owns forge's interactive layer (the console mirror, never-sleep, the harness unit). **OpenTofu**, here, owns the infrastructure a node's services stand on: the `fleet` Docker network and the named volumes that hold their data. **Compose** owns the containers, which are disposable; the overlay `tools/dash node gen` writes takes this directory's network and volumes as `external`, so `docker compose down -v` can never delete them.

[OpenTofu](https://opentofu.org) is the MPL-2.0 fork of Terraform under the Linux Foundation. Terraform itself has been under the Business Source License since 1.6 (August 2023), which is not open source. The HCL is Terraform-compatible, and nothing here depends on an OpenTofu-only feature yet.

## Operate

```bash
tools/dash node plan --assume-enabled   # what would run where, and what OpenTofu would hold
tools/dash infra plan forge             # write .fleet/nodes/forge.tfvars.json, init, plan, save the plan
tools/dash infra apply forge --yes      # apply that saved plan, only if its inputs are still current
```

`plan` reads the node over SSH (`ssh://forge`) and changes nothing. `apply` changes the node, so it refuses without `--yes` and without a saved plan made from the current inputs (constitution § 10.5): a placement edit after the plan forces a new plan.

## Rules

- **Inputs are generated.** `.fleet/nodes/<node>.tfvars.json` comes from `_data/fleet.yml` `nodes:` resolved against `docker-compose.yml` by `tools/fleetcore/nodes.py`; never hand-write one.
- **State lives outside every checkout,** in `nodes.infra.state_dir` (`~/.local/state/bamr87-infra/<node>.tfstate`, provider cache under `<node>/.terraform`), so worktrees share one state and nothing lands in the tree.
- **Durable volumes carry `prevent_destroy`.** A plan that would delete one fails. Which volumes are durable is `nodes.durable_volumes`.
- **Floors, no ceilings, no lock file** (docs/DEPENDENCIES.md): `init -upgrade` takes the newest provider that satisfies `>=`, and `.terraform.lock.hcl` is gitignored.
- **CI validates and never plans.** `.github/workflows/infra.yml` runs `tofu fmt -check`, `init -backend=false` and `validate` on every root module. CI holds no SSH key to a fleet node.
- **SSH is the only API to a workload node.** The `docker_host` variable refuses a TCP socket.

## Adopting a node that already has the resources

If forge already holds a `fleet` network or volumes from the old `dash host rebuild`, the first plan wants to create them and `apply` would fail on "already exists". Import them instead, one per resource, then plan again:

```bash
export TF_DATA_DIR=~/.local/state/bamr87-infra/forge/.terraform
tofu -chdir=infra/node import -var-file="$PWD/.fleet/nodes/forge.tfvars.json" docker_network.fleet "$(ssh forge docker network inspect -f '{{.Id}}' fleet)"
tofu -chdir=infra/node import -var-file="$PWD/.fleet/nodes/forge.tfvars.json" 'docker_volume.rebuildable["fleet_es-data"]' fleet_es-data
```
