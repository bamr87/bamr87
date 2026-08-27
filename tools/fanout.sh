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
#   - additive-only seeding for the seeding kits (standardize/schema/prose):
#     never overwrites a file the target already has. The deps-latest kit is
#     the deliberate exception — converting a repo to the always-latest
#     dependency policy MEANS editing manifests and deleting lockfiles
#     (docs/DEPENDENCIES.md); every other guarantee here still applies to it
#   - one bot identity: bamr87-bot <10567847+bamr87@users.noreply.github.com>
#
# Usage:
#   tools/fanout.sh --kit standardize --target <name|all> [--apply] [--upgrade]
#                   [--artifacts editorconfig,ci,agent-context,claude,claude-settings,
#                    claude-guardrails,claude-agent-auditor]
#   tools/fanout.sh --kit schema --target <name|all> [--apply]
#   tools/fanout.sh --kit prose --target <name|all> [--apply]
#   tools/fanout.sh --kit deps-latest --target <name|all> [--apply]
#
# Kits:
#   standardize  branch chore/standardize-baseline; artifacts (default
#                editorconfig,ci):
#                  editorconfig    copy the hub's .editorconfig
#                  ci              templates/standard-ci/ci.yml caller
#                  agent-context   templates/agent-context/CLAUDE.template.md,
#                                  only when the repo has NO agent-context file
#                  claude          templates/agent-context/claude.yml
#                                  (@claude mention workflow, OAuth-first)
#                  claude-settings templates/agent-context/settings.template.json
#                                  → .claude/settings.json (minimal read-only
#                                  permissions baseline)
#                  claude-guardrails      quarantine.template.md →
#                                  .claude/skills/_shared/quarantine.md (the
#                                  canonical shared guardrails doc; FF-0021)
#                  claude-agent-auditor   agent-auditor.template.md →
#                                  .claude/agents/agent-auditor.md, only when
#                                  no auditor-role agent exists (FF-0020)
#                The three claude-* .claude artifacts are OPT-IN (never in the
#                default set); other hooks/skills/commands/agents stay
#                repo-local and never fan out.
#                Seeded agent-context/claude files carry a `kit: agent-context
#                vX.Y.Z` stamp (from templates/agent-context/VERSION).
#   schema       branch chore/schema-adoption; delegates to
#                tools/seed-schema.sh (SCHEMA.md contracts + linter + CI)
#   prose        branch style/markdown-oneline; vendors the Liquid-safe
#                tools/unwrap-prose.py, seeds the markdown-oneline CI gate,
#                and does a one-time unwrap of wrapped prose
#                (SCHEMA.md/CHANGELOG.md skipped)
#   deps-latest  branch chore/deps-latest; converts the repo to the fleet's
#                ALWAYS-LATEST dependency policy via tools/unpin-deps.sh —
#                strips exact pins (package.json/requirements*.txt/Gemfile),
#                deletes + gitignores lockfiles, npm ci → npm install,
#                lockfile-keyed caches removed, action tags floated to @major
#                (_data/fleet.yml `dependencies:`, docs/DEPENDENCIES.md)
#
# --upgrade (every templated artifact, not just claude.yml):
#   Each kit dir carries a VERSION and an archive/ of the shapes it has seeded
#   over time. A target's existing file is refreshed ONLY when it is
#   byte-identical to the current template or to one of those archived shapes —
#   proof it was machine-seeded and never touched. Anything else is treated as
#   hand-modified and left alone, stamp or no stamp.
#
#   Keeping archive/ current is therefore load-bearing: SNAPSHOT THE OUTGOING
#   SHAPE INTO archive/ BEFORE editing a template. Skip that and every deployed
#   copy reads as hand-modified, so --upgrade silently stops reaching the fleet
#   — which is exactly how templates/prose/ sat two major action versions BEHIND
#   its own 30 deployed copies (fixed in prose kit 0.2.0). The reverse failure
#   is worse: re-seeding from a stale template downgrades the fleet.
# ============================================================================
set -euo pipefail

