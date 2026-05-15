"""OAuth 2.0 client credentials flow for Workspace ONE UEM API access."""
import time
from typing import Optional

import httpx

from wingman_mcp.credentials import UEMCredentials


class UEMAuth:
    """Manages OAuth 2.0 bearer tokens for UEM API calls.

    Uses the client_credentials grant type. Tokens are cached in memory
    and automatically refreshed ~60 seconds before expiry.
    """

    def __init__(self, credentials: UEMCredentials) -> None:
        self._client_id = credentials["client_id"]
        self._client_secret = credentials["client_secret"]
        self._token_url = credentials["token_url"]
        self.api_base_url = credentials["api_base_url"]

        self._access_token: Optional[str] = None
        self._expires_at: float = 0.0

    def get_token(self) -> str:
        """Return a valid bearer token, refreshing if needed."""
        if self._access_token and time.time() < self._expires_at:
            return self._access_token
        self._refresh()
        return self._access_token

    def _refresh(self) -> None:
        """Fetch a new token from the OAuth server."""
        response = httpx.post(
            self._token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15.0,
        )
        response.raise_for_status()
        body = response.json()

        self._access_token = body["access_token"]
        expires_in = int(body.get("expires_in", 3600))
        # Refresh 60 seconds early to avoid using an about-to-expire token
        self._expires_at = time.time() + max(expires_in - 60, 0)

    def test_connection(self) -> dict:
        """Attempt to fetch a token and return the result for diagnostics."""
        try:
            self._refresh()
            return {
                "success": True,
                "token_url": self._token_url,
                "api_base_url": self.api_base_url,
                "expires_in": int(self._expires_at - time.time()),
            }
        except httpx.HTTPStatusError as e:
            return {
                "success": False,
                "error": f"HTTP {e.response.status_code}: {e.response.text[:200]}",
                "token_url": self._token_url,
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "token_url": self._token_url,
            }
