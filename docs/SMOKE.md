# SMOKE — the monorepo's live smoke test

> `record` connects to every container in the local fleet and exercises it for
> real; `check` re-runs those probes and fails on any move away from what was
> recorded. The topology comes from [`_data/ports.yml`](../_data/ports.yml), so a
> service added there is probed automatically.

```bash
tools/dash dev up --all                 # bring the fleet up
tools/dash dev smoke record             # exercise everything, write _data/smoke.yml
tools/dash dev smoke show               # the recorded table
tools/dash dev smoke check              # re-probe, diff, exit 1 on regression
tools/dash dev smoke check --project law-ai
./tools/run-all-tests.sh                # includes the check (skips if the stack is down)
```

## What it actually does to each container

Not a port scan — it talks to the services:

| Band | Probe |
| --- | --- |
| `jekyll` `frontend` `api` `docs` `hub` | HTTP GET on `/`, recording status, content-type, byte count, `<title>`, latency — **without following redirects** |
| `database` | TCP connect, then a real `select current_setting('server_version')` through the container's **own** `psql`, plus the database list |
| `cache` | TCP connect, then `redis-cli PING` and the server version |
| `debug` | TCP connect (debugpy does not speak HTTP) |
| every running container | `docker exec … id -un` — proves a shell is reachable and records **which user the process runs as** |

Everything the daemon knows is recorded too: state, health, image, and the containers that are running but have **no** allocation in the registry.

## What is asserted, and what is only recorded

`check` holds the fleet to the *stable* subset: state, verdict, HTTP status class, Postgres/Redis **major** version, exec user, health. Latency, byte counts, patch versions, container ids and titles are recorded for context but **never asserted** — they move on their own, and a gate that cries wolf gets ignored. On a failure the un-asserted fields are printed as evidence.

Four verdicts, and the difference matters:

- **ok** — running and every probe answered.
- **broken** — running but something it should answer does not. The only one
  that is an incident.
- **optional** — not running because a compose **profile** gates it
(`--profile celery` starts djangoerp's worker; nothing else does). 7 of the fleet's 9 stopped services are this, and calling them failures would bury the one that is not.
- **absent** — not running and nothing explains why.

## What the first recording found

35 services: **26 ok, 0 broken, 7 optional, 2 absent**.

The two absent ones are both known: `barodybroject/web-prod` is excluded from the fleet stack (production settings, needs a real `SECRET_KEY`), and `zer0-image-generator/web` fails to build because its Dockerfile `COPY`s a `Gemfile.lock` the always-latest policy forbids committing.

Facts the recording makes visible that nothing else did:

- **Postgres sprawl** — 15.19 (ai-seed, barodybroject), 16.15 (aieo, law-ai),
17.11 (djangoerp). The open harmonization PRs converge these to 18 except where a pin says otherwise.
- **Redis** — 7.4.11 vs 8.10.1.
- **Almost everything runs as root.** Only three of 26 do not: `bamr87/console`
(vscode), `fredgar-ai/web` (appuser), `zer0-cms/cms` (rails). UPS-REPO-31 has said this for a while; this is the first time it is measured per service.
- **`barodybroject/docs` reports `unhealthy` while serving HTTP 200** — the
`localhost`/`::1` healthcheck trap (docs/DOCKER.md rule H1), now a recorded fact rather than an anecdote.
- **The hub's MkDocs redirects `/` → `/README/` → …** in a loop. The probe
  records the 302 and does not chase it.

## Two failure modes the tool is built around

- **A flaky daemon must not become a false baseline.** `docker ps` on this
machine measured 0.2s and 18s minutes apart. An early cut swallowed the error and recorded *every service in the fleet as absent* — confidently wrong, and worse than no baseline. It now retries and then refuses to write.
- **The probe must not contend with itself.** A cold `docker exec` costs ~7s and
a warm one 0.2s; twelve threads arriving at once all queued past the timeout and nine healthy services were recorded as broken. Daemon calls are now serialized behind a semaphore, per-container env comes from one batched `docker inspect`, and only HTTP/TCP run in parallel.

## Re-recording

Re-record when a change is intended — a merged harmonization PR (Postgres major moves), a service added to `_data/ports.yml`, or a profile started on purpose. The diff in `_data/smoke.yml` is the review artifact: it shows exactly which service's observable behaviour changed.

## See also

[`docs/FLEET-COMPOSE.md`](FLEET-COMPOSE.md) · [`docs/DOCKER.md`](DOCKER.md) · [`_data/ports.yml`](../_data/ports.yml) · [`_data/smoke.yml`](../_data/smoke.yml)
