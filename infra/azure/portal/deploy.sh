#!/usr/bin/env bash
# ============================================================================
# infra/azure/portal/deploy.sh — the portal's Azure resources from main.bicep:
# its resource group, the Static Web App, its custom domain once DNS is ready,
# and the deploy identity's one role. Run by the maintainer with the az CLI;
# CI never runs it (infra.yml only builds the Bicep).
#
#   az login
#   infra/azure/portal/deploy.sh             # what-if: what would change
#   infra/azure/portal/deploy.sh --apply     # change it
#
# Inputs: parameters.json beside this file, and the service principal
# bootstrap.sh made (ENTRA_APP_NAME, default sp-bash365-portal-github); without
# it the role is left out and the script says so.
#
# The custom domain: parameters.json `customDomain` stays empty until its
# CNAME exists. This script prints the record to add; with a domain set, it
# refuses to apply until DNS answers with that record, because Azure checks it
# when the domain is attached. The domain must be the host of
# _data/profile.yml sites.bash-365.url (tools/test_portal_azure.py holds that).
# ============================================================================
set -euo pipefail

APPLY=0
case "${1:-}" in
  --apply) APPLY=1 ;;
  "") ;;
  *) echo "usage: $0 [--apply]" >&2; exit 2 ;;
esac

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PARAMS="$HERE/parameters.json"
APP_NAME="${ENTRA_APP_NAME:-sp-bash365-portal-github}"

command -v az >/dev/null 2>&1 || { echo "deploy: the az CLI is required (https://aka.ms/azcli)" >&2; exit 1; }
az account show >/dev/null 2>&1 || { echo "deploy: not signed in; run: az login" >&2; exit 1; }

param() { python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["parameters"][sys.argv[2]]["value"])' "$PARAMS" "$1"; }
LOCATION="$(param location)"
RG="$(param resourceGroupName)"
SWA="$(param staticWebAppName)"
DOMAIN="$(param customDomain)"

APP_ID="$(az ad app list --display-name "$APP_NAME" --query '[0].appId' -o tsv)"
PRINCIPAL=""
[[ -n "$APP_ID" ]] && PRINCIPAL="$(az ad sp list --filter "appId eq '${APP_ID}'" --query '[0].id' -o tsv)"
[[ -n "$PRINCIPAL" ]] || echo "deploy: no service principal ${APP_NAME} yet (run bootstrap.sh --apply first); the role is left out" >&2

# Where the app answers today, if it exists: the CNAME's target.
HOST="$(az staticwebapp show --name "$SWA" --resource-group "$RG" --query defaultHostname -o tsv 2>/dev/null || true)"

if [[ -n "$DOMAIN" ]]; then
  [[ -n "$HOST" ]] || { echo "deploy: ${SWA} does not exist yet; apply once with customDomain empty, then add the CNAME" >&2; exit 1; }
  ANSWER="$(dig +short CNAME "$DOMAIN" | sed 's/\.$//' | head -1)"
  if [[ "$ANSWER" != "$HOST" ]]; then
    echo "deploy: ${DOMAIN} answers CNAME '${ANSWER:-nothing}', not ${HOST}." >&2
    echo "        Add the record below at the domain's DNS host, wait for it to answer, and run again." >&2
    echo "        ${DOMAIN}.  CNAME  ${HOST}." >&2
    [[ "$APPLY" == 1 ]] && exit 1
  fi
fi

ARGS=(--location "$LOCATION" --template-file "$HERE/main.bicep" --parameters "@${PARAMS}" deployerPrincipalId="$PRINCIPAL")

if [[ "$APPLY" != 1 ]]; then
  az deployment sub what-if --name bash365-portal "${ARGS[@]}"
  echo
  echo "Nothing changed. Run again with --apply to make these changes."
  exit 0
fi

az deployment sub create --name bash365-portal "${ARGS[@]}" --query properties.outputs -o json
HOST="$(az staticwebapp show --name "$SWA" --resource-group "$RG" --query defaultHostname -o tsv)"

echo
echo "The portal's default address: https://${HOST}"
if [[ -z "$DOMAIN" ]]; then
  SITE_URL="$(cd "$HERE/../../.." && python3 tools/console/site_docs.py build-env bash-365 | sed -n "s/^SITE_DEFAULT_URL=//p" | tr -d "'")"
  WANT="${SITE_URL#https://}"
  echo "To serve it at ${WANT}, add this record at the domain's DNS host:"
  echo "  ${WANT}.  CNAME  ${HOST}."
  echo "then set parameters.json customDomain to ${WANT} in a pull request and run this script with --apply again."
fi
