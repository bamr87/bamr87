# DOCKER — one standard for every Dockerfile and compose file in the fleet

> Image versions come from **one registry**, a tool rewrites each repo to match,
> and a fan-out delivers it as PRs — so "latest, consistent, and scalable" is a
> property of the machinery, not of forty people remembering.

```bash
tools/dash docker fleet                      # what would change, per checked-out submodule
tools/dash docker audit projects/law-ai --project law-ai
tools/dash docker apply projects/law-ai --project law-ai     # edit in place (review the diff!)
tools/dash docker check .  --project bamr87  # gate: exit 1 if anything would change
tools/dash docker tags                       # do the registry's tags exist upstream?
tools/fanout.sh --kit docker --target all    # dry run: build every PR branch, push nothing
tools/fanout.sh --kit docker --target law-ai --apply           # open the PR
tools/dash dev db-upgrade <project> --yes    # Postgres major bump without losing data
```

## The registry

[`_data/fleet.yml`](../_data/fleet.yml) `images:` is the **only** place a container image version is bumped:

| image | version | note |
| --- | --- | --- |
| postgres | 18 | 18 moved its data directory — see below |
| redis | 8 | |
| node | 24 | Active LTS; 26 is "Current" and becomes LTS in Oct 2026 |
| python | 3.14 | law-ai is held at 3.13 (see overrides) |
| ruby | **3.4** | **not 4.0** — `github-pages` declares `Ruby < 4.0` |
| nginx | 1 | mainline major; `nginx:1-alpine` floats to the newest 1.x |

Only the **version** lives there. A file keeps its own tag *variant* (`-alpine`, `-slim`), because that is a per-image decision; `bookworm` moves to `trixie` (Debian 13). Floating tags (`latest`, bare `alpine`) are already latest and are left alone, matching the always-latest dependency policy. Third-party service images (neo4j, qdrant, ollama, grafana…) are **not** managed — they version independently and each repo owns its choice.

This block governs **container images only**. `toolchain:` and `variables:` in the same file govern the *CI runners* (`standard-ci.yml` still falls back to Node 20) and are deliberately separate: moving every repo's CI runtime is its own fleet-wide change (`dash config sync`), not a side effect of a Dockerfile.

### Why not hub-published base images?

The obvious alternative — `ghcr.io/bamr87/fleet-base-python` and friends — was considered and rejected: it makes every repo's build depend on a private registry being reachable and current, adds a publish workflow to keep alive, and buys only layer sharing. A version registry gives the same *consistency* with **zero runtime coupling**: each repo still builds from a stock official image.

## What the transformer does

Surgical **line edits**, never a YAML round-trip — the compose files' comments are the valuable part (they record *why*), and a load/dump cycle destroys them. Every rule is idempotent: a second `apply` changes nothing.

| rule | change |
| --- | --- |
| V1 | drop the obsolete top-level `version:` |
| I1 | bump managed images to the registry; variant kept; **never lowered** |
| P1 | postgres ≥ 18: mount at `/var/lib/postgresql` (the old path is a startup error) |
| N1 | drop `container_name` (global to the daemon) unless a script/config references it; a *comment* or doc mention does not block |
| T1 | ports → `"127.0.0.1:${VAR:-<same port>}:<target>"` — loopback, env-overridable, **defaults unchanged** |
| T2 | env values that hardcode a host port (`VITE_API_URL=http://localhost:3001`, a CORS allow-list) follow that variable |
| H1 / H2 | healthchecks probe `127.0.0.1`; qdrant (no `curl`) and `celery inspect ping` (needs a timeout) fixed |
| E1 | an `env_file` a fresh clone cannot have becomes `required: false` |
| L1 | a `COPY` of a lockfile the fleet forbids committing is trimmed; `npm ci` → `npm install` |
| D1 | seed a `.dockerignore` beside a build context that has none — **additive**, never overwrites |

Variable names come from the registry's `prefix:` in [`_data/ports.yml`](../_data/ports.yml), so a repo's variables share one stem with the ports already allocated there (`FREDGAR_API_PORT`, not `FREDGAR_AI_API_PORT`) and `.env.fleet` drives both the fleet stack and a standalone run.

The seeded `.dockerignore` is deliberately conservative: `.git`, `.env*` (keeping `.env.example`), dependency trees and caches — but **not** `dist/` or `build/`, because several repos `COPY` a pre-built frontend out of one. It lands beside the **build context** (which is what Docker resolves it against), not beside the Dockerfile, and never next to a `*.template` file, which is seed material for another repo rather than a build this one runs.

**Reported, never auto-fixed** (they need judgement): running as root, no `HEALTHCHECK`, single-stage builds, the unmaintained `jekyll/jekyll` image, `platform:` pins, and — importantly — `pinned-deps`.

## Deliberate pins and per-repo ceilings

- **A pin comment wins.** A comment on or directly above an `image:`/`FROM` line
containing *pinned*, *bump deliberately*, *do not bump* or *fleet-pin* freezes that image's family **for that file** — so law-ai's Postgres 16 pin also covers the `langgraph-db-init` sidecar that talks to the same server, while the hub's Wiki.js pin does not hold back the unrelated `fleet-db` in `compose/shared.yml`.
- **A ceiling with a reason** lives in `image_overrides:` in the registry. law-ai
is held at Python 3.13 because `crewai>=1.14` publishes no release for 3.14 (every candidate says `Requires-Python <3.14`). Delete the line when the ecosystem catches up. The tool still never lowers a version.

