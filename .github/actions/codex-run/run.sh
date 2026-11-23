#!/usr/bin/env bash
# =============================================================================
# codex-run/run.sh — one OpenAI call through the Codex CLI on a ChatGPT
# (OAuth) login. The engine behind .github/actions/codex-run and
# tools/openai-auth.sh; the same code runs in CI and on a laptop.
# -----------------------------------------------------------------------------
#   run.sh <mode> [--prompt TEXT | --prompt-file FILE] [--out FILE]
#                 [--model ID] [--schema FILE] [--workdir DIR] [--sandbox MODE]
#
# MODES
#   review  read-only: Codex reads the work dir and answers; the last message
#           (JSON when --schema is given) lands in --out, redacted.
#   exec    the same, with the sandbox the caller names (read-only default).
#   image   Codex's built-in `$imagegen` (gpt-image-2) paints ONE image into a
#           private work dir; the PNG is copied to --out with a provenance
#           sidecar (<out>.prompt.json). No image, no success: it never falls
#           back to anything else, the caller decides what an idle run means.
#   setup   restore the credential into a CODEX_HOME that later steps of the
#           same job reuse (exported through $GITHUB_ENV), and point
#           $FLEET_IMAGEGEN at the image helper. ai-lane.yml uses it.
#   check   restore and prove the login with one tiny call (the model pin too).
#
# THE CREDENTIAL (docs/OPENAI-AUTH.md)
#   CI: $CODEX_AUTH_JSON, the fleet's ChatGPT-login auth.json. It is written to
#   a fresh 0700 CODEX_HOME, Codex is forced to the ChatGPT login and
#   OPENAI_API_KEY is unset for the call, so the metered path is unreachable.
#   The bundle is refused when it is older than CODEX_MAX_SEED_AGE_DAYS or its
#   access token lapses within CODEX_MIN_TTL_MINUTES: the hub's weekly re-mint
#   is the ONE refresher, and Codex refreshing it here would rotate the fleet's
#   refresh token. If Codex rotates it anyway, the run says so loudly. The
#   CODEX_HOME is deleted when the call ends (never in setup mode): nothing is
#   ever persisted back.
#   Local: CODEX_LOCAL=1 uses your own `codex login` as it is (no restore).
#
# EXIT CODES (the attempted-and-failed-is-RED rule, as in claude-run)
#   0  success; or idle because there is no usable credential (outcome
#      `skipped`, with the reason); or a spent ChatGPT usage window under
#      CODEX_USAGE_LIMIT=skip (outcome `limited`, a warning — capacity, not a
#      defect).
#   1  attempted and failed: Codex errored, timed out, returned nothing, or
#      the image never appeared.
#   2  usage error.
#
# OUTPUTS ($GITHUB_OUTPUT when set): ready, outcome, reason, refreshed, image.
# =============================================================================
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HELPER=(python3 "$HERE/codex_auth.py")

# Fleet defaults. They mirror _data/fleet.yml openai_auth: (the action is
# fetched without the hub's data); test_codex_run.py holds them equal.
DEFAULT_MODEL_REVIEW="gpt-6.1-sol"
DEFAULT_MODEL_IMAGE_DRIVER="gpt-6.1-sol"
DEFAULT_MODEL_IMAGE="gpt-image-2"
DEFAULT_MAX_SEED_AGE_DAYS="7.5"
DEFAULT_MIN_TTL_MINUTES="30"

MODE="${CODEX_MODE:-}"
PROMPT="${CODEX_PROMPT:-}"
PROMPT_FILE="${CODEX_PROMPT_FILE:-}"
OUT="${CODEX_OUT:-}"
MODEL="${CODEX_MODEL:-}"
SCHEMA="${CODEX_OUTPUT_SCHEMA:-}"
WORKDIR="${CODEX_WORKDIR:-}"
SANDBOX="${CODEX_SANDBOX:-}"
TIMEOUT_MIN="${CODEX_TIMEOUT_MINUTES:-}"
MAX_AGE="${CODEX_MAX_SEED_AGE_DAYS:-$DEFAULT_MAX_SEED_AGE_DAYS}"
MIN_TTL="${CODEX_MIN_TTL_MINUTES:-$DEFAULT_MIN_TTL_MINUTES}"
CLI_VERSION="${CODEX_VERSION:-latest}"
USAGE_LIMIT="${CODEX_USAGE_LIMIT:-skip}"

