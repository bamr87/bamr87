#!/usr/bin/env bash
# ============================================================================
# tools/console/run.sh — start the Harness Console (FastAPI + uvicorn)
#
# Bootstraps a private virtualenv (CONSOLE_VENV, default .venv-console at the
# repo root — gitignored; the compose service backs it with a named volume),
# installs tools/console/requirements.txt at LATEST (fleet dependency policy),
# and execs uvicorn.
#
#   CONSOLE_HOST   bind address (default 127.0.0.1; compose sets 0.0.0.0 and
#                  publishes the port on loopback only)
#   CONSOLE_PORT   default 4001
#   CONSOLE_RELOAD 1 to auto-reload on edits (development)
#   DASH_CONSOLE_TOKEN  optional bearer token required on /api/* when set
#   DASH_CONSOLE_ALLOWED_HOSTS  extra Host values to answer to (comma-separated);
#                  loopback names only by default — the DNS-rebinding guard
#   CONSOLE_UDS    also listen on this Unix socket (serve.py) — how the `tui`
#                  compose service reaches the same runtime; ignored with RELOAD
#   CONSOLE_SKIP_WEB  1 to skip (re)building the page (web/ → web/dist)
#
# Usage: tools/console/run.sh            (or: tools/dash console)
# ============================================================================
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
VENV="${CONSOLE_VENV:-$ROOT/.venv-console}"
HOST="${CONSOLE_HOST:-127.0.0.1}"
PORT="${CONSOLE_PORT:-4001}"

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
      (cd "$WEB" && npm run --silent build) || echo "console: page build FAILED — serving the API only" >&2
    fi
  elif [[ ! -f "$WEB/dist/index.html" ]]; then
    echo "console: npm not found — the API will serve, but the page is unbuilt (see web/README.md)" >&2
  fi
fi

RELOAD=()
[[ "${CONSOLE_RELOAD:-0}" == "1" ]] && RELOAD=(--reload --reload-dir "$HERE")

echo "console: http://${HOST}:${PORT}/  (repo: $ROOT)"
cd "$HERE"
if [[ -n "${CONSOLE_UDS:-}" && ${#RELOAD[@]} -eq 0 ]]; then
  export CONSOLE_HOST="$HOST" CONSOLE_PORT="$PORT"
  exec "$VENV/bin/python" serve.py
fi
exec "$VENV/bin/python" -m uvicorn app:app --host "$HOST" --port "$PORT" ${RELOAD[@]+"${RELOAD[@]}"}
