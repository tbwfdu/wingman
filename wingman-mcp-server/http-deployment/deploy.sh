#!/usr/bin/env bash
# Single-region wingman-mcp deployment wrapper.
#
# Two phases:
#   1) Foundation  -> ACR, KV, Log Analytics, Container Apps env, UAMI, roles
#   2) Container App -> wingman-mcp on the env
#
# Configuration is read from environment variables or a `.env` file next to
# this script. Required:
#
#   SUBSCRIPTION       Azure subscription ID
#   RG                 Resource group name (created if missing)
#   REGION             Azure region (e.g. eastus, westus2)
#   ENTRA_TENANT_ID    Entra tenant GUID
#
# Optional:
#
#   ENTRA_AUDIENCE          default 'api://wingman-mcp'
#   ENTRA_REQUIRED_SCOPE    default 'mcp.access'; '' to disable scope check
#   ENTRA_CLIENT_ID         Pre-registered client app ID. When set, enables the
#                           OAuth DCR shim so MCP clients only need the server URL.
#   CUSTOM_DOMAIN           default ''; e.g. wingman.example.com
#   PUBLIC_URL              default ''; canonical URL for OAuth discovery doc, e.g. https://wingman.example.com
#   ENABLE_STATIC_KEY       default 'false'; set 'true' to wire WINGMAN_MCP_ACCESS_KEY
#   WINGMAN_MCP_SRC         default '../wingman-mcp'; path to source for `az acr build`
#   IMAGE_TAG               default 'latest'
#   CERT_ID                 Managed cert resource ID; set after `az containerapp hostname bind`
#
# Flags:
#   --skip-build        Don't run the image build step
#   --skip-secrets      Don't prompt for KV secrets
#   --skip-foundation   Skip phase 1 (useful for re-deploys)
#   --foundation-only   Stop after phase 1
#   --local             Build with local `docker buildx` instead of `az acr build`.
#                       Enables registry-side layer caching (--cache-from /
#                       --cache-to=type=inline), so code-only re-builds skip the
#                       dep/model/stores layers. Requires Docker running locally.
#                       On Apple Silicon, builds amd64 via qemu emulation (slow
#                       cold, fast warm). Without --local, `az acr build` runs on
#                       Azure x86 infra but is uncached.
#   --tag <tag>         Override IMAGE_TAG
#   --cert-id <id>      Override CERT_ID

set -euo pipefail

cd "$(dirname "$0")"

[ -f .env ] && set -a && . ./.env && set +a

: "${SUBSCRIPTION:?SUBSCRIPTION env var required}"
: "${RG:?RG env var required}"
: "${REGION:?REGION env var required}"
: "${ENTRA_TENANT_ID:?ENTRA_TENANT_ID env var required}"

ENTRA_AUDIENCE="${ENTRA_AUDIENCE:-api://wingman-mcp}"
ENTRA_APP_ID_URI="${ENTRA_APP_ID_URI:-api://wingman-mcp}"
ENTRA_REQUIRED_SCOPE="${ENTRA_REQUIRED_SCOPE:-mcp.access}"
ENTRA_CLIENT_ID="${ENTRA_CLIENT_ID:-}"
CUSTOM_DOMAIN="${CUSTOM_DOMAIN:-}"
PUBLIC_URL="${PUBLIC_URL:-}"
ENABLE_STATIC_KEY="${ENABLE_STATIC_KEY:-false}"
WINGMAN_MCP_SRC="${WINGMAN_MCP_SRC:-../wingman-mcp}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
CERT_ID="${CERT_ID:-}"

SKIP_BUILD=false
SKIP_SECRETS=false
SKIP_FOUNDATION=false
FOUNDATION_ONLY=false
LOCAL_BUILD=false

while [ $# -gt 0 ]; do
  case "$1" in
    --skip-build) SKIP_BUILD=true ;;
    --skip-secrets) SKIP_SECRETS=true ;;
    --skip-foundation) SKIP_FOUNDATION=true ;;
    --foundation-only) FOUNDATION_ONLY=true ;;
    --local) LOCAL_BUILD=true ;;
    --tag) IMAGE_TAG="$2"; shift ;;
    --cert-id) CERT_ID="$2"; shift ;;
    -h|--help)
      sed -n '2,30p' "$0"
      exit 0
      ;;
    *) echo "Unknown flag: $1" >&2; exit 1 ;;
  esac
  shift
done