if [ $# -gt 0 ] && [[ "$1" != --* ]]; then MODE="$1"; shift; fi
while [ $# -gt 0 ]; do
  case "$1" in
    --prompt)      PROMPT="${2-}"; shift 2 ;;
    --prompt-file) PROMPT_FILE="${2-}"; shift 2 ;;
    --out)         OUT="${2-}"; shift 2 ;;
    --model)       MODEL="${2-}"; shift 2 ;;
    --schema)      SCHEMA="${2-}"; shift 2 ;;
    --workdir)     WORKDIR="${2-}"; shift 2 ;;
    --sandbox)     SANDBOX="${2-}"; shift 2 ;;
    --timeout-minutes) TIMEOUT_MIN="${2-}"; shift 2 ;;
    -h|--help)     sed -n '2,46p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "[codex-run] unknown argument: $1" >&2; exit 2 ;;
  esac
done
MODE="${MODE:-exec}"

emit() { [ -n "${GITHUB_OUTPUT:-}" ] && printf '%s=%s\n' "$1" "$2" >> "$GITHUB_OUTPUT"; return 0; }
note() { if [ "${GITHUB_ACTIONS:-}" = "true" ]; then echo "::$1::codex-run ($MODE): $2"; else echo "[codex-run] $2" >&2; fi; }
skip() { emit ready false; emit outcome skipped; emit reason "$1"; note notice "idle — $1"; exit 0; }
fail() { emit outcome failure; emit reason "$1"; note error "$1"; exit 1; }

case "$MODE" in
  review|exec|image|setup|check) ;;
  *) echo "[codex-run] unknown mode '$MODE' (review|exec|image|setup|check)" >&2; exit 2 ;;
esac
if [ -n "$PROMPT_FILE" ]; then
  [ -f "$PROMPT_FILE" ] || { echo "[codex-run] --prompt-file $PROMPT_FILE does not exist" >&2; exit 2; }
  PROMPT="$(cat "$PROMPT_FILE")"
fi
if [[ "$MODE" =~ ^(review|exec|image)$ ]]; then
  [ -n "${PROMPT//[[:space:]]/}" ] || { echo "[codex-run] a prompt is required in mode $MODE" >&2; exit 2; }
  [ "$MODE" != image ] || [ -n "$OUT" ] || { echo "[codex-run] --out <file.png> is required in image mode" >&2; exit 2; }
fi

# ---- the credential --------------------------------------------------------
created_home=""
# shellcheck disable=SC2329  # invoked by the EXIT trap
cleanup() { [ -n "$created_home" ] && rm -rf "$created_home"; return 0; }
trap cleanup EXIT

if [ "${CODEX_LOCAL:-}" = "1" ]; then
  export CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
  echo "[codex-run] local: using your own Codex login in $CODEX_HOME" >&2
elif [ "${CODEX_HOME_READY:-}" = "1" ] && [ -f "${CODEX_HOME:-/nonexistent}/auth.json" ]; then
  : # a setup step earlier in this job restored it
