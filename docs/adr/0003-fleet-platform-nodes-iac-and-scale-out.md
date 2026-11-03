# ADR 0003 — The fleet platform: workloads placed across nodes, OpenTofu for infrastructure, Ansible and Salt for configuration, a path to any cluster

- **Status**: accepted
- **Accepted in**: https://github.com/bamr87/bamr87/pull/606 (merged 2026-11-03 by @bamr87)
- **Date**: 2026-11-02
- **Deciders**: proposed by an agent at the maintainer's request (2026-11-02); the maintainer accepts or rejects it by merging the PR that adds it
- **Related**: [docs/PLATFORM.md](../PLATFORM.md), [docs/FORGE-HOST.md](../FORGE-HOST.md), [docs/CONTAINERS.md](../CONTAINERS.md), [docs/OBSERVABILITY.md](../OBSERVABILITY.md), roadmap `FF-0035`, the proposed amendment `container-management` (#591, backlog #590), #512 (declarative repo settings), [ADR 0002](0002-agent-step-specs-and-local-runner.md) (the local loop runner), #593 (the console's git-status saturation)
- **Tracking**: #594

<!-- Accepted in and Completed are added by the post-merge ratify job when the maintainer merges this ADR's PR and when the maintainer closes the Tracking issue as completed (docs/adr/README.md#lifecycle). Never write them by hand. A PR that adds or changes an ADR is gated (constitution § 12.3). -->

## Context

### Needs assessment

**Who needs what.** The maintainer asked for six things in one session. First, offload processing, capacity and workload from the Mac onto `forge`, the always-on LAN server. Second, infrastructure as code built into the stack, Terraform or a better open-source equivalent. Third, use Docker's own features for MCP servers, images and Kubernetes, so that an efficient local development platform can scale into any cloud or on-premise environment. Fourth, capture and stream Docker logs into the Harness Console and the ELK stack for deeper analysis. Fifth, use Ansible and Salt for configuration management. Sixth, put the plan on the roadmap and build the architecture.

**Evidence: the Mac is the bottleneck.** Measured on 2026-11-02:

- The Mac (Apple M3 Pro, 18 GiB, 11 CPUs) gives Docker Desktop a 7.75 GiB VM. 25 containers used 6.53 GiB of it (84%).
- `docker stats --no-stream` took longer than 60 seconds, both buildx builders reported `error`, and `docker model status` hung for over two minutes.
- The console sat at 100% CPU, fixed separately in #593.
- At sample time the observability planes alone held about 3.2 GiB and about 4.3 cores: Elasticsearch 924 MiB, Kibana 874, Logstash 600, Phoenix 448, Grafana 140 (98% CPU), Qdrant 132, the OTel collector 129, Prometheus 42 and Filebeat 30.
- The zer0-cms background workers held about 2.2 GiB, the four Jekyll previews about 0.95 GiB, and the console and MCP server about 0.15 GiB.
- The constraint is old. Elasticsearch was OOM-killed at a 1 GB heap and now runs at 512 MB, and Kibana is "the one to stop first" ([OBSERVABILITY.md](../OBSERVABILITY.md)). `containers.max_projects: 8` exists for the same reason.

**Evidence: forge has room, but nothing places work on it.**

- forge is an i7-3820 (4 cores, 8 threads) with 32 GB, a 1 TB SSD (about 464 GB of it unallocated), Debian 13 with the bashOS layer, and a GTX 660 on nouveau (no CUDA). It is configured never to sleep and answers Wake-on-LAN on the /22's broadcast.
- What exists today is `dash host` (setup, ps, up, rebuild), the `compose/forge.yml` overlay (LAN binds), read-only Docker inventory over `DASH_DOCKER_HOST=local,ssh://forge`, and `bashos-harness`, the console as a systemd unit on forge's loopback.
- There is no placement model: nothing says which service belongs where.
- There is no transparent way for the Mac's consumers to reach a service that moved.
- `dash host rebuild` rsyncs the Mac's working tree, uncommitted edits included, then deletes every container **and every volume** on forge. That is harmless on an empty box and a data-loss button once forge holds data.
- forge's `~/dev/bamr87` is an rsync copy with no `.git`.
- There is no infrastructure as code.
- Reachability is LAN-only, by mDNS. forge did not answer during this session (`forge.local` did not resolve), so a workload node must be treated as intermittently available.

**Evidence: the Docker features are already installed.** Docker Desktop on the Mac (engine 29.8, compose v5.5, buildx 0.37) ships:

- `docker mcp`: the MCP Toolkit and Gateway, with stdio, SSE and streaming transports, profiles, tool allowlists, and secrets from the keychain or a `.env` file.
- `docker model` (Model Runner).
- `docker compose bridge`: converts compose to Kubernetes manifests or Helm charts through transformation images.
- `docker scout`, `docker dhi` (Hardened Images) and `docker offload`.

`kubectl` is installed with no cluster configured.

**Constraints.**

- § 10.5: nothing running on the Mac changes before an approved deploy step. The bashOS docs apply the same rule to forge.
- § 10.6: new tools are read-only by default, with allowlists, caps, time limits and redaction.
- § 13.6: a deploy is an external, high-risk action.
- § 17: a scheduled loop gets a central kill switch.
- Dependencies float on floors and lockfiles are never committed.
- SSH is the only API to forge.
- Compose evaluates bind mounts on the daemon, so compose runs on the node from the node's own checkout.

## Decision

### 1. Placement is data, resolved by one implementation

`_data/fleet.yml` `nodes:` declares:

- the **edge** node (`mac`): the working tree and everything that bind-mounts it;
- the **workload** nodes (`forge`), each with `runtime`, `docker`, `ssh`, `checkout`, `capacity` and `backup`;
- the map from hub compose services to nodes, where `every` means a node agent, one copy per active node;
- the durable volumes;
- the link;
- the infrastructure settings.

`tools/fleetcore/nodes.py` resolves that map against `docker-compose.yml`. It is the one implementation the CLI (`tools/dash node`, `tools/dash infra`) uses now and the console, TUI and MCP server will share. A workload node ships `enabled: false`. Until it is flipped, every service placed on it resolves to the edge and nothing moves, so flipping the flag is the deploy step.

### 2. Four placement rules, enforced in code

1. **Edge-bound services never leave the edge.** A service that bind-mounts the working tree or the user's own state (`devenv`, `console`, `tui`, `mcp`) stays on the Mac. A Docker-socket mount marks a node agent instead.
2. **Dependencies flow from the edge to workload nodes only.** A workload service never calls back to the edge, because the Mac sleeps and travels. Calls are read from `depends_on`, from `name:port` in a service's environment and command, and from the repo config files it mounts.
3. **Durable data moves only where it is backed up.** A service that mounts a durable volume (`db-data`, `redis-data`, `wiki-data`, `wiki-repo`, `pgadmin-data`) may only be placed on a node that has an off-box `backup:` target.
4. **The link's ports never collide.** A forwarded port must not already be published on the edge.

### 3. The link: an SSH ambassador

The edge reaches placed services through one SSH connection that holds a local forward per published port. The key can only forward: `restrict,port-forwarding,command="/bin/false",permitopen="127.0.0.1:<port>"…`, printed by `dash node key`, which refuses to render a key with no ports because that would forward anywhere.

`127.0.0.1:<port>` on the Mac and the service's name on the `fleet` network keep working wherever the service runs, so no consumer is reconfigured: not the console's `ES_URL`, not Claude Code's OTel endpoint, not Kibana in the browser. Placed services bind forge's loopback, so nothing new is exposed on the LAN, and Elasticsearch's `xpack.security.enabled: false` stays defensible.

An overlay network for use off the LAN (Tailscale, Headscale or plain WireGuard) is an open decision for phase 2.

### 4. Infrastructure as code: OpenTofu

[`infra/node`](../../infra/node) is an OpenTofu root module. It owns a workload node's `fleet` network and the named volumes of its placed services, and the durable ones carry `prevent_destroy`. The overlay `dash node gen` writes takes both as `external`, so `docker compose down -v` cannot delete them.

The stack has four owners, one per kind of resource:

- **Ansible and Salt** own the host's configuration (section 5).
- **bashOS** owns forge's interactive layer.
- **OpenTofu** owns what outlives a container.
- **Compose** owns the containers.

`dash infra plan` reads the node over SSH and saves a plan. `dash infra apply` refuses without `--yes` and without a saved plan of the current inputs. State lives outside every checkout (`~/.local/state/bamr87-infra`).

`.github/workflows/infra.yml` checks `fmt` and runs `validate` on every root module. CI never plans, because it holds no SSH key to a node.

### 5. Configuration management: Ansible bootstraps, Salt holds the steady state

The two tools have different jobs, and every managed resource has exactly one owner, so they never fight over the same file.

**Ansible: day 0 and day 1, push over SSH.** It is agentless and uses the SSH alias `forge` like everything else, so SSH stays the only API.

- It bootstraps a node: packages, the Docker engine, users, SSH hardening, `vm.max_map_count` for Elasticsearch, the firewall, the forwarding-only link key, the hub's git checkout, and the off-box backup.
- It runs bashOS's installer as one task.
- It installs and enrols the Salt minion.
- It runs every ordered deploy step (phases 1, 2 and 9). `ansible-playbook --check --diff` is the plan; the run without `--check` is the approved apply.
- Its inventory is generated: `tools/dash node gen` writes `.fleet/nodes/inventory.yml` from `nodes:`. It lists the workload nodes only, never the Mac (§ 10.5).

**Salt: day 2, continuous enforcement and events.** A Salt master on forge and a minion on each workload node.

- Highstate holds each node's baseline (sysctl, firewall, the Docker daemon's log rotation, the node agents), with `test=True` as its preview.
- Beacons watch disk, services and OOM kills; the reactor responds; and the event bus is shipped into ELK beside the container logs.
- The scheduled highstate is a loop, so it gets a § 17 kill switch.
- The master listens on loopback or the overlay network only, never the internet (exposed masters were exploited at scale in 2020, CVE-2020-11651/11652). Minion keys are accepted by hand, never auto-accepted. Salt is patched promptly.

