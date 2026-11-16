#!/usr/bin/env bash
# =============================================================================
# test_ai_runner.sh — unit tests for the universal AI runner's exit contract
# -----------------------------------------------------------------------------
# Covers scripts/ai/run.sh by stubbing `claude` on PATH so a run can be made to
# succeed, to fail with a real `--output-format json` error payload, or to be
# missing entirely — no network, no credentials, no tokens spent.
#
# The case that matters is case 2: a call that was ATTEMPTED and REJECTED, with
# no ANTHROPIC_API_KEY to fall back to, must exit NON-ZERO and name the reason.
# It used to exit 0, which is how six days of content-factory runs (2026-08-17
# onward) reported a dead credential as "no PR was opened — auth? duplicate?
# build failure?" one step downstream, with the error payload already deleted.
# Case 4 pins the other half: a genuine no-op (nothing ever attempted) stays
# exit 0, so a human running a skill locally without credentials still degrades
# gracefully instead of aborting.
#
#   bash templates/ai-runner/tests/contract.sh            # the hub's runner
#   AI_RUNNER_SUT=scripts/ai/run.sh bash tests/contract.sh  # a vendored copy
# =============================================================================
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# System under test: the hub's runner by default (this file lives in
# templates/ai-runner/tests/); a consumer that vendors the runner points
# AI_RUNNER_SUT at its own copy to prove parity.
SUT="${AI_RUNNER_SUT:-$(cd "$HERE/../../.." && pwd)/.github/actions/claude-run/run.sh}"

if [[ ! -f "$SUT" ]]; then
  echo "FAIL: $SUT does not exist"
  exit 1
fi

pass=0
fail=0

# A throwaway PATH whose `claude` prints $2 on stdout and exits $1. An empty $2
# means "print nothing" (the CLI died before producing a payload).
stub_claude() {
  local rc="$1" payload="${2:-}" dir
  dir="$(mktemp -d)"
  {
    printf '#!/usr/bin/env bash\n'
    printf 'cat <<'"'"'STUBJSON'"'"'\n%s\nSTUBJSON\n' "$payload"
    printf 'exit %s\n' "$rc"
  } > "$dir/claude"
  chmod +x "$dir/claude"
  echo "$dir"
}

# run_case <name> <stub-dir|"none"> <want-rc> [want-stdout-substring] [want-stderr-substring]
run_case() {
  local name="$1" stub="$2" want_rc="$3" want_out="${4:-}" want_err="${5:-}"
  local outf errf rc usage_dir path
  outf="$(mktemp)"; errf="$(mktemp)"; usage_dir="$(mktemp -d)"
  # A PATH that keeps ruby/coreutils but holds only the stub `claude` we chose.
  path="${stub}:/usr/local/bin:/usr/bin:/bin"
  [[ "$stub" == "none" ]] && path="/usr/local/bin:/usr/bin:/bin"

  env -i \
    PATH="$path" \
    HOME="${HOME:-/root}" \
    AI_USAGE_DIR="$usage_dir" \
    CLAUDE_CODE_OAUTH_TOKEN="stub-token" \
    bash "$SUT" --prompt "hello" --agent test-agent >"$outf" 2>"$errf"
  rc=$?

  local why=""
  [[ "$rc" != "$want_rc" ]] && why="exit $rc, wanted $want_rc"
  if [[ -z "$why" && -n "$want_out" ]] && ! grep -qF "$want_out" "$outf"; then
    why="stdout missing '$want_out'"
  fi
  if [[ -z "$why" && -n "$want_err" ]] && ! grep -qF "$want_err" "$errf"; then
    why="stderr missing '$want_err'"
  fi

  if [[ -z "$why" ]]; then
    echo "PASS: $name"
    pass=$((pass + 1))
  else
    echo "FAIL: $name — $why"
    echo "  stdout: $(head -c 300 "$outf")"
    echo "  stderr: $(head -c 300 "$errf")"
    fail=$((fail + 1))
  fi
  rm -rf "$outf" "$errf" "$usage_dir"
}

OK_JSON='{"type":"result","subtype":"success","is_error":false,"duration_ms":1200,"num_turns":2,"session_id":"s1","total_cost_usd":0.01,"usage":{"input_tokens":10,"output_tokens":5},"modelUsage":{"claude-opus-5-5":{"inputTokens":10,"outputTokens":5,"costUSD":0.01}},"result":"THE ANSWER"}'
# The shape a rejected call actually produced on 2026-08-22: one turn, ~1.8s,
# zero tokens, no model, is_error — the request never reached the model.
ERR_JSON='{"type":"result","subtype":"error_during_execution","is_error":true,"duration_ms":1803,"num_turns":1,"session_id":"s2","total_cost_usd":0,"usage":{"input_tokens":0,"output_tokens":0},"result":"Claude AI usage limit reached"}'

