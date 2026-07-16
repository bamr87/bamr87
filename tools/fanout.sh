#!/usr/bin/env bash
# ============================================================================
# tools/fanout.sh — shared downward-propagation engine for the fleet
#
# One safety posture for every fan-out: clone each target repo, create the
# kit branch, seed files, commit, and (only with --apply) push + open a PR.
# Called by .github/workflows/standardize-fanout.yml and schema-fanout.yml;
# runs locally too. Auth (`gh` / FANOUT_TOKEN) needs contents:write +
# pull-requests:write AND workflows:write on the targets — every kit can seed
# .github/workflows/* files, which GitHub refuses to push without it.
#
# Guarantees:
#   - DRY RUN by default: builds the branch, prints the diffstat, no push/PR
#   - never pushes to a default branch (PR only, --force-with-lease)
#   - skips submodules whose upstream isn't github.com/bamr87 (external
#     mirrors like microsoft/skills)
#   - additive-only seeding: never overwrites a file the target already has
#   - one bot identity: bamr87-bot <10567847+bamr87@users.noreply.github.com>
#
# Usage:
#   tools/fanout.sh --kit standardize --target <name|all> [--apply]
#                   [--artifacts editorconfig,ci,agent-context,claude]
#   tools/fanout.sh --kit schema --target <name|all> [--apply]
#
# Kits:
#   standardize  branch chore/standardize-baseline; artifacts (default
#                editorconfig,ci):
#                  editorconfig   copy the hub's .editorconfig
#                  ci             templates/standard-ci/ci.yml caller
#                  agent-context  templates/agent-context/CLAUDE.template.md,
#                                 only when the repo has NO agent-context file
#                  claude         templates/agent-context/claude.yml
#                                 (@claude mention workflow, OAuth-first)
#   schema       branch chore/schema-adoption; delegates to
#                tools/seed-schema.sh (SCHEMA.md contracts + linter + CI)
# ============================================================================
set -euo pipefail

HUB="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BOT_NAME="bamr87-bot"
BOT_EMAIL="10567847+bamr87@users.noreply.github.com"

KIT="" TARGET="" ARTIFACTS="editorconfig,ci" APPLY=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --kit)       KIT="${2:?--kit needs a value}"; shift ;;
    --target)    TARGET="${2:?--target needs a value}"; shift ;;
    --artifacts) ARTIFACTS="${2:?--artifacts needs a value}"; shift ;;
    --apply)     APPLY=1 ;;
    *) echo "unknown flag: $1" >&2; exit 2 ;;
  esac
  shift
done

case "$KIT" in
  standardize|schema) ;;
  *) echo "usage: tools/fanout.sh --kit <standardize|schema> --target <name|all> [--artifacts csv] [--apply]" >&2
     exit 2 ;;
esac
[[ -n "$TARGET" ]] || { echo "--target is required (submodule name, or 'all')" >&2; exit 2; }

case "$KIT" in
  standardize)
    BRANCH="chore/standardize-baseline"
    COMMIT_MSG="chore: adopt standardization baseline (${ARTIFACTS})"
    PR_TITLE="chore: adopt standardization baseline"
    PR_BODY="Automated by bamr87 standardize-fanout (tools/fanout.sh): seeds the baseline artifacts (${ARTIFACTS}). Additive-only — nothing the repo already has is overwritten. See bamr87/bamr87 docs/STANDARDS.md."
    ;;
  schema)
    BRANCH="chore/schema-adoption"
    COMMIT_MSG="docs: adopt Pyramid Schema (SCHEMA.md contracts + linter + CI)"
    PR_TITLE="docs: adopt Pyramid Schema structural contracts"
    PR_BODY="$(printf 'Automated by bamr87 schema-fanout: seeds SCHEMA.md contracts in every directory, the vendored schema_lint.py, a schema-check CI gate, and the agent protocol in CLAUDE.md.\n\nScaffold purposes are TODO until the agent/human pass fills them (dispatch schema-fanout with agent_fill, or edit by hand). See bamr87/bamr87 docs/SCHEMA-FRAMEWORK.md.')"
    ;;
esac

