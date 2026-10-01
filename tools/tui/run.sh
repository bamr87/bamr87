#!/usr/bin/env bash
# tools/tui/run.sh — terminal twin of the Jekyll command center.
# Bootstraps .venv-tui (gitignored) at latest and execs the Textual app.
#
#   DASH_DOCKER_HOST  comma-separated Docker endpoints to poll; `local` is this
#                     machine's current context (where `tools/dash up` runs the
#                     shared core), anything else goes to `docker -H`.
#                     Default: local,ssh://forge. Empty string: no Docker.
#   TUI_VENV          virtualenv path (default .venv-tui at the repo root)
#   TUI_SKIP_INSTALL  1 to skip the always-latest upgrade (faster start)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
VENV="${TUI_VENV:-$ROOT/.venv-tui}"

if [[ ! -x "$VENV/bin/python" ]]; then
  echo "tui: creating virtualenv at $VENV"
  python3 -m venv "$VENV"
fi
# Always-latest, like the console and the fleet's CI. (Offline is fine: pip
# keeps the installed versions and exits 0 when the index is unreachable.)
if [[ "${TUI_SKIP_INSTALL:-0}" != "1" ]]; then
  "$VENV/bin/pip" install --quiet --upgrade pip
  "$VENV/bin/pip" install --quiet --upgrade -r "$HERE/requirements.txt"
fi

export DASH_DOCKER_HOST="${DASH_DOCKER_HOST-local,ssh://forge}"
cd "$ROOT"
exec "$VENV/bin/python" "$HERE/app.py"
