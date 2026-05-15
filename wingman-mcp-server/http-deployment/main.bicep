// =============================================================================
// main.bicep
//
// Single-region Azure deployment for wingman-mcp (HTTP transport).
//
// Provisions:
//   - Log Analytics workspace
//   - Container Apps managed environment (Consumption profile)
//   - User-assigned managed identity
//   - Azure Container Registry (Basic SKU, admin disabled)
//   - Key Vault (RBAC mode, empty; operator populates secrets)
//   - Role assignments: AcrPull on ACR, Key Vault Secrets User on KV (UAMI)
//   - Container App: wingman-mcp HTTP server (gated by `deployContainerApp`)
//
// Out of scope (operator-managed):
//   - Resource group (deploy.sh creates it via `az group create`)
//   - Entra ID app registration (Graph, not ARM)
//   - DNS CNAME for the custom domain
//   - Managed certificate (issued via `az containerapp hostname bind` after DNS)
//
// Deploy in two passes:
//   1) deployContainerApp=false   -> foundation only; push image; populate KV
//   2) deployContainerApp=true    -> Container App + (optional) cert binding
// =============================================================================

targetScope = 'resourceGroup'

// -----------------------------------------------------------------------------
// Parameters
// -----------------------------------------------------------------------------

@description('Azure region for all resources.')
param location string = resourceGroup().location

@description('Entra tenant ID. Required: wingman-mcp validates JWTs against this tenant.')
param entraTenantId string

@description('Expected JWT `aud` claim. Defaults to the App ID URI; override if Entra emits a GUID-style audience (a known v2 quirk on some tenants).')
param entraAudience string = 'api://wingman-mcp'

@description('App ID URI of the server app registration. Used to qualify scopes in OAuth metadata and shim redirects. Defaults to api://wingman-mcp.')
param entraAppIdUri string = 'api://wingman-mcp'

@description('Required `scp` claim. Set empty to skip the scope check.')
param entraRequiredScope string = 'mcp.access'

@description('Pre-registered Entra client app ID for the OAuth DCR shim. When set together with entraTenantId, wingman-mcp serves /.well-known/oauth-authorization-server and proxies the auth dance to Entra, so MCP clients (mcp-remote, etc.) only need the server URL in their config. Leave empty to disable the shim.')
param entraClientId string = ''

@description('Public custom domain for the Container App (e.g. wingman.example.com). Empty string means use the default *.azurecontainerapps.io FQDN only.')
param customDomain string = ''

@description('Canonical public URL of wingman-mcp (e.g. https://wingman.example.com). Used as the `resource` value in the /.well-known/oauth-protected-resource discovery document. Leave empty to derive from the request Host header at runtime.')
param publicUrl string = ''

@description('Resource ID of the managed certificate bound to customDomain. Leave empty on first deploy; populate on the follow-up deploy after `az containerapp hostname bind` issues the cert.')
param uiCertificateId string = ''

@description('If true, wire WINGMAN_MCP_ACCESS_KEY (KV secret `wingman-mcp-access-key`) into the Container App. The KV secret must exist before phase 2.')
param enableStaticAccessKey bool = false

@description('Gate for the Container App resource. Foundation phase: false. App phase: true.')
param deployContainerApp bool = false

@description('Container image tag in ACR.')
param imageTag string = 'latest'

@description('Container image repository name within the ACR (no registry prefix, no tag).')
param imageRepository string = 'wingman-mcp'

@description('Override resource names. Defaults derive from a deterministic suffix to keep ACR + KV globally unique.')
param logAnalyticsName string = 'law-wingman-mcp'
param containerAppEnvName string = 'cae-wingman-mcp'
param managedIdentityName string = 'mi-wingman-mcp'
param containerAppName string = 'wingman-mcp'

@description('ACR name. Must be 5-50 chars, alphanumeric only, globally unique.')
param acrName string = 'crwingmanmcp${take(uniqueString(resourceGroup().id), 8)}'

@description('Key Vault name. Must be 3-24 chars, alphanumeric + hyphens, must start with a letter, globally unique.')
param keyVaultName string = 'kv-wgmnmcp-${take(uniqueString(resourceGroup().id), 8)}'

@description('Container resource sizing.')
param cpu string = '0.5'
param memory string = '1Gi'

@description('Container scaling.')
param minReplicas int = 1
param maxReplicas int = 3

@description('Log Analytics retention (days).')
param logRetentionDays int = 30

// -----------------------------------------------------------------------------
// Built-in role definition IDs
// -----------------------------------------------------------------------------

var roleDefinitions = {
  acrPull:             '7f951dda-4ed3-4680-a7ca-43fe172d538d'
  keyVaultSecretsUser: '4633458b-17de-408a-b874-0445c86b69e6'
}

// -----------------------------------------------------------------------------
// Foundation: Log Analytics, Container Apps env, UAMI, ACR, KV, role assignments
// -----------------------------------------------------------------------------

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: logAnalyticsName
  location: location
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: logRetentionDays
    features: {
      enableLogAccessUsingOnlyResourcePermissions: true
    }
  }
}

