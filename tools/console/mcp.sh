#!/usr/bin/env bash
# ============================================================================
# tools/console/mcp.sh — start the Harness Console MCP server (mcp_layer/)
#
# Bootstraps a private virtualenv (HARNESS_MCP_VENV, default .venv-mcp at the
# repo root — gitignored), installs requirements-mcp.txt at LATEST when the
# venv is new or the requirements changed, and execs the server. stdout is the
# MCP stdio channel, so everything this script says goes to stderr.
#
#   (no args)           stdio transport — what Claude Code / Cursor launch
#   --http [--port N]   streamable HTTP on 127.0.0.1:4002/mcp, bearer auth
#   --list-tools        print the tool catalog and exit
#
#   DASH_CONSOLE_URL / DASH_CONSOLE_TOKEN   the console it wraps (token falls back to .env)
#   HARNESS_MCP_TOKEN                       bearer for --http (falls back to DASH_CONSOLE_TOKEN)
#   HARNESS_MCP_ALLOW_WRITES=1              register the destructive write tools (off by default)
#
# Usage: tools/console/mcp.sh [--http]     (or: tools/dash mcp [--http])
# ============================================================================
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
VENV="${HARNESS_MCP_VENV:-$ROOT/.venv-mcp}"
REQ="$HERE/requirements-mcp.txt"
# A PYTHONPATH from the shell (e.g. the dash's site-packages) would shadow the venv's packages.
unset PYTHONPATH

if [[ ! -x "$VENV/bin/python" ]]; then
  echo "harness-mcp: creating virtualenv at $VENV" >&2
  python3 -m venv "$VENV" >&2
fi
stamp="$VENV/.requirements-mcp.stamp"
if [[ "${HARNESS_MCP_SKIP_INSTALL:-0}" != "1" ]] && { [[ ! -f "$stamp" ]] || [[ "$REQ" -nt "$stamp" ]]; }; then
  "$VENV/bin/pip" install --quiet --upgrade -r "$REQ" >&2
  touch "$stamp"
fi

cd "$HERE"
exec "$VENV/bin/python" -m mcp_layer.server "$@"
