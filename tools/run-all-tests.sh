#!/usr/bin/env bash
#
# Run the root repository's available verification checks.
#
# This script intentionally delegates to each project/submodule's existing
# commands instead of inventing a separate test framework at the parent level.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_DIR
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
readonly PROJECT_ROOT

FAILED=0

log_info() {
    printf '[INFO] %s\n' "$1"
}

log_warn() {
    printf '[WARN] %s\n' "$1"
}

run_step() {
    local label="$1"
    shift

    printf '\n[CHECK] %s\n' "$label"
    if "$@"; then
        printf '[PASS] %s\n' "$label"
    else
        printf '[FAIL] %s\n' "$label"
        FAILED=1
    fi
}

has_command() {
    command -v "$1" >/dev/null 2>&1
}

has_npm_script() {
    local package_dir="$1"
    local script_name="$2"

    if ! has_command node || [[ ! -f "${package_dir}/package.json" ]]; then
        return 1
    fi

    (
        cd "$package_dir"
        node -e "const pkg = require('./package.json'); process.exit(pkg.scripts && pkg.scripts[process.argv[1]] ? 0 : 1)" "$script_name"
    )
}

run_cv_checks() {
    local cv_dir="${PROJECT_ROOT}/cv"

    if [[ ! -d "$cv_dir" ]]; then
        log_warn "Skipping cv checks; cv/ is not initialized."
        return 0
    fi

    if ! has_command npm; then
        log_warn "Skipping cv checks; npm is not installed."
        return 0
    fi

    if [[ ! -d "${cv_dir}/node_modules" ]]; then
        log_warn "Skipping cv checks; dependencies are not installed. Run 'cd cv && npm install' first."
        return 0
    fi

    if has_npm_script "$cv_dir" test; then
        run_step "cv npm test" bash -c "cd \"${cv_dir}\" && npm test"
    fi

    if has_npm_script "$cv_dir" lint; then
        run_step "cv npm run lint" bash -c "cd \"${cv_dir}\" && npm run lint"
    fi

    if has_npm_script "$cv_dir" build; then
        run_step "cv npm run build" bash -c "cd \"${cv_dir}\" && npm run build"
    fi
}

run_docs_checks() {
    local readme_dir="${PROJECT_ROOT}/README"

    if [[ -d "${readme_dir}/tests" ]] && has_command python3 && python3 -m pytest --version >/dev/null 2>&1; then
        run_step "README pytest" bash -c "cd \"${readme_dir}\" && python3 -m pytest tests"
    else
        log_warn "Skipping README pytest; tests, python3, or pytest are unavailable."
    fi

    if has_command mkdocs; then
        run_step "MkDocs build" bash -c "cd \"${PROJECT_ROOT}\" && mkdocs build --clean"
    else
        log_warn "Skipping MkDocs build; mkdocs is not installed."
    fi
}

run_shell_checks() {
    if ! has_command shellcheck; then
        log_warn "Skipping shellcheck; shellcheck is not installed."
        return 0
    fi

    run_step "tools shellcheck" bash -c "cd \"${PROJECT_ROOT}\" && shellcheck tools/*.sh"

    if [[ -d "${PROJECT_ROOT}/scripts" ]]; then
        run_step "scripts shellcheck" bash -c "cd \"${PROJECT_ROOT}\" && shellcheck scripts/*.sh"
    fi
}

main() {
    log_info "Running repository verification checks from ${PROJECT_ROOT}"

    run_cv_checks
    run_docs_checks
    run_shell_checks

    if [[ "$FAILED" -ne 0 ]]; then
        printf '\n[FAIL] One or more checks failed.\n'
        return 1
    fi

    printf '\n[PASS] All available checks passed.\n'
}

main "$@"
