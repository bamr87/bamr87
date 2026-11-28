#!/usr/bin/env bash
# =============================================================================
# tools/openai-auth.sh — the local front door to the fleet's OpenAI route:
# image generation and the independent review, on a ChatGPT (OAuth) login.
# Full doc: docs/OPENAI-AUTH.md. Contract: _data/fleet.yml openai_auth:.
# -----------------------------------------------------------------------------
#   tools/openai-auth.sh seed [--apply] [--device-auth] [--repo OWNER/NAME]
#       Mint the fleet's CODEX_AUTH_JSON from a DEDICATED `codex login` in a
#       throwaway CODEX_HOME (never your own ~/.codex: refresh tokens rotate,
#       and the hub's weekly rotation becomes this login's only refresher).
#       Checks it is a ChatGPT login with a refresh token; with --apply, writes
#       it to the hub's secret store (hub-first) and prints the one command
#       that propagates it. The throwaway home is deleted either way.
#   tools/openai-auth.sh check [--model ID]
#       One tiny call on YOUR login: proves the login and the model pin before
#       openai_auth.models changes.
#   tools/openai-auth.sh image --prompt TEXT --out FILE.png [--model ID]
#       Paint one image on your login ($imagegen), with its provenance sidecar.
#   tools/openai-auth.sh review [--base REF] [--head REF] [--scope S] [--model ID]
#       The independent review of your branch, printed; nothing is posted.
#
# Nothing here prints a token, and nothing writes to GitHub without --apply.
# Needs: codex (npm install -g @openai/codex), python3; gh for `seed --apply`.
# =============================================================================
set -euo pipefail

HUB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ACTION="$HUB_DIR/.github/actions/codex-run"
REVIEW="$HUB_DIR/.github/scripts/dash-gen/independent_review.py"
HUB_REPO="${FLEET_HUB:-bamr87/bamr87}"

usage() { sed -n '2,25p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; }
need() { command -v "$1" >/dev/null 2>&1 || { echo "openai-auth: '$1' is not installed${2:+ ($2)}" >&2; exit 2; }; }

cmd="${1:-}"; [ $# -gt 0 ] && shift
case "$cmd" in
  seed)
    apply=0; device=(); repo="$HUB_REPO"
    while [ $# -gt 0 ]; do
      case "$1" in
        --apply) apply=1 ;;
        --device-auth) device=(--device-auth) ;;
        --repo) repo="${2:?--repo needs OWNER/NAME}"; shift ;;
        *) echo "openai-auth seed: unknown argument $1" >&2; exit 2 ;;
      esac
      shift
    done
    need codex "npm install -g @openai/codex"
    need python3
    [ "$apply" -eq 1 ] && need gh
    home="$(mktemp -d "${TMPDIR:-/tmp}/codex-fleet-seed.XXXXXX")"
    trap 'rm -rf "$home"' EXIT
    chmod 700 "$home"
    printf '%s\n' 'forced_login_method = "chatgpt"' 'cli_auth_credentials_store = "file"' > "$home/config.toml"
    echo "== A dedicated ChatGPT login for the fleet (not your own ~/.codex) =="
    echo "   Sign in with the ChatGPT account whose plan the fleet should use."
    CODEX_HOME="$home" codex login ${device[@]+"${device[@]}"}
    [ -f "$home/auth.json" ] || { echo "openai-auth: no auth.json was written — did the login finish?" >&2; exit 1; }
    verdict="$(python3 "$ACTION/codex_auth.py" inspect --file "$home/auth.json" --max-age-days 1 --min-ttl-minutes 60)"
    ok="$(printf '%s' "$verdict" | python3 -c 'import json,sys; v=json.load(sys.stdin); print("yes" if v["ok"] else v["reason"])')"
    [ "$ok" = "yes" ] || { echo "openai-auth: refusing this login: $ok" >&2; exit 1; }
    echo "   ✓ ChatGPT login with a refresh token"
    if [ "$apply" -ne 1 ]; then
      echo "Dry run: would write CODEX_AUTH_JSON to $repo. Re-run with --apply to seed it."
      exit 0
    fi
    gh secret set CODEX_AUTH_JSON -R "$repo" < "$home/auth.json"
    echo "   ✓ CODEX_AUTH_JSON written to $repo (the hub's copy is the canonical one)"
    echo
    echo "Propagate it to the fleet now (otherwise the weekly rotation does it):"
    echo "  gh workflow run token-rotation.yml -R $repo -f apply=true -f only=CODEX_AUTH_JSON -f source=env -f force=true"
    echo
    echo "The local copy is deleted: from here on the weekly rotation is this login's only refresher."
    ;;
  check)
    need codex "npm install -g @openai/codex"
    CODEX_LOCAL=1 bash "$ACTION/run.sh" check "$@"
    ;;
  image)
    need codex "npm install -g @openai/codex"
    CODEX_LOCAL=1 CODEX_TIMEOUT_MINUTES="${CODEX_TIMEOUT_MINUTES:-12}" bash "$ACTION/run.sh" image "$@"
    ;;
  review)
    need codex "npm install -g @openai/codex"
    python3 "$REVIEW" local "$@"
    ;;
  -h|--help|help|"") usage ;;
  *) echo "openai-auth: unknown command '$cmd' (seed | check | image | review)" >&2; exit 2 ;;
esac
