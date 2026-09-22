---
schema: "0.1"
coverage: listed
---

# SCHEMA — compose

> The hub's half of the fleet dev stack: the shared-services layer plus one generated override per submodule, so any project can be launched and debugged from the hub without a commit in its own repo.

## Conventions

- `overrides/*.yml` are **generated** from [`_data/ports.yml`](../_data/ports.yml) by `tools/fleet-compose.py sync` — never hand-edited. Change the registry, re-sync, commit both.
- `shared.yml` is hand-written: it is policy (what the fleet shares), not projection.
- Submodule compose files are never modified from here. An override may only remap where a service is *published* (`ports`, `container_name`, `networks`, and the `depends_on`/`env_file` edges those force); it must never change what a service *is*.
- Each submodule runs as its own compose project joined by the external `fleet-net`. `include:` merges into one namespace and the fleet's service names collide (`jekyll` ×5, `redis` ×4), so one file is not an option — see [`docs/FLEET-COMPOSE.md`](../docs/FLEET-COMPOSE.md).

## Structure

| entry | kind | purpose | rules |
|---|---|---|---|
| `README.md` | file | What `compose/` is and the two rules an override must obey | required |
| `shared.yml` | file | Shared-services layer overlaid on the hub's `docker-compose.yml`: `fleet-net` attachment, the Phoenix aliases, and the opt-in `shared-db` Postgres/Redis | required |
| `overrides/` | dir | One generated override per compose-hosted project, plus `hub.yml` for devenv's fleet-mode port map | generated |
| `initdb/` | dir | Postgres entrypoint scripts for the shared `fleet-db` — one database per consumer | required |

## Placement

- New shared service → `shared.yml`, plus a `shared:` entry in `_data/ports.yml`
- New project in the fleet stack → a `projects:` entry in `_data/ports.yml`, then `tools/fleet-compose.py sync`
- New shared-Postgres bootstrap step → `initdb/NN-name.sh` (numbered; runs once, on an empty data dir)

## Forbidden

- No hand edits to `overrides/*.yml` — the drift gate (check (m)) fails on divergence from the registry.
- No secrets: these files are public and are read by every fleet surface.
- No `container_name` that is not `fleet-`prefixed — container names are global to the daemon.
