#!/usr/bin/env bash
# ============================================================================
# infra/gcp/deploy.sh — plan, and only when told apply, one of the platform's
# Google Cloud modules (ADR 0020, docs/HOSTING.md). Run by the maintainer with
# OpenTofu and their own Google Cloud sign-in; CI never runs it (infra.yml only
# validates the HCL, and holds no cloud credential).
#
#   gcloud auth application-default login          # once, as yourself
#   export GCP_PROJECT_ID=<the project>            # never committed
#   infra/gcp/deploy.sh foundation                 # what would change
#   infra/gcp/deploy.sh foundation --apply         # change it, from that plan
#   infra/gcp/deploy.sh node                       # the machine (plans nothing
#                                                  # while node.enabled is false)
#
# What is created is decided by _data/hosting.yml, which each module reads
# itself. This script only supplies what must stay out of the repo:
#
#   GCP_PROJECT_ID        the project (required)
#   GCP_BILLING_ACCOUNT   foundation only: with it, a budget ALERT is created
#   GCP_BUDGET_USD        foundation only: the alert's monthly amount (50)
#
# --apply applies the plan the last run saved, and refuses when that plan is
# older than the module or _data/hosting.yml: a change after the plan needs a
# new plan (constitution § 10.5). State lives outside every checkout
# (FLEET_INFRA_STATE, default ~/.local/state/bamr87-infra), as for the nodes.
# ============================================================================
set -euo pipefail

usage() { echo "usage: $0 <foundation|node> [--apply]" >&2; exit 2; }

MODULE="${1:-}"
APPLY=0
case "${2:-}" in
  --apply) APPLY=1 ;;
  "") ;;
  *) usage ;;
esac
case "$MODULE" in
  foundation|node) ;;
  *) usage ;;
esac

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
DIR="$HERE/$MODULE"
HOSTING="$ROOT/_data/hosting.yml"
TOOL="${TOFU:-tofu}"

command -v "$TOOL" >/dev/null 2>&1 || { echo "deploy: OpenTofu is required (brew install opentofu; https://opentofu.org/docs/intro/install/)" >&2; exit 1; }
[[ -n "${GCP_PROJECT_ID:-}" ]] || { echo "deploy: set GCP_PROJECT_ID to the Google Cloud project (it is never written in the repo)" >&2; exit 1; }
[[ -f "$HOSTING" ]] || { echo "deploy: $HOSTING is missing" >&2; exit 1; }

STATE_DIR="${FLEET_INFRA_STATE:-$HOME/.local/state/bamr87-infra}"
STATE="$STATE_DIR/gcp-$MODULE.tfstate"
PLAN="$STATE_DIR/gcp-$MODULE.tfplan"
mkdir -p "$STATE_DIR"
export TF_DATA_DIR="$STATE_DIR/gcp-$MODULE/.terraform"
export TF_IN_AUTOMATION=1
export TF_VAR_project_id="$GCP_PROJECT_ID"
if [[ "$MODULE" == foundation ]]; then
  export TF_VAR_billing_account="${GCP_BILLING_ACCOUNT:-}"
  [[ -z "${GCP_BUDGET_USD:-}" ]] || export TF_VAR_budget_usd="$GCP_BUDGET_USD"
fi

if [[ "$APPLY" -eq 1 ]]; then
  [[ -f "$PLAN" ]] || { echo "deploy: no saved plan; run '$0 $MODULE' first and read it" >&2; exit 1; }
  # A plan made before the last edit describes a change nobody has read.
  newer="$(find "$DIR" "$HOSTING" -type f -newer "$PLAN" -print -quit)"
  [[ -z "$newer" ]] || { echo "deploy: $newer changed after the plan was made; run '$0 $MODULE' again and read the new plan" >&2; exit 1; }
  echo "deploy: applying the saved plan for $MODULE to project $GCP_PROJECT_ID"
  "$TOOL" -chdir="$DIR" apply -input=false "$PLAN"
  rm -f "$PLAN"
  exit 0
fi

"$TOOL" -chdir="$DIR" init -input=false -upgrade -backend-config="path=$STATE" >/dev/null
"$TOOL" -chdir="$DIR" plan -input=false -out="$PLAN"
echo
echo "deploy: nothing was changed. This is the plan for '$MODULE' in project $GCP_PROJECT_ID."
echo "deploy: to apply exactly this plan: $0 $MODULE --apply"