s_ok="$(stub_claude 0 "$OK_JSON")"
s_err="$(stub_claude 1 "$ERR_JSON")"
s_silent="$(stub_claude 1 "")"

# 1. A clean run emits the result text and succeeds.
run_case "success: emits result text, exit 0" "$s_ok" 0 "THE ANSWER"

# 2. THE REGRESSION: rejected call, no fallback key -> exit 1, reason + hint.
run_case "rejected call: exit 1 and names the reason" "$s_err" 1 "" "usage limit reached"
run_case "rejected call: names the operator action" "$s_err" 1 "" "likely cause:"

# 3. A CLI that dies without a payload is still a failure, not a no-op.
run_case "no payload: still exit 1" "$s_silent" 1 "" "Claude Code failed"

# 4. Nothing attempted (no claude, no key) stays a graceful no-op.
run_case "no claude, no key: no-op exit 0" "none" 0 "" "no-op"

# 5. An exit-0 run whose payload carries is_error is a failure too — and it must
#    record its usage exactly ONCE. That path already ingested on the way in, so
#    a second ingest in the failure branch would double-count the call in the
#    step summary and the ledger.
ERR0_JSON='{"type":"result","subtype":"error_during_execution","is_error":true,"duration_ms":900,"num_turns":1,"session_id":"s3","total_cost_usd":0,"usage":{"input_tokens":3,"output_tokens":0},"result":"authentication_error: invalid api key"}'
s_err0="$(stub_claude 0 "$ERR0_JSON")"
run_case "exit 0 but is_error: still exit 1" "$s_err0" 1 "" "unusable result"

# The once-only assertion needs the metering companion, which is CONSUMER-owned
# (scripts/ai/usage.rb beside a vendored runner, or in the tree the hub runner
# acts on). The hub itself carries none, so there it is a documented SKIP; a
# consumer running this file with AI_RUNNER_SUT exercises it for real.
if [[ "$SUT" == */scripts/ai/run.sh ]]; then metering_root="$(cd "$(dirname "$SUT")/../.." && pwd)"; else metering_root="$PWD"; fi
if [[ -f "$metering_root/scripts/ai/usage.rb" ]]; then
  usage_dir="$(mktemp -d)"
  env -i PATH="${s_err0}:/usr/local/bin:/usr/bin:/bin" HOME="${HOME:-/root}" \
    AI_USAGE_DIR="$usage_dir" CLAUDE_CODE_OAUTH_TOKEN="stub-token" \
    bash "$SUT" --prompt "hello" --agent test-agent >/dev/null 2>&1
  n="$(wc -l < "$usage_dir/records.jsonl" 2>/dev/null | tr -d ' ')"
  if [[ "$n" == "1" ]]; then
    echo "PASS: exit 0 but is_error: records the call exactly once"
    pass=$((pass + 1))
  else
    echo "FAIL: exit 0 but is_error: recorded ${n:-0} usage record(s), wanted 1"
    fail=$((fail + 1))
  fi
  rm -rf "$usage_dir"
else
  echo "SKIP: exit 0 but is_error: records the call exactly once (no scripts/ai/usage.rb at $metering_root — metering is consumer-owned)"
fi

rm -rf "$s_ok" "$s_err" "$s_silent" "$s_err0"

# 6. The kit contract WITHOUT the metering companion: a repo that carries only
#    run.sh (no scripts/ai/usage.rb) must keep the same exit semantics via the
#    inline emitter — success prints the result, is_error still exits 1.
kit="$(mktemp -d)"; mkdir -p "$kit/scripts/ai" "$kit/_data"
cp "$SUT" "$kit/scripts/ai/run.sh"; printf 'model: claude-opus-5-5\n' > "$kit/_data/ai.yml"
for want in ok err0; do
  stub="$(stub_claude 0 "$([ "$want" = ok ] && echo "$OK_JSON" || echo "$ERR0_JSON")")"
  outf="$(mktemp)"; errf="$(mktemp)"
  env -i PATH="${stub}:/usr/local/bin:/usr/bin:/bin" HOME="${HOME:-/root}" CLAUDE_CODE_OAUTH_TOKEN="stub-token" \
    bash "$kit/scripts/ai/run.sh" --prompt "hello" >"$outf" 2>"$errf"; rc=$?
  if [ "$want" = ok ] && [ "$rc" = 0 ] && grep -qF "THE ANSWER" "$outf"; then
    echo "PASS: no usage.rb: success emits result, exit 0"; pass=$((pass + 1))
  elif [ "$want" = err0 ] && [ "$rc" = 1 ] && grep -qF "unusable result" "$errf"; then
    echo "PASS: no usage.rb: is_error still exits 1"; pass=$((pass + 1))
  else
    echo "FAIL: no usage.rb ($want): exit $rc; stdout=$(head -c 120 "$outf"); stderr=$(head -c 200 "$errf")"; fail=$((fail + 1))
  fi
  rm -rf "$stub" "$outf" "$errf"