seed_standardize() {
  # cwd = target clone; $1 = repo name, $2 = default branch
  local name="$1" def="$2"
  case ",$ARTIFACTS," in *,editorconfig,*)
    [[ -f .editorconfig ]] || cp "$HUB/.editorconfig" .editorconfig ;;
  esac
  case ",$ARTIFACTS," in *,ci,*)
    if [[ ! -f .github/workflows/ci.yml ]]; then
      mkdir -p .github/workflows
      sed "s/__DEFAULT_BRANCH__/${def}/g" "$HUB/templates/standard-ci/ci.yml" \
        > .github/workflows/ci.yml
    fi ;;
  esac
  case ",$ARTIFACTS," in *,agent-context,*)
    if [[ ! -f CLAUDE.md && ! -f AGENTS.md && ! -f .github/copilot-instructions.md && ! -f .cursorrules ]]; then
      sed -e "s/__PROJECT_NAME__/${name}/g" -e "s/__DEFAULT_BRANCH__/${def}/g" \
        "$HUB/templates/agent-context/CLAUDE.template.md" > CLAUDE.md
    fi ;;
  esac
  case ",$ARTIFACTS," in *,claude,*)
    if [[ ! -f .github/workflows/claude.yml ]]; then
      mkdir -p .github/workflows
      cp "$HUB/templates/agent-context/claude.yml" .github/workflows/claude.yml
    fi ;;
  esac
}

run_one() {
  local path="$1" name sect url slug def work rc
  name="$(basename "$path")"
  sect="$(git config -f "$HUB/.gitmodules" --get-regexp '^submodule\..*\.path$' \
          | awk -v p="$path" '$2==p{print $1}' | sed 's/^submodule\.//; s/\.path$//')"
  if [[ -z "$sect" ]]; then
    echo "skip ${name}: not in .gitmodules"; return 0
  fi
  url="$(git config -f "$HUB/.gitmodules" --get "submodule.${sect}.url")"
  case "$url" in
    *github.com/bamr87/*|*github.com:bamr87/*) ;;
    *) echo "skip ${name}: external upstream (${url})"; return 0 ;;
  esac
  slug="bamr87/$(basename "${url%.git}")"
  work="$(mktemp -d)"
  echo "::group::${slug}"
  if ! gh repo clone "$slug" "$work" -- --depth=1 >/dev/null 2>&1; then
    echo "skip ${slug}: clone failed"; echo "::endgroup::"; rm -rf "$work"; return 0
  fi
  # gh authenticates the clone itself but not later pushes from this repo —
  # route git credentials through gh (uses GH_TOKEN in CI, keyring locally).
  git -C "$work" config credential.helper '!gh auth git-credential'
  # Seed in a subshell whose exit code we capture WITHOUT a condition context
  # (that would suppress errexit inside it), so cleanup always runs and a
  # failure is reported to the caller instead of aborting the whole script.
  set +e
  (
    set -e
    def="$(gh api "repos/${slug}" --jq .default_branch)"
    cd "$work"
    git checkout -b "$BRANCH"
    case "$KIT" in
      standardize) seed_standardize "$(basename "${url%.git}")" "$def" ;;
      schema)      "$HUB/tools/seed-schema.sh" "$work" --apply --default-branch "$def" ;;
    esac
    if [[ -z "$(git status --porcelain)" ]]; then
      echo "${slug}: already conformant"; exit 0
    fi
    git add -A
    git -c user.name="$BOT_NAME" -c user.email="$BOT_EMAIL" \
      commit -m "$COMMIT_MSG" >/dev/null
    if [[ "$APPLY" -eq 0 ]]; then
      echo "${slug}: DRY RUN — would open PR:"; git show --stat HEAD | head -25; exit 0
    fi
    # A depth-1 (single-branch) clone has no tracking ref for the kit branch,
    # and its restricted fetch refspec means a plain fetch lands in FETCH_HEAD
    # only — fetch with an explicit refspec so --force-with-lease has lease
    # info when the branch already exists remotely (re-run / earlier fan-out).
    git fetch origin "+refs/heads/${BRANCH}:refs/remotes/origin/${BRANCH}" >/dev/null 2>&1 || true
    git push -u origin "$BRANCH" --force-with-lease
    gh pr create --repo "$slug" --base "$def" --head "$BRANCH" \
      --title "$PR_TITLE" --body "$PR_BODY" \
      || echo "${slug}: PR may already exist"
  )
  rc=$?
  set -e
  rm -rf "$work"
  echo "::endgroup::"
  return "$rc"
}

# Process substitution (not a pipe) keeps the loop in the main shell so the
# failure counter survives; per-repo failures warn and continue — one flaky
# target must not strand the rest of the fleet. macOS bash 3.2-compatible.
if [[ "$TARGET" == "all" ]]; then
  FAILED=0
  while IFS= read -r p; do
    set +e
    ( set -e; run_one "$p" )
    rc=$?
    set -e
    if [[ "$rc" -ne 0 ]]; then
      echo "::warning::${p}: fan-out failed (exit ${rc}) — continuing with remaining targets"
      FAILED=$((FAILED + 1))
    fi
  done < <(git config -f "$HUB/.gitmodules" --get-regexp '^submodule\..*\.path$' | awk '{print $2}')
  if [[ "$FAILED" -gt 0 ]]; then
    echo "::error::${FAILED} target(s) failed — see warnings above"
    exit 1
  fi
else
  run_one "projects/${TARGET}"
fi
