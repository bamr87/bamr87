#!/usr/bin/env bash
#
# install-prose-hook.sh — global git pre-commit hook that fixes the
# markdown-oneline blocker before a commit exists, in EVERY repo on this machine
#
# The fleet's `markdown-oneline` gate enforces "one paragraph per line". CI now
# self-heals a pull request that breaks it (templates/prose/markdown-oneline.yml),
# but the cheapest red build is the one that never runs: this hook fixes the
# prose locally, so the commit is already correct when it is pushed.
#
#   1. installs ~/.git-hooks/ and points `git config --global core.hooksPath`
#      at it, so one install covers the hub, every submodule, and any future
#      clone — no per-repo setup, nothing to remember in a fresh checkout
#   2. pre-commit: runs unwrap-prose.py --write over the STAGED *.md files (the
#      repo's vendored tools/unwrap-prose.py when present, else the copy
#      vendored beside the hook), honouring the --exclude patterns declared in
#      that repo's own .github/workflows/markdown-oneline.yml, and restages
#      them — the commit is born correct, with no history rewrite
#   3. every hook name then forwards to the repo's own .git/hooks/<name> and
#      .husky/<name>, so a global hooksPath does not silently disable per-repo
#      hooks; the prose fix runs FIRST, so repo-local linters see fixed content
#
# Skip once with PROSE_HOOK_SKIP=1 (e.g. `PROSE_HOOK_SKIP=1 git commit ...`).
#
# Caveat: the `pre-commit` FRAMEWORK refuses to install while core.hooksPath is
# set ("Cowardly refusing..."). Nothing in this fleet installs it today, but if
# a repo needs it, run --uninstall (or unset core.hooksPath) there first.
#
# Usage:
#   tools/install-prose-hook.sh              # install / refresh
#   tools/install-prose-hook.sh --uninstall  # remove the hooks + global setting
#

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOOKS_DIR="${PROSE_HOOKS_DIR:-${HOME}/.git-hooks}"
UNINSTALL=false
# Every hook git knows how to run: each gets a dispatcher so per-repo hooks keep
# firing. pre-commit is handled separately (it carries the prose fix).
FORWARDED_HOOKS=(applypatch-msg pre-applypatch post-applypatch pre-merge-commit
  prepare-commit-msg commit-msg post-commit post-checkout post-merge pre-push
  pre-rebase post-rewrite pre-auto-gc post-index-change reference-transaction)

while [[ $# -gt 0 ]]; do
    case $1 in
        --uninstall) UNINSTALL=true; shift ;;
        -h|--help)   sed -n '2,31p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *)           echo "unknown option: $1" >&2; exit 1 ;;
    esac
done

if $UNINSTALL; then
    if [[ "$(git config --global --get core.hooksPath || true)" == "$HOOKS_DIR" ]]; then
        git config --global --unset core.hooksPath
    fi
    rm -rf "$HOOKS_DIR"
    echo "removed $HOOKS_DIR and global core.hooksPath"
    exit 0
fi

mkdir -p "$HOOKS_DIR"

# --- shared forwarder: run the repo's own hook of the same name, if any -------
cat > "$HOOKS_DIR/_forward" <<'HOOK'
#!/usr/bin/env bash
# Forward a git hook to the repo-local implementations that a global
# core.hooksPath would otherwise shadow. Usage: _forward <hook-name> "$@"
name="$1"; shift
git_dir="$(git rev-parse --git-dir 2>/dev/null)" || exit 0
top="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
candidates=("$git_dir/hooks/$name")
# Only run .husky/<name> when husky is actually installed (its _/ runtime
# exists); a checked-in .husky/ without `npm install` is a stale shim that
# would fail every commit on a missing husky.sh — the hub's is exactly that.
if [[ -f "$top/.husky/_/h" || -f "$top/.husky/_/husky.sh" ]]; then
    candidates+=("$top/.husky/_/$name" "$top/.husky/$name")
fi
for candidate in "${candidates[@]}"; do
    if [[ -x "$candidate" ]]; then
        "$candidate" "$@" || exit $?
        break   # husky's _/<name> wraps .husky/<name>; never run both
    fi
done
exit 0
HOOK
chmod +x "$HOOKS_DIR/_forward"

for h in "${FORWARDED_HOOKS[@]}"; do
    printf '#!/usr/bin/env bash\nexec "$(dirname "$0")/_forward" %s "$@"\n' "$h" > "$HOOKS_DIR/$h"
    chmod +x "$HOOKS_DIR/$h"
done

