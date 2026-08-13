#!/usr/bin/env bash
# =============================================================================
# issue-evidence.sh — build an EVIDENCE BUNDLE for one issue, in an isolated
#                     virtual environment.
# =============================================================================
# Tier 1 of the issue pipeline (docs/ISSUE-PIPELINE.md) does not guess at what a
# report means: it clones the repo into a throwaway sandbox, installs the
# toolchain, runs the project's own lint / test / build, captures a screenshot
# where there is something to look at, and greps the tree for the files the
# issue is probably about. What comes back is the structured context that makes
# tiers 2 and 3 cheap:
#
#   $OUT/evidence.md        the comment T1 posts on the issue
#   $OUT/evidence.json      the same facts, machine-readable
#   $OUT/env.md             toolchain versions, commit SHA, OS
#   $OUT/logs/*.log         install / lint / test / build / repro output
#   $OUT/screenshots/*.png  rendered UI, when the stack has one
#   $OUT/candidates.md      files ranked by relevance to the issue text
#   $OUT/workspace/         the clone + its venv/node_modules
#
# EVERY PHASE IS BEST-EFFORT. A missing toolchain, a project with no tests, a
# dev server that won't start — each is recorded as `skipped` with a reason and
# never fails the run. An evidence bundle that reports "no test script" is a
# useful finding; a harness that exits 1 because of it is not.
#
# SECURITY: this script NEVER executes commands found in an issue body. Issue
# text is attacker-controlled (anyone can open an issue) and this runs on a
# runner holding a token. Candidate repro commands are EXTRACTED and REPORTED
# for a human or agent to read; only `--cmd`, passed explicitly by the caller,
# is executed.
#
# Dependency policy: the fleet installs latest, never from a lockfile
# (docs/DEPENDENCIES.md), so this uses `npm install`, not `npm ci`.
#
# Usage:
#   tools/issue-evidence.sh --repo owner/name --issue 42 [--ref main] \
#       [--out DIR] [--body-file FILE] [--timeout MIN] [--cmd 'pytest -k x'] \
#       [--no-screenshot] [--rerun] [--quiet]
#
#   --rerun   re-run the test phase in an already-prepared $OUT/workspace and
#             re-render the report. This is how T1 proves a repro test FAILS
#             before tier 2 makes it pass.
# =============================================================================
set -uo pipefail

REPO=""
ISSUE=""
REF=""
OUT=""
BODY_FILE=""
CUSTOM_CMD=""
TIMEOUT_MIN=12
SCREENSHOT=1
RERUN=0
QUIET=0

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

die() { printf 'issue-evidence: %s\n' "$*" >&2; exit 2; }
log() { [ "$QUIET" -eq 1 ] || printf '  · %s\n' "$*" >&2; }

usage() { sed -n '2,45p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; }

while [ $# -gt 0 ]; do
  case "$1" in
    --repo) REPO="${2:-}"; shift 2 ;;
    --issue) ISSUE="${2:-}"; shift 2 ;;
    --ref) REF="${2:-}"; shift 2 ;;
    --out) OUT="${2:-}"; shift 2 ;;
    --body-file) BODY_FILE="${2:-}"; shift 2 ;;
    --cmd) CUSTOM_CMD="${2:-}"; shift 2 ;;
    --timeout) TIMEOUT_MIN="${2:-12}"; shift 2 ;;
    --no-screenshot) SCREENSHOT=0; shift ;;
    --rerun) RERUN=1; shift ;;
    --quiet) QUIET=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown argument: $1 (try --help)" ;;
  esac
done

[ -n "$REPO" ] || die "--repo owner/name is required"
[ -n "$ISSUE" ] || die "--issue N is required"
case "$REPO" in */*) : ;; *) die "--repo must be owner/name, got '$REPO'" ;; esac
case "$ISSUE" in ''|*[!0-9]*) die "--issue must be a number, got '$ISSUE'" ;; esac

SLUG="${REPO##*/}-${ISSUE}"
OUT="${OUT:-${REPO_ROOT}/.evidence/${SLUG}}"
WS="${OUT}/workspace"
LOGS="${OUT}/logs"
SHOTS="${OUT}/screenshots"
PHASES="${OUT}/.phases.tsv"     # name<TAB>status<TAB>seconds<TAB>detail<TAB>logfile
TIMEOUT_S=$(( TIMEOUT_MIN * 60 ))

