#!/usr/bin/env bash
# ============================================================================
# tools/console/run.sh — start the Harness Console (FastAPI + Django, uvicorn)
#
# Bootstraps a private virtualenv (CONSOLE_VENV, default .venv-console at the
# repo root — gitignored; the compose service backs it with a named volume),
# installs tools/console/requirements.txt at LATEST (fleet dependency policy),
# applies the Django backend's migrations, and execs uvicorn on dispatch.py:
# /admin/, /accounts/ and /api/v1/ go to Django (backend/), the rest to the
# FastAPI app (ADR 0006).
#
#   CONSOLE_HOST   bind address (default 127.0.0.1; compose sets 0.0.0.0 and
#                  publishes the port on loopback only)
#   CONSOLE_PORT   default 4001
#   CONSOLE_RELOAD 1 to auto-reload on edits (development)
#   DASH_CONSOLE_TOKEN  optional bearer token required on /api/* when set,
#                  and on every Django path but /api/v1/{healthz,readyz,version}
#   DASH_CONSOLE_ALLOWED_HOSTS  extra Host values to answer to (comma-separated);
#                  loopback names only by default — the DNS-rebinding guard
#   CONSOLE_UDS    also listen on this Unix socket (serve.py) — how the `tui`
#                  compose service reaches the same runtime; ignored with RELOAD
#   CONSOLE_SKIP_WEB  1 to skip (re)building the page (web/ → web/dist)
#   DASH_CONSOLE_STATE  the Django backend's state directory (default
#                  .fleet/console: the SQLite database and, on loopback, the
#                  generated secret key)
#   DATABASE_URL   the backend's database instead (postgres://…); unset → SQLite
#   DJANGO_SECRET_KEY  required when DASH_CONSOLE_ALLOWED_HOSTS names a
#                  non-loopback host; generated once otherwise
#
# Usage: tools/console/run.sh            (or: tools/dash console)
# ============================================================================
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
VENV="${CONSOLE_VENV:-$ROOT/.venv-console}"
HOST="${CONSOLE_HOST:-127.0.0.1}"
PORT="${CONSOLE_PORT:-4001}"
# A PYTHONPATH from the shell (e.g. the dash's site-packages) would shadow the venv's packages.
unset PYTHONPATH

if [[ ! -x "$VENV/bin/python" ]]; then
  echo "console: creating virtualenv at $VENV"
  python3 -m venv "$VENV"
fi
# Always-latest: every start resolves the newest published versions, exactly
# like the fleet's CI installs. Skip with CONSOLE_SKIP_INSTALL=1 when offline.
if [[ "${CONSOLE_SKIP_INSTALL:-0}" != "1" ]]; then
  "$VENV/bin/pip" install --quiet --upgrade pip
  "$VENV/bin/pip" install --quiet --upgrade -r "$HERE/requirements.txt"
fi

# The page (web/, React + Mantine) is built into web/dist, which is gitignored.
# Rebuild whenever a source file is newer than the last build — always-latest
# like the venv (no lockfile: web/.npmrc sets package-lock=false). Without npm
# the API still serves, and / explains how to build the page.
WEB="$HERE/web"
if [[ "${CONSOLE_SKIP_WEB:-0}" != "1" ]]; then
  if command -v npm >/dev/null 2>&1; then
    stamp="$WEB/dist/index.html"
    if [[ ! -f "$stamp" ]] || [[ -n "$(find "$WEB/src" "$WEB/index.html" "$WEB/package.json" "$WEB/vite.config.ts" -newer "$stamp" -print -quit 2>/dev/null)" ]]; then
      echo "console: building the page (web/ → web/dist)"
      if [[ ! -d "$WEB/node_modules" || "$WEB/package.json" -nt "$WEB/node_modules" ]]; then
        (cd "$WEB" && npm install --no-package-lock --loglevel=error) && touch "$WEB/node_modules"
      fi
      # A build can fail on a node_modules that is present but broken — e.g.
      # TypeScript's or Vite's native binary for THIS platform missing after an
      # always-latest upgrade — so reinstall once and retry before giving up.
      if ! (cd "$WEB" && npm run --silent build); then
        echo "console: page build failed — reinstalling the page's dependencies and retrying once" >&2
        (cd "$WEB" && npm install --no-package-lock --loglevel=error) && touch "$WEB/node_modules"
        if ! (cd "$WEB" && npm run --silent build); then
          if [[ -f "$stamp" ]]; then
            echo "console: page build FAILED — serving the PREVIOUS build from $(date -r "$stamp" '+%Y-%m-%d %H:%M')" >&2
          else
            echo "console: page build FAILED — serving the API only" >&2
          fi
        fi
      fi
    fi
  elif [[ ! -f "$WEB/dist/index.html" ]]; then
    echo "console: npm not found — the API will serve, but the page is unbuilt (see web/README.md)" >&2
  fi
fi

RELOAD=()
[[ "${CONSOLE_RELOAD:-0}" == "1" ]] && RELOAD=(--reload --reload-dir "$HERE")

echo "console: http://${HOST}:${PORT}/  (repo: $ROOT)"
cd "$HERE"
# The Django backend's migrations, committed and applied at every start (ADR
# 0006 decision 7). A failure is reported and the console starts anyway: no
# FastAPI route needs the database, and /api/v1/readyz says what is wrong.
if ! "$VENV/bin/python" backend/manage.py migrate --noinput; then
  echo "console: Django migrate FAILED — starting anyway; /api/v1/readyz reports the database" >&2
fi
if [[ -n "${CONSOLE_UDS:-}" && ${#RELOAD[@]} -eq 0 ]]; then
  export CONSOLE_HOST="$HOST" CONSOLE_PORT="$PORT"
  exec "$VENV/bin/python" serve.py
fi
exec "$VENV/bin/python" -m uvicorn dispatch:app --host "$HOST" --port "$PORT" ${RELOAD[@]+"${RELOAD[@]}"}