done
rm -rf "$kit"

# 7. --max-turns / --model reach the CLI (the stub echoes its argv into the payload's result).
argstub="$(mktemp -d)"
cat > "$argstub/claude" <<'STUB'
#!/usr/bin/env bash
# A usage block is mandatory: the real CLI always sends one and usage.rb refuses a payload without it.
printf '{"type":"result","subtype":"success","is_error":false,"usage":{"input_tokens":1,"output_tokens":1},"result":"ARGS: %s"}' "$*"
STUB
chmod +x "$argstub/claude"; outf="$(mktemp)"
env -i PATH="${argstub}:/usr/local/bin:/usr/bin:/bin" HOME="${HOME:-/root}" AI_USAGE_DIR="$(mktemp -d)" CLAUDE_CODE_OAUTH_TOKEN="stub-token" \
  bash "$SUT" --prompt "hello" --max-turns 7 --model claude-sonnet-5-5 >"$outf" 2>/dev/null
if grep -qF -- "--max-turns 7" "$outf" && grep -qF -- "--model claude-sonnet-5-5" "$outf"; then
  echo "PASS: --max-turns and --model are passed to the CLI"; pass=$((pass + 1))
else
  echo "FAIL: flags not passed: $(head -c 200 "$outf")"; fail=$((fail + 1))
fi
outf="$(mktemp)"
env -i PATH="${argstub}:/usr/local/bin:/usr/bin:/bin" HOME="${HOME:-/root}" AI_USAGE_DIR="$(mktemp -d)" CLAUDE_CODE_OAUTH_TOKEN="stub-token" \
  bash "$SUT" --prompt "hello" --max-budget-usd 3 >"$outf" 2>/dev/null
if grep -qF -- "--max-budget-usd 3" "$outf"; then
  echo "PASS: --max-budget-usd is passed to the CLI"; pass=$((pass + 1))
else
  echo "FAIL: --max-budget-usd not passed: $(head -c 200 "$outf")"; fail=$((fail + 1))
fi
rm -f "$outf"; outf="$(mktemp)"
env -i PATH="${argstub}:/usr/local/bin:/usr/bin:/bin" HOME="${HOME:-/root}" AI_USAGE_DIR="$(mktemp -d)" CLAUDE_CODE_OAUTH_TOKEN="stub-token" AI_MAX_BUDGET_USD=4 \
  bash "$SUT" --prompt "hello" >"$outf" 2>/dev/null
if grep -qF -- "--max-budget-usd 4" "$outf"; then
  echo "PASS: AI_MAX_BUDGET_USD reaches the CLI as --max-budget-usd"; pass=$((pass + 1))
else
  echo "FAIL: AI_MAX_BUDGET_USD not passed: $(head -c 200 "$outf")"; fail=$((fail + 1))
fi
# 7b. The permission mode: acceptEdits unless the caller narrows it, and a mode
#    outside the short list is refused before the CLI is ever called.
perm_case() {  # <name> <extra args...> ; reads PERM_WANT / PERM_ENV
  local name="$1"; shift
  env -i PATH="${argstub}:/usr/local/bin:/usr/bin:/bin" HOME="${HOME:-/root}" AI_USAGE_DIR="$(mktemp -d)" CLAUDE_CODE_OAUTH_TOKEN="stub-token" \
    ${PERM_ENV:+AI_PERMISSION_MODE="$PERM_ENV"} bash "$SUT" --prompt "hello" "$@" >"$outf" 2>/dev/null
  if grep -qF -- "--permission-mode ${PERM_WANT} " "$outf"; then
    echo "PASS: permission mode: $name"; pass=$((pass + 1))
  else
    echo "FAIL: permission mode: $name — $(head -c 200 "$outf")"; fail=$((fail + 1))
  fi
}
PERM_WANT=acceptEdits PERM_ENV="" perm_case "acceptEdits when the caller says nothing"
PERM_WANT=default PERM_ENV="" perm_case "--permission-mode default reaches the CLI" --permission-mode default
PERM_WANT=plan PERM_ENV=plan perm_case "AI_PERMISSION_MODE reaches the CLI"
errf="$(mktemp)"
env -i PATH="${argstub}:/usr/local/bin:/usr/bin:/bin" HOME="${HOME:-/root}" AI_USAGE_DIR="$(mktemp -d)" CLAUDE_CODE_OAUTH_TOKEN="stub-token" \
  bash "$SUT" --prompt "hello" --permission-mode bypassPermissions >"$outf" 2>"$errf"; rc=$?
