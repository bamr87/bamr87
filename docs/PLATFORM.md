# Platform — local first, placed across nodes, portable to any cluster

> How the fleet's development platform spreads its workloads across the Mac and forge, which layer owns what, and how the same definitions scale out to any cloud or on-premise cluster.

The decision record is [ADR 0003](adr/0003-fleet-platform-nodes-iac-and-scale-out.md). The work is epic #594 on the [Fleet project](https://github.com/users/bamr87/projects/14), and roadmap `FF-0035`.

## The model in one paragraph

The **Mac is the edge**: the editor, Claude Code, the browser, the working tree, and every service that bind-mounts it. **forge is a workload node**: an always-on box with 32 GB and about 464 GB of free disk, which carries the planes and the batch work the Mac's 7.7 GiB Docker VM cannot afford. Where each service runs is **data**, in `_data/fleet.yml` `nodes:`. One implementation, `tools/fleetcore/nodes.py`, resolves it against `docker-compose.yml` and refuses a placement that would break something. **The link** keeps every address the same, wherever the service runs: one SSH connection with a forward per port, so `127.0.0.1:9200` on the Mac and `elasticsearch:9200` on the `fleet` network still answer. **OpenTofu** owns what must outlive a container, a node's network and its data volumes. **Ansible** bootstraps a node and runs every ordered deploy step on it; **Salt** then holds its configuration steady and reports its events. **Compose** owns the containers. Nothing moves while a node is `enabled: false`, and flipping that flag is the deploy step.

```text
                         _data/fleet.yml  nodes:  (placement, nodes, link, infra)
                                       │
                     tools/fleetcore/nodes.py  ── resolve · validate · plan · gen
                    ┌──────────────────┴───────────────────┐
                    ▼                                      ▼
   ┌──────── Mac · EDGE (compose) ────────┐   ┌──────── forge · WORKLOAD (compose) ───────┐
   │ editor · Claude Code · browser        │   │ elasticsearch · logstash · kibana         │
   │ devenv · console · tui · mcp          │   │ grafana · prometheus · otel-collector     │
   │ db · redis · wiki (until phase 9)     │   │ phoenix · qdrant · mkdocs                 │
   │ filebeat (agent)                      │   │ filebeat (agent)                          │
   │ node-link ════ SSH, forwarding-only ══╪═══╪══▶ 127.0.0.1:<port> on forge              │
   │   127.0.0.1:9200 … · aliases on fleet │   │ network + volumes ◀── OpenTofu (infra/)   │
   └───────────────────────────────────────┘   │ host OS ◀── bashOS (os install)           │
                                               └───────────────────────────────────────────┘
          scale out (phase 10):  the same compose ──▶ generated manifests ──▶ k3s / any cluster
```

## Who owns what

| Layer | Owner | Where | Changes by |
| --- | --- | --- | --- |
| Host bootstrap and deploy steps | Ansible | phase 1 (playbooks); inventory from `tools/dash node gen` | `ansible-playbook --check --diff` (the plan), then the approved run |
| Host steady state and events | Salt | phase 5 (master on forge, a minion per workload node) | `state.apply test=True` (the preview), then highstate on a schedule behind a § 17 switch |
| forge's interactive layer | bashOS | `projects/bashos/os/` | `bashos os install`, run by an Ansible task |
| Infrastructure | OpenTofu | [`infra/`](../infra/README.md) | `tools/dash infra plan` → `apply --yes` |
| Placement | `nodes:` in `_data/fleet.yml` | [`tools/fleetcore/nodes.py`](../tools/fleetcore/nodes.py) | a reviewed PR; `enabled: true` is the deploy step |
| Containers | Compose | `docker-compose.yml` and the overlays in `.fleet/nodes/` | `dash up` on the edge; `docker compose` on the node, from its own checkout |
| Images | buildx and GHCR | phase 6 | — |
| Scale-out | Kubernetes, manifests generated from compose | phase 10 | — |

