#!/bin/sh
# ============================================================================
# File:          compose/initdb/10-fleet-databases.sh
# Description:   Creates one database per fleet consumer inside the shared
#                Postgres server (compose/shared.yml, profile `shared-db`).
# Author:        bamr87
# Created:       2026-09-20
# Last Modified: 2026-09-20
# Version:       1.0.0
# Usage:         Mounted at /docker-entrypoint-initdb.d — run by the postgres
#                entrypoint on FIRST start only (empty data dir). Adding a name
#                to FLEET_DATABASES later needs `docker compose down -v` on the
#                fleet-db-data volume, or a manual CREATE DATABASE.
# ============================================================================
set -eu

# One server, one database per app. Owner is the single POSTGRES_USER: these
# are local development databases on a loopback-only port, and per-app roles
# would need per-app credentials in a file that is not a secret store.
for db in $(printf '%s' "${FLEET_DATABASES:-}" | tr ',' ' '); do
    [ -n "$db" ] || continue
    echo "fleet-db: creating database '$db'"
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-SQL
	SELECT 'CREATE DATABASE "$db"'
	 WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '$db')\gexec
SQL
done
