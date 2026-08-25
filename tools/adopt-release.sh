#!/usr/bin/env bash
# ============================================================================
# tools/adopt-release.sh — roll the standardized release pipeline into a repo
#
# Detects the repo's ecosystem, scaffolds the caller workflows + a release-please
# config (from templates/release-pipeline/), and opens a PR. The shared logic
# lives in bamr87/.github; this only adds the thin per-repo glue.
#
# Usage:
#   tools/adopt-release.sh <repo> [--owner bamr87] [--dry-run] [--no-pr]
#
#   <repo>      repo name (e.g. zpl-viewer) or a projects/<name> submodule path
#   --dry-run   build the branch locally, show the diff, but don't push/PR
#   --no-pr     push the branch but don't open a PR
# ============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEMPLATES="${ROOT}/templates/release-pipeline"
OWNER="bamr87"
DRY_RUN=false
OPEN_PR=true
BRANCH="chore/adopt-release-pipeline"
WORKDIR="${ADOPT_WORKDIR:-$HOME/bamr87-release-work}"

err() { printf '\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }
note() { printf '\033[36m▸ %s\033[0m\n' "$*"; }
ok()  { printf '\033[32m✓ %s\033[0m\n' "$*"; }

[[ $# -ge 1 ]] || err "usage: tools/adopt-release.sh <repo> [--owner X] [--dry-run] [--no-pr]"
REPO="${1#projects/}"; REPO="${REPO%/}"; shift
while [[ $# -gt 0 ]]; do
  case "$1" in
    --owner) OWNER="$2"; shift 2;;
    --dry-run) DRY_RUN=true; shift;;
    --no-pr) OPEN_PR=false; shift;;
    *) err "unknown arg: $1";;
  esac
done

command -v gh >/dev/null || err "gh CLI required"
command -v jq >/dev/null || err "jq required"

SLUG="${OWNER}/${REPO}"
note "Target: ${SLUG}"
gh repo view "$SLUG" >/dev/null 2>&1 || err "repo not found: $SLUG"

DEFAULT_BRANCH="$(gh api "repos/${SLUG}" --jq .default_branch)"
note "Default branch: ${DEFAULT_BRANCH}"

# --- fresh clone -----------------------------------------------------------
mkdir -p "$WORKDIR"
DIR="${WORKDIR}/${REPO}"
rm -rf "$DIR"
git clone --depth 1 "https://github.com/${SLUG}.git" "$DIR" >/dev/null 2>&1 || err "clone failed"
cd "$DIR"
git checkout -q -b "$BRANCH"

# --- detect ecosystem ------------------------------------------------------
# Relax pipefail here: a no-match grep in a version-extraction pipeline is normal
# and must not abort the script.
set +o pipefail
RELEASE_TYPE=simple; REGISTRY="GitHub Releases only"; SECRET="(none)"; VERSION_SOURCE="VERSION"
VERSION="0.1.0"; VERSION_FILE=""

if ls ./*.gemspec >/dev/null 2>&1; then
  RELEASE_TYPE=ruby; REGISTRY="RubyGems"; SECRET="RUBYGEMS_API_KEY"
  VERSION_FILE="$(find lib -name version.rb 2>/dev/null | head -1)"
  VERSION_SOURCE="${VERSION_FILE:-*.gemspec}"
  [[ -n "$VERSION_FILE" ]] && VERSION="$(grep -oE 'VERSION *= *"[^"]+"' "$VERSION_FILE" | grep -oE '[0-9][^"]*' | head -1)"
elif [[ -f package.json ]] && ! jq -e '.private == true' package.json >/dev/null 2>&1; then
  RELEASE_TYPE=node; REGISTRY="npm"; SECRET="NPM_TOKEN"; VERSION_SOURCE="package.json"
  VERSION="$(jq -r '.version // "0.1.0"' package.json)"
elif { [[ -f pyproject.toml ]] && grep -qE '^\[project\]|^\[tool\.poetry\]|^\[build-system\]' pyproject.toml; } || [[ -f setup.py ]]; then
  # Publishable Python package (has packaging metadata, not just tool config).
  RELEASE_TYPE=python; REGISTRY="PyPI (trusted publishing, OIDC)"; SECRET="(none, OIDC)"; VERSION_SOURCE="pyproject.toml"
  VERSION="$(grep -oE '^version *= *"[^"]+"' pyproject.toml 2>/dev/null | grep -oE '[0-9][^"]*' | head -1)"
  [[ -z "$VERSION" ]] && VERSION="$(grep -oE 'version *= *"[^"]+"' setup.py 2>/dev/null | grep -oE '[0-9][^"]*' | head -1)"
fi
# else: stays `simple` — versioning + CHANGELOG + GitHub Release, no package publish
# (covers docs / jekyll / bash / script repos and Python repos without packaging metadata).
VERSION="${VERSION:-0.1.0}"
set -o pipefail
note "Ecosystem: ${RELEASE_TYPE} · registry: ${REGISTRY} · version: ${VERSION}"

# --- scaffold caller workflows (never clobber existing CI) -----------------
mkdir -p .github/workflows
subst() { sed -e "s/__DEFAULT_BRANCH__/${DEFAULT_BRANCH}/g" "$1"; }

if [[ -f .github/workflows/ci.yml ]]; then
  note "ci.yml already exists — leaving the repo's CI untouched"
else
  subst "${TEMPLATES}/ci.yml" > .github/workflows/ci.yml; ok "added .github/workflows/ci.yml"
fi
[[ -f .github/workflows/release.yml ]] && err "release.yml already exists — resolve manually before adopting"
subst "${TEMPLATES}/release.yml" > .github/workflows/release.yml; ok "added .github/workflows/release.yml"

# --- release-please config + manifest --------------------------------------
case "$RELEASE_TYPE" in
  ruby)
    EXTRA=""
    [[ -f package.json ]] && EXTRA=', "extra-files": [ { "type": "json", "path": "package.json", "jsonpath": "$.version" } ]'
    # Only pin version-file when we actually found one; an empty "version-file": ""
    # breaks release-please. Without it, the ruby strategy falls back to its default.
    VF=""
    [[ -n "$VERSION_FILE" ]] && VF="\"version-file\": \"${VERSION_FILE}\", "
    cat > release-please-config.json <<JSON
{
  "\$schema": "https://raw.githubusercontent.com/googleapis/release-please/main/schemas/config.json",
  "packages": { ".": { "release-type": "ruby", ${VF}"changelog-path": "CHANGELOG.md"${EXTRA} } }
}
JSON
    [[ -z "$VERSION_FILE" ]] && note "no lib/**/version.rb found — omitted version-file; set it manually if needed"
    ;;
  *)
    cat > release-please-config.json <<JSON
{
  "\$schema": "https://raw.githubusercontent.com/googleapis/release-please/main/schemas/config.json",
  "packages": { ".": { "release-type": "${RELEASE_TYPE}", "changelog-path": "CHANGELOG.md" } }
}
JSON
    ;;