# --- fallback fixer for repos that have not received the prose kit ------------
cp "$ROOT/tools/unwrap-prose.py" "$HOOKS_DIR/unwrap-prose.py"

# --- the pre-commit hook -------------------------------------------------------
cat > "$HOOKS_DIR/pre-commit" <<'HOOK'
#!/usr/bin/env bash
# Global pre-commit: unwrap soft-wrapped markdown prose in the files being
# committed and restage them, so the commit is born passing the fleet's
# markdown-oneline gate — and the CI run it would have cost never happens.
# Installed by bamr87/bamr87 tools/install-prose-hook.sh.
# (bash 3.2 on stock macOS has no mapfile — hence the read loops.)
set -uo pipefail

here="$(cd "$(dirname "$0")" && pwd)"

fix_prose() {
    [[ "${PROSE_HOOK_SKIP:-0}" == "1" ]] && return 0
    command -v python3 >/dev/null 2>&1 || return 0

    local top; top="$(git rev-parse --show-toplevel 2>/dev/null)" || return 0
    cd "$top" || return 0

    # The repo's vendored copy is the version its CI runs; else the hub copy.
    local fixer="tools/unwrap-prose.py"
    [[ -f "$fixer" ]] || fixer="$here/unwrap-prose.py"
    [[ -f "$fixer" ]] || return 0

    # Honour the repo's own gate excludes; fall back to the fleet baseline.
    local excludes gate pat
    excludes=(--exclude '(^|/)SCHEMA\.md$' --exclude '(^|/)CHANGELOG\.md$')
    gate=".github/workflows/markdown-oneline.yml"
    if [[ -f "$gate" ]] && grep -q -- "--exclude '" "$gate"; then
        excludes=()
        while IFS= read -r pat; do excludes+=(--exclude "$pat"); done \
            < <(grep -o -- "--exclude '[^']*'" "$gate" | sed "s/^--exclude '//; s/'\$//")
    fi

    local staged=() targets=() f
    while IFS= read -r f; do staged+=("$f"); done \
        < <(git diff --cached --name-only --diff-filter=AM -- '*.md' '*.markdown' 2>/dev/null)
    [[ ${#staged[@]} -eq 0 ]] && return 0

    # Only touch files whose worktree copy matches the index. A partially
    # staged file would otherwise have its UNSTAGED edits swept into the
    # commit by the restage below — the classic pre-commit-formatter bug.
    for f in "${staged[@]+"${staged[@]}"}"; do
        [[ -f "$f" ]] || continue
        git diff --quiet -- "$f" 2>/dev/null || continue
        targets+=("$f")
    done
    [[ ${#targets[@]} -eq 0 ]] && return 0

    python3 "$fixer" --check "${excludes[@]}" "${targets[@]}" >/dev/null 2>&1 && return 0
    python3 "$fixer" --write "${excludes[@]}" "${targets[@]}" >/dev/null 2>&1 || return 0

    local changed; changed="$(git diff --name-only -- "${targets[@]}")"
    [[ -z "$changed" ]] && return 0
    echo "$changed" | while IFS= read -r f; do [[ -n "$f" ]] && git add -- "$f"; done
    echo "prose-hook: unwrapped markdown prose in:" >&2
    echo "$changed" | sed 's/^/  /' >&2
    return 0
}

fix_prose
# Repo-local pre-commit hooks run last, so they see the fixed content.
exec "$here/_forward" pre-commit "$@"
HOOK
chmod +x "$HOOKS_DIR/pre-commit"

# The old kit shipped the fix as a post-commit amend; that hook is now a plain
# forwarder (rewritten above), so an upgrade in place needs no cleanup.
git config --global core.hooksPath "$HOOKS_DIR"

# Repos that pin their own core.hooksPath (husky) shadow the global one; the
# dispatcher forwards to .husky anyway, so unsetting the local value is safe.
shadowed=()
while IFS= read -r repo; do
    if v="$(git -C "$repo" config --local --get core.hooksPath 2>/dev/null)"; then
        shadowed+=("$repo -> $v")
    fi
done < <(printf '%s\n' "$ROOT" "$ROOT"/projects/*/)

echo "installed $HOOKS_DIR (global core.hooksPath); pre-commit auto-unwraps markdown prose"
if [[ ${#shadowed[@]} -gt 0 ]]; then
    echo "NOTE: these repos set a local core.hooksPath that overrides the global hook;"
    echo "      run 'git -C <repo> config --unset core.hooksPath' to enable it there:"
    printf '  %s\n' "${shadowed[@]}"
fi