mkdir -p "$LOGS" "$SHOTS"
[ "$RERUN" -eq 1 ] || : > "$PHASES"
[ -f "$PHASES" ] || : > "$PHASES"

# --------------------------------------------------------------------------- #
# phase runner — records status, never aborts the script
# --------------------------------------------------------------------------- #
record() {  # name status seconds detail [logfile]
  printf '%s\t%s\t%s\t%s\t%s\n' "$1" "$2" "$3" "$4" "${5:-}" >> "$PHASES"
}

skip() { log "skip  $1 — $2"; record "$1" skipped 0 "$2" ""; }

# Strip anything credential-shaped before it reaches a log, a comment, or an
# uploaded artifact. The clone URL carries `x-access-token:<PAT>@github.com`,
# and echoing the command verbatim publishes a live fleet token.
redact() {
  local s="$1"
  s="${s//:\/\/x-access-token:*@/://x-access-token:***@}"
  [ -n "${GH_TOKEN:-}" ] && s="${s//${GH_TOKEN}/\*\*\*}"
  [ -n "${GITHUB_TOKEN:-}" ] && s="${s//${GITHUB_TOKEN}/\*\*\*}"
  printf '%s' "$s"
}

# run <name> <logfile> <cmd...>
run_phase() {
  local name="$1" logfile="$2"; shift 2
  local start end status rc
  start=$(date +%s)
  log "run   ${name}: $(redact "$*")"
  {
    printf '$ %s\n\n' "$(redact "$*")"
    if command -v timeout >/dev/null 2>&1; then
      timeout --signal=TERM --kill-after=30s "${TIMEOUT_S}s" "$@" 2>&1
    else
      "$@" 2>&1
    fi
  } > "${LOGS}/${logfile}" 2>&1
  rc=$?
  end=$(date +%s)
  case "$rc" in
    0) status=pass ;;
    124|137) status=timeout ;;
    *) status=fail ;;
  esac
  log "      ${name} → ${status} (${rc}) in $(( end - start ))s"
  record "$name" "$status" "$(( end - start ))" "exit ${rc}" "$logfile"
  # Belt and braces: a command can print a credential the echo never saw
  # (a `set -x` trace, a verbose transport). Scrub the log we just wrote.
  if [ -n "${GH_TOKEN:-}${GITHUB_TOKEN:-}" ] && [ -f "${LOGS}/${logfile}" ]; then
    sed -i -e 's#x-access-token:[^@]*@#x-access-token:***@#g' \
      ${GH_TOKEN:+-e "s#${GH_TOKEN}#***#g"} \
      ${GITHUB_TOKEN:+-e "s#${GITHUB_TOKEN}#***#g"} \
      "${LOGS}/${logfile}" 2>/dev/null || true
  fi
  return 0
}

# Run a shell one-liner as a phase (needed for pipelines / globs).
run_sh() {
  local name="$1" logfile="$2" script="$3"
  run_phase "$name" "$logfile" bash -lc "$script"
}

have() { command -v "$1" >/dev/null 2>&1; }

