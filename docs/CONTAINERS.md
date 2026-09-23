# Containers — how ~24 compose files become one runnable fleet

> **`docs/DEVELOPMENT.md` is how you set a machine up; this is how the fleet runs on it.** One shared plane, many independent projects, and a port map nobody maintains by hand.

## The model in one paragraph

The fleet is **not one compose project, and cannot be**. Compose's `include:` does not namespace service names: five submodules define a service called `jekyll`, and compose merges them by name — silently keeping one and discarding the rest, with no error and no warning. Postgres appeared eight times across the fleet, Redis five, Phoenix three, and seventeen host ports were claimed by more than one project. So each repo stays its **own** compose project, and three things make them compose: **one network** (`fleet`, created by the hub, joined by everyone), **one of each backing service** (the hub's Postgres, Redis and Phoenix, reachable by service name across project boundaries), and **one port map** (declared in the registry, applied by a generated override). `tools/dash up` is the loop that brings them up together.

```text
        _data/projects.yml  dev_port · database         _data/fleet.yml  containers:
                     │                                            │
                     └──────────────┬─────────────────────────────┘
                                    ▼
                        dash gen compose   (fleet_compose.py)
                                    │
             ┌──────────────────────┼───────────────────────────┐
             ▼                      ▼                           ▼
   .fleet/compose/<slug>.yml   tools/fleet/db-init/     the validated port map
   (per-project override,      (one database + role     (collisions are an ERROR,
    gitignored, never in        per project that         before anything is written)
    the submodule)              asks for one)
             │
             ▼
   docker compose -p <slug> --project-directory projects/<slug> \
       -f projects/<slug>/docker-compose.yml -f .fleet/compose/<slug>.yml up -d
             │
             ▼
   ┌─────────────────────── network: fleet ───────────────────────┐
   │  hub project `fleet`        each submodule, its own project  │
   │  devenv  console            it-journey   zer0-pages   law-ai │
   │  db      redis              …every one reaching db, redis    │
   │  (+ phoenix, wiki, elk      by NAME across project lines     │
   │   behind profiles)                                           │
   └──────────────────────────────────────────────────────────────┘
```

## Operate — the short card

```bash
tools/dash up                          # the shared core: devenv, console, db, redis
tools/dash up it-journey law-ai        # …plus those projects
tools/dash up --group jekyll           # …plus a group from _data/fleet.yml
tools/dash up --all [--force]          # …everything registered, capped by max_projects
tools/dash up --profile traces         # …and an optional hub service (traces|docs|admin|elk)
tools/dash ps                          # what is running fleet-wide, and who is on the network
tools/dash down                        # stop the core
tools/dash down --all [-v]             # stop every project too; -v also drops volumes
tools/dash gen compose                 # regenerate the overrides after a registry change
tools/dash gen compose --check         # verify they still match the registry
```

**The core comes up first, always.** Every other project needs its network and its database, so `dash up` starts the hub before it starts anything named.

## What changed, and why

### devenv is a workspace again

It used to publish about thirty host ports in ranges (`4010-4020`, `5174-5177`, `8010-8013`…) so that every submodule's dev server could be run **inside** it by `compose exec`. That made it a second, hand-maintained copy of the fleet's port map, and it could only ever run the projects someone had remembered to reserve a range for.

Each project with its own compose file now runs as its own project on the `fleet` network and takes its port from the registry. devenv keeps the hub's Jekyll dash on `:4000` and one **workspace block** — because nine projects (`bamr87.github.io`, `lifehacker.dev`, `wargames`, `drsai`, `irony-works`, `2005`, `cv-builder-pro`, `gitnexus`, `rewind-arcade`) have no compose file at all and can only run by `compose exec`. Those ranges are declared in `containers.ports.workspace*` and are deliberately clear of the fleet map; a test holds the two apart, because an overlap is not an error at runtime — the loser simply never binds.

A project graduates out of the workspace block by gaining a compose file and a `dev_port`.

### One Postgres, one Redis

The hub runs them; a project asks for a database by declaring `database: true` in `_data/projects.yml` and gets one, with its own role, named after its directory. Six projects have one today.

Provisioning is generated into `tools/fleet/db-init/` and mounted at `/docker-entrypoint-initdb.d`, **and** re-applied by `dash up` on every start — because Postgres runs that directory exactly once, on an empty data directory, so a volume created before a project was registered would otherwise never see it. Every statement is guarded, so the second run is a no-op rather than an error.

**Switching a project's own Postgres off is a separate, later step.** Using the hub's means the app's connection string points at `db`, which is a change inside that project — so `shared_services: [postgres]` in the registry is opt-in per project, and until it is set the project keeps its own database container, just on a port that no longer collides. That ordering is deliberate: de-colliding ports fixes "nothing can run together" immediately and safely; consolidating databases is a migration each project takes when someone has actually repointed it.

