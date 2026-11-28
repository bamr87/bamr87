// The portal's resources, in its own resource group (main.bicep): the Static
// Web App, its custom domain once the DNS record exists, and the one role the
// GitHub Actions identity holds, on this app alone.

param location string
param staticWebAppName string
param sku string
param customDomain string
param deployerPrincipalId string
param tags object

// Contributor, assigned below at the scope of this one Static Web App: enough
// to read its deployment token (listSecrets) and deploy, and nothing else in
// the subscription. The GitHub identity never runs this template.
var contributorRoleId = 'b24988ac-6180-42a0-ab88-20f7382dd24c'

resource swa 'Microsoft.Web/staticSites@2024-04-01' = {
  name: staticWebAppName
  location: location
  tags: tags
  sku: {
    name: sku
    tier: sku
  }
  properties: {
    // Content arrives from build-dash.yml with a deployment token, not from a
    // linked repository: linking one would make Azure write its own workflow.
    provider: 'None'
    allowConfigFileUpdates: true
    // Pull requests build the portal and never deploy it, so no preview environments.
    stagingEnvironmentPolicy: 'Disabled'
  }
}

resource domain 'Microsoft.Web/staticSites/customDomains@2024-04-01' = if (!empty(customDomain)) {
  parent: swa
  name: customDomain
  properties: {
    // The CNAME to the default hostname is the proof: deploy.sh checks it first.
    validationMethod: 'cname-delegation'
  }
}

resource deployer 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(deployerPrincipalId)) {
  name: guid(swa.id, deployerPrincipalId, contributorRoleId)
  scope: swa
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', contributorRoleId)
    principalId: deployerPrincipalId
    principalType: 'ServicePrincipal'
    description: 'bamr87/bamr87 build-dash.yml deploys the bash-365 portal to this app'
  }
}

output staticWebAppName string = swa.name
output defaultHostname string = swa.properties.defaultHostname
