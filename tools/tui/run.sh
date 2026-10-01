#!/usr/bin/env bash
# tools/tui/run.sh — terminal twin of the Jekyll command center.
# Bootstraps .venv-tui (gitignored) at latest and execs the Textual app.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
VENV="${TUI_VENV:-$ROOT/.venv-tui}"

if [[ ! -x "$VENV/bin/python" ]]; then
  echo "tui: creating virtualenv at $VENV"
  python3 -m venv "$VENV"
fi
if [[ "${TUI_SKIP_INSTALL:-0}" != "1" ]]; then
  "$VENV/bin/pip" install --quiet --upgrade pip
  "$VENV/bin/pip" install --quiet --upgrade -r "$HERE/requirements.txt"
fi

export DASH_DOCKER_HOST="${DASH_DOCKER_HOST:-ssh://forge}"
cd "$ROOT"
exec "$VENV/bin/python" "$HERE/app.py"
