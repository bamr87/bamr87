---
schema: "0.1"
coverage: listed
---

# SCHEMA — compose/initdb

> Postgres entrypoint scripts for the shared `fleet-db` server: one database per fleet consumer, created on first start.

## Conventions

- Mounted read-only at `/docker-entrypoint-initdb.d` by the `fleet-db` service in [`../shared.yml`](../shared.yml).
- The Postgres entrypoint runs these **only when the data directory is empty**. Adding a consumer later means `docker compose down -v` on `fleet-db-data`, or a manual `CREATE DATABASE`.
- Numbered prefixes set the order; keep them two digits.

## Structure

| entry | kind | purpose | rules |
|---|---|---|---|
| `10-fleet-databases.sh` | file | Creates one database per name in `FLEET_DATABASES` (comma-separated, set from `compose/shared.yml`) | required |

## Placement

- New bootstrap step → `NN-name.sh`, executable, `set -eu`, idempotent

## Forbidden

- No credentials beyond the local-development defaults already in `shared.yml` — these files are public.
- No application schema or migrations: each app owns its own, run by its own tooling.
