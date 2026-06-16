# wingman-mcp HTTP Transport Flow

How an HTTP request travels through the hosted/cloud transport of the
wingman-mcp server, from the MCP client to MCP tool dispatch.

The server wraps the shared MCP tool app (`wingman_mcp.server.app`) in a
three-layer ASGI stack: Entra ID authentication, per-request credential-header
extraction, and a path router that also serves the OAuth discovery and shim
endpoints. Authenticated identity and per-request credentials are carried in
`ContextVar`s; nothing is stored server-side.

> Scope: this diagram covers the HTTP transport, auth, OAuth, and routing
> layers only. The downstream per-product UEM and Horizon environment tool
> flows are deliberately collapsed into a single abstract node.

```mermaid
flowchart TD
    Client["MCP Client<br/><span>mcp-remote · Claude Desktop</span><br/><br/>Authorization: Bearer &lt;jwt&gt;<br/>or X-Wingman-Access-Key<br/>+ product X-* credential headers"]

    Uvicorn["Uvicorn ASGI server<br/><span>0.0.0.0:8000</span>"]

    subgraph L1["Layer 1 — EntraAuthMiddleware · entra_auth.py"]
        direction TB
        EntraPub{"is_public_path?"}
        EntraAuthSel{"Authorization<br/>header present?"}
        Bearer["Validate Bearer JWT<br/><span>JWKS · RS256 · aud / iss / tid / scp</span>"]
        Static["Validate static key<br/><span>HMAC compare X-Wingman-Access-Key</span>"]
        Principal["Set _request_principal<br/><span>Principal: oid · tid · upn · auth_method</span>"]
    end

    Reject["401 / 403 JSON error<br/><span>WWW-Authenticate: Bearer</span>"]

    subgraph L2["Layer 2 — CredentialHeaderMiddleware · middleware.py"]
        direction TB
        CredPub{"is_public_path?"}
        Collect["Collect per-product X-* headers<br/><span>fully-populated products only</span>"]
        Creds["Set _request_credentials<br/><span>bundle keyed by product slug</span>"]
    end

    subgraph L3["Layer 3 — _App path router · http_server.py"]
        direction TB
        Router{"route on path"}
        Health["/health<br/><span>PlainTextResponse ok</span>"]
        PRM["/.well-known/oauth-protected-resource<br/><span>RFC 9728 metadata · build_metadata()</span>"]
        ASM["/.well-known/oauth-authorization-server<br/><span>RFC 8414 metadata · shim only</span>"]
        Register["/oauth/register · POST<br/><span>RFC 7591 DCR shim · fixed client_id</span>"]
        Authorize["/oauth/authorize · GET<br/><span>302 redirect · entra_authorize_url()</span>"]
        Token["/oauth/token · POST<br/><span>proxy_token_request()</span>"]
        MCP["/mcp<br/><span>default route</span>"]
    end

    Session["StreamableHTTPSessionManager<br/><span>stateless · json_response=false</span>"]
    Tools["MCP tool handlers<br/><span>wingman_mcp.server.app — reads ContextVars</span>"]

    Entra(["Microsoft Entra ID<br/><span>login.microsoftonline.com</span>"])

    Client -->|"HTTP request"| Uvicorn
    Uvicorn --> EntraPub

    EntraPub -->|"yes"| CredPub
    EntraPub -->|"no"| EntraAuthSel
    EntraAuthSel -->|"yes"| Bearer
    EntraAuthSel -->|"no"| Static
    Bearer -->|"invalid"| Reject
    Static -->|"invalid"| Reject
    Bearer -->|"valid"| Principal
    Static -->|"valid"| Principal
    Principal --> CredPub

    CredPub -->|"yes"| Router
    CredPub -->|"no"| Collect
    Collect --> Creds
    Creds --> Router

    Router --> Health
    Router --> PRM
    Router --> ASM
    Router --> Register
    Router --> Authorize
    Router --> Token
    Router --> MCP

    Bearer -. "fetch signing keys (JWKS)" .-> Entra
    Authorize -. "302 redirect" .-> Entra
    Token -. "proxy token exchange" .-> Entra

    MCP --> Session
    Session --> Tools

    Tools -. "Streamable HTTP response (SSE / chunked JSON)" .-> Client

    classDef client fill:#1e293b,stroke:#0f172a,color:#f8fafc
    classDef server fill:#334155,stroke:#1e293b,color:#f8fafc
    classDef auth fill:#0e7490,stroke:#155e75,color:#ecfeff
    classDef cred fill:#7c3aed,stroke:#5b21b6,color:#f5f3ff
    classDef router fill:#b45309,stroke:#92400e,color:#fffbeb
    classDef oauth fill:#15803d,stroke:#166534,color:#f0fdf4
    classDef mcp fill:#be123c,stroke:#9f1239,color:#fff1f2
    classDef ext fill:#475569,stroke:#1e293b,color:#f8fafc,stroke-dasharray:4 3
    classDef reject fill:#dc2626,stroke:#991b1b,color:#fef2f2
    classDef gate fill:#1e293b,stroke:#475569,color:#e2e8f0

    class Client client
    class Uvicorn server
    class Bearer,Static,Principal auth
    class EntraPub,EntraAuthSel,CredPub,Router gate
    class Collect,Creds cred
    class Health,MCP router
    class PRM,ASM,Register,Authorize,Token oauth
    class Session,Tools mcp
    class Entra ext
    class Reject reject
```

## Components

| Component | Source | Role |
|-----------|--------|------|
| Uvicorn ASGI server | `http_server.py:250` | Listens on `0.0.0.0:8000`; serves the wrapped ASGI app. |
| EntraAuthMiddleware | `entra_auth.py:52` | Validates `Authorization: Bearer` JWTs against one Entra tenant (JWKS, RS256, `aud`/`iss`/`tid`/`scp`); falls back to `X-Wingman-Access-Key` when no `Authorization` header is sent. Stamps `_request_principal`. |
| CredentialHeaderMiddleware | `middleware.py:54` | Extracts per-product API credentials from `X-*` headers; a product is included only when all of its fields are present. Stamps `_request_credentials`. |
| `_App` path router | `http_server.py:94` | Routes on path: `/health`, OAuth discovery + shim endpoints, and `/mcp` (default). |
| OAuth discovery + shim | `well_known.py`, `oauth_shim.py` | RFC 9728 / 8414 metadata, RFC 7591 registration shim, and `/oauth/authorize` + `/oauth/token` proxying the dance to Entra. |
| StreamableHTTPSessionManager | `http_server.py:61` | Stateless Streamable HTTP transport; dispatches MCP requests to the shared tool app. |

## Notes

- **Public-path bypass.** `/health`, the `/.well-known/*` discovery docs, and the
  `/oauth/*` shim endpoints are listed in `well_known._PUBLIC_PATHS`. Both
  middleware layers check `is_public_path()` and pass straight through to the
  router, so these endpoints are served unauthenticated.
- **Stateless and storage-free.** `_request_principal` and
  `_request_credentials` are `ContextVar`s scoped to a single request. MCP tool
  handlers read them directly; no identity or credential is persisted.
- **Startup guard.** The HTTP server refuses to start unless either
  `ENTRA_TENANT_ID` or `WINGMAN_MCP_ACCESS_KEY` is set (`http_server.py:13`).
- **Shim gating.** The OAuth authorization-server metadata and `/oauth/*` shim
  endpoints return `404` unless both `ENTRA_TENANT_ID` and `ENTRA_CLIENT_ID`
  are configured (`shim_enabled`).