if [ "$rc" = 1 ] && ! grep -qF "ARGS:" "$outf" && grep -qF "is not allowed" "$errf"; then
  echo "PASS: permission mode: a mode that skips permission checks is refused and nothing runs"; pass=$((pass + 1))
else
  echo "FAIL: permission mode: bypassPermissions was not refused (exit $rc): $(head -c 200 "$outf")"; fail=$((fail + 1))
fi
rm -f "$errf"
rm -rf "$argstub" "$outf"

# 8-12. AI_AUTH_ORDER — the per-repo credential order (ai_auth: in the hub's
#    _data/fleet.yml). The stubs report which credentials the CLI could SEE, so
#    "one credential per attempt" is asserted, not assumed.
authstub="$(mktemp -d)"
cat > "$authstub/claude" <<'STUB'
#!/usr/bin/env bash
seen="${CLAUDE_CODE_OAUTH_TOKEN:+oauth}+${ANTHROPIC_API_KEY:+key}"
if [ -n "${REFUSE_KEY:-}" ] && [ -n "${ANTHROPIC_API_KEY:-}" ]; then
  printf '{"type":"result","subtype":"error_during_execution","is_error":true,"num_turns":1,"usage":{"input_tokens":0,"output_tokens":0},"result":"authentication_error: invalid x-api-key"}'
  exit 1
fi
if [ -n "${OVERLOAD:-}" ]; then
  printf '{"type":"result","subtype":"error_during_execution","is_error":true,"num_turns":1,"usage":{"input_tokens":0,"output_tokens":0},"result":"overloaded_error"}'
  exit 1
fi
printf '{"type":"result","subtype":"success","is_error":false,"usage":{"input_tokens":1,"output_tokens":1},"result":"SAW %s"}' "$seen"
STUB
chmod +x "$authstub/claude"

# auth_case <name> <want-rc> <want-stdout> <want-stderr|""> <not-in-stderr|""> VAR=value…
# These cases pin the credential order, one call per method, so they run with
# the in-run transient retry off (AI_TRANSIENT_RETRIES=0); cases 17-21 cover it.
auth_case() {
  local name="$1" want_rc="$2" want_out="$3" want_err="$4" not_err="$5"; shift 5
  local outf errf rc why=""
  outf="$(mktemp)"; errf="$(mktemp)"
  env -i PATH="${authstub}:/usr/local/bin:/usr/bin:/bin" HOME="${HOME:-/root}" AI_USAGE_DIR="$(mktemp -d)" AI_TRANSIENT_RETRIES=0 \
    "$@" bash "$SUT" --prompt "hello" >"$outf" 2>"$errf"; rc=$?
  [[ "$rc" != "$want_rc" ]] && why="exit $rc, wanted $want_rc"
  [[ -z "$why" && -n "$want_out" ]] && ! grep -qF -- "$want_out" "$outf" && why="stdout missing '$want_out'"
  [[ -z "$why" && -n "$want_err" ]] && ! grep -qF -- "$want_err" "$errf" && why="stderr missing '$want_err'"
  [[ -z "$why" && -n "$not_err" ]] && grep -qF -- "$not_err" "$errf" && why="stderr should not contain '$not_err'"
  if [[ -z "$why" ]]; then echo "PASS: $name"; pass=$((pass + 1))
  else echo "FAIL: $name — $why"; echo "  stdout: $(head -c 200 "$outf")"; echo "  stderr: $(head -c 300 "$errf")"; fail=$((fail + 1)); fi
  rm -f "$outf" "$errf"
}

auth_case "default order: OAuth first, the key hidden from the CLI" 0 "SAW oauth+" "" "" \
  CLAUDE_CODE_OAUTH_TOKEN=o ANTHROPIC_API_KEY=k
