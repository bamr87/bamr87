---
schema: '0.1'
coverage: listed
---

# SCHEMA — tools/console/backend

> The Harness Console's Django project (ADR 0006): what `../dispatch.py` sends `/admin/`, `/accounts/` and `/api/v1/` to, beside the FastAPI app, in one process on one port.

## Conventions

- Phase B1 ports no route: the admin over Django's own users and groups, and the health endpoints. Each later phase moves one route family here against the tests that hold the FastAPI route today, and deletes that route in the same change (ADR 0006 decision 4).
- Every setting comes from the environment (`settings.py`'s docstring names them); DEBUG is always off; a message never carries a secret or a database URL.
- Git stays the source of truth for the registries: a model here holds operational records, accounts or a derived read model, never a copy that overrides a file.
- Nothing outside the console's runtime imports this package: the public snapshot, the terminal dash and the MCP server call the service layer (`../core.py`, `tools/fleetcore/`) and need neither Django nor a database.

## Structure

| entry | kind | purpose | rules |
| --- | --- | --- | --- |
| `__init__.py` | file | Package marker (`DJANGO_SETTINGS_MODULE=backend.settings`) | required |
| `settings.py` | file | Settings from the environment: `DJANGO_SECRET_KEY` (required off loopback, else generated once into the state directory, mode 600), `DATABASE_URL` (SQLite in `DASH_CONSOLE_STATE`, default `.fleet/console/`, when unset), `ALLOWED_HOSTS` equal to the console's DNS-rebinding allowlist, the console's own cookie names, `STATIC_URL` `/admin/static/` | required |
| `urls.py` | file | `/admin/` and `/api/v1/{healthz,readyz,version}`; `/accounts/` reserved for B3's sign-in | required |
| `views.py` | file | The health endpoints (UPS-BE-10, UPS-BE-11): liveness, readiness (database and migrations), version | required |
| `manage.py` | file | Django's command line (`migrate`, `createsuperuser`, `check`), runnable from any directory with the console's interpreter; `../run.sh` runs `migrate --noinput` before every start | required |

## Placement

- A new Django app (accounts, the registry read model, operations) → its own package here with its `models.py`, committed `migrations/`, an `INSTALLED_APPS` entry and a row in this table.
- A new `/api/v1/` route → a view here and a pattern in `urls.py`, with its test in `../test_backend.py`; it is token-guarded by the dispatcher unless it is added to `HEALTH` there, which only a health endpoint may be.
- A new top-level prefix for Django → `PREFIXES` in `../dispatch.py`, with a test that the FastAPI page never answered that path.

## Forbidden

- No secret in a settings default, a log line, a response or an error message; no `DEBUG = True`.
- No route answered here and by `../app.py` at once: a family moves, then the old route goes.
- No credential or token stored in the database in clear.
