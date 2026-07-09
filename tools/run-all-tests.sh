#!/usr/bin/env bash
#
# Run available verification checks across the whole dash.
#
# Fans out over EVERY checked-out submodule (not a hardcoded two) and runs each
# project's own test runner when its dependencies are present, skipping — loudly,
# with a reason — anything that can't run. A green result means "every suite that
# COULD run passed", and the skip list shows exactly what wasn't exercised. This
# replaces the previous cv+README-only script that reported a misleading pass.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_DIR
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
readonly PROJECT_ROOT

FAILED=0
RAN=0
SKIPPED=0
declare -a SKIP_REASONS=()

c_bold=$'\033[1m'; c_dim=$'\033[2m'; c_off=$'\033[0m'

log_info() { printf '[INFO] %s\n' "$1"; }
skip()     { SKIPPED=$((SKIPPED+1)); SKIP_REASONS+=("$1"); printf '%s[SKIP]%s %s\n' "$c_dim" "$c_off" "$1"; }

run_step() {
    local label="$1"; shift
    RAN=$((RAN+1))
    printf '\n[CHECK] %s\n' "$label"
    if "$@"; then
        printf '[PASS] %s\n' "$label"
    else
        printf '[FAIL] %s\n' "$label"
        FAILED=1
    fi
}

has_command() { command -v "$1" >/dev/null 2>&1; }

has_npm_script() {
    local dir="$1" name="$2"
    [[ -f "${dir}/package.json" ]] || return 1
    has_command node || return 1
    ( cd "$dir" && node -e "const p=require('./package.json');process.exit(p.scripts&&p.scripts[process.argv[1]]?0:1)" "$name" )
}

# Detect and run a submodule's own checks, or skip with a reason.
test_submodule() {
    local dir="$1" name; name="$(basename "$dir")"

    # The dash does not manage each submodule's dependency install, so we only
    # EXECUTE a suite when a project-local environment is clearly present — that
    # keeps a green result honest without turning "deps not installed" into a
    # false failure. Anything else is a reasoned skip.

    # Node project: run its test script only when node_modules is installed.
    if [[ -f "${dir}/package.json" ]]; then
        if ! has_npm_script "$dir" test; then skip "${name}: node project, no test script"; return; fi
        if ! has_command npm; then skip "${name}: npm not installed"; return; fi
        if [[ ! -d "${dir}/node_modules" ]]; then skip "${name}: node deps not installed (npm install)"; return; fi
        run_step "${name}: npm test" bash -c "cd '${dir}' && npm test --silent"
        return
    fi

    # Python project: run pytest only against a project-local venv.
    if [[ -f "${dir}/pytest.ini" || -d "${dir}/tests" || -d "${dir}/test" ]]; then
        local vpy=""
        [[ -x "${dir}/.venv/bin/python" ]] && vpy="${dir}/.venv/bin/python"
        [[ -z "$vpy" && -x "${dir}/venv/bin/python" ]] && vpy="${dir}/venv/bin/python"
        if [[ -n "$vpy" ]] && "$vpy" -c 'import pytest' >/dev/null 2>&1; then
            run_step "${name}: pytest" bash -c "cd '${dir}' && '${vpy}' -m pytest -q"
        else
            skip "${name}: python deps not installed (no local venv with pytest)"
        fi
        return
    fi

    skip "${name}: no local test environment (deps not installed here)"
}

run_submodule_checks() {
    printf '\n%s== Submodule test suites ==%s\n' "$c_bold" "$c_off"
    local sp dir
    while IFS= read -r sp; do
        dir="${PROJECT_ROOT}/${sp}"
        if [[ ! -d "$dir" ]] || [[ -z "$(ls -A "$dir" 2>/dev/null)" ]]; then
            skip "$(basename "$sp"): not checked out"; continue
        fi
        test_submodule "$dir"
    done < <(git -C "$PROJECT_ROOT" config -f .gitmodules --get-regexp '\.path$' | awk '{print $2}')
}

run_root_checks() {
    printf '\n%s== Root checks ==%s\n' "$c_bold" "$c_off"
    if has_command shellcheck; then
        run_step "tools shellcheck" bash -c "cd '${PROJECT_ROOT}' && shellcheck tools/*.sh"
        [[ -d "${PROJECT_ROOT}/projects/scripts" ]] && \
            run_step "scripts shellcheck" bash -c "cd '${PROJECT_ROOT}' && shellcheck projects/scripts/*.sh"
    else
        skip "shellcheck not installed"
    fi
    if has_command mkdocs; then
        run_step "MkDocs build" bash -c "cd '${PROJECT_ROOT}' && mkdocs build --clean"
    else
        skip "mkdocs not installed"
    fi
}

main() {
    log_info "Verification sweep from ${PROJECT_ROOT}"
    run_root_checks
    run_submodule_checks

    printf '\n%s== Summary ==%s\n' "$c_bold" "$c_off"
    printf '  ran %d · skipped %d\n' "$RAN" "$SKIPPED"
    if [[ "$FAILED" -ne 0 ]]; then
        printf '\n[FAIL] One or more checks failed.\n'
        return 1
    fi
    printf '\n[PASS] All %d executed checks passed (%d skipped — see reasons above).\n' "$RAN" "$SKIPPED"
}

main "$@"
