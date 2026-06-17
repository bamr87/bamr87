#!/usr/bin/env bash
# ============================================================================
# tools/protect-branch.sh — require the CI gate before merging to the default
# branch of a repo. Needs admin on the repo.
#
# Usage:
#   tools/protect-branch.sh <repo> [--owner bamr87] [--checks "CI / 🧪 Test,CI / 🎨 Lint"]
#
# By default it requires a PR (1 approving review), linear history, and the named
# status checks. Inspect a repo's check names with:  gh pr checks <num> -R owner/repo
# ============================================================================
set -euo pipefail

OWNER="bamr87"
CHECKS_DEFAULT="ci"   # the job name from the caller's ci.yml; adjust per repo

[[ $# -ge 1 ]] || { echo "usage: tools/protect-branch.sh <repo> [--owner X] [--checks \"a,b\"]" >&2; exit 1; }
REPO="${1#projects/}"; REPO="${REPO%/}"; shift
CHECKS="$CHECKS_DEFAULT"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --owner) OWNER="$2"; shift 2;;
    --checks) CHECKS="$2"; shift 2;;
    *) echo "unknown arg: $1" >&2; exit 1;;
  esac
done

command -v gh >/dev/null || { echo "gh required" >&2; exit 1; }
command -v jq >/dev/null || { echo "jq required" >&2; exit 1; }

SLUG="${OWNER}/${REPO}"
BRANCH="$(gh api "repos/${SLUG}" --jq .default_branch)"
echo "▸ Protecting ${SLUG}@${BRANCH} — requiring checks: ${CHECKS}"

# Build the required-status-checks contexts array from the comma list.
CONTEXTS="$(printf '%s' "$CHECKS" | jq -R 'split(",") | map(gsub("^\\s+|\\s+$";""))')"

gh api -X PUT "repos/${SLUG}/branches/${BRANCH}/protection" \
  --input - <<JSON
{
  "required_status_checks": { "strict": true, "contexts": ${CONTEXTS} },
  "enforce_admins": false,
  "required_pull_request_reviews": { "required_approving_review_count": 1 },
  "restrictions": null,
  "required_linear_history": true,
  "allow_force_pushes": false,
  "allow_deletions": false
}
JSON

echo "✓ Branch protection applied. Verify: gh api repos/${SLUG}/branches/${BRANCH}/protection --jq '.required_status_checks.contexts'"
