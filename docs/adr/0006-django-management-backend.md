# ADR 0006 — Django is the hub's management backend and what a frontend's private mode signs in to: accounts, admin and operational records in a database, the registries still in git, the FastAPI console ported route family by route family

- **Status**: proposed
- **Date**: 2026-11-04
- **Deciders**: proposed by an agent at the maintainer's request (2026-11-04: "use django as a backend management/framework for the monorepo", and private mode as "one that can authenticate with a django backend, either locally in docker, or from a cloud host"); the maintainer accepts or rejects it by merging the PR that adds it
- **Related**: [ADR 0005](0005-console-as-fleet-portal.md) (the portal this backend serves), [specs/STACKS.md](../../specs/STACKS.md) (the fleet's Django stack profile), [specs/BACKEND.md](../../specs/BACKEND.md) (UPS-BE, the API conventions), constitution § 2 (the registry invariant), § 10.5, § 10.6, § 10.8, § 11 (write-back gates), § 12.3, bamr87/bamr87#583 (accounts, organizations and teams for the console), [docs/HARNESS-OPS.md](../HARNESS-OPS.md), [docs/CONTAINERS.md](../CONTAINERS.md)

<!-- Accepted in and Completed are added by the post-merge ratify job when the maintainer merges this ADR's PR and when the maintainer closes the Tracking issue as completed (docs/adr/README.md#lifecycle). Never write them by hand. A PR that adds or changes an ADR is gated (constitution § 12.3). -->

## Context

### Needs assessment

**Who needs what.** The maintainer asked for Django as the backend management framework for the monorepo, in the same session that made the Harness Console the fleet's portal (ADR 0005). A portal that several surfaces sign in to, that remembers what was checked and verified, and that more than one person may use needs what the console's backend does not have: accounts, permissions, a database with migrations, and an administration surface.

**Evidence from the hub.**

- The console's backend is FastAPI: `tools/console/app.py` (68 routes) over `core.py` and its siblings, about 9,800 lines of Python with their tests. It is a single-operator tool by construction: one optional bearer token (`DASH_CONSOLE_TOKEN`), no users, no roles.
- Its state is files: the job index and logs under `DASH_CONSOLE_JOBS`, the write-back audit as JSONL (`state/audit/github-writes.jsonl`), the lake as SQLite (`.dash-lake/fleet.sqlite`), a GitHub session held in the process. None of it has a schema migration, an admin view or a query surface.
- #583 already asks for the console to become account-based: organizations, teams, users, roles, per-tenant data boundaries and an audit trail, on "a framework or provider that supports organization and team administration".
- ADR 0005 adds state with nowhere to live: probe results per target, verification runs and their evidence, and one identity for the browser, the terminal, the VS Code extension and a mobile shell.
- ADR 0005 gives every frontend two modes. The private one signs in to a Django backend that must be the same thing on a laptop in Docker and on a cloud host. The fleet standard has no such contract: UPS-BE-50 fixes how a token travels (`Authorization: Bearer`), and UPS-BE-51 recommends Firebase Auth for a browser app that needs identity (one app, cv-pro, uses it) and "the framework's session auth" for server apps, so nothing says how a static frontend signs in to a fleet backend.
- Django is already the fleet's majority backend. djangoerp, fredgar-ai, zer0-CMS and law-ai run Django with Django REST Framework and Celery (zer0-CMS adds django-allauth and Wagtail, law-ai adds Channels); FastAPI backs gitorio, ragio-ai and the hub console. [specs/STACKS.md](../../specs/STACKS.md) already carries a Django profile (Django latest, DRF with drf-spectacular, pytest-django, Postgres through `DATABASE_URL`, `/api/v1/`, `/healthz`, `/readyz`, a committed OpenAPI document).
- The shared core `tools/dash up` starts already includes one Postgres and one Redis.

**Constraints that do not move.** `_data/projects.yml` is the project registry (constitution § 2), and the governed configuration beside it (`_data/fleet.yml`, the standards, the specs, the feature index) changes only through reviewed pull requests. The public site is a static snapshot that must build with no backend running. The § 11 write-back gates, the operation allowlist and "a credential goes in and never comes back" hold whatever framework serves the routes. Dependencies stay at latest with no lockfile.

**Why now.** Each of the portal's next phases (starting a stack, recording a validation, signing in from a second surface) would otherwise add another file format and another hand-built check to a backend that has no place for them. § 10.8 requires this record before that work starts.

### Prior art survey (§ 10.8)

- **Django** (ORM and migrations, auth with groups and permissions, sessions, the admin, management commands, ASGI). Fit: the four things the console lacks, integrated and already in four fleet repos. Cost: a second web framework in the hub until the port finishes, and a database the console did not need before.
- **Django REST Framework with drf-spectacular.** Fit: what the fleet's Django apps and the Django stack profile already use; generates the OpenAPI document UPS-BE-12 asks for.
- **django-ninja.** Fit: typed, async-first routes close in feel to the FastAPI code being ported. Not chosen as the default: it would give the fleet's Django repos two API conventions.
- **django-allauth.** Fit: GitHub sign-in and account management; zer0-CMS already runs it.
- **Channels.** Fit: WebSockets under Django (law-ai runs it). Needed only if the terminal bridge moves into Django; it can stay a small ASGI app beside it.
- **Stay on FastAPI and add the pieces** (SQLAlchemy with Alembic, fastapi-users, SQLAdmin or Starlette-Admin). Fit: no port. Cost: assembling and maintaining by hand what Django ships as one thing, on a stack only two fleet services share.
- **zer0-CMS as the hub's backend.** Fit: Django, already in the fleet. Not fit: it is a content product built on Wagtail with its own release cycle; a control plane inside it couples the two.
- **A hosted or packaged admin backend** (Supabase, PocketBase, Directus). Fit: accounts and tables quickly. Not fit: not Python, cannot run the allowlisted operations, and a new runtime to operate.

**Build versus adopt.** Adopt Django with DRF, drf-spectacular and django-allauth, on the stack profile the fleet already holds its Django repos to. Build only the hub's own apps on top.

## Decision

1. **Django is the hub's management backend, and the default for a new backend service in the fleet.** The hub's Django project follows the Django profile in specs/STACKS.md and the UPS-BE conventions, so the hub is held to the standard it publishes. gitorio and ragio-ai stay on FastAPI; nothing in the fleet is ported by this ADR except the hub console.

2. **Three layers, and the bottom one does not know Django exists.**

   | Layer | What it is | Who calls it |
   | --- | --- | --- |
   | Services | plain Python: `tools/fleetcore/` and the functions in `tools/console/core.py` (the operation allowlist, the job runner, the config editor, the launcher) | Django views, the static snapshot builder, the TUI, the MCP server, the tests |
   | Django project | apps for accounts, the registry read model, operations, the portal and the API; settings, migrations, management commands | the web shell, the terminal client, the VS Code extension, the mobile shell |
   | Admin | the Django admin over the operational records | the operator |

   The snapshot builder keeps calling the service layer directly, so the public site builds with no backend and no database.

3. **Git stays the source of truth for everything the constitution governs; the database holds what git never held.**

   | Data | Lives in | Django's part |
   | --- | --- | --- |
   | The registry, `fleet.yml`, standards, specs, features | YAML in git, changed by pull request | a read model rebuilt by a `sync_registry` management command; shown read-only in the admin; a row never overrides a file |
   | Jobs, run records, the write-back audit | files today | models with migrations; the admin lists and searches them |
   | Probe results and verification runs (ADR 0005) | nowhere today | models, written by the portal |
   | Accounts, organizations, teams, roles, sessions | nowhere today | Django auth, groups and permissions |
   | Credentials and tokens | the environment, `.env`, GitHub secrets | never stored in the database |

   A config edit from the console still writes the working tree and shows its diff, exactly as now. A drift check holds the read model equal to the files.

4. **The port is a strangler, one route family at a time, in one process on one port.** The Django project runs under ASGI beside the existing FastAPI app: a small ASGI dispatcher sends `/admin/`, `/accounts/` and `/api/v1/` to Django and everything else to FastAPI. A route family (the launcher, jobs, fleet views, config, GitHub, …) moves when its Django view passes the tests that hold the FastAPI route today, and the FastAPI route is deleted in the same PR, so nothing is ever implemented twice. Server-sent events use Django's async streaming responses. The terminal bridge's WebSocket stays a mounted ASGI app unless a later phase needs Channels. When the last family has moved, FastAPI leaves `requirements.txt`.

5. **The API is `/api/v1/`, in the UPS-BE shape, with a generated OpenAPI document.** That document is the contract every surface in ADR 0005 builds its client from. The web client moves to `/api/v1/` family by family; the unversioned `/api/` paths answer until the last one is ported.

6. **Identity, and the private-mode contract every Django backend in the fleet serves.** A frontend's private mode (ADR 0005, decision 6) signs in to a Django backend, and the contract is the same whether that backend is a container on this machine or a cloud host:

   | Part | Rule |
   | --- | --- |
   | Sign-in | OAuth 2.0 authorization code with PKCE from the browser (a public client, no secret in the frontend); the account behind it is a Django user, signed in with GitHub through django-allauth or with a local password |
   | Calls | `Authorization: Bearer` with a short-lived access token and a rotating refresh token, held in memory or session storage; never a cross-site cookie, because browsers refuse those to a framed or cross-origin page |
   | Who may call | a CORS allowlist of exactly the frontend's registry origins (its live address and its local ports), generated from the registry as the console's Content-Security-Policy is |
   | Which backend | the frontend picks among the backends the registry declares for it by name: `local` (the API service at its `_data/ports.yml` port, started by `tools/dash dev up`) or `cloud` (an https address); the address never comes from a link |
   | Local and cloud | one image and one settings module; the host, the database, the allowed origins and the redirect addresses come from the environment. https is required off loopback |
   | Public mode | needs none of this: a public build must not call the backend or ask for sign-in |

   The terminal dash, the MCP server, the VS Code extension and a mobile shell use the same bearer tokens. During the port, `DASH_CONSOLE_TOKEN` maps to one service account, so a single-operator console keeps working unchanged, and the console's existing "connect a console" page becomes the first client of this contract. Each allowlisted operation gets a Django permission; an operation that writes to GitHub or spends Claude budget needs a role as well as the confirm it already needs. The § 11 gates stay in the service layer: a permission can only narrow who may ask, never skip the dry run, the confirm or the audit record. The provider package (django-allauth's own, or django-oauth-toolkit) is chosen in the phase that builds this, against the contract above. This replaces UPS-BE-51's recommendation of Firebase Auth for new work, so that row changes in the same phase through the standard's own change process; cv-pro keeps Firebase until its owner moves it or records a deviation.

