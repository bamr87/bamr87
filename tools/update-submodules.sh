#!/usr/bin/env bash
#
# update-submodules.sh — refresh the projects/ folder to be current
#
# Brings every Git submodule onto its DECLARED branch (from .gitmodules) at the
# latest remote commit, then records the moved pointers in the root repo.
#
# "Current" here means, per submodule:
#   - initialized + checked out (missing ones are cloned)
#   - sitting ON its declared branch — not detached HEAD (the repo house rule)
#   - fast-forwarded to origin/<branch>
#
# Safe by default: a submodule with uncommitted (tracked) changes, unpushed
# commits, or a history that has diverged from its remote is SKIPPED with a
# warning rather than reset — your local work is never destroyed. Use --force
# to hard-reset those onto origin/<branch>, or --detach for the old behaviour
# (detached HEAD at the remote tip).
#

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || { echo "cannot cd to repo root: $ROOT" >&2; exit 1; }

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Helper functions
info()   { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()   { echo -e "${YELLOW}[WARN]${NC} $1"; }
error()  { echo -e "${RED}[ERROR]${NC} $1"; }
status() { echo -e "${BLUE}[STATUS]${NC} $1"; }
ok()     { echo -e "  ${GREEN}✓${NC} $1"; }

# Usage information
usage() {
    cat << EOF
Usage: $0 [OPTIONS] [SUBMODULE]

Refreshes Git submodules to their declared branch at the latest remote commit
and records the moved pointers in the root repository.

OPTIONS:
    -h, --help          Show this help message
    -s, --status        Show current submodule status only
    -a, --all           Update all submodules (default)
    -c, --check         Check for available updates without applying
    --detach            Leave submodules in detached HEAD at origin/<branch>
                        (legacy behaviour) instead of checking out the branch
    --force             Hard-reset submodules that are dirty or have diverged
                        from origin/<branch> (DESTROYS local submodule changes)
    --no-commit         Don't create a commit for pointer changes
    --no-push           Don't push changes (even in CI)

ARGUMENTS:
    SUBMODULE           A submodule to update. Accepts the path (projects/cv),
                        the short name (cv), or the .gitmodules name.

EXAMPLES:
    $0                  # Refresh all submodules onto their declared branch
    $0 cv               # Refresh only the cv submodule
    $0 --status         # Show current status
    $0 --check          # Check for updates without applying
    $0 --force          # Also re-align dirty/diverged submodules

EOF
    exit 0
}

# Parse arguments
SUBMODULE=""
STATUS_ONLY=false
CHECK_ONLY=false
NO_COMMIT=false
NO_PUSH=false
DETACH=false
FORCE=false

while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help)   usage ;;
        -s|--status) STATUS_ONLY=true; shift ;;
        -a|--all)    SUBMODULE=""; shift ;;
        -c|--check)  CHECK_ONLY=true; shift ;;
        --detach)    DETACH=true; shift ;;
        --force)     FORCE=true; shift ;;
        --no-commit) NO_COMMIT=true; shift ;;
        --no-push)   NO_PUSH=true; shift ;;
        -*)          error "Unknown option: $1"; usage ;;
        *)           SUBMODULE="$1"; shift ;;
    esac
done

# ---------------------------------------------------------------------------
# .gitmodules helpers
# ---------------------------------------------------------------------------

# List every submodule path declared in .gitmodules (one per line).
all_paths() {
    git config -f .gitmodules --get-regexp '\.path$' | awk '{print $2}'
}

# Resolve a user-supplied argument (path / short name / .gitmodules name) to a
# declared submodule path. Prints the path and returns 0, or returns 1.
resolve_path() {
    local arg="$1" key val name
    while read -r key val; do
        name="${key#submodule.}"; name="${name%.path}"
        if [[ "$arg" == "$val" || "$arg" == "$name" || "projects/$arg" == "$val" ]]; then
            echo "$val"; return 0
        fi
    done < <(git config -f .gitmodules --get-regexp '\.path$')
    return 1
}

# Declared branch for a submodule path (defaults to main when unset).
declared_branch() {
    local path="$1" key val name br=""
    while read -r key val; do
        name="${key#submodule.}"; name="${name%.path}"
        if [[ "$val" == "$path" ]]; then
            br="$(git config -f .gitmodules "submodule.${name}.branch" 2>/dev/null || true)"
            break
        fi
    done < <(git config -f .gitmodules --get-regexp '\.path$')
    echo "${br:-main}"
}

