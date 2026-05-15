// Parameters for the single-region wingman-mcp deployment.
//
// Edit the values below (or override on the `az deployment group create`
// command line). `deploy.sh` injects `location`, `entraTenantId`,
// `customDomain`, `enableStaticAccessKey`, `deployContainerApp`,
// `uiCertificateId`, and `imageTag` from environment variables, so the
// values for those here are only used when calling `az` directly.

using './main.bicep'

// Region. Override via deploy.sh's REGION env var.
param location = 'eastus'

// Entra tenant ID (GUID). Required. Override via ENTRA_TENANT_ID.
param entraTenantId = '00000000-0000-0000-0000-000000000000'

// Application ID URI from the Entra app registration's "Expose an API" blade.
param entraAudience = 'api://wingman-mcp'

// App ID URI used for scope qualification. Normally same as entraAudience,
// but split out because entraAudience may need to be the client GUID on
// tenants where Entra emits a GUID-style aud despite accessTokenAcceptedVersion=2.
param entraAppIdUri = 'api://wingman-mcp'

// Scope required in the JWT `scp` claim. Set to '' to skip the scope check.
param entraRequiredScope = 'mcp.access'

// Pre-registered Entra client app ID for the OAuth DCR shim. When set, MCP
// clients only need the server URL in their config; the shim handles
// registration + redirects to Entra. Override via ENTRA_CLIENT_ID env var.
param entraClientId = ''

// Custom domain for the Container App. Leave '' to use the default Container
// Apps FQDN only.
param customDomain = ''

// Set after `az containerapp hostname bind` issues the managed cert.
param uiCertificateId = ''

// Canonical public URL for the OAuth discovery document. Leave '' to derive
// from the request Host header at runtime (works fine behind Container Apps
// ingress). Override via deploy.sh's PUBLIC_URL env var.
param publicUrl = ''

// Enable the WINGMAN_MCP_ACCESS_KEY fallback. When true, the Container App
// reads the value from the KV secret `wingman-mcp-access-key`.
param enableStaticAccessKey = false

// Foundation deploy: false. App deploy: true.
param deployContainerApp = false

// Container image tag in the ACR.
param imageTag = 'latest'

// Sizing and scale.
param cpu = '0.5'
param memory = '1Gi'
param minReplicas = 1
param maxReplicas = 3
param logRetentionDays = 30
