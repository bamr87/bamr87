#!/usr/bin/env bash
# ============================================================================
# tools/seed-schema.sh — seed the Pyramid Schema kit into one repo
#
# Idempotent and additive-only: never overwrites an existing file, `init`
# never touches an existing SCHEMA.md, and the agent-protocol snippet is
# appended only when the destination lacks a '## SCHEMA.md protocol' heading.
#
# What lands in the target (from templates/schema/ + tools/):
#   tools/schema_lint.py                    vendored stdlib linter
#   SCHEMA.md (every directory)             scaffolds via `schema_lint.py init`
#   .github/workflows/schema-check.yml      CI gate (__DEFAULT_BRANCH__ filled)
#   CLAUDE.md (or AGENTS.md)                protocol snippet appended
#
# Usage:
#   tools/seed-schema.sh <submodule-name | path> [--apply]
#                        [--default-branch BR] [--force-external]
#
# DRY RUN by default — prints the plan. Pass --apply to write. Refuses
# submodules whose upstream isn't github.com/bamr87 (e.g. the microsoft/skills
# mirror) unless --force-external. After seeding a local submodule, commit
# inside the submodule's own repo first (see CLAUDE.md), then bump the pointer.
# ============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
KIT="$ROOT/templates/schema"
PY="${PYTHON:-python3}"

TARGET_ARG="${1:-}"
[[ -n "$TARGET_ARG" ]] || {
  echo "usage: tools/seed-schema.sh <submodule-name|path> [--apply] [--default-branch BR] [--force-external]" >&2
  exit 2
}
shift
APPLY=0 BRANCH="" FORCE_EXT=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply) APPLY=1 ;;
    --default-branch) BRANCH="${2:?--default-branch needs a value}"; shift ;;
    --force-external) FORCE_EXT=1 ;;
    *) echo "unknown flag: $1" >&2; exit 2 ;;
  esac
  shift
done

if [[ -d "$TARGET_ARG" ]]; then
  TARGET="$(cd "$TARGET_ARG" && pwd)"
elif [[ -d "$ROOT/projects/$TARGET_ARG" ]]; then
  TARGET="$ROOT/projects/$TARGET_ARG"
else
  echo "no such target: $TARGET_ARG (not a directory, not a projects/ submodule)" >&2
  exit 2
fi

# Ownership guard + branch lookup for local submodules.
REL="${TARGET#"$ROOT"/}"
if [[ "$REL" == projects/* ]]; then
  sect="$(git config -f "$ROOT/.gitmodules" --get-regexp '^submodule\..*\.path$' 2>/dev/null \
          | awk -v p="$REL" '$2==p{print $1}' | sed 's/^submodule\.//; s/\.path$//')" || sect=""
  if [[ -n "${sect:-}" ]]; then
    url="$(git config -f "$ROOT/.gitmodules" --get "submodule.${sect}.url" 2>/dev/null || true)"
    case "$url" in
      *github.com/bamr87/*|*github.com:bamr87/*) ;;
      "") ;;
      *) if [[ $FORCE_EXT -eq 0 ]]; then
           echo "refusing to seed external submodule ($url) — pass --force-external to override" >&2
           exit 3
         fi ;;
    esac
    [[ -z "$BRANCH" ]] && BRANCH="$(git config -f "$ROOT/.gitmodules" --get "submodule.${sect}.branch" 2>/dev/null || true)"
  fi
fi
[[ -z "$BRANCH" ]] && BRANCH="$(git -C "$TARGET" symbolic-ref --short HEAD 2>/dev/null || echo main)"

MODE="DRY RUN (pass --apply to write)"; [[ $APPLY -eq 1 ]] && MODE="APPLY"
echo "== seed-schema → ${REL:-$TARGET} (branch: $BRANCH; $MODE) =="

step() { if [[ $APPLY -eq 1 ]]; then printf '  + %s\n' "$1"; else printf '  ~ would: %s\n' "$1"; fi; }
have() { printf '  = %s\n' "$1"; }

# 1. Vendored linter
if [[ -f "$TARGET/tools/schema_lint.py" ]]; then
  have "tools/schema_lint.py already present"
else
  step "vendor tools/schema_lint.py"
  if [[ $APPLY -eq 1 ]]; then
    mkdir -p "$TARGET/tools"
    cp "$ROOT/tools/schema_lint.py" "$TARGET/tools/schema_lint.py"
    chmod +x "$TARGET/tools/schema_lint.py"
  fi
fi

# 2. CI gate
WF="$TARGET/.github/workflows/schema-check.yml"
if [[ -f "$WF" ]]; then
  have ".github/workflows/schema-check.yml already present"
else
  step "seed .github/workflows/schema-check.yml (gates on: $BRANCH)"
  if [[ $APPLY -eq 1 ]]; then
    mkdir -p "$TARGET/.github/workflows"
    sed "s/__DEFAULT_BRANCH__/$BRANCH/g" "$KIT/schema-check.yml" > "$WF"
  fi
fi

# 3. Agent protocol snippet (CLAUDE.md preferred, AGENTS.md fallback)
DEST="$TARGET/CLAUDE.md"
[[ ! -f "$DEST" && -f "$TARGET/AGENTS.md" ]] && DEST="$TARGET/AGENTS.md"
if [[ -f "$DEST" ]] && grep -q '^## SCHEMA.md protocol' "$DEST"; then
  have "protocol already in $(basename "$DEST")"
else
  step "append SCHEMA.md protocol to $(basename "$DEST")"
  if [[ $APPLY -eq 1 ]]; then
    snippet="$(sed '1{/^<!--/d;}' "$KIT/CLAUDE.snippet.md")"
    if [[ -f "$DEST" ]]; then
      printf '\n%s\n' "$snippet" >> "$DEST"
    else
      printf '%s\n' "$snippet" > "$DEST"
    fi
  fi
fi

# 4. Scaffold the pyramid (never overwrites an existing SCHEMA.md)
if [[ $APPLY -eq 1 ]]; then
  "$PY" "$ROOT/tools/schema_lint.py" init "$TARGET" | sed 's/^/  /'
else
  step "scaffold SCHEMA.md into every directory (schema_lint.py init)"
fi

# 5. Verify
if [[ $APPLY -eq 1 ]]; then
  if "$PY" "$TARGET/tools/schema_lint.py" check "$TARGET" >/dev/null 2>&1; then
    echo "  ✓ pyramid lints green"
  else
    echo "  ✗ pyramid has errors — inspect: $PY tools/schema_lint.py check ." >&2
    exit 1
  fi
  echo "Next: replace TODO purposes (or dispatch schema-fanout with agent_fill),"
  echo "      then commit INSIDE the target repo first — see CLAUDE.md."
else
  step "verify: schema_lint.py check"
fi