# ---------------------------------------------------------------------------
# Status / check (read-only)
# ---------------------------------------------------------------------------

show_status() {
    info "Current submodule status (declared branch ↔ checked-out branch):"
    echo ""
    local p branch cur dirty
    while read -r p; do
        [[ -e "$p/.git" ]] || { printf '    %-34s %s\n' "$p" "(not initialized)"; continue; }
        branch="$(declared_branch "$p")"
        cur="$(git -C "$p" rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')"
        dirty=""
        [[ -n "$(git -C "$p" status --porcelain --untracked-files=no 2>/dev/null)" ]] && dirty=" *dirty*"
        local flag="  "
        [[ "$cur" != "$branch" && "$cur" != "HEAD" ]] && flag="${YELLOW}!!${NC}"
        printf '  %b %-34s declared=%-8s on=%-26s%s\n' "$flag" "$p" "$branch" "$cur" "$dirty"
    done < <(all_paths)
    echo ""
    info "(!! = checked-out branch differs from declared; HEAD = detached, which is fine)"
}

check_updates() {
    info "Checking for available updates against each declared branch..."
    local p branch
    while read -r p; do
        [[ -e "$p/.git" ]] || { echo "  - $p: not initialized"; continue; }
        branch="$(declared_branch "$p")"
        git -C "$p" fetch --prune --quiet origin 2>/dev/null || { echo "  ? $p: fetch failed"; continue; }
        if ! git -C "$p" rev-parse --verify --quiet "origin/${branch}" >/dev/null; then
            echo "  ? $p: origin/${branch} not found"
            continue
        fi
        local behind
        behind="$(git -C "$p" rev-list --count "HEAD..origin/${branch}" 2>/dev/null || echo 0)"
        if [[ "${behind:-0}" -gt 0 ]]; then
            echo "  ✓ $p: ${behind} new commit(s) on ${branch}"
            git -C "$p" log --oneline "HEAD..origin/${branch}" 2>/dev/null | head -3 | sed 's/^/      /'
        else
            echo "  - $p: up to date with ${branch}"
        fi
    done < <(all_paths)
}

# ---------------------------------------------------------------------------
# Refresh one submodule onto its declared branch at origin tip (safe).
# ---------------------------------------------------------------------------
refresh_one() {
    local path="$1"
    local branch; branch="$(declared_branch "$path")"

    # Clone if the submodule is not yet checked out.
    if [[ ! -e "$path/.git" ]]; then
        info "Initializing ${path}"
        git submodule update --init --recursive --quiet "$path" \
            || { error "${path}: init failed"; return 1; }
    fi

    if ! git -C "$path" fetch --prune --quiet origin; then
        warn "${path}: fetch failed (offline?) — leaving as-is"
        return 0
    fi

    if ! git -C "$path" rev-parse --verify --quiet "origin/${branch}" >/dev/null; then
        warn "${path}: origin/${branch} not found — leaving as-is"
        return 0
    fi

    # Refuse to clobber uncommitted tracked changes (untracked files are safe).
    if [[ -n "$(git -C "$path" status --porcelain --untracked-files=no)" ]]; then
        if [[ "$FORCE" == false ]]; then
            warn "${path}: uncommitted changes — skipping (use --force to override)"
            return 0
        fi
        git -C "$path" reset --hard --quiet HEAD
    fi

    # Legacy mode: detached HEAD at the remote tip.
    if [[ "$DETACH" == true ]]; then
        if git -C "$path" checkout --quiet --detach "origin/${branch}"; then
            ok "${path} → detached @ origin/${branch}"
        else
            warn "${path}: detach checkout failed"
        fi
        return 0
    fi

    # Put HEAD on the declared branch (create it tracking origin if needed).
    if git -C "$path" show-ref --verify --quiet "refs/heads/${branch}"; then
        git -C "$path" checkout --quiet "$branch" \
            || { warn "${path}: checkout ${branch} failed"; return 0; }
    else
        git -C "$path" checkout --quiet -b "$branch" --track "origin/${branch}" \
            || { warn "${path}: cannot create branch ${branch}"; return 0; }
    fi

    # Reconcile the local branch with origin/<branch>.
    local ahead behind
    behind="$(git -C "$path" rev-list --count "HEAD..origin/${branch}" 2>/dev/null || echo 0)"
    ahead="$(git -C "$path" rev-list --count "origin/${branch}..HEAD" 2>/dev/null || echo 0)"

    if [[ "${ahead:-0}" -gt 0 && "${behind:-0}" -gt 0 ]]; then
        if [[ "$FORCE" == true ]]; then
            git -C "$path" reset --hard --quiet "origin/${branch}"
            warn "${path}: diverged — hard-reset to origin/${branch} (--force)"
        else
            warn "${path}: diverged from origin/${branch} (ahead ${ahead}, behind ${behind}) — skipping (use --force)"
        fi
    elif [[ "${behind:-0}" -gt 0 ]]; then
        if git -C "$path" merge --ff-only --quiet "origin/${branch}"; then
            ok "${path} → ${branch} (advanced ${behind})"
        else
            warn "${path}: fast-forward to origin/${branch} failed"
        fi
    elif [[ "${ahead:-0}" -gt 0 ]]; then
        warn "${path}: ${branch} is ${ahead} commit(s) ahead of origin (unpushed) — left as-is"
    else
        ok "${path} → ${branch} (up to date)"
    fi
}

