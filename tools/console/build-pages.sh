#!/usr/bin/env bash
# ============================================================================
# tools/console/build-pages.sh — build the PUBLIC site: the Harness Console's
# page, static, for GitHub Pages (https://bamr87.github.io/bamr87/).
#
#   1. the React app (web/) with the Pages base path and VITE_STATIC=1, so it
#      reads files instead of a console's API — into web/dist-pages/
#   2. snapshot.py: every document the page reads, rendered by the console's
#      own Python, plus a page per route, 404.html, sitemap, feed and theme
#   3. (build-dash.yml then adds the machine API: dash-gen machine-api)
#
#   CONSOLE_BASE   path the site is served under   (default /bamr87/; `/` for
#                  verify/ and local previews served at the root)
#   SITE_URL       absolute URL of the site root    (default https://bamr87.github.io/bamr87)
#   OUT            output directory                 (default tools/console/web/dist-pages)
#   PYTHON         interpreter with PyYAML          (default python3)
#
# Preview:  CONSOLE_BASE=/ tools/console/build-pages.sh && \
#           python3 -m http.server 4000 -d tools/console/web/dist-pages
# ============================================================================
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WEB="$HERE/web"
BASE="${CONSOLE_BASE:-/bamr87/}"
SITE_URL="${SITE_URL:-https://bamr87.github.io/bamr87}"
OUT="${OUT:-$WEB/dist-pages}"
PY="${PYTHON:-python3}"

# Vite runs from web/, so a relative OUT is made absolute against the caller's cwd.
mkdir -p "$OUT" && OUT="$(cd "$OUT" && pwd)"

case "$BASE" in /*/ | /) ;; *) echo "build-pages: CONSOLE_BASE must start and end with / (got '$BASE')" >&2; exit 2 ;; esac

# Always-latest, no lockfile (web/.npmrc), like the console's own run.sh.
if [[ ! -d "$WEB/node_modules" || "$WEB/package.json" -nt "$WEB/node_modules" ]]; then
  (cd "$WEB" && npm install --no-package-lock --no-audit --no-fund --loglevel=error) && touch "$WEB/node_modules"
fi

echo "build-pages: the page (base $BASE) → $OUT"
(cd "$WEB" && npx tsc -b && CONSOLE_BASE="$BASE" CONSOLE_OUT="$OUT" VITE_STATIC=1 npx vite build --logLevel warn)

# The archify diagrams the Health page embeds (diagrams/*.html, tools/render-diagrams.sh).
mkdir -p "$OUT/diagrams" && cp "$HERE/../../diagrams/"*.html "$OUT/diagrams/"

echo "build-pages: the snapshot"
"$PY" "$HERE/snapshot.py" --out "$OUT" --base "$BASE" --site-url "$SITE_URL"