esac
echo "{ \".\": \"${VERSION}\" }" | jq . > .release-please-manifest.json
jq -e . release-please-config.json >/dev/null || err "generated config is invalid JSON"
ok "added release-please-config.json + .release-please-manifest.json (v${VERSION})"

# --- seed CHANGELOG + RELEASING --------------------------------------------
if [[ ! -f CHANGELOG.md ]]; then
  cat > CHANGELOG.md <<MD
# Changelog

All notable changes to this project are documented here. This file is maintained
automatically by [release-please](https://github.com/googleapis/release-please)
from [Conventional Commits](https://www.conventionalcommits.org/).
MD
  ok "seeded CHANGELOG.md"
fi
sed -e "s|__REGISTRY__|${REGISTRY}|g" -e "s|__VERSION_SOURCE__|${VERSION_SOURCE}|g" -e "s|__SECRET__|${SECRET}|g" \
  "${TEMPLATES}/RELEASING.md" > RELEASING.md; ok "added RELEASING.md"

# --- show / commit / push / PR ---------------------------------------------
git add -A
echo; note "Changes:"; git -c color.ui=always status --short; echo

if $DRY_RUN; then note "--dry-run: not pushing. Inspect ${DIR}"; exit 0; fi

UID_NUM="$(gh api user --jq .id)"; LOGIN="$(gh api user --jq .login)"
NOREPLY="${UID_NUM}+${LOGIN}@users.noreply.github.com"
git -c user.name="$LOGIN" -c user.email="$NOREPLY" commit -q -m "ci: adopt standardized release pipeline

Scaffolds release-please (${RELEASE_TYPE}) + caller workflows referencing
bamr87/.github. Conventional Commits now drive versioning, CHANGELOG, and the
GitHub Release; ${REGISTRY} publishing runs on release."
git push -u origin "$BRANCH" >/dev/null 2>&1 && ok "pushed ${BRANCH}"

$OPEN_PR || { note "--no-pr: skipping PR"; exit 0; }
gh pr create --repo "$SLUG" --base "$DEFAULT_BRANCH" --head "$BRANCH" \
  --title "ci: adopt standardized release pipeline" \
  --body "Adopts the shared [release pipeline](https://github.com/bamr87/.github#readme): release-please (\`${RELEASE_TYPE}\`) drives version + CHANGELOG + GitHub Release, then publishes to **${REGISTRY}**.

- Version source: \`${VERSION_SOURCE}\` (current: \`${VERSION}\`)
- Required secret: \`${SECRET}\`
- Caller workflows reference \`bamr87/.github@main\`; see \`RELEASING.md\`.

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