**Ownership.** Ansible never re-manages a path a Salt state declares, and an overlap check arrives with the Salt phase. Neither tool creates the Docker networks or volumes OpenTofu owns. The Mac is managed by neither until the maintainer opts it in.

### 6. The legacy rebuild is fenced

`dash host rebuild` now refuses without `--wipe-all`.

### 7. The platform direction, one phase each

Each item below is a phase of the epic and decides its details in its own PR, with its own prior-art step where § 10.8 applies.

- **Logs: capture, stream, analyse.**
  - Node agents feed the central planes on forge: Filebeat runs as `every`, and an OTel collector per node runs the `docker_stats` receiver for per-container CPU and memory.
  - The console gains a live tail. By default it follows Elasticsearch, which is central across nodes and already redacted by the Logstash pipeline. A raw `docker logs -f` tail through `fleetcore.host` is the fallback for an unshipped container, filtered through the same `observability.logs.redact` list.
  - Error signatures come from a fingerprint of the normalised message.
  - A Docker events dataset records die, OOM and restart, so an exit 137 becomes a fact rather than a guess.
  - Kibana deep links carry `fleet.repo`, `service.name` and `trace.id`.
  - A read-only, capped and redacted `logs_query` MCP tool serves agents (§ 13.8: private data plus untrusted content, never an external send).