HUB="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BOT_NAME="bamr87-bot"
BOT_EMAIL="10567847+bamr87@users.noreply.github.com"

KIT="" TARGET="" ARTIFACTS="editorconfig,ci" APPLY=0 UPGRADE=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --kit)       KIT="${2:?--kit needs a value}"; shift ;;
    --target)    TARGET="${2:?--target needs a value}"; shift ;;
    --artifacts) ARTIFACTS="${2:?--artifacts needs a value}"; shift ;;
    --apply)     APPLY=1 ;;
    --upgrade)   UPGRADE=1 ;;
    *) echo "unknown flag: $1" >&2; exit 2 ;;
  esac
  shift
done

kit_version() {  # $1 = kit dir under templates/
  local v="$HUB/templates/$1/VERSION"
  [[ -f "$v" ]] && awk '/^version:/{print $2; exit}' "$v" || echo "0.0.0"
}

# Kit version stamped into seeded agent-context files (see the VERSION file).
AC_VERSION="$(kit_version agent-context)"
PROSE_VERSION="$(kit_version prose)"
CI_VERSION="$(kit_version standard-ci)"

# Render a kit template exactly as seeding would, so an on-disk copy can be
# compared byte-for-byte against it.
render_kit_template() {  # $1 template, $2 repo name, $3 default branch, $4 kit version
  sed -e "s/__PROJECT_NAME__/${2}/g" \
      -e "s/__DEFAULT_BRANCH__/${3}/g" \
      -e "s/__KIT_VERSION__/${4}/g" "$1"
}

# True when the on-disk file is byte-identical to some ARCHIVED machine-seeded
# shape of its template — i.e. it was seeded by a previous kit version and never
# touched, so --upgrade may replace it. Hand-modified copies never match and are
# always left alone. Archived shapes live beside the template as
# archive/<template-basename>-<version>[-<variant>].yml.
machine_seeded() {  # $1 file, $2 template, $3 repo name, $4 default branch, $5 version
  local f="$1" tpl="$2" dir base cand tmp
  dir="$(dirname "$tpl")"; base="$(basename "$tpl" .yml)"
  tmp="$(mktemp)"
  for cand in "$dir/archive/$base"-*.yml; do
    [[ -f "$cand" ]] || continue
    render_kit_template "$cand" "$3" "$4" "$5" > "$tmp"
    if cmp -s "$f" "$tmp"; then rm -f "$tmp"; return 0; fi
  done
  rm -f "$tmp"
  return 1
}

# Seed one templated workflow artifact, or report/refresh an existing copy.
# This is the single upgrade path for EVERY kit artifact: previously only
# claude.yml could be upgraded, which is how the prose kit drifted two major
# action versions behind the fleet unnoticed.
seed_workflow_artifact() {  # $1 label, $2 dest, $3 template, $4 name, $5 branch, $6 version
  local label="$1" dest="$2" tpl="$3" name="$4" def="$5" ver="$6" stamp
  if [[ ! -f "$dest" ]]; then
    mkdir -p "$(dirname "$dest")"
    render_kit_template "$tpl" "$name" "$def" "$ver" > "$dest"
    echo "${label}: seeded (kit v${ver})"
  elif cmp -s "$dest" <(render_kit_template "$tpl" "$name" "$def" "$ver"); then
    echo "${label}: current (kit v${ver})"
  elif machine_seeded "$dest" "$tpl" "$name" "$def" "$ver"; then
    if [[ "$UPGRADE" -eq 1 ]]; then
      render_kit_template "$tpl" "$name" "$def" "$ver" > "$dest"
      echo "${label}: upgraded machine seed -> kit v${ver}"
    else
      echo "${label}: upgradeable machine seed (latest kit v${ver}; rerun with --upgrade)"
    fi
  else
    stamp="$(sed -n 's/^# kit: [a-z-]* v//p' "$dest" | head -1)"
    echo "${label}: hand-modified — left alone (stamp: ${stamp:-none})"
  fi
}