## Nodes and placement

Placement as committed. While forge is disabled every row runs on the Mac. `tools/dash node plan --assume-enabled` prints the move.

| Service | Placed on | Why |
| --- | --- | --- |
| `elasticsearch`, `logstash`, `kibana`, `grafana`, `prometheus`, `otel-collector`, `phoenix`, `qdrant` | forge | the planes: about 3.2 GiB and about 4 cores on the Mac at the 2026-11-02 measurement, and they call only each other |
| `mkdocs` | forge | reads `projects/README` from forge's own checkout |
| `filebeat` | `every` | a node agent: it reads the Docker socket of the host it runs on, so each node ships its own containers |
| `devenv`, `console`, `tui`, `mcp`, `mcp-tunnel` | Mac | edge-bound: they bind-mount the working tree or `~/.claude` and `~/.ssh` |
| `db`, `redis`, `wiki`, `pgadmin` | Mac | durable data: they move in phase 9, once forge has an off-box backup and a restore drill |

The resolver refuses four things, so they fail in review rather than at runtime:

1. **An edge-bound service off the edge.** A bind of `.` or of a host path outside the repo pins a service to the Mac. A bind of the Docker socket makes it a node agent instead.
2. **A call back to the edge.** A workload service may only depend on services on its own node. Dependencies are read from `depends_on`, from `name:port` in the environment and command, and from the repo config files the service mounts. The Mac sleeps and travels; forge must not need it.
3. **Durable data without a backup.** A service that mounts a volume in `nodes.durable_volumes` may only be placed on a node whose `backup:` names an off-box target.
4. **A link port collision.** A forwarded port must not be one the edge already publishes.

## Operate — the short card

```bash
tools/dash node status                    # reachability, capacity, and drift between placement and what runs
tools/dash node plan [--assume-enabled]   # what runs where, what would move, the link's ports, what OpenTofu holds
tools/dash node gen [--assume-enabled]    # write .fleet/nodes/: <node>.yml, <node>.tfvars.json, inventory.yml (gitignored)
tools/dash node key                       # the forwarding-only authorized_keys line for the link key
tools/dash infra plan forge               # OpenTofu: the network and volumes forge needs, saved as a plan
tools/dash infra apply forge --yes        # apply that plan (deploy step, § 10.5)
```

`status`, `plan` and `key` only read. `gen` writes only `.fleet/nodes/`. Nothing in `dash node` starts, stops or deletes a container. Those verbs arrive with the phases that need them, each an approved deploy.

## The link

The edge reaches every service placed elsewhere through **one SSH connection** that carries a local forward per published port. In phase 2 it becomes the `node-link` service on the `fleet` network, holding the moved services' names as network aliases and publishing their ports on the Mac's loopback. Consumers keep their addresses: the console's `ES_URL=http://elasticsearch:9200`, Claude Code's OTel export to `127.0.0.1:4318`, Kibana and Grafana in the browser. On forge the placed services bind **loopback only**, so the link is the only way in, and nothing new appears on the LAN. That is what keeps Elasticsearch's `xpack.security.enabled: false` defensible, exactly as on the Mac today.

The key can do nothing but forward. `tools/dash node key` prints its line for forge's `~/.ssh/authorized_keys`: `restrict` (no shell, pty, agent or X11), `port-forwarding` back on, `command="/bin/false"`, and one `permitopen="127.0.0.1:<port>"` per forwarded port. It refuses to print a line with no ports, because `port-forwarding` without `permitopen` would forward anywhere. Reinstall the line whenever placement changes the ports.

## Infrastructure as code (OpenTofu)

`infra/node` creates, on the node's Docker engine over `ssh://forge`, the `fleet` network and one named volume per volume its placed services mount. Durable volumes carry `prevent_destroy`, so a plan that would delete one fails. The forge overlay takes all of them as `external`, so compose can never delete them. Inputs are generated, state lives in `~/.local/state/bamr87-infra`, and CI (`infra.yml`) validates without ever reaching a node. Details, and how to adopt resources a legacy rebuild left behind: [infra/README.md](../infra/README.md).

