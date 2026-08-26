#!/usr/bin/env bash
#
# install-prose-hook.sh — global git post-commit hook that auto-fixes the
# markdown-oneline CI blocker in EVERY repo on this machine
#
# The fleet's `markdown-oneline` gate (tools/fanout.sh --kit prose) fails CI
# whenever a hand-authored paragraph is soft-wrapped across lines. Fixing it
# after the red check costs a round-trip every time; this hook fixes it at
# commit time instead:
#
#   1. installs ~/.git-hooks/ and points `git config --global core.hooksPath`
#      at it, so it applies to the hub, every submodule, and any other clone
#   2. post-commit: runs unwrap-prose.py --write over the *.md files touched by
#      the commit (the repo's vendored tools/unwrap-prose.py when present, else
#      the hub copy vendored next to the hook), honouring the --exclude patterns
#      declared in the repo's own .github/workflows/markdown-oneline.yml
#   3. if anything changed, amends the commit in place (`--amend --no-edit`),
#      so the fixed commit is the one that gets pushed and CI-checked — set
#      PROSE_HOOK_MODE=commit to append a separate `style: unwrap prose` commit
#      instead of amending
#   4. every other hook name is a dispatcher that forwards to the repo's own
#      .git/hooks/<name> and .husky/<name>, so setting a global hooksPath does
#      not silently disable per-repo hooks (husky, pre-commit, ...)
#
# Skip once with PROSE_HOOK_SKIP=1 (e.g. `PROSE_HOOK_SKIP=1 git commit ...`).
#
# Usage:
#   tools/install-prose-hook.sh              # install / refresh
#   tools/install-prose-hook.sh --uninstall  # remove the hooks + global setting
#

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOOKS_DIR="${PROSE_HOOKS_DIR:-${HOME}/.git-hooks}"
UNINSTALL=false
# Every hook git knows how to run: each gets a dispatcher so per-repo hooks keep firing.
FORWARDED_HOOKS=(applypatch-msg pre-applypatch post-applypatch pre-commit pre-merge-commit
  prepare-commit-msg commit-msg post-checkout post-merge pre-push pre-rebase
  post-rewrite pre-auto-gc post-index-change reference-transaction)

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
# would fail every commit on a missing husky.sh.
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

# --- the post-commit hook ------------------------------------------------------
cat > "$HOOKS_DIR/post-commit" <<'HOOK'
#!/usr/bin/env bash
# Global post-commit: unwrap soft-wrapped markdown prose in the files this
# commit touched and fold the fix back into the commit, so the fleet's
# markdown-oneline CI gate never sees it. Installed by
# bamr87/bamr87 tools/install-prose-hook.sh.
set -uo pipefail

here="$(cd "$(dirname "$0")" && pwd)"

# Guards: explicit skip, recursion from our own amend, or a repo-local hook
# already running (keep per-repo post-commit behaviour regardless).
"$here/_forward" post-commit "$@"
[[ "${PROSE_HOOK_SKIP:-0}" == "1" ]] && exit 0
[[ -n "${PROSE_HOOK_RUNNING:-}" ]] && exit 0

git_dir="$(git rev-parse --git-dir 2>/dev/null)" || exit 0
top="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
cd "$top" || exit 0

# Never rewrite history mid-rebase/merge/cherry-pick — those commits are
# replayed by git, and amending underneath it corrupts the sequence.
for state in rebase-merge rebase-apply MERGE_HEAD CHERRY_PICK_HEAD REVERT_HEAD; do
    [[ -e "$git_dir/$state" ]] && exit 0
done

# Markdown files added/modified by this commit.
# (bash 3.2 on stock macOS has no mapfile — read line by line.)
files=()
while IFS= read -r f; do files+=("$f"); done \
    < <(git diff-tree --root --no-commit-id --name-only -r --diff-filter=AM HEAD -- '*.md' '*.markdown' 2>/dev/null)
[[ ${#files[@]} -eq 0 ]] && exit 0

# The repo's vendored copy is the version its CI runs; fall back to the hub copy.
fixer="tools/unwrap-prose.py"
[[ -f "$fixer" ]] || fixer="$here/unwrap-prose.py"
command -v python3 >/dev/null 2>&1 || exit 0

# Honour the repo's own gate excludes (from its markdown-oneline workflow);
# default to the fleet baseline when the workflow is absent.
excludes=(--exclude '(^|/)SCHEMA\.md$' --exclude '(^|/)CHANGELOG\.md$')
gate=".github/workflows/markdown-oneline.yml"
if [[ -f "$gate" ]] && grep -q -- "--exclude '" "$gate"; then
    excludes=()
    while IFS= read -r pat; do excludes+=(--exclude "$pat"); done \
        < <(grep -o -- "--exclude '[^']*'" "$gate" | sed "s/^--exclude '//; s/'$//")
fi

# Only touch files that are clean in the worktree (so an uncommitted edit to
# the same file is never swept into the commit).
targets=()
for f in "${files[@]+"${files[@]}"}"; do
    [[ -f "$f" ]] || continue
    git diff --quiet -- "$f" 2>/dev/null || continue
    targets+=("$f")
done
[[ ${#targets[@]} -eq 0 ]] && exit 0

if ! python3 "$fixer" --check "${excludes[@]}" "${targets[@]}" >/dev/null 2>&1; then
    python3 "$fixer" --write "${excludes[@]}" "${targets[@]}" >/dev/null 2>&1 || exit 0
    changed="$(git diff --name-only -- "${targets[@]}")"
    [[ -z "$changed" ]] && exit 0
    git add -- "${targets[@]}"
    export PROSE_HOOK_RUNNING=1
    if [[ "${PROSE_HOOK_MODE:-amend}" == "commit" ]]; then
        git commit --quiet --no-verify -m "style: unwrap soft-wrapped markdown prose (prose hook)"
        echo "prose-hook: added fix commit for:" >&2
    else
        git commit --quiet --no-verify --amend --no-edit
        echo "prose-hook: amended commit with unwrapped prose in:" >&2
    fi
    printf '  %s\n' $changed >&2
fi
exit 0
HOOK
chmod +x "$HOOKS_DIR/post-commit"

git config --global core.hooksPath "$HOOKS_DIR"

# Repos that pin their own core.hooksPath (husky) shadow the global one; the
# dispatcher forwards to .husky anyway, so unsetting the local value is safe.
shadowed=()
while IFS= read -r repo; do
    if v="$(git -C "$repo" config --local --get core.hooksPath 2>/dev/null)"; then
        shadowed+=("$repo -> $v")
    fi
done < <(printf '%s\n' "$ROOT" "$ROOT"/projects/*/)

echo "installed $HOOKS_DIR (global core.hooksPath); post-commit auto-unwraps markdown prose"
if [[ ${#shadowed[@]} -gt 0 ]]; then
    echo "NOTE: these repos set a local core.hooksPath that overrides the global hook;"
    echo "      run 'git -C <repo> config --unset core.hooksPath' to enable it there:"
    printf '  %s\n' "${shadowed[@]}"
fi
