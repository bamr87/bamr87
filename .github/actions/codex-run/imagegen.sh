#!/usr/bin/env bash
# =============================================================================
# imagegen.sh — paint one image on the fleet's ChatGPT (OAuth) login, from a
# job where `codex-run` ran in `setup` mode (it exports this path as
# $FLEET_IMAGEGEN). An agent or a script calls it like any CLI:
#
#   "$FLEET_IMAGEGEN" --prompt "an oil-painted server room at dawn" \
#                     --out assets/images/posts/<slug>/hero.png
#
# Writes the PNG and <out>.prompt.json (prompt, model, sha256, date): every
# AI-painted image in the fleet carries its provenance, and the page that
# embeds it captions it as AI-generated. Exit 0 with the image, 1 when none
# was produced, 0 with a warning when the plan's usage window is spent. Never
# falls back to a metered OPENAI_API_KEY.
# =============================================================================
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export CODEX_HOME_READY="${CODEX_HOME_READY:-1}"
export CODEX_SKIP_INSTALL="${CODEX_SKIP_INSTALL:-1}"
exec "$HERE/run.sh" image "$@"
