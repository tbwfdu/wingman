"""OAuth 2.0 client for the wingman-mcp stdio bridge.

The bridge (`wingman-mcp serve --remote <url>`) talks to a remote, Entra-
protected MCP server. This module obtains and caches the bearer token the
bridge needs, so credentials never have to be pasted into a Claude config.

Flow (all routed through the server's OAuth shim, so no npx / mcp-remote):

  1. Discover the protected-resource metadata + authorization-server
     metadata from the remote server's /.well-known endpoints.
  2. Register (the shim hands back a fixed Entra client_id).
  3. Run an Authorization Code + PKCE flow with a loopback redirect,
     launching the user's browser once.
  4. Cache access + refresh tokens in the OS keychain.
  5. On later calls, return the cached token, refreshing transparently
     when it is close to expiry.

Token cache layout:
    keychain service   wingman-mcp.oauth.<host>
    keychain account   bundle   -> JSON {access_token, refresh_token,
                                          expires_at, token_endpoint,
                                          client_id, scope}
"""
from __future__ import annotations

import base64
import hashlib
import http.server
import json
import secrets
import threading
import time
import urllib.parse
import webbrowser
from dataclasses import dataclass
from typing import Optional

import httpx
import keyring

# RFC 9728 fixed path. Inlined (rather than imported from the server-side
# well_known module) so the bridge package has no dependency on server code.
PRM_PATH = "/.well-known/oauth-protected-resource"

OAUTH_SERVICE_BASE = "wingman-mcp.oauth"
_BUNDLE_ACCOUNT = "bundle"
# Refresh when the token has this many seconds (or fewer) of life left.
_EXPIRY_BUFFER_SECONDS = 120
_CALLBACK_PATH = "/callback"


class NotLoggedIn(RuntimeError):
    """Raised when no usable token is cached and no browser flow has run."""


class OAuthError(RuntimeError):
    """Raised when an OAuth endpoint returns an error response."""


# ---------------------------------------------------------------------------
# Pure helpers (no I/O — unit tested directly)
# ---------------------------------------------------------------------------

def host_of(remote_url: str) -> str:
    """Network location (host[:port]) of a remote MCP server URL."""
    netloc = urllib.parse.urlparse(remote_url).netloc
    if not netloc:
        raise ValueError(f"remote URL has no host: {remote_url!r}")
    return netloc


def _service_name(remote_url: str) -> str:
    return f"{OAUTH_SERVICE_BASE}.{host_of(remote_url)}"