echo "Subscription : $SUBSCRIPTION"
echo "Resource grp : $RG"
echo "Region       : $REGION"
echo "Tenant       : $ENTRA_TENANT_ID"
echo "Client ID    : ${ENTRA_CLIENT_ID:-(none, DCR shim disabled)}"
echo "Custom domain: ${CUSTOM_DOMAIN:-(none)}"
echo "Public URL   : ${PUBLIC_URL:-(derive from Host header)}"
echo "Static key   : $ENABLE_STATIC_KEY"
echo

az account set --subscription "$SUBSCRIPTION"

# ---- Step 1: resource group --------------------------------------------------
echo "==> Ensuring resource group $RG in $REGION"
az group create -n "$RG" -l "$REGION" -o none

# ---- Step 2: foundation deploy -----------------------------------------------
if [ "$SKIP_FOUNDATION" != "true" ]; then
  echo "==> Phase 1: foundation"
  az deployment group create \
    -g "$RG" -n wingman-mcp-foundation \
    -f main.bicep -p params.bicepparam \
    -p location="$REGION" \
    -p entraTenantId="$ENTRA_TENANT_ID" \
    -p entraAudience="$ENTRA_AUDIENCE" \
    -p entraAppIdUri="$ENTRA_APP_ID_URI" \
    -p entraRequiredScope="$ENTRA_REQUIRED_SCOPE" \
    -p entraClientId="$ENTRA_CLIENT_ID" \
    -p customDomain="$CUSTOM_DOMAIN" \
    -p publicUrl="$PUBLIC_URL" \
    -p enableStaticAccessKey="$ENABLE_STATIC_KEY" \
    -p deployContainerApp=false \
    -o none
fi

ACR_NAME=$(az deployment group show -g "$RG" -n wingman-mcp-foundation \
  --query 'properties.outputs.acrName.value' -o tsv)
ACR_LOGIN_SERVER=$(az deployment group show -g "$RG" -n wingman-mcp-foundation \
  --query 'properties.outputs.acrLoginServer.value' -o tsv)
KV_NAME=$(az deployment group show -g "$RG" -n wingman-mcp-foundation \
  --query 'properties.outputs.keyVaultName.value' -o tsv)
CAE_NAME=$(az deployment group show -g "$RG" -n wingman-mcp-foundation \
  --query 'properties.outputs.containerAppEnvName.value' -o tsv)

echo "ACR  : $ACR_LOGIN_SERVER"
echo "KV   : $KV_NAME"
echo "CAE  : $CAE_NAME"

# ---- Step 3: secrets ---------------------------------------------------------
if [ "$ENABLE_STATIC_KEY" = "true" ] && [ "$SKIP_SECRETS" != "true" ]; then
  if az keyvault secret show --vault-name "$KV_NAME" --name wingman-mcp-access-key --query id -o tsv >/dev/null 2>&1; then
    echo "==> KV secret wingman-mcp-access-key already set; leaving as-is."
  else
    echo "==> Setting WINGMAN_MCP_ACCESS_KEY in KV"
    read -rsp "Enter value for WINGMAN_MCP_ACCESS_KEY (input hidden): " AK
    echo
    az keyvault secret set --vault-name "$KV_NAME" --name wingman-mcp-access-key --value "$AK" -o none
    unset AK
  fi
fi

if [ "$FOUNDATION_ONLY" = "true" ]; then
  echo
  echo "Stopped after foundation phase (--foundation-only)."
  exit 0
fi

# ---- Step 4: build image -----------------------------------------------------
if [ "$SKIP_BUILD" != "true" ]; then
  if [ ! -f "$WINGMAN_MCP_SRC/Dockerfile.bundled" ]; then
    echo "Cannot find $WINGMAN_MCP_SRC/Dockerfile.bundled" >&2
    echo "Set WINGMAN_MCP_SRC, or pass --skip-build and push the image yourself." >&2
    exit 1
  fi

  if [ "$LOCAL_BUILD" = "true" ]; then
    # Local buildx path: registry-side layer cache via --cache-from / inline
    # cache. Forces linux/amd64 so the image runs on Container Apps regardless
    # of host arch (qemu emulation on Apple Silicon).
    command -v docker >/dev/null 2>&1 || {
      echo "docker not found; --local requires Docker Desktop or equivalent" >&2
      exit 1
    }
    docker info >/dev/null 2>&1 || {
      echo "docker daemon not reachable; start Docker Desktop and retry" >&2
      exit 1
    }

    echo "==> Logging in to $ACR_LOGIN_SERVER"
    az acr login --name "$ACR_NAME" -o none

    # Ensure a buildx builder exists and is selected. Idempotent.
    if ! docker buildx inspect wingman-mcp-builder >/dev/null 2>&1; then
      docker buildx create --name wingman-mcp-builder --use >/dev/null
    else
      docker buildx use wingman-mcp-builder
    fi

    CACHE_REF="$ACR_LOGIN_SERVER/wingman-mcp:cache"
    echo "==> Building $ACR_LOGIN_SERVER/wingman-mcp:$IMAGE_TAG via docker buildx (linux/amd64, cache=$CACHE_REF)"
    docker buildx build \
      --platform linux/amd64 \
      -f "$WINGMAN_MCP_SRC/Dockerfile.bundled" \
      -t "$ACR_LOGIN_SERVER/wingman-mcp:$IMAGE_TAG" \
      -t "$ACR_LOGIN_SERVER/wingman-mcp:latest" \
      --cache-from "type=registry,ref=$CACHE_REF" \
      --cache-to "type=registry,ref=$CACHE_REF,mode=max" \
      --push \
      "$WINGMAN_MCP_SRC"
  else
    echo "==> Building image $ACR_LOGIN_SERVER/wingman-mcp:$IMAGE_TAG via az acr build (uncached)"
    az acr build \
      -r "$ACR_NAME" \
      -t "wingman-mcp:$IMAGE_TAG" \
      -t "wingman-mcp:latest" \
      -f "$WINGMAN_MCP_SRC/Dockerfile.bundled" \
      "$WINGMAN_MCP_SRC" \
      -o none
  fi