auth_case "api_key,oauth: the key first, the OAuth token hidden" 0 "SAW +key" "" "" \
  AI_AUTH_ORDER=api_key,oauth CLAUDE_CODE_OAUTH_TOKEN=o ANTHROPIC_API_KEY=k
auth_case "CLAUDE_AUTH_ORDER is read when AI_AUTH_ORDER is unset" 0 "SAW +key" "" "" \
  CLAUDE_AUTH_ORDER=api_key,oauth CLAUDE_CODE_OAUTH_TOKEN=o ANTHROPIC_API_KEY=k
auth_case "a REFUSED first method hands over to the next" 0 "SAW oauth+" "retrying with oauth" "" \
  AI_AUTH_ORDER=api_key,oauth REFUSE_KEY=1 CLAUDE_CODE_OAUTH_TOKEN=o ANTHROPIC_API_KEY=k
auth_case "a refused key's hint names the key, not the OAuth token" 1 "" "ANTHROPIC_API_KEY was rejected" "" \
  AI_AUTH_ORDER=api_key REFUSE_KEY=1 CLAUDE_CODE_OAUTH_TOKEN=o ANTHROPIC_API_KEY=k
auth_case "a non-credential failure does NOT re-run the task" 1 "" "overloaded" "retrying with" \
  AI_AUTH_ORDER=api_key,oauth OVERLOAD=1 CLAUDE_CODE_OAUTH_TOKEN=o ANTHROPIC_API_KEY=k

# The single-shot API fallback is billed to the key, so an order without
# api_key must never reach it. Needs a consumer tree with an api_call script.
kit="$(mktemp -d)"; mkdir -p "$kit/scripts/ai"
cp "$SUT" "$kit/scripts/ai/run.sh"
printf 'print "API FALLBACK"\n' > "$kit/scripts/ai/api_call.rb"
for order in oauth oauth,api_key; do
  outf="$(mktemp)"
  env -i PATH="${authstub}:/usr/local/bin:/usr/bin:/bin" HOME="${HOME:-/root}" AI_USAGE_DIR="$(mktemp -d)" AI_TRANSIENT_RETRIES=0 \
    AI_AUTH_ORDER="$order" OVERLOAD=1 CLAUDE_CODE_OAUTH_TOKEN=o ANTHROPIC_API_KEY=k \
    bash "$kit/scripts/ai/run.sh" --prompt "hello" >"$outf" 2>/dev/null; rc=$?
  if [ "$order" = oauth ] && [ "$rc" = 1 ] && ! grep -qF "API FALLBACK" "$outf"; then
    echo "PASS: order without api_key never spends the key on the API fallback"; pass=$((pass + 1))
  elif [ "$order" = oauth,api_key ] && grep -qF "API FALLBACK" "$outf"; then
    echo "PASS: order with api_key still reaches the API fallback"; pass=$((pass + 1))
  else
    echo "FAIL: API fallback under AI_AUTH_ORDER=$order: exit $rc, stdout=$(head -c 120 "$outf")"; fail=$((fail + 1))
  fi
  rm -f "$outf"
done
rm -rf "$kit" "$authstub"

# 13-14. A BUDGET ABORT is a circuit breaker, not a refusal: it must fail the
#    step, never hand over to the next credential, and never reach the API
#    fallback — any of those would just move the spend somewhere else.
budgetstub="$(mktemp -d)"
cat > "$budgetstub/claude" <<'STUB'
#!/usr/bin/env bash
printf '{"type":"result","subtype":"error_max_budget_usd","is_error":true,"num_turns":12,"total_cost_usd":3.02,"usage":{"input_tokens":9,"output_tokens":9},"result":"Reached maximum budget ($3)"}'
exit 1
STUB
chmod +x "$budgetstub/claude"
kit="$(mktemp -d)"; mkdir -p "$kit/scripts/ai"
cp "$SUT" "$kit/scripts/ai/run.sh"
printf 'print "API FALLBACK"\n' > "$kit/scripts/ai/api_call.rb"
outf="$(mktemp)"; errf="$(mktemp)"
env -i PATH="${budgetstub}:/usr/local/bin:/usr/bin:/bin" HOME="${HOME:-/root}" AI_USAGE_DIR="$(mktemp -d)" \
  AI_AUTH_ORDER=oauth,api_key CLAUDE_CODE_OAUTH_TOKEN=o ANTHROPIC_API_KEY=k \
  bash "$kit/scripts/ai/run.sh" --prompt "hello" --max-budget-usd 3 >"$outf" 2>"$errf"; rc=$?