# --------------------------------------------------------------------------- #
# 1. clone
# --------------------------------------------------------------------------- #
clone_repo() {
  if [ -d "${WS}/.git" ]; then
    log "reusing existing workspace ${WS}"
    return 0
  fi
  local url="https://github.com/${REPO}.git"
  # A token in the environment is used for private repos, but never written to
  # disk or into the git remote — the workspace is uploaded as an artifact.
  local auth=""
  if [ -n "${GH_TOKEN:-}" ]; then
    auth="https://x-access-token:${GH_TOKEN}@github.com/${REPO}.git"
  elif [ -n "${GITHUB_TOKEN:-}" ]; then
    auth="https://x-access-token:${GITHUB_TOKEN}@github.com/${REPO}.git"
  fi
  mkdir -p "$(dirname "$WS")"
  local args=(git clone --depth 30 --no-tags)
  [ -n "$REF" ] && args+=(--branch "$REF")
  if [ -n "$auth" ]; then
    run_phase clone clone.log "${args[@]}" "$auth" "$WS"
  else
    run_phase clone clone.log "${args[@]}" "$url" "$WS"
  fi
  if [ -d "${WS}/.git" ] && [ -n "$auth" ]; then
    git -C "$WS" remote set-url origin "$url" 2>/dev/null || true
  fi
  [ -d "${WS}/.git" ]
}

# --------------------------------------------------------------------------- #
# 2. stack detection
# --------------------------------------------------------------------------- #
STACKS=""
detect_stack() {
  local s=""
  [ -f "${WS}/package.json" ] && s="${s} node"
  { [ -f "${WS}/requirements.txt" ] || [ -f "${WS}/pyproject.toml" ] || \
    [ -f "${WS}/setup.py" ]; } && s="${s} python"
  [ -f "${WS}/Gemfile" ] && s="${s} ruby"
  { [ -f "${WS}/_config.yml" ] && [ -f "${WS}/Gemfile" ]; } && s="${s} jekyll"
  [ -f "${WS}/go.mod" ] && s="${s} go"
  [ -f "${WS}/Cargo.toml" ] && s="${s} rust"
  if [ -z "$s" ] && compgen -G "${WS}/*.sh" >/dev/null 2>&1; then s=" shell"; fi
  STACKS="${s# }"
  [ -n "$STACKS" ] || STACKS="unknown"
  log "stack: ${STACKS}"
}

has_stack() { case " ${STACKS} " in *" $1 "*) return 0 ;; *) return 1 ;; esac; }