fi

# ---- Step 5: recover CERT_ID from existing binding (if any) ------------------
# The customDomains array in main.bicep is gated on uiCertificateId. If we
# re-deploy without CERT_ID after a previous bind, ARM would strip the binding
# (customDomains becomes []). Recover the cert from the live app so re-deploys
# preserve the bound hostname automatically.
if [ -n "$CUSTOM_DOMAIN" ] && [ -z "$CERT_ID" ]; then
  EXISTING_CERT_ID=$(az containerapp hostname list \
    -n wingman-mcp -g "$RG" \
    --query "[?name=='$CUSTOM_DOMAIN'].certificateId | [0]" \
    -o tsv 2>/dev/null || true)
  if [ -n "$EXISTING_CERT_ID" ] && [ "$EXISTING_CERT_ID" != "None" ]; then
    CERT_ID="$EXISTING_CERT_ID"
    echo "Recovered CERT_ID from existing binding: $CERT_ID"
  fi
fi

# ---- Step 6: app deploy ------------------------------------------------------
echo "==> Phase 2: container app"
az deployment group create \
  -g "$RG" -n wingman-mcp-app \
  -f main.bicep -p params.bicepparam \
  -p location="$REGION" \
  -p entraTenantId="$ENTRA_TENANT_ID" \
  -p entraAudience="$ENTRA_AUDIENCE" \
  -p entraAppIdUri="$ENTRA_APP_ID_URI" \
  -p entraRequiredScope="$ENTRA_REQUIRED_SCOPE" \
  -p entraClientId="$ENTRA_CLIENT_ID" \
  -p customDomain="$CUSTOM_DOMAIN" \
  -p publicUrl="$PUBLIC_URL" \
  -p enableStaticAccessKey="$ENABLE_STATIC_KEY" \
  -p deployContainerApp=true \
  -p uiCertificateId="$CERT_ID" \
  -p imageTag="$IMAGE_TAG" \
  -o none

FQDN=$(az deployment group show -g "$RG" -n wingman-mcp-app \
  --query 'properties.outputs.containerAppFqdn.value' -o tsv)

echo
echo "wingman-mcp deployed."
echo "  Default FQDN  : https://$FQDN"
echo "  Health check  : https://$FQDN/health"
echo "  MCP endpoint  : https://$FQDN/mcp"
echo

if [ -n "$CUSTOM_DOMAIN" ] && [ -z "$CERT_ID" ]; then
  cat <<EOF
Custom domain not yet bound. Next steps for $CUSTOM_DOMAIN:

  1) DNS: add a CNAME record
       $CUSTOM_DOMAIN  ->  $FQDN
     (some DNS providers require flattening; ALIAS / ANAME also works.)

  2) Once the CNAME resolves, bind the hostname and issue a managed cert:
       az containerapp hostname bind \\
         -n wingman-mcp -g $RG \\
         --hostname $CUSTOM_DOMAIN \\
         --environment $CAE_NAME \\
         --validation-method CNAME

  3) Capture the managed certificate resource ID:
       az containerapp hostname list \\
         -n wingman-mcp -g $RG \\
         --query "[?name=='$CUSTOM_DOMAIN'].certificateId" -o tsv

  4) Re-run with the cert ID to wire SNI binding:
       CERT_ID=<id-from-step-3> ./deploy.sh --skip-build --skip-secrets

EOF
fi