if [ "$rc" = 1 ] && grep -qF "max-budget-usd 3 reached" "$errf" && ! grep -qF "retrying with" "$errf"; then
  echo "PASS: a budget abort exits 1 and does not retry with the next credential"; pass=$((pass + 1))
else
  echo "FAIL: budget abort: exit $rc; stderr=$(head -c 300 "$errf")"; fail=$((fail + 1))
fi
if ! grep -qF "API FALLBACK" "$outf"; then
  echo "PASS: a budget abort never reaches the API fallback"; pass=$((pass + 1))
else
  echo "FAIL: budget abort reached the API fallback"; fail=$((fail + 1))
fi
rm -rf "$kit" "$budgetstub" "$outf" "$errf"

# 15-16. A TURN-CAP STOP is the same kind of event: the agent used its turns and
#    was cut off. It must fail the step and never reach the single-shot API
#    fallback, which would end the step GREEN on one completion while the
#    agent's work is truncated (it did, until kit 0.3.0).
turnstub="$(mktemp -d)"
cat > "$turnstub/claude" <<'STUB'
#!/usr/bin/env bash
printf '{"type":"result","subtype":"error_max_turns","is_error":true,"num_turns":60,"total_cost_usd":4.10,"usage":{"input_tokens":9,"output_tokens":9}}'
exit 1
STUB
chmod +x "$turnstub/claude"
kit="$(mktemp -d)"; mkdir -p "$kit/scripts/ai"
cp "$SUT" "$kit/scripts/ai/run.sh"
printf 'print "API FALLBACK"\n' > "$kit/scripts/ai/api_call.rb"
outf="$(mktemp)"; errf="$(mktemp)"
env -i PATH="${turnstub}:/usr/local/bin:/usr/bin:/bin" HOME="${HOME:-/root}" AI_USAGE_DIR="$(mktemp -d)" \
  AI_AUTH_ORDER=oauth,api_key CLAUDE_CODE_OAUTH_TOKEN=o ANTHROPIC_API_KEY=k \
  bash "$kit/scripts/ai/run.sh" --prompt "hello" --max-turns 60 >"$outf" 2>"$errf"; rc=$?
if [ "$rc" = 1 ] && grep -qF "max-turns 60 reached" "$errf" && ! grep -qF "retrying with" "$errf"; then
  echo "PASS: a turn-cap stop exits 1 and does not retry with the next credential"; pass=$((pass + 1))
else
  echo "FAIL: turn-cap stop: exit $rc; stderr=$(head -c 300 "$errf")"; fail=$((fail + 1))
fi
if ! grep -qF "API FALLBACK" "$outf"; then
  echo "PASS: a turn-cap stop never reaches the API fallback"; pass=$((pass + 1))
else
  echo "FAIL: turn-cap stop reached the API fallback"; fail=$((fail + 1))
fi
rm -rf "$kit" "$turnstub" "$outf" "$errf"

# 14. Model resolution: --model > AI_MODEL > the consumer's _data/ai.yml > the
# fleet default. An EMPTY `model:` in ai.yml is the fleet default — the kit seeds
# `model: ""` with that comment — and used to reach the CLI as `--model ""`.
argstub="$(mktemp -d)"
cat > "$argstub/claude" <<'STUB'
#!/usr/bin/env bash
printf '%s\n' "$@" > "$CLAUDE_ARGV_FILE"
printf '{"type":"result","subtype":"success","is_error":false,"num_turns":1,"total_cost_usd":0,"usage":{"input_tokens":1,"output_tokens":1},"result":"ok"}\n'
STUB
chmod +x "$argstub/claude"
model_case() {  # <name> <ai.yml text | "-" for no file> <AI_MODEL | ""> <want model>
  local name="$1" yml="$2" env_model="$3" want="$4" repo argv got
  repo="$(mktemp -d)"; argv="$(mktemp)"
  if [[ "$yml" != "-" ]]; then mkdir -p "$repo/_data"; printf '%s\n' "$yml" > "$repo/_data/ai.yml"; fi
  env -i PATH="${argstub}:/usr/local/bin:/usr/bin:/bin" HOME="${HOME:-/root}" AI_USAGE_DIR="$(mktemp -d)" \
    AI_REPO_ROOT="$repo" CLAUDE_ARGV_FILE="$argv" CLAUDE_CODE_OAUTH_TOKEN=o ${env_model:+AI_MODEL="$env_model"} \
    bash "$SUT" --prompt "hello" >/dev/null 2>&1
  got="$(awk 'prev == "--model" { print; exit } { prev = $0 }' "$argv")"
  if [[ "$got" == "$want" ]]; then
    echo "PASS: model: $name"; pass=$((pass + 1))
  else
    echo "FAIL: model: $name — --model was '$got', wanted '$want'"; fail=$((fail + 1))
  fi
  rm -rf "$repo" "$argv"
}
model_case 'an empty model in ai.yml is the fleet default' 'model: ""' "" "claude-opus-5-5"
model_case 'a null model in ai.yml is the fleet default' 'model:' "" "claude-opus-5-5"
model_case 'no ai.yml is the fleet default' '-' "" "claude-opus-5-5"
model_case 'ai.yml names the model' 'model: claude-sonnet-5-5' "" "claude-sonnet-5-5"
model_case 'AI_MODEL wins over ai.yml' 'model: claude-sonnet-5-5' "claude-haiku-5-5" "claude-haiku-5-5"
model_case 'AI_MODEL wins over an empty ai.yml' 'model: ""' "claude-haiku-5-5" "claude-haiku-5-5"
rm -rf "$argstub"