# --------------------------------------------------------------------------- #
# 3. environment record
# --------------------------------------------------------------------------- #
write_env() {
  local sha branch
  sha=$(git -C "$WS" rev-parse --short HEAD 2>/dev/null || echo '?')
  branch=$(git -C "$WS" rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')
  {
    echo "# Environment"
    echo
    echo "| key | value |"
    echo "| --- | --- |"
    echo "| repo | \`${REPO}\` |"
    echo "| issue | #${ISSUE} |"
    echo "| ref | \`${branch}\` @ \`${sha}\` |"
    echo "| detected stack | ${STACKS} |"
    echo "| runner | $(uname -srm) |"
    echo "| captured | $(date -u '+%Y-%m-%d %H:%M UTC') |"
    for t in node npm python3 ruby bundle cargo shellcheck; do
      if have "$t"; then
        echo "| ${t} | $("$t" --version 2>&1 | head -1) |"
      fi
    done
    # `go --version` is not a thing — it prints a flag error into the record.
    have go && echo "| go | $(go version 2>&1 | head -1) |"
  } > "${OUT}/env.md"
}

# --------------------------------------------------------------------------- #
# 4. install / lint / test / build, per stack
# --------------------------------------------------------------------------- #
npm_script() {  # does package.json define this script?
  [ -f "${WS}/package.json" ] || return 1
  python3 - "$1" <<'PY' "${WS}/package.json"
import json, sys
name = sys.argv[1]
try:
    with open(sys.argv[2]) as fh:
        data = json.load(fh)
except Exception:
    sys.exit(1)
sys.exit(0 if name in (data.get("scripts") or {}) else 1)
PY
}

phase_node() {
  have npm || { skip node-install "npm not installed on this runner"; return; }
  # Always-latest policy: no lockfile install. `npm ci` would also hard-fail on
  # the missing lockfile the fleet deliberately does not commit.
  run_sh node-install install.log "cd '${WS}' && npm install --no-audit --no-fund"
  if npm_script lint; then
    run_sh node-lint lint.log "cd '${WS}' && npm run lint"
  else
    skip node-lint "no \`lint\` script in package.json"
  fi
  if npm_script test; then
    run_sh node-test test.log "cd '${WS}' && npm test"
  else
    skip node-test "no \`test\` script in package.json — this project's tests \
are elsewhere (check for cypress/, e2e/, or a CI workflow)"
  fi
  if npm_script build; then
    run_sh node-build build.log "cd '${WS}' && npm run build"
  else
    skip node-build "no \`build\` script in package.json"
  fi
}

phase_python() {
  have python3 || { skip python-venv "python3 not installed"; return; }
  # The isolated virtual environment: nothing installed here can reach the
  # runner's system python or another evidence run.
  run_sh python-venv install.log "cd '${WS}' && python3 -m venv .venv"
  [ -x "${WS}/.venv/bin/pip" ] || { skip python-install "venv creation failed"; return; }
  local pip="${WS}/.venv/bin/pip" py="${WS}/.venv/bin/python"
  run_sh python-install install.log "cd '${WS}' && '${pip}' install --upgrade pip \
&& { [ -f requirements.txt ] && '${pip}' install -r requirements.txt || true; } \
&& { [ -f pyproject.toml ] || [ -f setup.py ]; } && '${pip}' install -e . || true"
  if [ -d "${WS}/tests" ] || compgen -G "${WS}/test_*.py" >/dev/null 2>&1 || \
     compgen -G "${WS}/**/test_*.py" >/dev/null 2>&1; then
    run_sh python-test test.log "cd '${WS}' && '${pip}' install pytest >/dev/null 2>&1; \
'${py}' -m pytest -q"
  else
    skip python-test "no tests/ directory or test_*.py files found"
  fi
  if [ -f "${WS}/.flake8" ] || [ -f "${WS}/setup.cfg" ] || [ -f "${WS}/ruff.toml" ] || \
     grep -qs 'ruff\|flake8' "${WS}/pyproject.toml" 2>/dev/null; then
    run_sh python-lint lint.log "cd '${WS}' && '${pip}' install ruff >/dev/null 2>&1; \
'${WS}/.venv/bin/ruff' check . || '${py}' -m flake8 ."
  else
    skip python-lint "no ruff/flake8 configuration"
  fi
}

phase_ruby() {
  have bundle || { skip ruby-install "bundler not installed"; return; }
  # --path keeps gems inside the workspace, so the bundle is as disposable as
  # the clone and two evidence runs can never share state.
  run_sh ruby-install install.log \
    "cd '${WS}' && bundle config set --local path vendor/bundle && bundle install --jobs 4"
  if has_stack jekyll; then
    run_sh jekyll-build build.log "cd '${WS}' && bundle exec jekyll build --trace"
  elif [ -f "${WS}/Rakefile" ]; then
    run_sh ruby-test test.log "cd '${WS}' && bundle exec rake"
  elif [ -d "${WS}/spec" ]; then
    run_sh ruby-test test.log "cd '${WS}' && bundle exec rspec"
  else
    skip ruby-test "no Rakefile or spec/ directory"
  fi
}

phase_go() {
  have go || { skip go-build "go toolchain not installed"; return; }
  run_sh go-build build.log "cd '${WS}' && go build ./..."
  run_sh go-test test.log "cd '${WS}' && go test ./..."
}

phase_rust() {
  have cargo || { skip rust-build "cargo not installed"; return; }
  run_sh rust-build build.log "cd '${WS}' && cargo build --locked || cargo build"
  run_sh rust-test test.log "cd '${WS}' && cargo test"
}

phase_shell() {
  have shellcheck || { skip shellcheck "shellcheck not installed"; return; }
  run_sh shellcheck lint.log \
    "cd '${WS}' && find . -name '*.sh' -not -path './.git/*' -print0 \
| xargs -0 -r shellcheck --severity=warning"
}

run_stack_phases() {
  has_stack node && phase_node
  has_stack python && phase_python
  has_stack ruby && phase_ruby
  has_stack go && phase_go
  has_stack rust && phase_rust
  has_stack shell && phase_shell
  [ "$STACKS" = "unknown" ] && skip stack-detect \
    "no package.json / requirements.txt / Gemfile / go.mod / Cargo.toml found"
  return 0
}

# The caller-supplied reproduction. Never sourced from the issue body.
run_custom_cmd() {
  [ -n "$CUSTOM_CMD" ] || return 0
  run_sh repro repro.log "cd '${WS}' && ${CUSTOM_CMD}"
}

# --------------------------------------------------------------------------- #
# 5. screenshot — only where there is a rendered surface to look at
# --------------------------------------------------------------------------- #
static_dir() {
  local d
  for d in _site dist build public out; do
    [ -d "${WS}/${d}" ] && { printf '%s' "${WS}/${d}"; return 0; }
  done
  return 1
}

browser_bin() {
  local b
  for b in google-chrome chromium chromium-browser google-chrome-stable; do
    have "$b" && { printf '%s' "$b"; return 0; }
  done
  [ -x /opt/pw-browsers/chromium ] && { printf '%s' /opt/pw-browsers/chromium; return 0; }
  return 1
}

capture_screenshot() {
  [ "$SCREENSHOT" -eq 1 ] || { skip screenshot "disabled with --no-screenshot"; return; }
  local root port url server_pid=0 browser
  if ! root=$(static_dir); then
    skip screenshot "no built static output (_site/dist/build/public/out) to serve"
    return
  fi
  if ! browser=$(browser_bin); then
    skip screenshot "no chromium/chrome on this runner"
    return
  fi
  have python3 || { skip screenshot "python3 needed to serve the built output"; return; }
  port=8731
  ( cd "$root" && python3 -m http.server "$port" >/dev/null 2>&1 ) &
  server_pid=$!
  # Poll instead of sleeping blind: a static server is up in well under a second
  # and waiting a fixed 5s in every run is 5s of nothing.
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    if have curl && curl -fsS -o /dev/null "http://127.0.0.1:${port}/" 2>/dev/null; then
      break
    fi
    sleep 0.5
  done
  url="http://127.0.0.1:${port}/"
  run_phase screenshot screenshot.log "$browser" \
    --headless=new --disable-gpu --no-sandbox --hide-scrollbars \
    --window-size=1280,900 --virtual-time-budget=6000 \
    --screenshot="${SHOTS}/home.png" "$url"
  kill "$server_pid" 2>/dev/null || true
  wait "$server_pid" 2>/dev/null || true
  if [ ! -s "${SHOTS}/home.png" ]; then
    rm -f "${SHOTS}/home.png"
    log "      screenshot produced no file"
  fi
}

# --------------------------------------------------------------------------- #
# 6. candidate files — where in the tree this issue probably lives
# --------------------------------------------------------------------------- #
find_candidates() {
  local terms_file="${OUT}/.terms"
  : > "$terms_file"
  {
    printf '%s\n' "${ISSUE_TITLE:-}"
    [ -n "$BODY_FILE" ] && [ -f "$BODY_FILE" ] && cat "$BODY_FILE"
  } | tr ' \t' '\n\n' \
    | sed -E 's/^[^A-Za-z0-9_./-]+//; s/[^A-Za-z0-9_./-]+$//' \
    | grep -oE '^[A-Za-z0-9_./-]{5,}$' \
    | grep -viE '^(https?|github|issue|about|actual|expected|steps|error|errors|should|would|could|because|instead|there|their|which|while|where|after|before|behaviour|behavior|following|reproduce|reproduction)$' \
    | sort -u | head -40 > "$terms_file"

  {
    echo "### Candidate files"
    echo
    echo "Ranked by how many issue terms appear in each file. This is a"
    echo "STARTING POINT for tier 2, not a diagnosis."
    echo
    if [ ! -s "$terms_file" ]; then
      echo "_No searchable terms in the issue title or body._"
    else
      echo "Terms searched: $(tr '\n' ' ' < "$terms_file")"
      echo
      echo "| hits | file |"
      echo "| ---: | --- |"
      local term
      while IFS= read -r term; do
        [ -n "$term" ] || continue
        grep -rIl --exclude-dir=.git --exclude-dir=node_modules \
          --exclude-dir=.venv --exclude-dir=vendor --exclude-dir=_site \
          --exclude-dir=dist -F -- "$term" "$WS" 2>/dev/null || true
      done < "$terms_file" \
        | sed "s#^${WS}/##" | sort | uniq -c | sort -rn | head -15 \
        | while read -r count file; do echo "| ${count} | \`${file}\` |"; done
    fi
  } > "${OUT}/candidates.md"
}

# --------------------------------------------------------------------------- #
# 7. reported (not executed) repro commands from the issue body
# --------------------------------------------------------------------------- #
extract_repro() {
  local f="${OUT}/repro-candidates.md"
  {
    echo "### Reproduction commands quoted in the issue"
    echo
    echo "> ⚠️ **Extracted, never executed.** Issue text is attacker-controlled."
    echo "> Review each line before running it, and prefer the project's own"
    echo "> scripts. Pass a vetted command back with \`--cmd\` to have it run"
    echo "> inside the sandbox."
    echo
    if [ -n "$BODY_FILE" ] && [ -f "$BODY_FILE" ]; then
      if grep -qE '^\s*\$ |^\s*(npm|yarn|pnpm|python3?|pytest|bundle|rake|go|cargo|make|tools/|\./)' "$BODY_FILE"; then
        echo '```'
        grep -hE '^\s*\$ |^\s*(npm|yarn|pnpm|python3?|pytest|bundle|rake|go|cargo|make|tools/|\./)' \
          "$BODY_FILE" | head -20
        echo '```'
      else
        echo "_None found._"
      fi
    else
      echo "_No issue body supplied (\`--body-file\`)._"
    fi
  } > "$f"
}

# --------------------------------------------------------------------------- #
# 8. report
# --------------------------------------------------------------------------- #
log_excerpt() {  # file -> the most useful ~25 lines
  local f="$1"
  [ -s "$f" ] || return 1
  # Prefer the failure context; fall back to the tail.
  if grep -nEi 'error|fail|traceback|exception|✗|FAILED' "$f" >/dev/null 2>&1; then
    grep -nEi -m1 'error|fail|traceback|exception|✗|FAILED' "$f" \
      | cut -d: -f1 \
      | while read -r ln; do
          sed -n "$(( ln > 6 ? ln - 6 : 1 )),$(( ln + 18 ))p" "$f"
        done
  else
    tail -n 25 "$f"
  fi
}

write_report() {
  local md="${OUT}/evidence.md"
  {
    printf '<!-- issue-evidence key="%s#%s" at="%s" -->\n' \
      "$REPO" "$ISSUE" "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    echo
    echo "## 🔬 Evidence bundle"
    echo
    echo "Built by \`tools/issue-evidence.sh\` in an isolated virtual environment:"
    echo "a fresh clone of \`${REPO}\`, its own toolchain install, and the"
    echo "project's own lint / test / build. Everything below is observed output,"
    echo "not inference."
    echo
    sed -n '3,99p' "${OUT}/env.md"
    echo
    echo "### Results"
    echo
    echo "| phase | result | time | detail |"
    echo "| --- | --- | ---: | --- |"
    local name status secs detail logfile icon
    while IFS=$'\t' read -r name status secs detail logfile; do
      [ -n "$name" ] || continue
      case "$status" in
        pass) icon="✅ pass" ;;
        fail) icon="❌ fail" ;;
        timeout) icon="⏱ timeout" ;;
        *) icon="⏭ skipped" ;;
      esac
      echo "| \`${name}\` | ${icon} | ${secs}s | ${detail} |"
    done < "$PHASES"
    echo

    # Failing output is the point of the whole exercise — lead with it. The log
    # file is READ FROM THE RECORD, never guessed from the phase name: several
    # phases share one log (shellcheck writes lint.log), and a name→file guess
    # silently drops exactly the excerpt the reader came for.
    local any_fail=0 f
    while IFS=$'\t' read -r name status secs detail logfile; do
      case "$status" in fail|timeout) : ;; *) continue ;; esac
      any_fail=1
      [ -n "$logfile" ] || continue
      f="${LOGS}/${logfile}"
      [ -f "$f" ] || continue
      echo "<details><summary><code>${name}</code> — failing output</summary>"
      echo
      echo '```'
      log_excerpt "$f" | head -40
      echo '```'
      echo
      echo "</details>"
      echo
    done < "$PHASES"
    if [ "$any_fail" -eq 0 ]; then
      echo "> ✅ Nothing failed in the sandbox. If the issue reports a failure,"
      echo "> it is environment-specific, data-dependent, or needs a narrower"
      echo "> reproduction — say so explicitly rather than assuming."
      echo
    fi

    if [ -s "${SHOTS}/home.png" ]; then
      echo "### Screenshot"
      echo
      echo "\`screenshots/home.png\` — attached to this run's workflow artifact."
      echo
    fi

    cat "${OUT}/candidates.md"
    echo
    cat "${OUT}/repro-candidates.md"
    echo
    echo "---"
    echo
    echo "_Logs, screenshots, and the full workspace listing are attached to the"
    echo "\`issue-evidence-${SLUG}\` artifact on the workflow run that produced"
    echo "this comment._"
  } > "$md"

  python3 - "$PHASES" "$OUT" "$REPO" "$ISSUE" "$STACKS" <<'PY'