- **Images.**
  - One buildx builder with a native node per platform: the Mac for arm64 and forge for amd64, so there is no QEMU.
  - A `docker-bake.hcl` build graph.
  - GHCR as the registry of record, addressed by digest, with a pull-through cache on forge (CNCF Distribution).
  - SBOM and provenance attestations, scanning with Trivy and Docker Scout, and signing with cosign. These are the mechanics under #590 and #591.
- **MCP.**
  - The Docker MCP Gateway runs as a container on each node. Heavy servers (Playwright's Chromium) run on forge's gateway.
  - The fleet MCP server is built as an image.
  - Profiles and tool allowlists are code, servers that need no network are network-blocked, and secrets come from a file.
  - `.mcp.json` points at the gateway through the link.
- **Delegated work.**
  - A forge worker console takes the operations whose outputs are stores (the lake, Elasticsearch, Qdrant) or pull requests, never working-tree writes.
  - The lake sits beside it.
  - JEV loop runs execute in container sandboxes (ADR 0002, § 13.8).
- **Stateful services and app stacks.**
  - Postgres, Redis, the wiki and pgAdmin move with a migration and a backup drill.
  - `dash up <project> --node forge` runs an app stack from forge's own checkout, starting with zer0-cms's background workers.
- **Kubernetes is the scale-out target, not the development runtime.**
  - Compose stays the contract, and manifests are generated from it: Compose Bridge or Kompose, chosen by a spike.
  - The manifests are validated with kubeconform, smoke-deployed to kind or k3d in CI, and piloted on k3s on forge.
  - OpenTofu modules provision clusters: k3s on-premise, a managed service in a cloud.
  - GitOps delivers by digest: Flux or Argo CD, decided in that phase.
  - A node gains `runtime: kubernetes`, and the same placement map targets it, with `every` mapping to a DaemonSet.

### Phases

The epic's sub-issues, in order:

| Phase | Scope | Changes a machine? |
| --- | --- | --- |
| P0 | This record, `nodes:` (forge disabled), `fleetcore/nodes.py`, `dash node` / `dash infra`, the generated Ansible inventory, `infra/node`, `infra.yml`, the rebuild fence | No |
| P1 | forge readiness by an Ansible playbook (`--check --diff` first): a git checkout, an off-box backup and a restore drill, `vm.max_map_count`, the link key; then `dash infra apply forge` | forge |
| P2 | The link on the Mac, `dash up` integration, the overlay-network decision | Mac |
| P3 | The observability planes to forge, a node agent per node, a measured saving on the Mac | both |
| P4 | Logs into the console and ELK: live tail, signatures, Docker events, per-container metrics, `logs_query` | both |
| P5 | Steady state with Salt: master on forge, minions enrolled by Ansible, baseline highstate, beacons and reactor events into ELK, a § 17 kill switch, the ownership-overlap check | forge |
| P6 | Images: multi-node buildx, bake, GHCR by digest, pull-through cache, SBOM, provenance, scan, sign | both |
| P7 | MCP: the gateway per node, the fleet server as an image, allowlists | both |
| P8 | Delegated work: a forge worker console, the lake, JEV runs in sandboxes | both |
| P9 | Stateful services and app stacks on forge | both |
| P10 | Kubernetes portability: generated manifests, CI smoke, a k3s pilot installed by Ansible, cluster modules, GitOps | forge, clouds |
| P11 | Surfaces: the console Nodes page, `/api/nodes`, MCP `fleet_nodes`, the TUI | No |

## Consequences

**Positive**

- The Mac sheds about 3.2 GiB and about 4 cores in P3, and about 5.5 GiB of 6.5 GiB by P9. The planes can grow on forge: a bigger Elasticsearch heap and longer retention.
- No consumer changes address. The link keeps loopback ports and service names.
- Placement has one declarative source, every change is planned before it is applied, and durable data is protected by infrastructure as code rather than by care.
- There is a path to any Kubernetes cluster without hand-written manifests, and to any cloud through OpenTofu providers.
- Nodes are configured by playbooks and states rather than by hand. One generated inventory serves every node, and a new on-premise or cloud node is enrolled with the same steps as forge.

**Negative**

- The planes depend on forge. While it is off, logs, metrics, traces and the code index are unavailable. Agents buffer (Filebeat's disk queue and the OTel sending queue are configured in P4). None of these is on the critical path of editing code.
- The stack gains OpenTofu, Ansible and Salt now, and a Kubernetes distribution later. Each needs its own upgrades and its own expertise.
- A Salt master is a high-value target. Its exposure, key policy and patch cadence are standing obligations.
- The SSH link is LAN-only until the overlay decision.
- The link key must be reinstalled whenever placement changes the forwarded ports.
- OpenTofu's state for forge lives on the Mac. P1 backs it up.

## Alternatives considered

**Do nothing.** The Mac stays at 84%, the planes stay throttled (a 512 MB heap, Kibana stopped first), and every new plane competes with the code being edited.

**Move everything, the edge included.** Running devenv and the console on forge would mean editing over the network, or syncing a tree of 40 submodules with their `.git` directories. Editing stays local.

**`dash host rebuild` as the deploy.** It is destructive, it ships the dirty tree, it has no plan step, and it moves the whole hub rather than chosen services.

### Prior art and the build-vs-adopt decision (§ 10.8)

| Candidate | Fit | Decision |
| --- | --- | --- |
| Docker Swarm | Multi-host services from compose | Rejected: Docker Desktop's VM behind NAT makes overlay networking fragile, swarm mode is in maintenance, and dev ergonomics (`build:`, bind mounts) are lost |
| Kubernetes (k3s, kind) as the dev runtime | Industry standard | Rejected for daily development (a second runtime and manifests for about 40 projects); **adopted as the scale-out target** (P10) |
| HashiCorp Nomad | Capable scheduler | Rejected: BUSL since August 2023, and one more control plane |
| Kamal | Deploys containers to servers over SSH | Rejected for now: an app-deploy tool with its own proxy, not a dev-plane placer. Revisit for public deploys |
| Docker contexts, `docker -H ssh://` | Remote engine over SSH | Adopted for inventory (already) and for the OpenTofu provider; not for compose with bind mounts, which evaluate on the daemon |
| Docker Offload | A remote engine in Docker's cloud | Rejected as the default (cost, and data leaves the house); forge is the same idea on-premise |
| Portainer | Management UI | Optional on forge, never the source of truth |
| OpenSSH local forwards | Already the API; keys exist; no new dependency | **Adopted** (P2), with a forwarding-only key |
| Tailscale, Headscale, WireGuard | Reachability off the LAN | Open decision (P2). Headscale is the open-source control server |
| Mutagen, Syncthing | Two-way file sync | Rejected for the hub tree (40 submodules with `.git` directories) |
| Terraform | The reference IaC tool | Rejected: BUSL-1.1 since 1.6 (August 2023), not open source |
| **OpenTofu** | MPL-2.0 fork under the Linux Foundation; Terraform-compatible HCL and providers; state encryption available | **Adopted** |
| Pulumi | IaC in general-purpose languages | Rejected: a language runtime and a hosted state service by default; HCL keeps parity with provider documentation |
| **Ansible** (GPL-3.0) | Agentless configuration over SSH; check mode with a diff | **Adopted** for bootstrap and ordered deploy steps, from the generated inventory |
| **Salt** (Apache-2.0) | An agent with an event bus, beacons and a reactor; highstate enforcement at scale | **Adopted** for day-2 steady state on workload nodes. Master on loopback or the overlay network only |
| Puppet, OpenVox | An agent with a declarative DSL | Rejected: a third configuration language beside Ansible and Salt |
| Chef, Cinc | An agent with a Ruby DSL | Rejected for the same reason, and for Chef's licensing |
| Crossplane | IaC from inside Kubernetes | Rejected: needs a cluster first |
| NixOS | Declarative OS | Rejected: forge runs Debian with bashOS |
| ELK (in place) | Full-text search, the field contract, redaction, the `trace.id` join | **Kept**, moved to forge |
| Grafana Loki with Alloy | Lighter, indexed by label | Rejected now. Revisit if Elasticsearch's memory still binds on forge |
| Vector | One binary for Filebeat plus Logstash | Candidate if Logstash's JVM stays costly (P4) |
| OTel collector `docker_stats` | Per-container metrics from the collector already in use | **Adopted** (P4) |
| Docker logging drivers (gelf, fluentd, syslog) | Push logs from the engine | Rejected: `json-file` plus autodiscover keeps `docker logs` working |
| buildx multi-node builders, bake | Native multi-architecture builds | **Adopted** (P6) |
| Docker Build Cloud | Hosted builders | Rejected: paid and off-site |
| GHCR; Distribution pull-through cache; Harbor | Registry of record; local cache; full registry | GHCR and the cache **adopted**; Harbor only if policy outgrows them |
| Trivy, cosign; Docker Scout, Hardened Images | Scanning and signing; Docker's equivalents | Trivy and cosign **adopted**; Scout and DHI evaluated (installed) |
| Docker MCP Gateway and Toolkit | Container isolation, secrets and allowlists for MCP servers | **Adopted** (P7) |
| Hand-rolled per-server MCP containers | — | Rejected: re-implements the gateway |
| Compose Bridge, Kompose | Compose to Kubernetes manifests or Helm charts | Spike in P10 |
| Flux, Argo CD | GitOps delivery | Decided in P10 |
| kubeconform, kind, k3d | Manifest validation and throwaway clusters | **Adopted** for CI (P10) |

## Supersedes / Superseded by

- Supersedes: none. `dash host rebuild` and `compose/forge.yml` stay, as the fenced legacy whole-hub path.
- Superseded by: none