case "$KIT" in
  standardize|schema|prose|deps-latest) ;;
  *) echo "usage: tools/fanout.sh --kit <standardize|schema|prose|deps-latest> --target <name|all> [--artifacts csv] [--apply]" >&2
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
  prose)
    BRANCH="style/markdown-oneline"
    COMMIT_MSG="style(markdown): one paragraph per line + CI enforcement"
    PR_TITLE="style(markdown): enforce one paragraph per line"
    PR_BODY="Automated by bamr87 prose-fanout (tools/fanout.sh): unwraps soft-wrapped markdown prose so each paragraph is a single line — Liquid/HTML/tables/code/front-matter left byte-for-byte, and SCHEMA.md/CHANGELOG.md skipped. Also vendors tools/unwrap-prose.py and seeds a markdown-oneline CI check. Additive-only. See bamr87/bamr87."
    ;;
  deps-latest)
    BRANCH="chore/deps-latest"
    COMMIT_MSG="build(deps): adopt fleet always-latest dependency policy"
    PR_TITLE="build(deps): always-latest dependencies — drop pins and lockfiles"
    PR_BODY="Automated by bamr87 deps-fanout (tools/fanout.sh --kit deps-latest): adopts the fleet's ALWAYS-LATEST dependency policy — strips exact version pins from package.json/requirements*.txt/Gemfile, deletes and gitignores lockfiles, floats GitHub Actions on their major tags, and adapts CI installs (npm ci → npm install; lockfile-keyed caches removed). Every install now resolves the newest published versions; breakage surfaces in CI and is triaged by the hub's daily fleet-pulse loop. Follow-ups the script won't automate (pyproject/poetry/Pipfile tables, hash-pinned requirements, npm overrides) are listed in the run log. See bamr87/bamr87 docs/DEPENDENCIES.md."
    ;;
esac

seed_standardize() {
  # cwd = target clone; $1 = repo name, $2 = default branch
  local name="$1" def="$2"
  case ",$ARTIFACTS," in *,editorconfig,*)
    [[ -f .editorconfig ]] || cp "$HUB/.editorconfig" .editorconfig ;;
  esac
  case ",$ARTIFACTS," in *,ci,*)
    seed_workflow_artifact "ci.yml" .github/workflows/ci.yml \
      "$HUB/templates/standard-ci/ci.yml" "$name" "$def" "$CI_VERSION" ;;
  esac
  case ",$ARTIFACTS," in *,agent-context,*)
    if [[ ! -f CLAUDE.md && ! -f AGENTS.md && ! -f .github/copilot-instructions.md && ! -f .cursorrules ]]; then
      sed -e "s/__PROJECT_NAME__/${name}/g" -e "s/__DEFAULT_BRANCH__/${def}/g" \
          -e "s/__KIT_VERSION__/${AC_VERSION}/g" \
        "$HUB/templates/agent-context/CLAUDE.template.md" > CLAUDE.md
    fi ;;
  esac
  case ",$ARTIFACTS," in *,claude,*)
    seed_workflow_artifact "claude.yml" .github/workflows/claude.yml \
      "$HUB/templates/agent-context/claude.yml" "$name" "$def" "$AC_VERSION" ;;
  esac
  case ",$ARTIFACTS," in *,claude-settings,*)
    if [[ ! -f .claude/settings.json ]]; then
      mkdir -p .claude
      cp "$HUB/templates/agent-context/settings.template.json" .claude/settings.json
    fi ;;
  esac
  case ",$ARTIFACTS," in *,claude-guardrails,*)
    if [[ ! -f .claude/skills/_shared/quarantine.md ]]; then
      mkdir -p .claude/skills/_shared
      sed -e "s/__PROJECT_NAME__/${name}/g" -e "s/__KIT_VERSION__/${AC_VERSION}/g" \
        "$HUB/templates/agent-context/quarantine.template.md" > .claude/skills/_shared/quarantine.md
    fi ;;
  esac
  case ",$ARTIFACTS," in *,claude-agent-auditor,*)
    # Skip when ANY auditor-role agent exists (hand-authored auditors are theirs).
    if [[ ! -f .claude/agents/agent-auditor.md && ! -f .claude/agents/agent-reviewer.md ]]; then
      mkdir -p .claude/agents
      sed -e "s/__PROJECT_NAME__/${name}/g" -e "s/__KIT_VERSION__/${AC_VERSION}/g" \
        "$HUB/templates/agent-context/agent-auditor.template.md" > .claude/agents/agent-auditor.md
    fi ;;
  esac
}