import json, os, sys
phases_path, out, repo, issue, stacks = sys.argv[1:6]
phases = []
with open(phases_path) as fh:
    for line in fh:
        parts = line.rstrip("\n").split("\t")
        if len(parts) >= 4 and parts[0]:
            phases.append({"name": parts[0], "status": parts[1],
                           "seconds": int(parts[2] or 0), "detail": parts[3],
                           "log": parts[4] if len(parts) > 4 else ""})
shots = os.path.join(out, "screenshots")
logs = os.path.join(out, "logs")
data = {
    "repo": repo,
    "issue": int(issue),
    "key": f"{repo}#{issue}",
    "stacks": stacks.split(),
    "phases": phases,
    "failed": [p["name"] for p in phases if p["status"] in ("fail", "timeout")],
    "skipped": [p["name"] for p in phases if p["status"] == "skipped"],
    "passed": [p["name"] for p in phases if p["status"] == "pass"],
    "reproduced": any(p["status"] in ("fail", "timeout") for p in phases
                      if "test" in p["name"] or p["name"] == "repro"),
    "screenshots": sorted(os.listdir(shots)) if os.path.isdir(shots) else [],
    "logs": sorted(os.listdir(logs)) if os.path.isdir(logs) else [],
}
with open(os.path.join(out, "evidence.json"), "w") as fh:
    json.dump(data, fh, indent=2)
    fh.write("\n")
