#!/usr/bin/env bash
# ============================================================================
# infra/azure/portal/bootstrap.sh — the identity GitHub Actions deploys the
# bash-365 portal as. One time, by the maintainer, with the az CLI.
#
# Creates (or reuses) an Entra application and its service principal, and one
# federated credential that trusts only bamr87/bamr87's workflow jobs that run
# in the `bash-365-portal` environment (build-dash.yml's deploy-portal job). No
# client secret is ever made: the job signs in with OIDC. It grants no role;
# deploy.sh assigns the one role, scoped to the portal's Static Web App.
#
# Writes nothing to Azure or Entra without --apply. Prints, never runs, the
# `gh variable set` commands that hand the ids to the workflow.
#
#   az login
#   infra/azure/portal/bootstrap.sh            # what it would create
#   infra/azure/portal/bootstrap.sh --apply    # create it
#
# Overrides: GITHUB_REPOSITORY (bamr87/bamr87), PORTAL_ENVIRONMENT
# (bash-365-portal), ENTRA_APP_NAME (sp-bash365-portal-github).
# ============================================================================
set -euo pipefail

APPLY=0
case "${1:-}" in
  --apply) APPLY=1 ;;
  "") ;;
  *) echo "usage: $0 [--apply]" >&2; exit 2 ;;
esac

REPO="${GITHUB_REPOSITORY:-bamr87/bamr87}"
ENVIRONMENT="${PORTAL_ENVIRONMENT:-bash-365-portal}"
APP_NAME="${ENTRA_APP_NAME:-sp-bash365-portal-github}"

command -v az >/dev/null 2>&1 || { echo "bootstrap: the az CLI is required (https://aka.ms/azcli)" >&2; exit 1; }
az account show >/dev/null 2>&1 || { echo "bootstrap: not signed in; run: az login" >&2; exit 1; }

TENANT_ID="$(az account show --query tenantId -o tsv)"
SUBSCRIPTION_ID="$(az account show --query id -o tsv)"

# The subject must be exactly what GitHub puts in the token. A repo with
# immutable subjects sends "repo:<owner>@<id>/<repo>@<id>"; GitHub reports the
# prefix it uses, so ask it (as bash-365.com's bootstrap does).
SUB_PREFIX="$(gh api "repos/${REPO}/actions/oidc/customization/sub" --jq '.sub_claim_prefix // empty' 2>/dev/null || true)"
SUBJECT="${SUB_PREFIX:-repo:${REPO}}:environment:${ENVIRONMENT}"
CRED_NAME="$(printf '%s' "${REPO##*/}-${ENVIRONMENT}" | tr -c 'A-Za-z0-9-' '-')"

APP_ID="$(az ad app list --display-name "$APP_NAME" --query '[0].appId' -o tsv)"

echo "tenant        ${TENANT_ID}"
echo "subscription  ${SUBSCRIPTION_ID}"
echo "Entra app     ${APP_NAME} $([[ -n "$APP_ID" ]] && echo "(exists: ${APP_ID})" || echo "(would be created)")"
echo "trusts        ${SUBJECT}"

if [[ "$APPLY" != 1 ]]; then
  echo
  echo "Nothing changed. Run again with --apply to create what is missing."
  exit 0
fi

if [[ -z "$APP_ID" ]]; then
  APP_ID="$(az ad app create --display-name "$APP_NAME" --query appId -o tsv)"
  echo "created the Entra app (${APP_ID})"
fi
if [[ -z "$(az ad sp list --filter "appId eq '${APP_ID}'" --query '[0].id' -o tsv)" ]]; then
  az ad sp create --id "$APP_ID" --query id -o tsv >/dev/null
  echo "created its service principal"
fi
if [[ -n "$(az ad app federated-credential list --id "$APP_ID" --query "[?subject=='${SUBJECT}'].name" -o tsv)" ]]; then
  echo "the federated credential for ${SUBJECT} exists"
else
  az ad app federated-credential create --id "$APP_ID" --parameters "$(cat <<JSON
{
  "name": "${CRED_NAME}",
  "issuer": "https://token.actions.githubusercontent.com",
  "subject": "${SUBJECT}",
  "description": "GitHub Actions OIDC: ${REPO} build-dash.yml deploy-portal, environment ${ENVIRONMENT}",
  "audiences": ["api://AzureADTokenExchange"]
}
JSON
)" >/dev/null
  echo "created the federated credential ${CRED_NAME}"
fi

cat <<EOT

Next:
  1. infra/azure/portal/deploy.sh            # preview the resource group, the app and the role
     infra/azure/portal/deploy.sh --apply
  2. Hand the ids to the workflow (repository variables, not secrets: none of them is a credential):
       gh variable set PORTAL_AZURE_CLIENT_ID       -R ${REPO} --body '${APP_ID}'
       gh variable set PORTAL_AZURE_TENANT_ID       -R ${REPO} --body '${TENANT_ID}'
       gh variable set PORTAL_AZURE_SUBSCRIPTION_ID -R ${REPO} --body '${SUBSCRIPTION_ID}'
  3. Switch the deploy on, and record the flip in _data/fleet.yml switches.loops["hub/bash-365-portal"]:
       gh variable set PORTAL_DEPLOY_ENABLED -R ${REPO} --body true
EOT
