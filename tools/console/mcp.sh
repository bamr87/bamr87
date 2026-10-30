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
#   --tunnel [--port N] --http plus a TEMPORARY cloudflared quick tunnel
#                       (https://<random>.trycloudflare.com/mcp), its hostname
#                       passed to --allow-host; Ctrl-C stops both. Uses a native
#                       `cloudflared`, else the cloudflare/cloudflared image.
#   --fleet-compat      also the legacy `fleet` console_run/console_cancel (.mcp.json `fleet`)
#   --list-tools        print the tool catalog and exit
#
#   DASH_CONSOLE_URL / DASH_CONSOLE_TOKEN   the console it wraps (token falls back to .env)
#   HARNESS_MCP_TOKEN                       bearer for --http (env or .env; never the console token)
#   HARNESS_MCP_DOTENV                      the .env to parse (default <repo>/.env)
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
if [[ "${1:-}" != "--tunnel" ]]; then
  exec "$VENV/bin/python" -m mcp_layer.server "$@"
fi

# --- --tunnel: a short-lived public URL for a remote agent. Never left running.
shift
port="${HARNESS_MCP_PORT:-4002}"
args=("$@")
for ((i = 0; i < ${#args[@]}; i++)); do [[ "${args[$i]}" == "--port" ]] && port="${args[$((i + 1))]}"; done
log="$(mktemp -t harness-mcp-tunnel.XXXXXX)"
if command -v cloudflared >/dev/null 2>&1; then
  cloudflared tunnel --no-autoupdate --url "http://127.0.0.1:${port}" >"$log" 2>&1 &
  tunnel_pid=$!
  stop_tunnel() { kill "$tunnel_pid" 2>/dev/null || true; }
elif command -v docker >/dev/null 2>&1; then
  name="harness-mcp-tunnel-$$"
  docker run --rm --name "$name" --add-host host.docker.internal:host-gateway cloudflare/cloudflared:latest \
    tunnel --no-autoupdate --url "http://host.docker.internal:${port}" >"$log" 2>&1 &
  tunnel_pid=$!
  stop_tunnel() { docker rm -f "$name" >/dev/null 2>&1 || true; kill "$tunnel_pid" 2>/dev/null || true; }
else
  echo "harness-mcp: --tunnel needs cloudflared (brew install cloudflared) or docker" >&2
  exit 2
fi
trap 'stop_tunnel; rm -f "$log"' EXIT INT TERM
host=""
for _ in $(seq 1 60); do
  host="$(grep -Eo '[a-z0-9-]+\.trycloudflare\.com' "$log" | head -1 || true)"
  [[ -n "$host" ]] && break
  sleep 1
done
if [[ -z "$host" ]]; then
  echo "harness-mcp: the tunnel did not come up; its log:" >&2
  cat "$log" >&2
  exit 1
fi
echo "harness-mcp: TEMPORARY public endpoint https://${host}/mcp (bearer HARNESS_MCP_TOKEN required; Ctrl-C ends it)" >&2
"$VENV/bin/python" -m mcp_layer.server --http "$@" --allow-host "$host"
