# FLEET-COMPOSE — launching and debugging any submodule from the hub

> One command brings up any project (or all of them) with its real database,
> cache and queue, on a port nobody else claims, joined to one shared network —
> without a commit in the submodule's own repo.

```bash
tools/dash dev list                     # every project and how it is hosted
tools/dash dev up hub                   # devenv + console + phoenix + shared layer
tools/dash dev up law-ai                # one project, its whole stack
tools/dash dev up law-ai --debug        # ...with the repo's own debugpy layer
tools/dash dev up --all                 # every checked-out project at once
tools/dash dev ps --all                 # what is running, with URLs
tools/dash dev ports                    # the allocation table
tools/dash dev down --all
```

In VS Code: the **0-fleet** launch group wraps all of the above, and **7-python** has real `debugpy` attach configurations.

---

## The problem this solves

The fleet is ~40 independent repos, 27 of which ship a compose file. Every one of them obeyed the old UPS-REPO-30, which mandated a single port map for every repo (4000 Jekyll, 5000 app, 5173 HMR, 8000 API, 5432 Postgres, 6379 Redis). The result was total conformance and total gridlock:

| Port | Repos publishing it |
| --- | --- |
| 5432 | 6 |
| 3000 | 6 |
| 8000, 8080 | 5 each |
| 6379, 4000, 5173, 5678 | 4 each |
| 6006 / 4317 | 3 — three separate Phoenix trace stores |

Plus a hard one: the hub and `projects/README` both set `container_name: bamr87-wiki`. Container names are global to the Docker daemon, so whichever started second failed outright.

Meanwhile `.vscode/launch.json` routed all ~50 configurations through the single `devenv` container. `devenv` carries toolchains, not dependencies, so `🐍 Django: law-ai runserver` started Django in a container where the hostnames its settings resolve — `postgres`, `neo4j`, `redis` — do not exist.

## Why this is NOT one compose file

The obvious design is `include:` in one `compose.fleet.yml`. It fails, and the reason is worth writing down so nobody re-attempts it:

**`include:` merges every included file into a single project namespace, and the fleet's service names collide.**

```
jekyll     x5  barodybroject, it-journey, zer0-mistakes, bashconsultants, zer0-pages-remote
redis      x4  law-ai, djangoerp, fredgar-ai, aieo
worker     x3  law-ai, djangoerp, fredgar-ai
frontend   x3  law-ai, fredgar-ai, ai-seed
web        x3  djangoerp, fredgar-ai, zer0-image-generator
postgres   x2  law-ai, aieo
db         x2  djangoerp, fredgar-ai
```

Merging would silently fuse law-ai's frontend with ai-seed's. So each submodule runs as **its own compose project** (`-p <name>`), and they interconnect over the external network `fleet-net`. That is the standard multi-repo pattern: per-project namespacing, `down` on one leaves the rest alone, containers auto-named `<project>-<service>-1`, and it scales past 40 repos. `tools/fleet-dev.sh` is the single command that drives them all — that is the "one structure", not one file.

## How the hub overrides a repo it cannot commit to

Submodules are separate repos. The hub fixes their ports anyway, using the fact that `docker compose -f base.yml -f override.yml` **resolves relative paths against the FIRST file's directory**:

```
docker compose -p law-ai \
  -f projects/law-ai/docker-compose.yml \   # submodule: authoritative for WHAT it builds
  -f compose/overrides/law-ai.yml           # hub: authoritative for WHERE it is published
```

`build.context: ./backend` still resolves to `projects/law-ai/backend`. The override only ever touches publication concerns, using the `!override` tag to *replace* a list rather than append to it:

```yaml
services:
  backend:
    ports: !override
      - "127.0.0.1:${LAW_AI_API_PORT:-8110}:8000"
      - "127.0.0.1:${LAW_AI_DEBUG_PORT:-5713}:5678"
    networks:
      - fleet-net        # additive: the project keeps its own networks
```

The submodule's file is never modified and still runs standalone.

## The registry

[`_data/ports.yml`](../_data/ports.yml) is the single source of truth — the same role `projects.yml` plays for repos. It defines **bands** (4010–4039 Jekyll, 5000–5199 frontends, 8100–8149 APIs, 5700–5749 debuggers, 35730–35759 livereload, 5430–5469 per-project databases, 6380–6399 per-project caches), the **shared** services, and every project's allocation.

