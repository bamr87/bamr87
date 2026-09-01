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

RELOAD=()
[[ "${CONSOLE_RELOAD:-0}" == "1" ]] && RELOAD=(--reload --reload-dir "$HERE")

echo "console: http://${HOST}:${PORT}/  (repo: $ROOT)"
cd "$HERE"
exec "$VENV/bin/python" -m uvicorn app:app --host "$HOST" --port "$PORT" ${RELOAD[@]+"${RELOAD[@]}"}