# ---------------------------------------------------------------------------
# Main execution
# ---------------------------------------------------------------------------

if [[ "$STATUS_ONLY" == true ]]; then
    show_status
    exit 0
fi

if [[ "$CHECK_ONLY" == true ]]; then
    check_updates
    exit 0
fi

# Build the list of target paths.
TARGET_PATHS=()
if [[ -n "$SUBMODULE" ]]; then
    if ! p="$(resolve_path "$SUBMODULE")"; then
        error "Submodule '${SUBMODULE}' not found in .gitmodules"
        exit 1
    fi
    TARGET_PATHS=("$p")
    info "Refreshing submodule: ${p}"
else
    info "Refreshing all submodules onto their declared branch..."
    while read -r p; do TARGET_PATHS+=("$p"); done < <(all_paths)
fi

if [[ ${#TARGET_PATHS[@]} -eq 0 ]]; then
    warn "No submodules declared in .gitmodules. Nothing to do."
    exit 0
fi

# Keep submodule URLs in sync with .gitmodules. Missing submodules are cloned
# per-path inside refresh_one; we deliberately do NOT run a blanket
# `git submodule update`, which would reset already-checked-out submodules to
# their recorded SHA and discard local work.
git submodule sync --quiet --recursive

for p in "${TARGET_PATHS[@]}"; do
    refresh_one "$p"
done

# ---------------------------------------------------------------------------
# Record moved pointers in the root repository
# ---------------------------------------------------------------------------
status "Checking for pointer changes in the root repository..."

# Stage only the targeted submodule gitlinks (+ .gitmodules if it changed),
# never unrelated working-tree changes. A pointer is recorded only when the
# submodule's HEAD is exactly at origin/<branch> — i.e. a commit that exists on
# the remote — so the root commit never references an unpushed submodule commit.
for p in "${TARGET_PATHS[@]}"; do
    [[ -e "$p/.git" ]] || continue
    branch="$(declared_branch "$p")"
    head_sha="$(git -C "$p" rev-parse HEAD 2>/dev/null || echo head)"
    origin_sha="$(git -C "$p" rev-parse "origin/${branch}" 2>/dev/null || echo origin)"
    if [[ "$head_sha" == "$origin_sha" ]]; then
        git add -- "$p" 2>/dev/null || true
    elif ! git diff --quiet -- "$p" 2>/dev/null; then
        warn "${p}: pointer moved but HEAD is not at origin/${branch} — not recording (push the submodule first)"
    fi
done
git add -- .gitmodules 2>/dev/null || true

if git diff --cached --quiet; then
    info "No submodule pointer changes detected. Nothing to commit."
else
    info "Submodule pointer(s) changed:"
    echo ""
    git diff --cached --submodule=log
    echo ""

    if [[ "$NO_COMMIT" == false ]]; then
        if [[ -n "$SUBMODULE" ]]; then
            COMMIT_MSG="chore: update ${SUBMODULE} submodule pointer"
        else
            COMMIT_MSG="chore: update submodule pointers"
        fi

        info "Creating commit..."
        git commit -m "$COMMIT_MSG"

        if [[ -n "${GITHUB_ACTIONS:-}" && "$NO_PUSH" == false ]]; then
            info "Running in GitHub Actions; pushing updates..."
            git push
        elif [[ "$NO_PUSH" == false ]]; then
            warn "Not in GitHub Actions. Run 'git push' to publish changes."
        else
            info "Skipping push (--no-push specified)"
        fi
    else
        info "Skipping commit (--no-commit specified). Changes are staged."
    fi
fi

echo ""
info "Refresh complete!"
show_status