## Order matters: deps-latest first, then docker

Both kits are idempotent and independent, but a runtime bump on top of a stale exact pin can break a build. barodybroject is the worked example:

1. `psycopg2-binary==2.9.10` has no Python 3.14 wheel (2.9.13 does) → the docker
   PR reports `pinned-deps` and the build fails in `pip install`.
2. Run `deps-fanout` first: it unpins **and deletes lockfiles**.
3. Re-run docker: rule L1 now fires (`npm ci` had nothing to install from).

After that barodybroject's remaining failure is its own frontend — the latest TypeScript rejects side-effect CSS imports without a type declaration (`TS2882`; add `/// <reference types="vite/client" />`). That is an always-latest breakage in application code, which the fleet policy accepts and the daily doctor triages.

## Postgres major bumps orphan local volumes

The new server refuses data written by an older major, and Postgres 18 also moved its data directory. Dev data is disposable (`docker compose down -v`) — but you should not have to guess:

- `tools/dash dev up` runs a **preflight** and, for a volume behind its image,
  names the exact command instead of letting the database crash-loop.
- `tools/dash dev db-upgrade <project> [--service S] [--yes]` stops the service,
copies the **raw volume** to `<volume>-pre<major>`, takes a `pg_dumpall` from a throwaway server of the *old* major into `~/.fleet-backups/`, **verifies the dump is complete before removing anything**, recreates the volume on the new layout, and restores. Dry run without `--yes`; a second run is a no-op. Tested end to end: 15.19 → 18.6 with data intact.
- TimescaleDB (aieo) is refused: its dump needs the extension in the *old*
  server, and guessing that image is how data gets lost. Do it by hand.

## Two hazards the design deliberately handles

- **The hub's own Wiki.js database is pinned at Postgres 15** — real content lives
in that volume, and because 18 also moved its data directory the new server would start on an *empty* cluster with the old data unreachable in the same volume. Migrate deliberately (`tools/dash dev db-upgrade hub --service db --yes`) and delete the pin.
- **The shared tier publishes 5439/6389, not 5432/6379**, because the hub's own
`db`/`redis` already hold those in the same compose project. Containers reach it as `fleet-db:5432` either way — the host port only matters to tools on the host.

## The consolidated view

`/docker/` is one page for everything containerized — what to open, what is running, which image each service is on, and where that diverges from this registry. It is a **rendering**, not a second source of truth: the join is done offline by `tools/dash docker view --write`, which merges four things that already exist and writes `_data/docker.yml`.

| Input | Contributes |
| --- | --- |
| [`_data/ports.yml`](../_data/ports.yml) | the allocation — project, service, band, port, debug attach points |
| [`_data/fleet.yml`](../_data/fleet.yml) `images:` | the version contract, plus `image_overrides:` ceilings |
| [`_data/smoke.yml`](../_data/smoke.yml) | what actually answered: state, health, image, HTTP status/title/latency, server versions, run-as user |
| `.vscode/launch.json` | the configuration that starts or attaches to each port |
| this transformer, read-only | pending changes per repo, deliberate pins, advisory findings |

Three things it is careful about, each because the first cut got it wrong:

- **Comparison happens at the contract's precision.** `python:3.11` is behind
`3.14` even though the major matches. Comparing majors reported Python as conforming while five repos sat on 3.11/3.12.
- **Below the contract is not automatically drift.** A deliberate `# pinned`, an
`image_overrides:` ceiling, and a floating tag (`alpine`) are counted separately from real drift, so the page does not cry wolf on exactly the decisions that were made most carefully.
- **Absence is not conformance.** A submodule that is not checked out has *no*
findings, which is different from having none — its previous audit is carried forward and marked stale rather than rendered as clean.

It is **local-first**: two of its inputs only exist on a machine that runs the fleet, so it is refreshed by the operator (like `dash ai`), not by CI. The page says how old the recording is.

It also reports two gaps nothing else covers: repos carrying Docker files with no port allocation, and host ports the hub's own compose publishes outside the registry (Wiki.js 3000, pgAdmin 5050, Postgres 5432, Redis 6379 — grandfathered, correctly outside the bands, but real services that belong on the page).

## Gates

- **Drift check (n)** — the hub's own Dockerfiles/compose match the standard
  (gating) and the transformer's tests pass; submodule drift is advisory.
- `docker-fanout.yml` runs the transformer's tests **before** it touches anyone's
  repo, dry-run by default, PR-only, external upstreams skipped.
- `tools/test_docker_harmonize.py` — 37 fixture tests: every rule, pin logic,
  never-downgrade, fixtures untouched, comment preservation, idempotency.

## See also

[`docs/FLEET-COMPOSE.md`](FLEET-COMPOSE.md) (launching everything at once) · [`docs/SMOKE.md`](SMOKE.md) (the recording this view reads) · [`specs/REPOSITORY.md`](../specs/REPOSITORY.md) UPS-REPO-31/34–39 · [`docs/DEPENDENCIES.md`](DEPENDENCIES.md)
