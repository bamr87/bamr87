# infra/azure/portal — the bash-365 portal on Azure Static Web Apps

> The console's bash-365 site build (`CONSOLE_SITE=bash-365`, [docs/CONSOLE-PAGES.md](../../../docs/CONSOLE-PAGES.md#site-builds-the-same-console-at-another-address)), served from its own Static Web App at the address `_data/profile.yml` `sites.bash-365.url` names.

## How it fits together

| Piece | Where | Who runs it |
| --- | --- | --- |
| The resource group, the Static Web App, its custom domain, the deploy role | `main.bicep`, `portal.bicep`, `parameters.json` | the maintainer, `deploy.sh --apply` |
| The identity GitHub signs in as (an Entra app with one federated credential, no secret) | `bootstrap.sh` | the maintainer, once |
| The build | `.github/workflows/build-dash.yml`, step "Build the bash-365 site build" | every build-dash run, pull requests included |
| The deploy | the same workflow, job `deploy-portal`, environment `bash-365-portal` | `main` only (push, the daily 08:37 UTC run, a dispatch), while `PORTAL_DEPLOY_ENABLED` is `true` |
| Response headers, caching, the 404 page | `staticwebapp.config.json`, copied into the build | Azure, on every response |
| The DNS record | the domain's DNS host | the maintainer, by hand |

The deploy job reads the app's deployment token from the app itself for that run only, with a Contributor role scoped to that one Static Web App, and masks it. Nothing is stored in GitHub but three ids, which are not credentials.

## Set it up

Prerequisites: the az CLI signed in (`az login`) as someone who can create resource groups and role assignments in the subscription (Owner, or Contributor plus User Access Administrator) and Entra applications; `gh` signed in for step 4.

1. **The identity.** `infra/azure/portal/bootstrap.sh` shows what it would create; `--apply` creates the Entra app `sp-bash365-portal-github`, its service principal and a federated credential for `repo:bamr87/bamr87:environment:bash-365-portal`. It prints the ids.
2. **The resources.** `infra/azure/portal/deploy.sh` runs a what-if; `--apply` creates `rg-bash365-portal-prod` in `westus2`, the Free Static Web App `swa-bash365-portal-prod` and the deploy role, and prints the app's default address and the DNS record for step 5.
3. **The ids.** Run the three `gh variable set PORTAL_AZURE_…` commands `bootstrap.sh` printed (client, tenant and subscription id: repository variables, not secrets).
4. **Switch it on.** `gh variable set PORTAL_DEPLOY_ENABLED -R bamr87/bamr87 --body true`, then record the flip in `_data/fleet.yml` `switches.loops["hub/bash-365-portal"]` in a pull request. The next push to `main` that touches the site, the daily run, or `gh workflow run build-dash.yml -R bamr87/bamr87` deploys it; the job ends by checking that the default address serves the bash-365 build.
5. **The address.** Add the CNAME `deploy.sh` printed (`os.bash-365.com. CNAME <app>.azurestaticapps.net.`) at the domain's DNS host. bash-365.com's DNS is hosted by Microsoft 365 (its name servers are `ns1`–`ns4.bdm.microsoftonline.com`), so the record is added in the Microsoft 365 admin center under the domain's DNS records, not in Azure. Once `dig +short CNAME os.bash-365.com` answers with the app's host, set `customDomain` in `parameters.json` to `os.bash-365.com` in a pull request and run `deploy.sh --apply`: it refuses until DNS answers, and Azure issues the certificate.

A different address: change `sites.bash-365.url` in `_data/profile.yml` and `customDomain` here together (`tools/test_portal_azure.py` holds them equal), then repeat step 5.

## Operate

| To | Do |
| --- | --- |
| Stop deploying | `gh variable set PORTAL_DEPLOY_ENABLED -R bamr87/bamr87 --body false` (the site stays up as last deployed) |
| Roll back | re-run an earlier successful `build-dash.yml` run's deploy-portal job, or revert on `main`; each deploy replaces the whole site |
| See what changed in Azure | `deploy.sh` (what-if) after editing a `.bicep` or `parameters.json` |
| Take it down | `az group delete --name rg-bash365-portal-prod`, then delete the CNAME |

## What the headers say

- `Content-Security-Policy: frame-ancestors 'self'`: only the portal may frame its own pages (its desktop opens console pages in windows). The page's own policy is the `<meta>` the build writes.
- `X-Robots-Tag: noindex`: the portal repeats content the Jekyll site at www.bash-365.com and the public console at bamr87.github.io/bamr87 already publish, and the Jekyll site stays the one search engines read until the portal replaces it. Remove the header when that changes.
- `Cache-Control`: hashed `/assets/*` are immutable; `/snapshot/*` is revalidated on every load, because the daily build replaces it.
