#!/usr/bin/env bash
# ============================================================================
# tools/protect-branch.sh — the fleet ruleset on a repo's default branch
# (UPS-QA-24, UPS-QA-36, ADR 0015). A thin wrapper over tools/branch_policy.py;
# the policy itself is _data/fleet.yml `branches:` and docs/BRANCHING.md says why.
#
# Usage:
#   tools/protect-branch.sh <repo> [--checks "a,b"] [--approvals N] [--apply]
#   tools/protect-branch.sh <repo>... --check          # read-only audit
#
#   <repo>             owner/name, a registry name, or projects/<dir>
#   --checks "a,b"     required check names, as the check runs are named (a
#                      reusable-workflow caller job `ci` reports as "ci / ci");
#                      a name not seen on the default branch is refused unless
#                      --allow-unseen. Omitted, the live ruleset's are kept.
#   --approvals N      required approvals (default 0: the review gate is the
#                      needs-amr label, constitution § 12.3-12.4)
#   --enforce-admins   no admin bypass   --strict   head must be up to date
#   --drop-classic     with --apply, delete the classic protection it replaces
#   --owner X          owner for a bare name the registry does not know
#   --apply            write the plan (needs admin: the maintainer's, § 4)
#
# A DRY RUN BY DEFAULT: without --apply it prints the plan and the audit and
# writes nothing. The ruleset allows merge commits only (§ 12.2), never adds a
# linear-history rule, and is created or updated by name, so other rulesets
# and settings a person made are left alone.
#
# Until 2026-11 this script PUT classic protection with linear history and one
# required approval: the first forbids the merge commit § 12.2 requires, and the
# second can never be given on a pull request opened with the maintainer's
# token. `--check` finds a repo still carrying that; `--apply --drop-classic`
# replaces it.
# ============================================================================
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PYTHON:-python3}"

[[ $# -ge 1 ]] || { sed -n '7,21p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//' >&2; exit 2; }

for arg in "$@"; do
  if [[ "$arg" == "--check" ]]; then
    rest=()
    for a in "$@"; do [[ "$a" == "--check" ]] || rest+=("$a"); done
    exec "$PY" "$HERE/branch_policy.py" check "${rest[@]}"
  fi
done

exec "$PY" "$HERE/branch_policy.py" protect "$@"