```bash
tools/fleet-compose.py show            # the table
tools/fleet-compose.py check --audit   # gate + what is still hardcoded upstream
tools/fleet-compose.py sync            # regenerate .env.fleet + overrides + compose.fleet.yml
```

`sync` writes `.env.fleet` (gitignored), `compose/overrides/*.yml`, `compose/overrides/hub.yml` (devenv's fleet-mode port map) and `compose.fleet.yml`. **Drift check (m)** fails the build if the allocation has a collision, is out of band, or the generated files have drifted from it.

Variables are namespaced (`DJANGOERP_DB_PORT`, not `POSTGRES_PORT`) because the submodules' own names collide: djangoerp and barodybroject both read `POSTGRES_PORT`; zer0-cms and zer0-image-generator both read `PORT`.

## What is actually shared

| Service | Shared by default | Why |
| --- | --- | --- |
| **Phoenix** (`fleet-phoenix`) | **Yes** | A trace sink with no schema coupling, and CLAUDE.md already designates one Phoenix as the local stack's trace store that `dash lake export` feeds. law-ai and bashos each ran a third copy on the same 6006/4317. Their own is profiled out and the shared one carries the network alias `phoenix`, so their `PHOENIX_COLLECTOR_ENDPOINT=http://phoenix:6006` keeps working untouched. |
| **Postgres** (`fleet-db`) | No — `--profile shared-db` | One server, one database per app is correct for plain-Postgres consumers, but it changes the behaviour of a working stack, and two consumers cannot join at all: aieo runs `timescale/timescaledb`, and law-ai pins its major version with a documented dump/restore step. Those keep their own, on a deconflicted port. |
| **Redis** (`fleet-redis`) | No — `--profile shared-db` | Safe in principle (a logical DB index per app); default-off until each consumer is moved deliberately. |

Profiling a service out forces two edits the generator makes automatically: any `depends_on` pointing at it must drop that edge (Compose rejects the whole project otherwise), and a missing `env_file` must become `required: false`.

## Debugging

`--debug` layers the repo's **own** `docker-compose.debug.yml` — the file that actually starts `debugpy` and bind-mounts the source. Without it an attach config connects to nothing.

| Project | Attach port | Container port | Needs |
| --- | --- | --- | --- |
| djangoerp `web` / `worker` | 5710 / 5711 | 5678 | `DEBUGPY_ENABLE=1` (its main compose is already debug-capable; it ships no debug file) |
| law-ai `backend` / `worker` | 5713 / 5714 | 5678 / **5679** | `--debug` |
| fredgar-ai `web` | 5712 | 5678 | `--debug` |

barodybroject deliberately has **no** attach target: its `web-prod` runs no debugpy and bind-mounts no source. The 5678 in that repo belongs to its `.devcontainer` stack, which the hub does not drive.

## Adding a project

1. Add a `projects:` entry to `_data/ports.yml` (`host: compose` or `devenv`),
   picking ports inside the right bands.
2. `tools/fleet-compose.py sync`
3. Commit the registry **and** the generated files. Drift check (m) gates both.

## Known gaps

- **Submodule services that still hardcode a published port or set a
`container_name`** (converge via `docker-fanout.yml`). The hub override neutralizes that inside the fleet stack, but two repos run *standalone* still collide. `tools/fleet-compose.py check --audit` lists them; UPS-REPO-34/35 are the requirements, and a fan-out (same machinery as `standardize-fanout.yml`) is the fix. Every override file shrinks to nothing as its repo adopts the parameterized form upstream.
- **`projects/README` duplicates the hub's Wiki.js stack**, including the
`bamr87-wiki` container name and ports 3000/5050. It is excluded from the fleet stack rather than deconflicted, because the hub's copy supersedes it.
- **Base images / version drift is solved differently than first planned.** Instead of
hub-published GHCR base images (a runtime dependency on a private registry, for layer sharing only), versions come from one registry and a fan-out converges every repo — see [DOCKER.md](DOCKER.md).

## See also

- [`_data/ports.yml`](../_data/ports.yml) — the allocation
- [`compose/SCHEMA.md`](../compose/SCHEMA.md) — what lives in `compose/`
- [`specs/REPOSITORY.md`](../specs/REPOSITORY.md) — UPS-REPO-30/34/35/36
- [`SUBMODULES.md`](../SUBMODULES.md) — committing inside a submodule