PY
}

# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
ISSUE_TITLE="${ISSUE_TITLE:-}"

if [ "$RERUN" -eq 1 ]; then
  [ -d "${WS}/.git" ] || die "--rerun needs an existing workspace at ${WS}"
  log "re-running tests in ${WS}"
  detect_stack
  has_stack node && npm_script test && run_sh node-test-rerun test.log "cd '${WS}' && npm test"
  has_stack python && [ -x "${WS}/.venv/bin/python" ] && \
    run_sh python-test-rerun test.log "cd '${WS}' && '${WS}/.venv/bin/python' -m pytest -q"
  run_custom_cmd
  write_env
  find_candidates
  extract_repro
  write_report
  log "re-run report: ${OUT}/evidence.md"
  exit 0
fi

log "evidence bundle for ${REPO}#${ISSUE} → ${OUT}"
if ! clone_repo; then
  record clone fail 0 "could not clone ${REPO} (private, renamed, or no token)"
  STACKS="unknown"
  write_env
  : > "${OUT}/candidates.md"
  extract_repro
  write_report
  log "clone failed — wrote a degraded bundle rather than nothing"
  exit 0
fi

detect_stack
write_env
run_stack_phases
run_custom_cmd
capture_screenshot
find_candidates
extract_repro
write_report

log "done: ${OUT}/evidence.md"
exit 0
