#!/usr/bin/env bash
# ============================================================================
# tools/test-assist-browser.sh — the fleet assistant kit's DOM rules, proven
# in a real browser at $0 (bamr87/bamr87#938, UPS-AST-42).
#
# Runs templates/assistant/tests/browser.test.mjs: its own credential-free
# console on a free loopback port (never :4001; the live console is never
# touched), the kit's fixture in headless Chromium, and a session played
# through the console's real MCP layer. No Claude session, no model.
#
# It bootstraps what it needs and nothing else:
#   - a virtualenv (FLEET_ASSIST_VENV, default .venv-assist, gitignored) with
#     tools/console/requirements.txt + requirements-mcp.txt at latest; or the
#     Python in FLEET_ASSIST_PYTHON, used as it is;
#   - Playwright and Chromium the way the verify job installs them, into
#     verify/node_modules (the hub's one browser toolchain).
# FLEET_ASSIST_SKIP_INSTALL=1 skips both (offline, already installed);
# FLEET_ASSIST_WITH_DEPS=1 adds Chromium's system libraries (CI).
#
# Usage: tools/test-assist-browser.sh               run the test
#        tools/test-assist-browser.sh --self-test   prove it can fail: serve the
#            payload with `dialog[open]` dropped from MODAL; succeed only when
#            the native-dialog checks go red and the Bootstrap-style one stays green
# ============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEST="$ROOT/templates/assistant/tests/browser.test.mjs"
SKIP="${FLEET_ASSIST_SKIP_INSTALL:-0}"

self_test=0
if [[ "${1:-}" == "--self-test" ]]; then self_test=1; shift; fi

if [[ -z "${FLEET_ASSIST_PYTHON:-}" ]]; then
  VENV="${FLEET_ASSIST_VENV:-$ROOT/.venv-assist}"
  if [[ ! -x "$VENV/bin/python" ]]; then
    echo "assist-browser: creating virtualenv at $VENV"
    python3 -m venv "$VENV"
  fi
  if [[ "$SKIP" != "1" ]]; then
    "$VENV/bin/pip" install --quiet --upgrade pip
    "$VENV/bin/pip" install --quiet --upgrade -r "$ROOT/tools/console/requirements.txt" \
      -r "$ROOT/tools/console/requirements-mcp.txt"
  fi
  export FLEET_ASSIST_PYTHON="$VENV/bin/python"
fi

if [[ "$SKIP" != "1" ]]; then
  # Always-latest fleet policy: install, never ci; no lockfiles (fleet-verify.yml does the same).
  npm install --prefix "$ROOT/verify" --no-save --no-audit --no-fund --no-package-lock @playwright/test yaml
  if [[ "${FLEET_ASSIST_WITH_DEPS:-0}" == "1" ]]; then
    "$ROOT/verify/node_modules/.bin/playwright" install --with-deps chromium
  else
    "$ROOT/verify/node_modules/.bin/playwright" install chromium
  fi
fi

if [[ "$self_test" == "0" ]]; then
  exec node --test --test-reporter=spec "$TEST" "$@"
fi

out="$(mktemp)"
trap 'rm -f "$out"' EXIT
status=0
FLEET_ASSIST_BREAK=modal node --test --test-reporter=spec "$TEST" "$@" >"$out" 2>&1 || status=$?
cat "$out"
if [[ "$status" == "0" ]]; then
  echo "::error title=assist browser self-test::the browser test PASSED with dialog[open] dropped from MODAL — it cannot see the rule it claims to hold"
  exit 1
fi
if ! grep -q '✖ a native modal dialog' "$out"; then
  echo "::error title=assist browser self-test::the test failed with the dialog rule broken, but not on the native dialog — it failed for another reason"
  exit 1
fi
if grep -q '✖ a Bootstrap-style modal' "$out"; then
  echo "::error title=assist browser self-test::the Bootstrap-style modal check failed too, though only dialog[open] was dropped — the failure is not the rule's"
  exit 1
fi
echo "assist-browser: self-test OK — with dialog[open] dropped from MODAL the native-dialog checks go red and the Bootstrap-style one stays green"