else
  # The verdict goes to a file: stdout carries the ::add-mask:: commands, and
  # they only work when they reach the runner.
  vfile="$(mktemp "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/codex-verdict.XXXXXX")"
  "${HELPER[@]}" inspect --max-age-days "$MAX_AGE" --min-ttl-minutes "$MIN_TTL" --out "$vfile" \
    || fail "could not read CODEX_AUTH_JSON"
  ok="$(python3 -c 'import json,sys; print(str(json.load(open(sys.argv[1]))["ok"]).lower())' "$vfile")"
  why="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["reason"])' "$vfile")"
  rm -f "$vfile"
  [ "$ok" = "true" ] || skip "$why"
  echo "[codex-run] credential: $why" >&2
  base="${RUNNER_TEMP:-${TMPDIR:-/tmp}}"
  CODEX_HOME="$(mktemp -d "$base/codex-home.XXXXXX")" || fail "could not create a CODEX_HOME"
  export CODEX_HOME
  [ "$MODE" = setup ] || created_home="$CODEX_HOME"
  chmod 700 "$CODEX_HOME"
  ( umask 077; printf '%s' "$CODEX_AUTH_JSON" > "$CODEX_HOME/auth.json" )
  # The ChatGPT login or nothing: a credential that does not match makes Codex
  # log out and exit, rather than quietly reaching for a key.
  printf '%s\n' 'forced_login_method = "chatgpt"' 'cli_auth_credentials_store = "file"' \
    > "$CODEX_HOME/config.toml"
fi
emit ready true

# ---- the CLI (always latest: docs/DEPENDENCIES.md) -------------------------
# In CI it is installed fresh each job (a setup step installs it once for the
# job: CODEX_SKIP_INSTALL); locally it is whatever you installed.
if [ "${CODEX_LOCAL:-}" != "1" ] && [ "${CODEX_SKIP_INSTALL:-}" != "1" ] && [ "${GITHUB_ACTIONS:-}" = "true" ]; then
  npm install -g "@openai/codex@${CLI_VERSION}" --no-fund --no-audit --loglevel=error >&2 \
    || fail "could not install @openai/codex@${CLI_VERSION} from npm"
fi
command -v codex >/dev/null 2>&1 || fail "the codex CLI is not installed (npm install -g @openai/codex)"
echo "[codex-run] $(codex --version 2>/dev/null | head -1)" >&2

if [ "$MODE" = setup ]; then
  if [ -n "${GITHUB_ENV:-}" ]; then
    { echo "CODEX_HOME=$CODEX_HOME"; echo "CODEX_HOME_READY=1"; echo "CODEX_SKIP_INSTALL=1"
      echo "FLEET_IMAGEGEN=$HERE/imagegen.sh"; } >> "$GITHUB_ENV"
  fi
  emit outcome success; emit reason "CODEX_HOME restored for this job; images: \$FLEET_IMAGEGEN"
  echo "[codex-run] ready: \$FLEET_IMAGEGEN --prompt '…' --out path/to/image.png" >&2
  exit 0
fi

# ---- the call --------------------------------------------------------------
fp_before="$("${HELPER[@]}" fingerprint "$CODEX_HOME/auth.json")"
tmo=()
if [ -n "$TIMEOUT_MIN" ]; then
  if command -v timeout >/dev/null 2>&1; then tmo=(timeout "${TIMEOUT_MIN}m")
  elif command -v gtimeout >/dev/null 2>&1; then tmo=(gtimeout "${TIMEOUT_MIN}m"); fi
fi
log="$(mktemp "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/codex-run-log.XXXXXX")"
started="$(date +%s)"

case "$MODE" in
  review|exec|check)
    [ -n "$MODEL" ] || MODEL="$DEFAULT_MODEL_REVIEW"
    sandbox="${SANDBOX:-read-only}"
    [ "$MODE" = review ] && sandbox=read-only
    last="$(mktemp "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/codex-last.XXXXXX")"
    args=(exec --skip-git-repo-check --sandbox "$sandbox" --model "$MODEL" --output-last-message "$last")
    [ -n "$WORKDIR" ] && args+=(--cd "$WORKDIR")
    [ -n "$SCHEMA" ] && args+=(--output-schema "$SCHEMA")
    [ "$MODE" = check ] && PROMPT="Reply with the single word OK."
    printf '%s' "$PROMPT" | env -u OPENAI_API_KEY -u CODEX_API_KEY ${tmo[@]+"${tmo[@]}"} codex "${args[@]}" - >"$log" 2>&1
    rc=$?
    ;;
  image)
    [ -n "$MODEL" ] || MODEL="$DEFAULT_MODEL_IMAGE_DRIVER"
    work="$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/codex-image.XXXXXX")"
    name="$(basename "$OUT")"; name="${name%.*}.png"
    instruction="Use the \$imagegen image generation tool to generate exactly one image. Save it as ./${name} in the current working directory, overwriting any file of that name; create no other files and do not edit anything else. Reply with the file name only.

