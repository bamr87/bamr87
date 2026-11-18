#!/usr/bin/env bash
# ============================================================================
# tools/console/web-deps.sh — the page's dependencies, at latest. Sourced by
# run.sh and build-pages.sh; defines web_deps and runs nothing on its own.
#
# The page has no lockfile and `*` ranges (web/.npmrc, docs/DEPENDENCIES.md),
# so a fresh `npm install` is the newest release of everything, which is what
# CI builds with. An install that already exists is another matter: `npm
# install` leaves it alone as long as it satisfies the ranges, and `*` is
# satisfied by anything. A long-lived checkout, and the compose service's
# node_modules volume, stayed on whatever was current the day they were first
# installed. On 2026-11-17 the console's volume held Mantine 9.7.2 while CI
# built with 9.8.1: the desktop's window menu, which 9.8 shows, stayed hidden
# locally and its scenario failed on a machine where nothing had changed.
#
#   web_deps <web dir>     installs when there is no node_modules (or
#                          package.json is newer), otherwise upgrades in place.
#                          Sets WEB_DEPS_CHANGED=1 when anything moved, so the
#                          caller knows to rebuild.
#   CONSOLE_SKIP_INSTALL=1 never reaches the registry for an install that
#                          exists (offline, or a review copy that must not move)
# ============================================================================

# WEB_DEPS_CHANGED is read by the script that sources this file.
# shellcheck disable=SC2034
web_deps() {
  local web="$1" lock before after
  lock="$web/node_modules/.package-lock.json"
  WEB_DEPS_CHANGED=0
  if [[ ! -d "$web/node_modules" || "$web/package.json" -nt "$web/node_modules" ]]; then
    (cd "$web" && npm install --no-package-lock --no-audit --no-fund --loglevel=error) && touch "$web/node_modules"
    WEB_DEPS_CHANGED=1
    return 0
  fi
  [[ "${CONSOLE_SKIP_INSTALL:-0}" == "1" ]] && return 0
  before="$(cksum < "$lock" 2>/dev/null || true)"
  if (cd "$web" && npm update --no-package-lock --no-audit --no-fund --loglevel=error); then
    after="$(cksum < "$lock" 2>/dev/null || true)"
    if [[ "$before" != "$after" ]]; then
      WEB_DEPS_CHANGED=1
      echo "console: the page's dependencies moved to their latest releases"
    fi
  else
    echo "console: could not check the page's dependencies for newer releases (offline?); building with the ones installed" >&2
  fi
  return 0
}
