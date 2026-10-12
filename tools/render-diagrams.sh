#!/usr/bin/env bash
# render-diagrams.sh — validate and deliver every diagram in diagrams/ with the
# vendored archify skill (.claude/skills/archify). Sources are typed JSON IR
# (diagrams/<name>.<type>.json); outputs are self-contained HTML beside them,
# copied into the public site by tools/console/build-pages.sh (and served by the
# console at /diagrams/<name>.<type>.html), embedded on the Harness health page.
#
# Usage: tools/render-diagrams.sh [--check]    # --check validates only, writes nothing
# Exit non-zero if any diagram fails showcase validation or delivery.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARCHIFY="$ROOT/.claude/skills/archify/bin/archify.mjs"
DIAGRAMS="$ROOT/diagrams"
MODE="${1:-deliver}"

if ! command -v node >/dev/null 2>&1; then
  echo "render-diagrams: node is required (archify is a Node.js renderer)" >&2
  exit 2
fi

status=0
for src in "$DIAGRAMS"/*.json; do
  name="$(basename "$src" .json)"
  type="${name##*.}"
  out="$DIAGRAMS/$name.html"
  case "$MODE" in
    --check)
      if node "$ARCHIFY" validate "$type" "$src" --quality showcase --json >/dev/null; then
        echo "ok    $name"
      else
        echo "FAIL  $name (validate)"; status=1
      fi
      ;;
    *)
      if node "$ARCHIFY" deliver "$type" "$src" "$out" --quality showcase --json >/dev/null; then
        echo "ok    $name -> diagrams/$name.html"
      else
        echo "FAIL  $name (deliver)"; status=1
      fi
      ;;
  esac
done
exit "$status"
