# Forge as the Docker host

> Running the fleet's containers on the `forge` LAN host while the Mac runs the terminal dash.

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
tools/dash tui                 # Apps tab Docker column + the Docker tab
```

Hub URLs on the LAN (ports from `.env`):

| Service | URL |
|---|---|
| Console (review / launch) | http://forge.local:4001 (compose path); the bashOS service binds loopback: [below](#the-harness-console-as-a-bashos-service) |
| Devenv (exec to build) | `ssh forge 'docker exec -it bamr87-devenv bash'` |
| Wiki | http://forge.local:3000 |
| MkDocs | http://forge.local:8001 |
| Jekyll (inside devenv) | http://forge.local:4000 |
| CV / Vite | http://forge.local:5000 / `:5173` |
| Phoenix | http://forge.local:6006 |
| Postgres | forge.local:5432 |
| Redis | forge.local:6379 |
| pgAdmin | http://forge.local:5050 |

The TUI polls every endpoint in `DASH_DOCKER_HOST`, which defaults to `local,ssh://forge`: this Mac's Docker, where `tools/dash up` runs the shared core, *and* forge. Its **Docker** tab is `docker ps -a` on each host. The **Apps** Docker column is a join onto the registry: the `com.bamr87.fleet.project` label first, then compose project / container name / `<name>-` prefix (longest registry name wins).

Label app services so the join is exact. It is the same UPS-OPS-17 label the log shipper keys on, so one label serves both:

```yaml
labels:
  com.bamr87.fleet.project: it-journey
```

The older `bamr87.project` label still works, but new services should use the standard one.

## The Harness Console as a bashOS service

forge also runs the [bashOS](../projects/bashos/docs/OS.md) OS layer (`bashos os install`, 2026-11-01). That serves the hub's `tools/console` without Docker: `bashos-harness.service`, a systemd user unit, runs `tools/console/run.sh` from the checkout in `~/dev/bamr87`, restarts it if it dies, and starts at boot (linger is on).

- **Reaching it:** it binds `127.0.0.1:4001`, so use a tunnel: `ssh -N -L 4001:127.0.0.1:4001 forge`, then open http://localhost:4001. If the Mac's own `tools/dash up` console already holds :4001, use another local port (`-L 14001:127.0.0.1:4001`).
- **On the LAN:** set `BASHOS_HARNESS_HOST` in `/etc/bashos/os.conf` and put `DASH_CONSOLE_TOKEN` in `~/.config/bashos/harness.env` (mode 0600). `bashos-harness` refuses a LAN address without the token. `BASHOS_LAN_CIDR` adds the ufw rule, like the one-time step above.
- **Operating it:** `bashos os status` gives the verdicts. `bashos os harness status|logs|restart|url` covers the unit.
- **One owner for :4001.** The compose `console` service (`tools/dash host rebuild`, `compose/forge.yml`) and `bashos-harness` can't both bind it. Either stop the service before a rebuild (`bashos os harness stop`), or set `BASHOS_HARNESS=compose` so systemd supervises the compose console itself.

forge can also boot the whole bashOS image from a USB stick, once, without touching its disk. It then runs as `forge-bashos.local`, serves the same console on its loopback, and offers the monitor's keyboard and mouse over VNC through ssh. While it does, `ssh forge` and `ssh://forge` (the TUI's Docker poll) don't answer. `sudo reboot` returns to Debian. How: [bashOS docs/OS.md § forge, step by step](../projects/bashos/docs/OS.md#forge-step-by-step).

## What belongs on forge

| On forge | Not on forge |
|---|---|
| App compose stacks, Postgres, Redis, Grafana | bamr87 `devenv` image (too heavy for the i7-3820) |
| Jekyll/site compose that is already small | Docker Desktop as the source of truth |
| Portainer `:9443` | Binding `127.0.0.1` if you want LAN access from the Mac |

The hub `compose/forge.yml` overlay is only for a **checkout on forge**. Prefer per-app compose in `~/dev/<slug>`.