7. **Database.** Postgres from the shared core when it is running (its own database on the existing server), SQLite otherwise, so `tools/dash console` on a laptop without Docker still starts. Migrations are committed and run by the console at startup. A Postgres major upgrade follows docs/DOCKER.md like every other stateful service.

8. **Jobs keep their model.** The console still runs allowlisted subprocesses one at a time under the remote lock; only their records move into the database. Celery is not added to the hub unless a later phase shows a need the job runner cannot meet.

9. **A Django kit for the fleet comes last.** Once the hub runs on the profile, a `django` kit carries the settings baseline to the four Django repos through `tools/fanout.sh` (dry-run, PR-only): the private-mode contract of decision 6 (sign-in, bearer tokens, the registry-derived CORS allowlist), the health endpoints, the API envelope, and a `frame-ancestors` setting that admits the fleet shell, because Django's default `X-Frame-Options: DENY` is what will refuse ADR 0005's local frames. Its frontend half is one small sign-in client every frontend can load, whatever its framework.

### Phases

Nothing is implemented by this ADR. Each phase is its own pull request and becomes a sub-issue of the tracking epic, with scope, acceptance criteria and guardrails (constitution § 10.2).

| Phase | What it delivers |
| --- | --- |
| B1 | Django beside FastAPI: the project on the fleet's Django profile, the ASGI dispatcher, the admin, `/healthz` and `/readyz`; no route ported, every existing suite untouched |
| B2 | the registry read model (`sync_registry`, drift-checked) and the portal's records (probe results, verification runs); `/api/v1/apps` replaces `/api/apps` |
| B3 | accounts, organizations, teams and roles; GitHub sign-in; the private-mode sign-in contract (authorization code with PKCE, bearer tokens, the registry-derived CORS allowlist); a permission per operation; the UPS-BE-51 change |
| B4 | jobs, runs and the audit trail as models, with the admin over them |
| B5 | the remaining route families ported one per PR, the generated OpenAPI contract and client types, FastAPI retired |
| B6 | the `django` kit for the four Django repos, and one backend on a cloud host to prove the local and cloud halves are one contract |