### The project name is pinned

`docker-compose.yml` sets `name: ${COMPOSE_PROJECT_NAME:-fleet}`. Without it compose derives the project name from the **directory**, so a git worktree and the main checkout get separate sets of volumes — which is how one Postgres becomes two, with the data in neither. Pinning it means every checkout of this repo drives one fleet.

## The port map

`dev_port` in `_data/projects.yml` is the **base** for a project. `dash gen compose` reads that project's own compose file and rewrites the **host** side of every published port from it, in declaration order, leaving container ports untouched — so nothing about the app's own configuration changes.

| Range | Kind |
| --- | --- |
| `4010-4039` | Jekyll / Ruby static sites |
| `3010-3039` | Rails, Node SSR, anything that wants `:3000` |
| `5174-5199` | Vite / node dev servers |
| `8010-8049` | Django, FastAPI, MkDocs, agents |
| `9010-9039` | per-project stores the fleet cannot share |
| `35730-35759` | livereload sidecars |
| `4040-4069`, `5000-5019`, `35760-35789` | the **workspace** block — projects with no compose file |

Below `4010` is the hub: `4000` dash, `4001` console, `3000` wiki, `5050` pgAdmin, `5432` Postgres, `6379` Redis, `6006`/`4317` Phoenix, `8001` MkDocs, `9200`/`5601`/`3001` the log plane.

**Livereload is allocated from its own range**, offset by the project's position in its kind's range rather than counted from the bottom. Counting restarts at the low end for every project, so all six Jekyll sites get the same livereload port and only the first binds — the generator's own validator caught exactly that. It matters beyond tidiness: Jekyll embeds the livereload port in the page it serves, so a port remapped into the middle of a site's block leaves the site looking fine while reload is quietly dead.

Validation runs **before anything is written** and refuses on a duplicate, on a port that is one of the hub's, and on a `dev_port` outside its kind's range. A port collision does not raise at `docker compose up` — the second binder fails and the container restarts, so the symptom is a flapping service and the cause is three layers away.

## The overrides

One file per project in `.fleet/compose/`, gitignored, regenerated. **Nothing is ever written into a submodule**: a submodule is a separate git repo, and the hub only writes to one through a fan-out PR. The override is applied as a second `-f`, with `--project-directory` pinned to the submodule so its relative build contexts still resolve.

`ports:` and `networks:` carry the `!override` tag, which is load-bearing. Without it compose **merges** the two lists, so the original colliding port comes back alongside the new one and the project still refuses to start — with a conflict on a port the override appears to have changed.

A project's own internal networks are preserved; `fleet` is added alongside. The network is declared `external: true` in the override and created by the hub, so a project brought up without the hub fails with a clear message instead of quietly creating a second, empty network of its own.

## Adding a project

1. Give it a `docker-compose.yml` in its own repo (if it has none, it lives in the workspace block instead).
2. Add `dev_port:` to its row in `_data/projects.yml`, picking a free number in its kind's range. Add `database: true` if it needs Postgres.
3. `tools/dash gen compose` — this validates the whole map and fails on a collision.
4. `tools/dash up <name>`.

Optionally add it to a group in `_data/fleet.yml` `containers.groups`; a test asserts every group member is a real submodule, because a typo there silently drops a project from `--group`.

## What is deliberately not done

- **`--all` is capped.** `containers.max_projects` is 8, and `--all` refuses past it without `--force`. This bench OOM-killed Elasticsearch at a 1 GB heap with five extra containers; law-ai alone pulls neo4j, ollama, vllm and Phoenix.
- **Submodule compose files are untouched.** Everything here is additive and reversible from the hub side. Consolidating each project onto the shared Postgres is a per-project migration, tracked by `shared_services:`.
- **`include:` is not used anywhere**, for the reason at the top. If a future compose version namespaces included services, this design collapses into something much smaller — until then it would silently lose services.

## Files

| Path | What |
| --- | --- |
| `docker-compose.yml` | The shared half: pinned project name, the `fleet` network, four core services, the rest behind profiles |
| [`_data/fleet.yml`](../_data/fleet.yml) `containers:` | The contract — network, shared services, port ranges, groups, the cap |
| [`_data/projects.yml`](../_data/projects.yml) | `dev_port`, `database`, `shared_services` per project |
| `.github/scripts/dash-gen/fleet_compose.py` | The generator, the validator and target resolution |
| `tools/fleet/db-init/` | Generated Postgres provisioning (committed — it is mounted at startup) |
| `.fleet/compose/` | Generated per-project overrides (gitignored) |
| `tools/dash up\|down\|ps` | The orchestrator |
| `.vscode/launch.json` | F5 entries — `tools/dash up <project>` for compose-backed projects, `compose exec devenv` for the workspace nine |

Tests: `.github/scripts/dash-gen/test_fleet_compose.py` — 24 checks, offline, no docker.
