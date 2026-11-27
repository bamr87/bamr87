// The bash-365 portal on Azure Static Web Apps: the Harness Console's site
// build for bash-365 (_data/profile.yml `sites.bash-365`, docs/CONSOLE-PAGES.md
// "Site builds"), built by .github/workflows/build-dash.yml and deployed there.
//
// Subscription scope so the resource group is declared too. Everything else is
// in portal.bicep, at the resource group's scope. Deployed by the maintainer
// with ./deploy.sh (a what-if by default; --apply to change Azure). CI only
// builds this file (infra.yml) and never deploys it.
targetScope = 'subscription'

@description('Region for the resource group and the Static Web App: one Static Web Apps offers. westus2 is the closest to Denver and the region bash-365.com\'s own app uses.')
param location string = 'westus2'

@description('The resource group that holds only the portal, apart from bash-365.com\'s, so the hub\'s deploy identity can reach nothing else.')
param resourceGroupName string

@description('The Static Web App\'s resource name.')
param staticWebAppName string

@description('Free carries two custom domains and 250 MB of content, which the portal fits; Standard is the step up.')
@allowed([
  'Free'
  'Standard'
])
param sku string = 'Free'

@description('The host the portal answers at: the host of _data/profile.yml sites.bash-365.url. Empty until its CNAME points at the default hostname, because Azure checks the record when the domain is attached.')
param customDomain string = ''

@description('Object id of the service principal GitHub Actions signs in as (bootstrap.sh creates it; deploy.sh looks it up). Empty: no role assignment.')
param deployerPrincipalId string = ''

param tags object = {
  project: 'bash365'
  component: 'portal'
  env: 'prod'
  'managed-by': 'bicep'
  source: 'bamr87/bamr87 infra/azure/portal'
}

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: resourceGroupName
  location: location
  tags: tags
}

module portal 'portal.bicep' = {
  name: 'portal-${staticWebAppName}'
  scope: rg
  params: {
    location: location
    staticWebAppName: staticWebAppName
    sku: sku
    customDomain: customDomain
    deployerPrincipalId: deployerPrincipalId
    tags: tags
  }
}

output resourceGroupName string = rg.name
output staticWebAppName string = portal.outputs.staticWebAppName
output defaultHostname string = portal.outputs.defaultHostname
output customDomain string = customDomain