## Consequences

**Positive**

- Accounts, roles, an admin and migrations arrive as one maintained framework instead of four hand-built pieces, which is what #583 and the portal both need.
- One backend framework for the hub and four fleet apps: one settings baseline, one API convention, one set of skills.
- Operational records become queryable and administrable; today a job, an audit entry and a probe are three file formats.
- The surfaces get one typed contract (OpenAPI) instead of a hand-kept `types.ts`.
- A frontend's private mode is written once against one sign-in contract and works against a laptop's Docker and a cloud host alike.
- The port cannot fork the behaviour: each family moves only against its existing tests, and the old route goes in the same change.

**Negative**

- Two web frameworks share one process until the last family is ported; the dispatcher is new code on the request path of a write-capable control plane.
- The console gains a database. That is state to back up and migrate, and a new way for a start to fail; SQLite as the fallback keeps the laptop case working but means two engines to test.
- A read model of the registries is a second copy. It is derived and drift-checked, but a stale copy is a failure mode that did not exist.
- The port is long: 68 routes and their suites. Half-done, the hub carries both stacks' dependencies and both mental models.
- Django's request handling is synchronous by default; the streaming and WebSocket paths need care that FastAPI gave for free.
- Each backend that serves private mode becomes an OAuth provider with tokens to rotate and origins to keep exact. One account across the whole fleet (a single provider the other backends rely on, the hub's Django or zer0-id) is not decided here and is the maintainer's call.
- The registry declares no cloud address for any fleet backend today, so the cloud half of the contract is designed here and unproven.

## Alternatives considered

- **Stay on FastAPI and add an ORM, auth and an admin.** No port, but the hub would maintain its own assembly of what Django ships, on the stack the fleet uses least, and #583 would be built by hand.
- **Rewrite the backend in one change.** A write-capable control plane with about a hundred test suites cannot be verified in one diff; the strangler keeps every gate green at every step.
- **Make the database the source of truth for the registry.** Breaks the § 2 invariant and takes configuration out of review; it would need a constitution amendment and is not proposed.
- **django-ninja instead of DRF.** Closer to the code being ported, but a second API convention across the fleet's Django repos.
- **Run Django as a separate service beside the console.** Two ports and two processes for one product, cross-origin calls between them, and a second thing for `dash up` to keep healthy.
- **Host the hub's management inside zer0-CMS.** Couples the control plane to a content product.
- **Cookie sessions for private mode.** Simplest inside one origin, but a deployed frontend and its backend are different sites, and browsers block or partition cross-site cookies, most of all inside the portal's frames.
- **A hosted identity provider** (Auth0, Clerk, Cognito). Works local and cloud, but puts every fleet sign-in behind a paid third party and leaves Django's own accounts and permissions unused.

## Supersedes / Superseded by

- Supersedes: none
- Superseded by: none