[OpenTofu](https://opentofu.org) was chosen over Terraform because Terraform has been BUSL since 1.6 (August 2023) and is no longer open source. OpenTofu is the MPL-2.0 fork, runs the same HCL and providers, and adds client-side state encryption for when state ever holds a secret. The same tool provisions clusters in phase 10: k3s on-premise, a managed service in any cloud.

## Configuration management — Ansible and Salt

Ansible and Salt have different jobs, and **every managed resource has exactly one owner**, so they never take turns rewriting the same file.

**Ansible, day 0 and day 1.** It is agentless and pushes over SSH through the same `forge` alias, so SSH stays the only API. A playbook bootstraps a node:

- packages, the Docker engine, users and SSH hardening;
- `vm.max_map_count=262144` for Elasticsearch, and the firewall;
- the forwarding-only link key line from `tools/dash node key`;
- the hub's git checkout (replacing today's rsync copy, which has no `.git`);
- the off-box backup;
- bashOS's installer, as one task;
- the Salt minion, installed and enrolled.

Ansible also runs every ordered deploy step. `--check --diff` is the plan; the run without `--check` is the approved apply. Its inventory is `.fleet/nodes/inventory.yml`, generated from `nodes:` by `tools/dash node gen`. It lists the workload nodes only, never the Mac.

**Salt, day 2.** A master on forge and a minion on each workload node. Highstate holds the baseline, with `state.apply test=True` as the preview:

- sysctl, the firewall rules and the Docker daemon's log rotation;
- the node agents.

Beacons watch disk use, services and OOM kills. The reactor answers them, and the event bus ships into ELK next to the container logs, so the console sees a node's configuration events and its containers' output in one place. The scheduled highstate is a loop, so it has a central kill switch (§ 17).

**Where the line falls.** Ansible never re-manages a path a Salt state declares; the Salt phase adds a check for overlap. Neither creates the Docker networks or volumes that OpenTofu owns. Nothing manages the Mac until the maintainer opts it in (§ 10.5).

## Logs — capture, stream, analyse

**Today**, Filebeat autodiscovers the containers labelled `com.bamr87.fleet.*`. Logstash drops verbatim copies, maps to ECS and redacts. Elasticsearch keeps three datasets with retention managed by ILM. Kibana searches them, Grafana trends them, and the console embeds both ([OBSERVABILITY.md](OBSERVABILITY.md)).

**Phase 3** moves the planes to forge. Filebeat runs as a node agent on each node and ships to the one Logstash, so logs from both machines land in one place, and Elasticsearch can take a larger heap and longer retention than the Mac allowed.

**Phase 4** builds the analysis on top:

- **A live tail in the console.** An SSE stream like `/api/live/stream` follows Elasticsearch: central across nodes, already redacted, filterable by `fleet.repo`, `service.name` and `log.level`. The fallback, for a container that is not shipped, is a raw `docker logs -f` through `fleetcore.host` on the container's own node, redacted with the same `observability.logs.redact` list, capped in lines per second and closed after a time limit.
- **Error signatures.** A fingerprint of the normalised message, so "new since yesterday" and "top five errors per repo" are aggregations rather than reading.
- **Docker events.** A dataset of die, OOM and restart events with exit codes, so an exit 137 is recorded rather than inferred.
- **Per-container CPU and memory.** The OTel collector's `docker_stats` receiver, run as an agent per node, feeds Prometheus and Grafana. It is also how the offload is measured.
- **Deep links and an agent tool.** Kibana Discover links pre-filtered on `trace.id`, `fleet.repo` and `service.name`. A read-only `logs_query` MCP tool, capped and redacted, never sends anything outward (§ 13.8).

