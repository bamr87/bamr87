### Fixed

- `tools/dash up` checks the core `db` volume against its Postgres image and refuses to recreate onto an older major, naming the exact migration; the PG 15 → 18 bump had left the core database restarting in a loop on the first recreate.
- The core `db` healthcheck passes `-d` to `pg_isready`, so it no longer logs `FATAL: database "wikijs" does not exist` into the log plane every 10 seconds.
- `tools/pg-major-upgrade.sh` reads the cluster the image will open (`<major>/docker`, then the mount root) before searching, so a volume holding a second cluster cannot report the wrong major.
- `docker-compose.yml`, `docs/DOCKER.md` and `AGENTS.md` no longer point the core's migration at `dash dev db-upgrade hub`, which targets the separate `fleet-hub` volume.
