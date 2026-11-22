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
#   CONSOLE_SITE   one of the other sites _data/profile.yml declares under
#                  `sites:`. It sets that site's title, mark and front door,
#                  lets the page frame the launcher's own origins, and makes
#                  that site's address and path the defaults for SITE_URL and
#                  CONSOLE_BASE. Unset, the build is the site above, unchanged
#                  (docs/CONSOLE-PAGES.md "Site builds").
#   OUT            output directory                 (default tools/console/web/dist-pages)
#   PYTHON         interpreter with PyYAML          (default python3)
#
# Preview:  CONSOLE_BASE=/ tools/console/build-pages.sh && \
#           python3 -m http.server 4000 -d tools/console/web/dist-pages
# ============================================================================
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WEB="$HERE/web"
PY="${PYTHON:-python3}"
SITE="${CONSOLE_SITE:-}"

# A named site: its settings come from _data/profile.yml, checked by
# site_docs.py, which also refuses a site that file does not declare.
SITE_FRONT_DOOR="" SITE_MARK="" SITE_DEFAULT_URL="" SITE_DEFAULT_BASE="" FRAME_SRC=""
if [[ -n "$SITE" ]]; then
  site_env="$("$PY" "$HERE/site_docs.py" build-env "$SITE")" || exit 2
  eval "$site_env"
  # The origins a framed app is served from: the launcher's, the list the
  # console's own policy names (ADR 0005, decision 4). Never a wildcard.
  FRAME_SRC="$(cd "$HERE/.." && "$PY" -c 'from pathlib import Path; from fleetcore import apps; print(" ".join(apps.target_origins(Path.cwd().parent)))')"
fi

BASE="${CONSOLE_BASE:-${SITE_DEFAULT_BASE:-/bamr87/}}"
SITE_URL="${SITE_URL:-${SITE_DEFAULT_URL:-https://bamr87.github.io/bamr87}}"
OUT="${OUT:-$WEB/dist-pages}"

# Vite runs from web/, so a relative OUT is made absolute against the caller's cwd.
mkdir -p "$OUT" && OUT="$(cd "$OUT" && pwd)"

case "$BASE" in /*/ | /) ;; *) echo "build-pages: CONSOLE_BASE must start and end with / (got '$BASE')" >&2; exit 2 ;; esac

# Always-latest, no lockfile (web/.npmrc), like the console's own run.sh: a
# missing install is installed, an existing one is upgraded in place.
# shellcheck source=tools/console/web-deps.sh
source "$HERE/web-deps.sh"
web_deps "$WEB"

echo "build-pages: the page${SITE:+ for $SITE} (base $BASE) → $OUT"
(cd "$WEB" && npx tsc -b && CONSOLE_BASE="$BASE" CONSOLE_OUT="$OUT" VITE_STATIC=1 \
  VITE_FRONT_DOOR="$SITE_FRONT_DOOR" VITE_SITE_MARK="$SITE_MARK" CONSOLE_FRAME_SRC="$FRAME_SRC" \
  npx vite build --logLevel warn)

# The archify diagrams the Health page embeds (diagrams/*.html, tools/render-diagrams.sh).
mkdir -p "$OUT/diagrams" && cp "$HERE/../../diagrams/"*.html "$OUT/diagrams/"

echo "build-pages: the snapshot"
"$PY" "$HERE/snapshot.py" --out "$OUT" --base "$BASE" --site-url "$SITE_URL" ${SITE:+--site "$SITE"}
