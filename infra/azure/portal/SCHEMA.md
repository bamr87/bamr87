---
schema: '0.1'
coverage: listed
---

# SCHEMA — infra/azure/portal

> The bash-365 portal on Azure Static Web Apps: the Bicep for its resources, the scripts the maintainer runs, and the response headers the built site ships with.

## Conventions

- `parameters.json` is the one place a name lives: `deploy.sh` deploys with it and `build-dash.yml`'s deploy-portal job reads it.
- `customDomain` is empty, or the host of `_data/profile.yml` `sites.bash-365.url` (`tools/test_portal_azure.py`).

## Structure

| entry | kind | purpose | rules |
| --- | --- | --- | --- |
| `README.md` | file | The runbook: bootstrap, deploy, DNS, switching the deploy on, rolling back | required |
| `main.bicep` | file | Subscription scope: the resource group and the module below | required |
| `portal.bicep` | file | The Static Web App, its custom domain, and the deploy identity's role on that app alone | required |
| `parameters.json` | file | Every non-secret value the template takes, read by the workflow too | required |
| `staticwebapp.config.json` | file | Response headers, caching and the 404 page; copied into the build by `build-dash.yml` | required |
| `bootstrap.sh` | file | One time: the Entra app and its federated credential for the `bash-365-portal` environment | required |
| `deploy.sh` | file | What-if, or with `--apply` the deployment of `main.bicep`; checks DNS before attaching the domain | required |

## Placement

- A new Azure resource for the portal → `portal.bicep`, with its values in `parameters.json`.
- Anything unrouted → propose an entry in this table first, then create it.

## Forbidden

- No secret values, deployment tokens or client secrets.
- No `navigationFallback` in `staticwebapp.config.json`: every route has its own page, and a fallback would answer 200 for addresses that do not exist.