resource containerAppEnv 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: containerAppEnvName
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalytics.properties.customerId
        sharedKey: logAnalytics.listKeys().primarySharedKey
      }
    }
    zoneRedundant: false
    workloadProfiles: [
      {
        name: 'Consumption'
        workloadProfileType: 'Consumption'
      }
    ]
    peerAuthentication: {
      mtls: {
        enabled: false
      }
    }
    peerTrafficConfiguration: {
      encryption: {
        enabled: false
      }
    }
  }
}

resource managedIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: managedIdentityName
  location: location
}

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: acrName
  location: location
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: false
    publicNetworkAccess: 'Enabled'
  }
}

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: keyVaultName
  location: location
  properties: {
    tenantId: subscription().tenantId
    sku: {
      family: 'A'
      name: 'standard'
    }
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
    enabledForDeployment: false
    enabledForDiskEncryption: false
    enabledForTemplateDeployment: false
    publicNetworkAccess: 'Enabled'
  }
}

resource acrPullAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, managedIdentity.id, roleDefinitions.acrPull)
  scope: acr
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleDefinitions.acrPull)
    principalId: managedIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource keyVaultSecretsUserAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, managedIdentity.id, roleDefinitions.keyVaultSecretsUser)
  scope: keyVault
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleDefinitions.keyVaultSecretsUser)
    principalId: managedIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// -----------------------------------------------------------------------------
// Container App (gated)
// -----------------------------------------------------------------------------

var customDomains = empty(customDomain) || empty(uiCertificateId) ? [] : [
  {
    name: customDomain
    bindingType: 'SniEnabled'
    certificateId: uiCertificateId
  }
]

var staticKeySecrets = enableStaticAccessKey ? [
  {
    name: 'wingman-mcp-access-key'
    keyVaultUrl: '${keyVault.properties.vaultUri}secrets/wingman-mcp-access-key'
    identity: managedIdentity.id
  }
] : []

var baseEnv = [
  { name: 'ENTRA_TENANT_ID', value: entraTenantId }
  { name: 'ENTRA_AUDIENCE', value: entraAudience }
  { name: 'ENTRA_REQUIRED_SCOPE', value: entraRequiredScope }
  { name: 'ENTRA_APP_ID_URI', value: entraAppIdUri }
]

var clientIdEnv = empty(entraClientId) ? [] : [
  { name: 'ENTRA_CLIENT_ID', value: entraClientId }
]

var publicUrlEnv = empty(publicUrl) ? [] : [
  { name: 'WINGMAN_MCP_PUBLIC_URL', value: publicUrl }
]

var staticKeyEnv = enableStaticAccessKey ? [
  { name: 'WINGMAN_MCP_ACCESS_KEY', secretRef: 'wingman-mcp-access-key' }
] : []

resource containerApp 'Microsoft.App/containerApps@2024-03-01' = if (deployContainerApp) {
  name: containerAppName
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${managedIdentity.id}': {}
    }
  }
  dependsOn: [
    acrPullAssignment
    keyVaultSecretsUserAssignment
  ]
  properties: {
    environmentId: containerAppEnv.id
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      maxInactiveRevisions: 50
      ingress: {
        external: true
        targetPort: 8000
        transport: 'http'
        allowInsecure: false
        customDomains: customDomains
        traffic: [
          {
            latestRevision: true
            weight: 100
          }
        ]
      }
      registries: [
        {
          server: acr.properties.loginServer
          identity: managedIdentity.id
        }
      ]
      secrets: staticKeySecrets
    }
    template: {
      containers: [
        {
          name: containerAppName
          image: '${acr.properties.loginServer}/${imageRepository}:${imageTag}'
          resources: {
            cpu: json(cpu)
            memory: memory
          }
          env: concat(baseEnv, clientIdEnv, publicUrlEnv, staticKeyEnv)
          probes: [
            {
              type: 'Readiness'
              httpGet: {
                path: '/health'
                port: 8000
              }
              initialDelaySeconds: 5
              periodSeconds: 10
              timeoutSeconds: 3
              failureThreshold: 3
            }
            {
              type: 'Liveness'
              httpGet: {
                path: '/health'
                port: 8000
              }
              initialDelaySeconds: 30
              periodSeconds: 30
              timeoutSeconds: 5
              failureThreshold: 3
            }
          ]
        }
      ]
      scale: {
        minReplicas: minReplicas
        maxReplicas: maxReplicas
      }
    }
  }
}

// -----------------------------------------------------------------------------
// Outputs
// -----------------------------------------------------------------------------

output acrName string = acr.name
output acrLoginServer string = acr.properties.loginServer
output keyVaultName string = keyVault.name
output keyVaultUri string = keyVault.properties.vaultUri
output containerAppEnvName string = containerAppEnv.name
output containerAppEnvDefaultDomain string = containerAppEnv.properties.defaultDomain
output managedIdentityClientId string = managedIdentity.properties.clientId
output managedIdentityPrincipalId string = managedIdentity.properties.principalId
output containerAppName string = deployContainerApp ? containerApp!.name : ''
output containerAppFqdn string = deployContainerApp ? containerApp!.properties.configuration.ingress.fqdn : ''