seed_prose() {
  # cwd = target clone; $1 = repo name (unused), $2 = default branch.
  # Liquid-safe: unwrap-prose.py only joins wrapped prose, so this is safe even
  # in Jekyll repos where blanket prettier would merge {% %} tags and break
  # rendering. Additive: nothing the repo already has is overwritten.
  local name="$1" def="$2"
  # 1. vendor the Liquid-safe unwrapper
  mkdir -p tools
  if [[ ! -f tools/unwrap-prose.py ]]; then
    cp "$HUB/tools/unwrap-prose.py" tools/unwrap-prose.py
  elif ! cmp -s tools/unwrap-prose.py "$HUB/tools/unwrap-prose.py"; then
    # The vendored copy is the fan-out payload — a drifted one silently changes
    # what the gate enforces. Refresh it only under --upgrade, same posture as
    # the workflow artifacts.
    if [[ "$UPGRADE" -eq 1 ]]; then
      cp "$HUB/tools/unwrap-prose.py" tools/unwrap-prose.py
      echo "unwrap-prose.py: upgraded to hub copy"
    else
      echo "unwrap-prose.py: drifted from hub copy (rerun with --upgrade to refresh)"
    fi
  fi
  # 2. seed the markdown-oneline CI gate
  seed_workflow_artifact "markdown-oneline.yml" .github/workflows/markdown-oneline.yml \
    "$HUB/templates/prose/markdown-oneline.yml" "$name" "$def" "$PROSE_VERSION"
  # 3. one-time fix: unwrap wrapped prose in every tracked markdown file, leaving
  #    lint-gated SCHEMA.md contracts and release-please CHANGELOGs untouched.
  #    Honour the repo's OWN gate excludes when it declares any: seeding with the
  #    defaults rewrote 24 machine-authored quest reports in it-journey, which
  #    exempts exactly those paths — a PR its own gate would never have asked for,
  #    against files the quest loop regenerates wrapped anyway.
  local ex pat
  ex=(--exclude '(^|/)SCHEMA\.md$' --exclude '(^|/)CHANGELOG\.md$')
  if [[ -f .github/workflows/markdown-oneline.yml ]] \
     && grep -q -- "--exclude '" .github/workflows/markdown-oneline.yml; then
    ex=()
    while IFS= read -r pat; do ex+=(--exclude "$pat"); done \
      < <(grep -o -- "--exclude '[^']*'" .github/workflows/markdown-oneline.yml \
          | sed "s/^--exclude '//; s/'$//")
  fi
  python3 tools/unwrap-prose.py --write "${ex[@]}" >/dev/null 2>&1 || true
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
      prose)       seed_prose "$(basename "${url%.git}")" "$def" ;;
      deps-latest) "$HUB/tools/unpin-deps.sh" . ;;
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
    # The kit branch is machine-owned: re-runs regenerate it. Bare
    # --force-with-lease is useless here — a single-branch clone's fetch
    # refspec doesn't map the kit branch, so git ignores even an explicitly
    # fetched tracking ref and rejects with 'stale info'. Fetch the remote
    # tip and lease on it EXPLICITLY; if the branch doesn't exist yet, a
    # plain push creates it.
    if git fetch origin "+refs/heads/${BRANCH}:refs/remotes/origin/${BRANCH}" >/dev/null 2>&1; then
      git push -u origin "$BRANCH" \
        --force-with-lease="${BRANCH}:$(git rev-parse "refs/remotes/origin/${BRANCH}")"
    else
      git push -u origin "$BRANCH"
    fi
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