Image brief:
${PROMPT}"
    printf '%s' "$instruction" | env -u OPENAI_API_KEY -u CODEX_API_KEY ${tmo[@]+"${tmo[@]}"} \
      codex exec --skip-git-repo-check --sandbox workspace-write --cd "$work" --model "$MODEL" - >"$log" 2>&1
    rc=$?
    ;;
esac

# Did Codex refresh the bundle in here? Then the fleet's stored copy is dead.
fp_after="$("${HELPER[@]}" fingerprint "$CODEX_HOME/auth.json")"
if [ "${CODEX_LOCAL:-}" != "1" ] && [ -n "$fp_before" ] && [ "$fp_after" != "$fp_before" ]; then
  emit refreshed true
  note warning "Codex refreshed the ChatGPT OAuth bundle inside this job, so the refresh token every repo holds has rotated and is no longer valid. Re-seed CODEX_AUTH_JSON (tools/openai-auth.sh seed --apply) and dispatch token-rotation.yml (only: CODEX_AUTH_JSON, source: env, force, apply). docs/OPENAI-AUTH.md"
else
  emit refreshed false
fi

tail_log() { "${HELPER[@]}" redact < "$log" | tail -n 30 >&2; }
if [ "$rc" -ne 0 ]; then
  tail_log
  if [ "$rc" -eq 124 ]; then fail "codex timed out after ${TIMEOUT_MIN} minutes"; fi
  if grep -qiE "usage limit|rate limit|too many requests|\b429\b|quota" "$log"; then
    if [ "$USAGE_LIMIT" = "skip" ]; then
      emit outcome limited; emit reason "the ChatGPT plan's usage window is spent"
      note warning "the ChatGPT plan's usage window is spent — capacity, not a defect; the next run tries again"
      exit 0
    fi
    fail "the ChatGPT plan's usage window is spent"
  fi
  if grep -qiE "not supported when using codex with a chatgpt account|model_not_found|does not exist|unknown model" "$log"; then
    fail "model '$MODEL' is not available to this ChatGPT account (retired or renamed?). Prove a replacement with tools/openai-auth.sh check --model <id>, then update openai_auth.models and ai_models.allowed.openai in bamr87/bamr87 _data/fleet.yml"
  fi
  if grep -qiE "logged out|not logged in|401|unauthori[sz]ed|refresh token" "$log"; then
    fail "the ChatGPT login was refused — re-seed CODEX_AUTH_JSON (tools/openai-auth.sh seed --apply)"
  fi
  fail "codex exited $rc (log tail above)"
fi

case "$MODE" in
  review|exec|check)
    [ -s "$last" ] || { tail_log; fail "codex finished but returned no message"; }
    if [ -n "$OUT" ]; then
      mkdir -p "$(dirname "$OUT")"
      "${HELPER[@]}" redact < "$last" > "$OUT"
    else
      "${HELPER[@]}" redact < "$last"
    fi
    [ "$MODE" = check ] && echo "[codex-run] login and model '$MODEL' answered" >&2
    ;;
  image)
    hit="$("${HELPER[@]}" find-image --want "$work/$name" --workdir "$work" \
            --codex-home "$CODEX_HOME" --since "$started")" \
      || { tail_log; fail "codex finished but produced no PNG (is \$imagegen available to this ChatGPT plan?)"; }
    mkdir -p "$(dirname "$OUT")"
    cp "$hit" "$OUT"
    sidecar="$("${HELPER[@]}" sidecar "$OUT" --prompt "$PROMPT" --model "$DEFAULT_MODEL_IMAGE" --driver "$MODEL")"
    rm -rf "$work"
    emit image "$OUT"
    echo "[codex-run] ✓ $OUT ($(wc -c < "$OUT" | tr -d ' ') bytes) + $sidecar" >&2
    ;;
esac
emit outcome success
emit reason "ok"
rm -f "$log" "${last:-}"
exit 0