def generate_pkce() -> tuple[str, str]:
    """Return a (code_verifier, code_challenge) PKCE pair using S256."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode("ascii")
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def token_needs_refresh(expires_at: float, *, now: Optional[float] = None) -> bool:
    """True if a token expiring at `expires_at` should be refreshed now."""
    now = time.time() if now is None else now
    return expires_at - now <= _EXPIRY_BUFFER_SECONDS


def prm_url(remote_url: str) -> str:
    """Protected-resource-metadata URL for a remote MCP server URL.

    RFC 9728 places the document at the origin root, not under the MCP
    path, so `https://host/mcp` -> `https://host/.well-known/...`.
    """
    parts = urllib.parse.urlparse(remote_url)
    return f"{parts.scheme}://{parts.netloc}{PRM_PATH}"


# ---------------------------------------------------------------------------
# Token cache (OS keychain)
# ---------------------------------------------------------------------------

@dataclass
class TokenBundle:
    access_token: str
    refresh_token: str
    expires_at: float
    token_endpoint: str
    client_id: str
    scope: str

    def to_json(self) -> str:
        return json.dumps(self.__dict__)

    @classmethod
    def from_json(cls, raw: str) -> "TokenBundle":
        return cls(**json.loads(raw))


def load_bundle(remote_url: str) -> Optional[TokenBundle]:
    raw = keyring.get_password(_service_name(remote_url), _BUNDLE_ACCOUNT)
    if not raw:
        return None
    try:
        return TokenBundle.from_json(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def store_bundle(remote_url: str, bundle: TokenBundle) -> None:
    keyring.set_password(_service_name(remote_url), _BUNDLE_ACCOUNT, bundle.to_json())


def clear_bundle(remote_url: str) -> None:
    try:
        keyring.delete_password(_service_name(remote_url), _BUNDLE_ACCOUNT)
    except keyring.errors.PasswordDeleteError:
        pass


# ---------------------------------------------------------------------------
# Discovery + token endpoint calls (httpx client injectable for tests)
# ---------------------------------------------------------------------------

@dataclass
class Discovery:
    authorization_endpoint: str
    token_endpoint: str
    registration_endpoint: str
    scopes_supported: list[str]


async def discover(remote_url: str, *, client: httpx.AsyncClient) -> Discovery:
    """Fetch protected-resource + authorization-server metadata."""
    prm_resp = await client.get(prm_url(remote_url))
    if prm_resp.status_code != 200:
        raise OAuthError(
            f"protected-resource discovery failed ({prm_resp.status_code}). "
            "The remote server may not require auth, or the URL is wrong."
        )
    prm = prm_resp.json()
    servers = prm.get("authorization_servers") or []
    if not servers:
        raise OAuthError("discovery document advertises no authorization server")
    as_base = servers[0].rstrip("/")
    scopes = list(prm.get("scopes_supported") or [])

    as_resp = await client.get(f"{as_base}/.well-known/oauth-authorization-server")
    if as_resp.status_code != 200:
        raise OAuthError(
            f"authorization-server discovery failed ({as_resp.status_code})"
        )
    meta = as_resp.json()
    try:
        return Discovery(
            authorization_endpoint=meta["authorization_endpoint"],
            token_endpoint=meta["token_endpoint"],
            registration_endpoint=meta["registration_endpoint"],
            scopes_supported=scopes or list(meta.get("scopes_supported") or []),
        )
    except KeyError as exc:
        raise OAuthError(f"authorization-server metadata missing {exc}") from exc


async def register_client(
    registration_endpoint: str,
    *,
    redirect_uri: str,
    client: httpx.AsyncClient,
) -> str:
    """Register with the shim and return the client_id it hands back."""
    resp = await client.post(
        registration_endpoint,
        json={
            "redirect_uris": [redirect_uri],
            "client_name": "wingman-mcp bridge",
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
        },
    )
    if resp.status_code not in (200, 201):
        raise OAuthError(f"client registration failed ({resp.status_code}): {resp.text}")
    client_id = resp.json().get("client_id")
    if not client_id:
        raise OAuthError("registration response carried no client_id")
    return client_id


def _bundle_from_token_response(
    payload: dict,
    *,
    token_endpoint: str,
    client_id: str,
    scope: str,
    fallback_refresh_token: str = "",
    now: Optional[float] = None,
) -> TokenBundle:
    now = time.time() if now is None else now
    access = payload.get("access_token")
    if not access:
        raise OAuthError(f"token response carried no access_token: {payload}")
    expires_in = float(payload.get("expires_in", 3600))
    return TokenBundle(
        access_token=access,
        refresh_token=payload.get("refresh_token") or fallback_refresh_token,
        expires_at=now + expires_in,
        token_endpoint=token_endpoint,
        client_id=client_id,
        scope=scope,
    )


async def exchange_code(
    *,
    token_endpoint: str,
    client_id: str,
    code: str,
    code_verifier: str,
    redirect_uri: str,
    scope: str,
    client: httpx.AsyncClient,
) -> TokenBundle:
    resp = await client.post(
        token_endpoint,
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": code,
            "code_verifier": code_verifier,
            "redirect_uri": redirect_uri,
        },
    )
    if resp.status_code != 200:
        raise OAuthError(f"code exchange failed ({resp.status_code}): {resp.text}")
    return _bundle_from_token_response(
        resp.json(), token_endpoint=token_endpoint, client_id=client_id, scope=scope
    )


async def refresh_bundle(
    bundle: TokenBundle, *, client: httpx.AsyncClient
) -> TokenBundle:
    if not bundle.refresh_token:
        raise NotLoggedIn("no refresh token cached")
    resp = await client.post(
        bundle.token_endpoint,
        data={
            "grant_type": "refresh_token",
            "client_id": bundle.client_id,
            "refresh_token": bundle.refresh_token,
            "scope": bundle.scope,
        },
    )
    if resp.status_code != 200:
        raise NotLoggedIn(
            f"token refresh failed ({resp.status_code}); run 'wingman-mcp login'"
        )
    return _bundle_from_token_response(
        resp.json(),
        token_endpoint=bundle.token_endpoint,
        client_id=bundle.client_id,
        scope=bundle.scope,
        fallback_refresh_token=bundle.refresh_token,
    )


# ---------------------------------------------------------------------------
# Loopback redirect listener for the browser flow
# ---------------------------------------------------------------------------

class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    """Captures the single OAuth redirect; ignores everything else."""

    def do_GET(self):  # noqa: N802 (stdlib naming)
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != _CALLBACK_PATH:
            self.send_response(404)
            self.end_headers()
            return
        params = dict(urllib.parse.parse_qsl(parsed.query))
        self.server.oauth_result = params  # type: ignore[attr-defined]
        body = (
            b"<html><body style='font-family:sans-serif'>"
            b"<h2>wingman-mcp</h2><p>Sign-in complete. "
            b"You can close this tab and return to your terminal.</p>"
            b"</body></html>"
        )
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # silence stdlib request logging
        pass


# ---------------------------------------------------------------------------
# Public orchestration
# ---------------------------------------------------------------------------

async def login(remote_url: str, *, client: Optional[httpx.AsyncClient] = None) -> None:
    """Run the interactive browser flow and cache tokens for `remote_url`."""
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=30.0, follow_redirects=False)
    try:
        disc = await discover(remote_url, client=client)
        scope = " ".join(disc.scopes_supported)
        verifier, challenge = generate_pkce()
        state = secrets.token_urlsafe(16)
        bundle = await _login_with_loopback(
            disc=disc,
            scope=scope,
            verifier=verifier,
            challenge=challenge,
            state=state,
            client=client,
        )
        store_bundle(remote_url, bundle)
        print("Sign-in complete; token cached in your OS keychain.", flush=True)
    finally:
        if owns_client:
            await client.aclose()


async def _login_with_loopback(
    *,
    disc: Discovery,
    scope: str,
    verifier: str,
    challenge: str,
    state: str,
    client: httpx.AsyncClient,
) -> TokenBundle:
    """Bind the loopback socket, register, run the browser flow, exchange."""
    import asyncio

    server = http.server.HTTPServer(("127.0.0.1", 0), _CallbackHandler)
    server.oauth_result = None  # type: ignore[attr-defined]
    port = server.server_address[1]
    redirect_uri = f"http://localhost:{port}{_CALLBACK_PATH}"

    client_id = await register_client(
        disc.registration_endpoint, redirect_uri=redirect_uri, client=client
    )

    query = urllib.parse.urlencode({
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scope,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })
    authorize_url = f"{disc.authorization_endpoint}?{query}"

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        print(f"Opening browser for sign-in:\n  {authorize_url}\n", flush=True)
        webbrowser.open(authorize_url)
        deadline = time.time() + 300.0
        while server.oauth_result is None and time.time() < deadline:  # type: ignore[attr-defined]
            await asyncio.sleep(0.2)
    finally:
        server.shutdown()
        thread.join(timeout=5)

    result = server.oauth_result  # type: ignore[attr-defined]
    if result is None:
        raise OAuthError("timed out waiting for the browser sign-in to complete")
    if "error" in result:
        raise OAuthError(
            f"authorization failed: {result.get('error')} "
            f"{result.get('error_description', '')}".strip()
        )
    if result.get("state") != state:
        raise OAuthError("state mismatch on OAuth callback (possible CSRF)")
    code = result.get("code")
    if not code:
        raise OAuthError("OAuth callback carried no authorization code")

    return await exchange_code(
        token_endpoint=disc.token_endpoint,
        client_id=client_id,
        code=code,
        code_verifier=verifier,
        redirect_uri=redirect_uri,
        scope=scope,
        client=client,
    )


async def get_access_token(
    remote_url: str, *, client: Optional[httpx.AsyncClient] = None
) -> str:
    """Return a valid bearer token, refreshing if needed.

    Raises NotLoggedIn if no token is cached or the refresh token is
    dead — the caller should tell the user to run `wingman-mcp login`.
    """
    bundle = load_bundle(remote_url)
    if bundle is None:
        raise NotLoggedIn(
            f"not signed in to {host_of(remote_url)}; run 'wingman-mcp login'"
        )
    if not token_needs_refresh(bundle.expires_at):
        return bundle.access_token

    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=30.0)
    try:
        refreshed = await refresh_bundle(bundle, client=client)
    finally:
        if owns_client:
            await client.aclose()
    store_bundle(remote_url, refreshed)
    return refreshed.access_token
