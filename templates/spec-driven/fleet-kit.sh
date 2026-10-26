#!/usr/bin/env bash
# kit: spec-driven — resolve the hub's spec-driven kit for a consumer repo.
#
# The ONE file a by-reference consumer vendors (lands at tools/fleet-kit.sh).
# It prints the directory of bamr87/bamr87 templates/spec-driven/ so a
# Makefile, a CI step or a skill can run the kit's tools without copying them:
#
#     KIT="$(tools/fleet-kit.sh)"
#     python3 "$KIT/tools/spec_validator.py" --root . --strict
#     python3 "$KIT/tools/backlog_lint.py" --root .
#
# Resolution order (first hit wins):
#   1. $FLEET_KIT_DIR                       an explicit kit directory
#   2. $FLEET_HUB/templates/spec-driven     an explicit hub checkout
#   3. a hub checkout this repo is a submodule of (../../templates/spec-driven
#      from the repo root, walking up to three levels)
#   4. a cached sparse clone of the hub at .fleet/hub (gitignore it) on
#      $FLEET_REF (default: main, the fleet's always-latest policy); --update
#      refreshes it, otherwise the cache is reused as is.
#
# Fleet copy: bamr87/bamr87 templates/spec-driven/fleet-kit.sh (keep it byte-identical).
set -euo pipefail

update=0
for arg in "$@"; do
  case "$arg" in
    --update) update=1 ;;
    -h|--help) sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "fleet-kit.sh: unknown argument $arg" >&2; exit 2 ;;
  esac
done

root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
hub_repo="${FLEET_HUB_REPO:-https://github.com/bamr87/bamr87.git}"
ref="${FLEET_REF:-main}"
cache="${FLEET_CACHE:-$root/.fleet/hub}"
kit_rel="templates/spec-driven"

is_kit() { [ -f "$1/tools/spec_validator.py" ] && [ -f "$1/tools/backlog_lint.py" ]; }

if [ -n "${FLEET_KIT_DIR:-}" ]; then
  is_kit "$FLEET_KIT_DIR" || { echo "fleet-kit.sh: FLEET_KIT_DIR=$FLEET_KIT_DIR is not a spec-driven kit" >&2; exit 1; }
  echo "$FLEET_KIT_DIR"; exit 0
fi
if [ -n "${FLEET_HUB:-}" ]; then
  is_kit "$FLEET_HUB/$kit_rel" || { echo "fleet-kit.sh: FLEET_HUB=$FLEET_HUB has no $kit_rel" >&2; exit 1; }
  echo "$FLEET_HUB/$kit_rel"; exit 0
fi

d="$root"
for _ in 1 2 3; do
  d="$(dirname "$d")"
  if is_kit "$d/$kit_rel"; then echo "$d/$kit_rel"; exit 0; fi
done

if [ -d "$cache/.git" ] && [ "$update" -eq 1 ]; then
  git -C "$cache" fetch -q --depth 1 origin "$ref" \
    && git -C "$cache" reset -q --hard FETCH_HEAD \
    || echo "fleet-kit.sh: refresh of $cache failed; using the cached copy" >&2
elif [ ! -d "$cache/.git" ]; then
  mkdir -p "$(dirname "$cache")"
  rm -rf "$cache"
  git clone -q --depth 1 --filter=blob:none --sparse --branch "$ref" "$hub_repo" "$cache" >&2
  # No -q: older gits (the backend image) reject it; output goes to stderr anyway.
  git -C "$cache" sparse-checkout set "$kit_rel" >&2
fi
is_kit "$cache/$kit_rel" || { echo "fleet-kit.sh: $cache/$kit_rel is not a spec-driven kit (ref $ref)" >&2; exit 1; }
echo "$cache/$kit_rel"
