# Forge as the Docker host

The Mac runs the terminal dash (`tools/dash tui`). **Forge runs the containers.** The registry is still `_data/projects.yml` — Docker is live state, not a second inventory.

```
Mac TUI  --ssh://forge-->  forge dockerd
   │                         │
   └─ projects.yml           ├─ ~/dev/<slug>/docker-compose.yml
      project_health.yml     ├─ postgres / redis / grafana (always-on)
                             └─ app containers
```

## Why not `docker context` + Mac bind mounts

`docker -H ssh://forge` talks to forge's daemon. Compose bind mounts (`.:/workspace`) are evaluated **on the daemon**. A Mac path like `/Users/bamr87/bamr87` does not exist on forge, so `docker compose --context forge up` from the Mac will fail or mount an empty dir.

**Rule:** start compose **on forge**, from a tree that already lives there (`~/dev/<slug>`).

Do not publish the Docker TCP socket. SSH (`ssh://forge`) is the API.

## One-time

```bash
tools/dash host setup          # docker context "forge" → ssh://forge
# optional, for the Harness Console on the LAN:
ssh forge 'sudo ufw allow from 192.168.4.0/24 to any port 4001 proto tcp comment "dash console LAN"'
```

## Rebuild the hub stack (wipes containers + volumes)

Uses `bamr87/.env` for tokens and compose ports.

```bash
tools/dash host rebuild        # rsync hub+.env, docker rm -f, compose --build
tools/dash host ps
tools/dash host up <slug>      # launch one submodule compose in ~/dev/<slug>
tools/dash tui                 # Apps + Forge tab
```

Hub URLs on the LAN (ports from `.env`):

| Service | URL |
|---|---|
| Console (review / launch) | http://forge.local:4001 |
| Devenv (exec to build) | `ssh forge 'docker exec -it bamr87-devenv bash'` |
| Wiki | http://forge.local:3000 |
| MkDocs | http://forge.local:8001 |
| Jekyll (inside devenv) | http://forge.local:4000 |
| CV / Vite | http://forge.local:5000 / `:5173` |
| Phoenix | http://forge.local:6006 |
| Postgres | forge.local:5432 |
| Redis | forge.local:6379 |
| pgAdmin | http://forge.local:5050 |

The TUI **Forge** tab is `docker ps -a` on the host. The **Apps** Forge column is a join: compose project / container name / `bamr87.project` label vs registry `name` or submodule dir.

Label app services so the join is exact:

```yaml
labels:
  bamr87.project: it-journey
```

## What belongs on forge

| On forge | Not on forge |
|---|---|
| App compose stacks, Postgres, Redis, Grafana | bamr87 `devenv` image (too heavy for the i7-3820) |
| Jekyll/site compose that is already small | Docker Desktop as the source of truth |
| Portainer `:9443` | Binding `127.0.0.1` if you want LAN access from the Mac |

The hub `docker-compose.forge.yml` overlay is only for a **checkout on forge**. Prefer per-app compose in `~/dev/<slug>`.
