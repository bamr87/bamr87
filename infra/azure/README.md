# infra/azure — the fleet's Azure deployments

> Bicep for what the hub runs on Azure. Today that is one deployment, `portal/`: the Harness Console's bash-365 site build served from Azure Static Web Apps.

The rest of `infra/` is OpenTofu, for fleet nodes (ADR 0003). Azure resources are Bicep, as in the fleet's other Azure deployments (bash-365/bash-365.com and bashcrawl each keep an `infra/azure/main.bicep`), so the same people run the same tool on the same cloud.

| Deployment | What it holds | Runbook |
| --- | --- | --- |
| [`portal/`](portal/README.md) | a resource group, a Static Web App, its custom domain, and the one role GitHub Actions holds | `portal/README.md` |

## Rules

- **The maintainer deploys, CI compiles.** `.github/workflows/infra.yml` builds and lints every `*/main.bicep` and checks its `parameters.json`; it holds no Azure credential. Changing Azure is a deploy step (constitution § 10.5), so every script here is a dry run (`what-if`) unless given `--apply`.
- **No stored credentials.** A workflow that publishes to Azure signs in with OIDC through an Entra federated credential that trusts one GitHub environment, and holds a role on one resource.
- **One source per value.** A name is written once, in the deployment's `parameters.json`, and the workflow reads it from there.