## Images, MCP and Kubernetes — the direction

- **Images (phase 6).**
  - One buildx builder with a native node per platform, the Mac for arm64 and forge for amd64, so no QEMU emulation.
  - A `docker-bake.hcl` build graph.
  - GHCR as the registry of record, deployed by digest, with a pull-through cache on forge.
  - SBOM and provenance on every build, Trivy and Docker Scout scans, and cosign signatures. These are the mechanics behind #590 and #591.
- **MCP (phase 7).**
  - The Docker MCP Gateway runs as a container on each node, isolating every server in its own container, with tool allowlists and secrets read from a file.
  - Playwright's Chromium and other heavy servers run on forge.
  - The fleet MCP server ships as an image, and `.mcp.json` reaches the gateway through the link.
- **Kubernetes (phase 10).**
  - Compose stays the one definition; manifests are generated from it (Compose Bridge or Kompose, settled by a spike).
  - They are validated with kubeconform, smoke-deployed to kind or k3d in CI, and piloted on k3s on forge.
  - OpenTofu provisions clusters, and GitOps (Flux or Argo CD) delivers images by digest.
  - A node gains `runtime: kubernetes`, the same placement map targets it, and `every` becomes a DaemonSet.

## When something is down

| Situation | What happens | What to do |
| --- | --- | --- |
| forge off, asleep, or booted from the bashOS USB image | The link is down, the planes do not answer, and the console shows them as not running. Agents buffer (phase 4). | `tools/dash node status`; wake it with Wake-on-LAN on `192.168.7.255`; editing is unaffected |
| The Mac is off the LAN | The SSH link cannot connect until the overlay-network decision (phase 2) | Work without the planes, or start a local copy by hand. Its data is separate |
| A placement edit changes the forwarded ports | The link key no longer permits the new port | Reinstall the line from `tools/dash node key` |
| `dash infra apply` refuses | No saved plan, or the inputs changed since it was made | `tools/dash infra plan forge`, read it, apply again |
| `dash host rebuild` refuses | It would delete every container and volume on forge | Use `dash node` / `dash infra`; `--wipe-all` only on purpose |

## Security

- **SSH is the only API to a workload node.** The OpenTofu provider refuses a TCP Docker socket.
- **Placed services bind forge's loopback.** The link key is limited to forwarding the placed ports.
- **CI holds no key to any node.** It validates the HCL and never plans or applies.
- **Secrets stay where they are.** Their values live in `.env` on each node (mode 0600) and in GitHub secrets, never in `_data/` or in OpenTofu state. State encryption is available if that ever changes.
- **The Salt master listens on forge's loopback or the overlay network, never the internet.** Exposed masters were exploited at scale in 2020 (CVE-2020-11651/11652). Minion keys are accepted by hand, never automatically, and Salt is patched promptly. Configuration secrets go in Salt pillar or Ansible Vault, never in `_data/`.
- **Every step that changes a machine is a deploy** (§ 10.5, § 13.6): `enabled: true`, `infra apply --yes`, a playbook run without `--check`, a highstate outside `test=True`, and installing the link key. None runs unattended until its phase adds a kill switch.

## Files

| File | Role |
| --- | --- |
| `_data/fleet.yml` `nodes:` | The model: nodes, placement, durable volumes, the link and infrastructure settings |
| `tools/fleetcore/nodes.py` | Resolve, validate, plan, generate; `dash node` and `dash infra` |
| `tools/test_fleetcore_nodes.py` | Fixture tests, the committed model included |
| `infra/node/*.tf` | OpenTofu: a node's network and volumes |
| `.github/workflows/infra.yml` | `fmt` and `validate` for every root module |
| `.fleet/nodes/` | Generated overlays, OpenTofu inputs and the Ansible inventory (gitignored) |
| [ADR 0003](adr/0003-fleet-platform-nodes-iac-and-scale-out.md) | The decision, the prior art and the phases |
