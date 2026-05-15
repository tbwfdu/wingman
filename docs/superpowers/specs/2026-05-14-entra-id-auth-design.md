# Entra ID Authentication for Wingman MCP (HTTP transport)

Status: Design approved, ready for plan
Date: 2026-05-14
Scope: HTTP mode only. The stdio transport is unaffected.

## Problem

Today, when Wingman MCP runs over HTTP (`run_http_server` in `src/wingman_mcp/server.py`), it accepts any caller that presents the right shared secret in the `X-Wingman-Access-Key` header (`src/wingman_mcp/middleware.py:49`). The same `CredentialHeaderMiddleware` also reads per-user UEM credentials from `X-UEM-*` headers. The result is:

- One static secret protects the whole server, shared by every user.
- No identity is captured per request; logs and downstream UEM audit trails cannot attribute actions to a person.
- Adding revocation or per-user policy requires rotating the shared key, which disrupts everyone.

We want to authenticate users with Entra ID instead, while leaving the per-user UEM credential model intact for now.

## Goals

- Validate Entra-issued OAuth 2.0 access tokens on every HTTP request.
- Capture the verified user identity (`oid`, `tid`, `upn`) per request so tools can read it.
- Keep the existing `X-UEM-*` header flow unchanged; this change adds identity, it does not move credentials.
- Single-tenant only. Multi-tenant and personal MSAs are out of scope.
- Keep the existing static-key path as an opt-in fallback for service accounts and smoke tests.
- Fail loudly at boot if no auth path is configured.

## Non-goals

- Server-side storage of UEM credentials keyed by user (deferred; can layer on later).
- Role-based authorization per tool (deferred; the design leaves room for it via `ENTRA_REQUIRED_SCOPE` and an unused `mcp.access` scope).
- ~~MCP authorization-server metadata discovery (`/.well-known/oauth-protected-resource`). Out of scope for v1; can be added without disturbing this middleware.~~ Added post-v1 in `src/wingman_mcp/well_known.py`; served unauthenticated alongside `/health`. Returns 404 when `ENTRA_TENANT_ID` is unset.
- ~~RFC 7591 dynamic client registration. Entra doesn't support it, so end users had to paste a static-oauth blob into their MCP client config.~~ Resolved by adding an OAuth DCR shim in `src/wingman_mcp/oauth_shim.py` (post-v1). The server advertises itself as the AS in protected-resource metadata, returns the operator-configured `ENTRA_CLIENT_ID` for any `/oauth/register` POST, 302-redirects `/oauth/authorize` to Entra v2 (with `offline_access` appended), and proxies `/oauth/token` to Entra. Tokens are still minted by and validated against Entra; the shim is stateless.
- Changes to the stdio transport or CLI mode.

## Approach

Add a dedicated `EntraAuthMiddleware` ASGI middleware in front of the existing `CredentialHeaderMiddleware`. Identity (who is calling) and credential extraction (what UEM creds did they bring) become separate concerns in separate modules, each independently testable.

```
ASGI request
  -> EntraAuthMiddleware       (identity)
  -> CredentialHeaderMiddleware (UEM creds: unchanged behavior)
  -> MCP StreamableHTTPSessionManager
```

Rejected alternatives:

- **Extend `CredentialHeaderMiddleware` to also validate the JWT.** Fewest lines but conflates two responsibilities that have already grown the file. Harder to test in isolation.
- **Use MSAL (Microsoft's official SDK).** MSAL is designed for *acquiring* tokens, not validating them on a resource server. We would still end up using `PyJWT` underneath. Extra dependency for no gain.

## Components

### New: `src/wingman_mcp/entra_auth.py`

Exports `EntraAuthMiddleware`, an ASGI middleware. Its only job is to decide whether a request is allowed through and stamp a verified identity into the request context. It does not touch UEM headers, does not mutate responses beyond the auth-failure paths, and is the sole owner of the static-key fallback.

### New: `src/wingman_mcp/jwks.py`

A small JWKS fetcher with in-memory caching. Contract:

- `get_signing_key(kid: str) -> jwt.PyJWK` returns the key matching `kid`.
- TTL: 1 hour. On cache miss for an unknown `kid`, refetch once before erroring (handles key rotation).
- Single asyncio lock guards refetches so concurrent cold-start requests issue one network call.
- Network failures raise `JWKSUnavailable` so the middleware can return a clean 503.

### Modified: `src/wingman_mcp/middleware.py`

`CredentialHeaderMiddleware` loses its static-key check (`middleware.py:49`). It keeps the `/health` bypass (left in place as defense in depth so the inner middleware is still safe if mounted alone in a test) and the `X-UEM-*` extraction. It becomes purely about UEM credentials.

### Modified: `src/wingman_mcp/request_context.py`

Adds one ContextVar: `_request_principal: ContextVar[Optional[Principal]]` with default `None`. `Principal` is a frozen dataclass: `oid: Optional[str]`, `tid: Optional[str]`, `upn: Optional[str]`, `auth_method: Literal["entra", "static_key"]`. Tools that want to log "who did this" can read it; nothing in this change requires them to.

### Modified: `src/wingman_mcp/server.py` (`run_http_server`)

- Mount `EntraAuthMiddleware` outside `CredentialHeaderMiddleware`.
- Before binding the socket, refuse to start if both `ENTRA_TENANT_ID` and `WINGMAN_MCP_ACCESS_KEY` are unset; print a clear error and exit non-zero.

## Configuration

Environment variables read at startup:

| Var | Required | Default | Purpose |
|---|---|---|---|
| `ENTRA_TENANT_ID` | If JWT auth is used | (none) | Single Entra tenant whose users are accepted. Used to derive `iss` and to enforce `tid` defense in depth. |
| `ENTRA_AUDIENCE` | No | `api://wingman-mcp` | Expected `aud` claim. |
| `ENTRA_REQUIRED_SCOPE` | No | `mcp.access` | If non-empty, token must carry this in the space-delimited `scp` claim. Set to empty to skip the scope check. |
| `WINGMAN_MCP_ACCESS_KEY` | If JWT auth is not used | (none) | Enables the static-key fallback. If unset, the static path is fully off. |

Boot-time guard: if both `ENTRA_TENANT_ID` and `WINGMAN_MCP_ACCESS_KEY` are unset, `run_http_server` raises before binding the socket. This prevents an effectively-open server from silently starting.

## Entra app registration (operator setup)

One-time configuration in the Entra admin center; the implementation depends on it but does not perform it.

1. **App registration**, single-tenant.
   - Name: `Wingman MCP`.
   - Supported account types: *Accounts in this organizational directory only*.
   - No redirect URI on the resource server itself; client apps register their own.
2. **Expose an API.**
   - Application ID URI: `api://wingman-mcp` (this becomes the JWT `aud`).
   - Add a default scope `mcp.access` (admin-and-user consent). Even with no RBAC today, exposing a scope lets future authorization slot in without breaking existing tokens.
3. **Token configuration.**
   - Add optional claims on the access token: `preferred_username`, `email`. `oid` and `tid` are present by default and are what we key on.
4. **Manifest.**
   - Set `accessTokenAcceptedVersion: 2` so the issuer is `https://login.microsoftonline.com/<tenant-id>/v2.0`.
5. **No client secret** on the resource server. Wingman MCP is a resource server only; it validates tokens but never acquires them. Client apps (Claude Desktop, scripts) do their own registration as public clients with PKCE if they need to call us.

## Per-request data flow

For each request to `/mcp`:

1. **Health bypass.** `path == "/health"` short-circuits with 200, before any auth. Preserves existing behavior.
2. **Extract `Authorization` header.** If present and starts with `Bearer `, take the rest as the token. Otherwise fall through to step 4.
3. **JWT validation path:**
   1. Decode the unverified header to get `kid`.
   2. Fetch the signing key from `jwks.py`; on `kid` miss, refetch once before erroring.
   3. `jwt.decode(token, key, algorithms=["RS256"], audience=ENTRA_AUDIENCE, issuer=f"https://login.microsoftonline.com/{TENANT_ID}/v2.0", options={"require": ["exp", "iss", "aud", "tid", "oid"]}, leeway=30)`.
   4. Enforce `tid == ENTRA_TENANT_ID` explicitly (defense in depth; `iss` already binds it, but a clearer error helps operators).
   5. If `ENTRA_REQUIRED_SCOPE` is non-empty, require it in the space-delimited `scp` claim.
   6. Build `Principal(oid=claims["oid"], tid=claims["tid"], upn=claims.get("preferred_username"), auth_method="entra")`. Set `_request_principal`. Forward to the inner app.
4. **Static-key fallback** (only if no `Authorization` header was present and `WINGMAN_MCP_ACCESS_KEY` is set):
   - Compare `X-Wingman-Access-Key` against the env value using `hmac.compare_digest` (constant-time).
   - On match: `Principal(oid=None, tid=None, upn=None, auth_method="static_key")`. Forward.
   - On miss: 401.
5. **No auth at all** (no bearer, static-key disabled or absent): 401.

Downstream, `CredentialHeaderMiddleware` runs unchanged and still sets `_request_credentials` from `X-UEM-*` headers.

## Error responses

All failures inside `EntraAuthMiddleware` return JSON and short-circuit. Status codes follow RFC 6750.

| Condition | Status | `WWW-Authenticate` | Body `error` |
|---|---|---|---|
| No `Authorization` and static-key disabled or missing | 401 | `Bearer realm="wingman-mcp"` | `unauthorized` |
| Malformed header (not `Bearer <token>`) | 401 | `Bearer error="invalid_request"` | `invalid_request` |
| JWKS unreachable after retry | 503 | (omitted) | `auth_unavailable` |
| Signature invalid, expired, wrong `iss`/`aud`/`tid` | 401 | `Bearer error="invalid_token"` | `invalid_token` |
| Missing required scope | 403 | `Bearer error="insufficient_scope", scope="mcp.access"` | `insufficient_scope` |
| Static-key path: header missing or mismatched | 401 | `Bearer realm="wingman-mcp"` | `unauthorized` |

Response bodies are minimal: `{"error": "<code>", "error_description": "<human-safe message>"}`. No claims, no token fragments, no internal exception text leaks to the caller.

Internal exception text is logged server-side at `WARNING` for auth failures and `ERROR` for JWKS or unexpected errors, with `kid`, `iss`, `aud` from the offending token where available, plus caller IP from `scope["client"]`. Successful requests log nothing at the auth layer; tools that want to attribute actions read `_request_principal` themselves.

## Testing

Three layers, all hermetic (no live Entra calls in CI). RSA keypair is generated per-test-session and used to mint test tokens with `PyJWT`.

### `tests/test_jwks.py`

- Fetches once, serves from cache on the second call.
- TTL expiry triggers a refetch.
- Cold-start stampede: many concurrent callers result in exactly one network call.
- Network failure raises `JWKSUnavailable`.
- Network mocked with `respx` or `httpx.MockTransport`.

### `tests/test_entra_auth.py`

Driven via Starlette's `TestClient` with a stub inner app that echoes `_request_principal`. `jwks` is monkeypatched to return the test public key.

Cases:

- Valid token: 200, principal stamped with `auth_method="entra"`.
- Expired token: 401 `invalid_token`.
- Wrong audience: 401.
- Wrong issuer: 401.
- Wrong tenant: 401 (catches the `tid` defense-in-depth check).
- Missing required scope: 403 `insufficient_scope`.
- Malformed `Authorization` header: 401 `invalid_request`.
- No auth header, static-key disabled: 401.
- No auth header, static-key enabled and matching: 200, `auth_method="static_key"`.
- No auth header, static-key enabled and wrong: 401.
- `/health` bypasses everything.
- Boot-time guard: with both `ENTRA_TENANT_ID` and `WINGMAN_MCP_ACCESS_KEY` unset, `run_http_server` raises before binding.

### `tests/test_http_auth_integration.py`

Wires `EntraAuthMiddleware` -> `CredentialHeaderMiddleware` -> a stub inner app. Sends a request carrying both a valid stubbed JWT and `X-UEM-*` headers; asserts the inner app sees both `_request_principal` and `_request_credentials`. Guards against future refactors that accidentally re-couple the two middlewares.

## Open questions

None blocking. Two items to track for follow-up work, explicitly deferred from this design:

- Server-side UEM credential lookup keyed by `oid`, so clients no longer need to send their UEM secret on every request.
- App roles for tiered authorization (e.g. `Wingman.Admin` to gate destructive tools like `horizon_restart_machines`).
