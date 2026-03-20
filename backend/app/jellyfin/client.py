"""Async HTTP client for the Jellyfin API.

Uses an injected httpx.AsyncClient for connection pooling and testability.
MediaBrowser authorization headers follow Jellyfin's own integration test
format (Authorization header, not X-Emby-Authorization; no quotes on Token).
"""

from __future__ import annotations

import logging

import httpx

from app.jellyfin.errors import (
    JellyfinAuthError,
    JellyfinConnectionError,
    JellyfinError,
)
from app.jellyfin.models import AuthResult

logger = logging.getLogger(__name__)

_APP_NAME = "ai-movie-suggester"
_APP_VERSION = "0.1.0"
_DEVICE = "Server"
_DEFAULT_DEVICE_ID = "ai-movie-suggester-server"


class JellyfinClient:
    """Async client for the Jellyfin REST API."""

    def __init__(
        self,
        base_url: str,
        http_client: httpx.AsyncClient,
        device_id: str = _DEFAULT_DEVICE_ID,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = http_client
        self._auth_value = (
            f'MediaBrowser Client="{_APP_NAME}", '
            f'Device="{_DEVICE}", '
            f'DeviceId="{device_id}", '
            f'Version="{_APP_VERSION}"'
        )

    def _headers(self, token: str | None = None) -> dict[str, str]:
        """Build Jellyfin Authorization header, optionally with token."""
        value = (
            self._auth_value
            if token is None
            else f"{self._auth_value}, Token={token}"
        )
        return {"Authorization": value}

    async def authenticate(self, username: str, password: str) -> AuthResult:
        """Authenticate a user against Jellyfin.

        Returns an AuthResult with the access token and user info.
        Raises JellyfinAuthError on invalid credentials.
        Raises JellyfinConnectionError if Jellyfin is unreachable.
        """
        try:
            resp = await self._client.post(
                f"{self._base_url}/Users/AuthenticateByName",
                json={"Username": username, "Pw": password},
                headers=self._headers(),
            )
        except httpx.TransportError as exc:
            raise JellyfinConnectionError(
                f"Cannot reach Jellyfin at {self._base_url}"
            ) from exc

        if resp.status_code == 401:
            raise JellyfinAuthError("Invalid username or password")

        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise JellyfinError(
                f"Unexpected response from Jellyfin: {resp.status_code}"
            ) from exc

        return AuthResult.from_jellyfin(resp.json())
