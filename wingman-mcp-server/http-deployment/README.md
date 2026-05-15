# wingman-mcp HTTP deployment (single region)

Bicep + a thin `deploy.sh` wrapper that stands up wingman-mcp's HTTP transport on Azure Container Apps in one region.

## What gets created

In one resource group, in one region:

- Azure Container Registry (Basic SKU, admin disabled)
- Key Vault (RBAC mode, empty; soft-delete on, no purge protection)
- Log Analytics workspace (30-day retention)
- Container Apps managed environment (Consumption profile)
- User-assigned managed identity, with `AcrPull` on the ACR and `Key Vault Secrets User` on the KV
- Container App `wingman-mcp`, external ingress on port 8000, optional custom domain

The Container App env vars are wired to the Entra ID validation path: `ENTRA_TENANT_ID`, `ENTRA_AUDIENCE`, `ENTRA_REQUIRED_SCOPE`. When `ENABLE_STATIC_KEY=true`, `WINGMAN_MCP_ACCESS_KEY` is loaded from the KV secret `wingman-mcp-access-key`. If `PUBLIC_URL` is set, `WINGMAN_MCP_PUBLIC_URL` is wired so the `/.well-known/oauth-protected-resource` discovery doc advertises a stable canonical URL (otherwise it's derived from the request `Host` header). If `ENTRA_CLIENT_ID` is set (the pre-registered client app's ID), the OAuth DCR shim is enabled, so end users get a one-line MCP client config.

## What you do yourself

- **Entra app registration.** Register the app (single-tenant), set Application ID URI to `api://wingman-mcp`, expose the `mcp.access` scope, set `accessTokenAcceptedVersion: 2` in the manifest. See `wingman-mcp/docs/superpowers/specs/2026-05-14-entra-id-auth-design.md` for the full checklist.
- **DNS.** After phase 2 deploy, add a CNAME for your custom domain pointing at the Container App's default FQDN.
- **Managed certificate.** After DNS resolves, run `az containerapp hostname bind` to issue and bind the cert. Then re-run `deploy.sh` with the resulting `CERT_ID` to wire SNI.

## Prerequisites

- Azure subscription with permissions to create the resource types above.
- `az` CLI logged in (`az login`).
- A built wingman-mcp source tree at `../wingman-mcp` (or pass `WINGMAN_MCP_SRC=/path/to/wingman-mcp`). Required only if you let `deploy.sh` build the image; otherwise push the image yourself and pass `--skip-build`.

## Quickstart

```bash
cd http-deployment/

cat > .env <<EOF
SUBSCRIPTION=00000000-0000-0000-0000-000000000000
RG=rg-wingman-mcp
REGION=eastus
ENTRA_TENANT_ID=11111111-1111-1111-1111-111111111111
# Optional
ENTRA_CLIENT_ID=22222222-2222-2222-2222-222222222222   # enables the DCR shim
CUSTOM_DOMAIN=wingman.example.com
PUBLIC_URL=https://wingman.example.com
ENABLE_STATIC_KEY=true
EOF

./deploy.sh
```

First run does:

1. `az group create` (idempotent).
2. Foundation Bicep deploy.
3. (If `ENABLE_STATIC_KEY=true`) prompt for the access-key value, write to KV.
4. `az acr build` to push `wingman-mcp:latest` to the new ACR.
5. App Bicep deploy.

At the end it prints the default Container App FQDN. If you set `CUSTOM_DOMAIN`, follow the instructions it prints for DNS + cert binding, then re-run with `CERT_ID=<id>` to wire the cert.

## Re-deploys

```bash
# Image only (CI publishes a new tag):
IMAGE_TAG=abc1234 ./deploy.sh --skip-foundation --skip-secrets

# Fast iteration with registry-side layer cache (Docker Desktop required;
# builds linux/amd64 via qemu on Apple Silicon):
IMAGE_TAG=$(git -C ../wingman-mcp rev-parse --short HEAD) \
  ./deploy.sh --local --skip-foundation --skip-secrets

# Cert binding (one-time, after the manual hostname bind):
CERT_ID=/subscriptions/.../managedCertificates/mc-... \
  ./deploy.sh --skip-build --skip-secrets

# Foundation only (e.g. rotating role assignments without touching the app):
./deploy.sh --foundation-only --skip-build
```

## Bicep direct (no wrapper)

```bash
# Lint
az bicep build --file main.bicep --stdout > /dev/null
az bicep build-params --file params.bicepparam --stdout > /dev/null

# Preview
az deployment group what-if \
  -g rg-wingman-mcp \
  -f main.bicep -p params.bicepparam \
  -p deployContainerApp=true

# Deploy
az deployment group create \
  -g rg-wingman-mcp \
  -f main.bicep -p params.bicepparam \
  -p deployContainerApp=true
```

## Notes

- The Container App is conditional (`if (deployContainerApp)`), so the foundation can be created and an image pushed before the app exists. On follow-up runs with `deployContainerApp=true`, ARM compares the rendered template against the stored one; even cosmetic differences trigger a Container App revision roll. Plan accordingly when promoting.
- The `customDomains` array in `main.bicep` is gated on `uiCertificateId`, so a re-deploy without `CERT_ID` would strip the bound hostname. `deploy.sh` auto-recovers `CERT_ID` from the live app via `az containerapp hostname list` before phase 2, so subsequent re-deploys preserve the binding without you having to remember.
- The deploy is RG-scope; the resource group is created out-of-band by `deploy.sh`.
- KV is provisioned with `enablePurgeProtection: false` (default) so the vault can be hard-deleted during teardown. Flip it on once you're confident in the setup.
- The default ACR + KV names include an 8-char suffix from `uniqueString(resourceGroup().id)` so the deploy can clone into a different RG without name collisions.
