# compose/ — the hub's half of the fleet dev stack

Launch and debug **any submodule from the hub**, with its real database, cache
and queue, on a port nobody else claims — without a commit in that submodule's
own repo.

```bash
tools/dash dev list            # every project and how it is hosted
tools/dash dev up law-ai       # one project's whole stack
tools/dash dev up law-ai --debug
tools/dash dev up --all
tools/dash dev ps --all
```

Full guide: **[`docs/FLEET-COMPOSE.md`](../docs/FLEET-COMPOSE.md)**.

## What is here

| Path | What it is |
| --- | --- |
| `shared.yml` | Hand-written policy: the `fleet-net` attachment, the Phoenix aliases every repo's tracing already points at, and the opt-in `shared-db` Postgres/Redis. Overlaid on the hub's `docker-compose.yml`, which is itself never modified — so a plain `docker compose up -d` still behaves exactly as before. |
| `overrides/*.yml` | **Generated** from [`_data/ports.yml`](../_data/ports.yml) by `tools/fleet-compose.py sync`. One per compose-hosted project, plus `hub.yml` for devenv's fleet-mode port map. Never hand-edit — drift check (m) fails on divergence. |
| `initdb/` | Postgres entrypoint scripts for the shared `fleet-db`: one database per consumer. |

## The two things worth knowing

**Each submodule is its own compose project, not one merged file.** Compose
`include:` collapses everything into a single namespace, and the fleet's service
names collide hard — `jekyll` is claimed by 5 repos, `redis` by 4, and
`worker`/`frontend`/`web` by 3 each. They interconnect over the external
`fleet-net` instead.

**An override may only change where a service is published, never what it is.**
`docker compose -f base.yml -f override.yml` resolves relative paths against the
*first* file's directory, so a submodule's `build.context: ./backend` keeps
working while the hub owns its `ports`, `container_name` and `networks` (and the
`depends_on`/`env_file` edges those force).

Every override file shrinks to nothing as its repo adopts the parameterized port
form upstream (UPS-REPO-34/35) — at which point it is deleted.