# 17-21. A TRANSIENT failure (529, 503, overloaded) whose payload shows NOTHING
#    BILLED is re-run on the same credential, at most AI_TRANSIENT_RETRIES times
#    (default 2) after the AI_TRANSIENT_BACKOFF waits (default "30 90", "0 0"
#    here). A failed call that billed anything is never re-run, and a transient
#    failure never hands over to the next credential. Until kit 0.3.1 a
#    transient payload produced exactly one call.
retrystub="$(mktemp -d)"
cat > "$retrystub/claude" <<'STUB'
#!/usr/bin/env bash
# One line per call in $CLAUDE_CALLS, naming the credential the CLI could see.
# The first $FAIL_CALLS calls print $FAIL_PAYLOAD and exit 1; later calls succeed.
echo "${CLAUDE_CODE_OAUTH_TOKEN:+oauth}+${ANTHROPIC_API_KEY:+key}" >> "$CLAUDE_CALLS"
n="$(wc -l < "$CLAUDE_CALLS" | tr -d ' ')"
if [ "$n" -le "${FAIL_CALLS:-99}" ]; then
  printf '%s' "$FAIL_PAYLOAD"
  exit 1
fi
printf '{"type":"result","subtype":"success","is_error":false,"num_turns":3,"total_cost_usd":0.02,"usage":{"input_tokens":5,"output_tokens":5},"result":"RECOVERED on call %s"}' "$n"
STUB
chmod +x "$retrystub/claude"
# A call the API refused before any work: the CLI gave up after its own retries
# ("Repeated 529 Overloaded errors"), one turn, no cost, no tokens.
T529_JSON='{"type":"result","subtype":"success","is_error":true,"duration_ms":41000,"num_turns":1,"session_id":"s6","total_cost_usd":0,"usage":{"input_tokens":0,"output_tokens":0,"cache_creation_input_tokens":0,"cache_read_input_tokens":0},"result":"API Error: Repeated 529 Overloaded errors"}'
# An overload that hit mid-task: seven turns and real tokens already spent.
TBILLED_JSON='{"type":"result","subtype":"error_during_execution","is_error":true,"num_turns":7,"total_cost_usd":0.84,"usage":{"input_tokens":5200,"output_tokens":900},"result":"overloaded_error: Overloaded"}'
retry_root="$(mktemp -d)"   # a consumer tree with no companions: nothing spooled, nothing normalized

