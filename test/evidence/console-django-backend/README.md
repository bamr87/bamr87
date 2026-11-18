# The Django backend beside the console — evidence

> **Issue:** #700 (phase B1 of epic #699, [ADR 0006](../../../docs/adr/0006-django-management-backend.md)) · **Result:** **PASS** (interactive pass) · **Verified:** 2026-11-16 against a console from this branch on `127.0.0.1:4031`

The console now serves the Django admin and the `/api/v1/` health endpoints beside the FastAPI app, in one process on one port. There is no scenario: the public build has no backend, and `verify/` scenarios run against that build.

**How it was run.** `CONSOLE_PORT=4031 CONSOLE_SKIP_WEB=1 CONSOLE_AUTO_HEALTH=0 tools/dash console` from the worktree, with a scratch virtualenv (`CONSOLE_VENV`, the requirements at latest: Django 6.1.3, FastAPI 0.163.1, Starlette 1.10.0, Python 3.14), its own `DASH_CONSOLE_STATE` and `DASH_CONSOLE_JOBS` in a temporary directory, and a throwaway superuser made with `manage.py createsuperuser --noinput`. `run.sh` applied the migrations before uvicorn started. The page was not built (`CONSOLE_SKIP_WEB=1`), so `/` answered the console's own "not built yet" page; that is the FastAPI half, unchanged. The running console on the maintainer's machine was not touched (§ 10.5).

| Image | What it shows |
| --- | --- |
| `admin-login-desktop.png` | `/admin/login/` at 1280 wide: the admin's stylesheets and scripts load under the console's Content-Security-Policy |
| `admin-index-desktop.png` | `/admin/` after signing in: the CSRF check passed with Django's `same-origin` Referrer-Policy |
| `admin-users-mobile.png` | `/admin/auth/user/` at 390 wide |

Measured in that pass, not pictured:

- **No CSP violation.** Chromium's console was empty on the login page, the admin index, the user list and the user change form (which loads the admin's jQuery, actions and widgets). The one error on every page was `/favicon.ico` answering 503, the unbuilt page's fallback.
- **curl.** `/api/v1/healthz` → `{"status": "ok"}`; `/api/v1/readyz` → `{"status": "ok", "checks": {"db": "ok", "migrations": "ok"}}`; `/api/v1/version` → name, `2.1.0`, the commit, `built_at` null; `HEAD /admin/login/` → 200 with the console's CSP, `X-Frame-Options: SAMEORIGIN` and `Referrer-Policy: same-origin`; `Host: evil.example` on `/admin/` → 421 with the FastAPI guard's own message; `/api/health` → 200; `/admin/static/admin/css/base.css` → 200.

## Not covered

Chromium only. The token guard on the Django paths (401 without the bearer, the health endpoints exempt) is held by `tools/console/test_backend.py`, not by this pass. A Postgres `DATABASE_URL` and the compose service were not started: the compose console keeps SQLite in its `console-run` volume, and moving it to the shared Postgres is a later decision.
