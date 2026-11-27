---
schema: '0.1'
coverage: listed
---

# SCHEMA — infra/azure

> Bicep deployments for the fleet's resources on Azure: one directory per deployment, each deployed by the maintainer and only compiled and linted in CI.

## Conventions

- Bicep, not OpenTofu: the fleet's Azure deployments are Bicep (bash-365.com's and bashcrawl's own `infra/azure/`), and this layer follows them. OpenTofu stays the tool for fleet nodes (`../node/`).
- Each deployment has a subscription-scope `main.bicep`, so its resource group is declared too, and a `parameters.json` that holds every non-secret value it needs.
- Scripts that change Azure preview by default and change it only with `--apply`.
- CI signs in to Azure only to deploy content, with OIDC and a role scoped to one resource; it never deploys a template.

## Structure

| entry | kind | purpose | rules |
| --- | --- | --- | --- |
| `README.md` | file | What this layer is and how its deployments are run | required |
| `portal/` | dir | The bash-365 portal: the console's bash-365 site build on Azure Static Web Apps | required |

## Placement

- New Azure deployment → `<name>/` here with `main.bicep`, `parameters.json`, a `SCHEMA.md` and a row in this table; `.github/workflows/infra.yml` builds every `*/main.bicep`.
- Anything unrouted → propose an entry in this table first, then create it.

## Forbidden

- No secret values and no client secrets: GitHub reaches Azure through an Entra federated credential.
- No compiled ARM JSON committed beside the Bicep.