# retry_case <name> <want-calls> <want-rc> <want-stdout|""> <want-stderr, |-separated|""> <not-in-stderr|""> VAR=value…
# Leaves the distinct credentials the CLI saw in $retry_seen.
retry_case() {
  local name="$1" want_calls="$2" want_rc="$3" want_out="$4" want_err="$5" not_err="$6"; shift 6
  local calls outf errf rc n pat pats why=""
  calls="$(mktemp)"; outf="$(mktemp)"; errf="$(mktemp)"; : > "$calls"
  env -i PATH="${retrystub}:/usr/local/bin:/usr/bin:/bin" HOME="${HOME:-/root}" AI_USAGE_DIR="$(mktemp -d)" \
    AI_REPO_ROOT="$retry_root" CLAUDE_CALLS="$calls" AI_TRANSIENT_BACKOFF="0 0" CLAUDE_CODE_OAUTH_TOKEN=o \
    "$@" bash "$SUT" --prompt "hello" >"$outf" 2>"$errf"; rc=$?
  n="$(wc -l < "$calls" | tr -d ' ')"
  [[ "$n" != "$want_calls" ]] && why="$n call(s), wanted $want_calls"
  [[ -z "$why" && "$rc" != "$want_rc" ]] && why="exit $rc, wanted $want_rc"
  [[ -z "$why" && -n "$want_out" ]] && ! grep -qF -- "$want_out" "$outf" && why="stdout missing '$want_out'"
  if [[ -z "$why" && -n "$want_err" ]]; then
    IFS='|' read -r -a pats <<<"$want_err"
    for pat in "${pats[@]}"; do grep -qF -- "$pat" "$errf" || { why="stderr missing '$pat'"; break; }; done
  fi
  [[ -z "$why" && -n "$not_err" ]] && grep -qF -- "$not_err" "$errf" && why="stderr should not contain '$not_err'"
  if [[ -z "$why" ]]; then echo "PASS: transient retry: $name"; pass=$((pass + 1))
  else echo "FAIL: transient retry: $name — $why"; echo "  stdout: $(head -c 200 "$outf")"; echo "  stderr: $(head -c 400 "$errf")"; fail=$((fail + 1)); fi
  retry_seen="$(sort -u "$calls" | tr '\n' ' ')"
  rm -f "$calls" "$outf" "$errf"
}

retry_case "a 529 with nothing billed is retried twice, then fails with the transient hint" 3 1 "" \
  "attempt 2/3|attempt 3/3|the API was overloaded|still failing after 2 transient retries" "retrying with" \
  FAIL_PAYLOAD="$T529_JSON" AI_AUTH_ORDER=oauth,api_key ANTHROPIC_API_KEY=k
if [[ "$retry_seen" == "oauth+ " ]]; then
  echo "PASS: transient retry: every retry used the same credential, never the next one"; pass=$((pass + 1))
else
  echo "FAIL: transient retry: the retries saw '$retry_seen', wanted only 'oauth+'"; fail=$((fail + 1))
fi
summary="$(mktemp)"
retry_case "a 529 twice, then success: exit 0 on the third call" 3 0 "RECOVERED on call 3" "attempt 3/3" "" \
  FAIL_PAYLOAD="$T529_JSON" FAIL_CALLS=2 GITHUB_STEP_SUMMARY="$summary"
if grep -qF "2 transient API retries" "$summary"; then
  echo "PASS: transient retry: the step summary counts the retries"; pass=$((pass + 1))
else
  echo "FAIL: transient retry: step summary = '$(head -c 200 "$summary")'"; fail=$((fail + 1))
fi
rm -f "$summary"
retry_case "an overload that billed usage is never re-run" 1 1 "" "billed usage|not retried" "attempt 2/" \
  FAIL_PAYLOAD="$TBILLED_JSON"
retry_case "AI_TRANSIENT_RETRIES=0 turns the retry off" 1 1 "" "the API was overloaded" "attempt 2/" \
  FAIL_PAYLOAD="$T529_JSON" AI_TRANSIENT_RETRIES=0

# The retry event reaches the fleet activity log's spool when the consumer tree
# carries tools/fleet_activity.py (the hub does; most consumers do not).
activity_py="$(cd "$HERE/../../.." && pwd)/tools/fleet_activity.py"
if [[ -f "$activity_py" ]] && env -i PATH="/usr/local/bin:/usr/bin:/bin" sh -c 'command -v python3' >/dev/null 2>&1; then
  mkdir -p "$retry_root/tools"; cp "$activity_py" "$retry_root/tools/"
  queue="$(mktemp)"
  retry_case "a retry with tools/fleet_activity.py present still recovers" 3 0 "RECOVERED on call 3" "" "" \
    FAIL_PAYLOAD="$T529_JSON" FAIL_CALLS=2 FLEET_ACTIVITY_QUEUE="$queue"
  if [[ "$(grep -c '"event_type": "retry"' "$queue")" == "2" ]] && grep -qF '"attempt": 3' "$queue" && grep -qF '"max_attempts": 3' "$queue"; then
    echo "PASS: transient retry: each retry is spooled as a fleet activity retry event"; pass=$((pass + 1))
  else
    echo "FAIL: transient retry: activity spool = '$(head -c 300 "$queue")'"; fail=$((fail + 1))
  fi
  rm -rf "$queue" "$retry_root/tools"
else
  echo "SKIP: transient retry: activity event (no tools/fleet_activity.py beside the hub runner, or no python3 on the minimal PATH)"
fi
rm -rf "$retrystub" "$retry_root"

echo
echo "ai runner contract: $pass passed, $fail failed"
[[ "$fail" -eq 0 ]] || exit 1
