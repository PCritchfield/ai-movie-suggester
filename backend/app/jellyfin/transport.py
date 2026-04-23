"""Shared Jellyfin HTTP transport helper.

Extracted from JellyfinClient so that capability clients
(JellyfinSessionsClient, JellyfinPlaybackClient, and future ones) can
consume the same MediaBrowser-auth-header + error-mapping logic without
duplicating it or inheriting from JellyfinClient.

Used via composition: each capability client holds a ``_JellyfinTransport``
and calls ``transport.request(...)`` internally.

Module-level helper functions were rejected: they would either re-derive
instance state (base URL, device id) per call or smuggle it through
closures, bloating call sites. A small class gives us a clean injection
seam at each capability client's constructor.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.jellyfin.errors import (
    JellyfinAuthError,
    JellyfinConnectionError,
    JellyfinError,
)

_APP_NAME = "ai-movie-suggester"
_APP_VERSION = "0.1.0"
_DEVICE = "Server"
_DEFAULT_DEVICE_ID = "ai-movie-suggester-server"


class _JellyfinTransport:
    """Shared HTTP transport for Jellyfin capability clients.

    Holds the base URL, a shared ``httpx.AsyncClient``, and the
    MediaBrowser auth-value template. Exposes:

    * ``headers(token=None)`` — build the Authorization header,
      optionally including a per-request user token.
    * ``request(method, path, ...)`` — perform a request and map
      401 → ``JellyfinAuthError``, transport errors →
      ``JellyfinConnectionError``, and other non-2xx →
      ``JellyfinError``.
    """

    __slots__ = ("_auth_value", "base_url", "client", "device_id")

    def __init__(
        self,
        base_url: str,
        client: httpx.AsyncClient,
        device_id: str = _DEFAULT_DEVICE_ID,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.client = client
        self.device_id = device_id
        self._auth_value = (
            f'MediaBrowser Client="{_APP_NAME}", '
            f'Device="{_DEVICE}", '
            f'DeviceId="{device_id}", '
            f'Version="{_APP_VERSION}"'
        )

    def headers(self, token: str | None = None) -> dict[str, str]:
        """Build Jellyfin Authorization header, optionally with token."""
        value = (
            self._auth_value
            if token is None
            else f"{self._auth_value}, Token={token.strip()}"
        )
        return {"Authorization": value}

    async def request(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        auth_error_message: str = "Token is invalid or expired",
        **kwargs: Any,
    ) -> httpx.Response:
        """Send a request to Jellyfin with standard error handling.

        Raises ``JellyfinAuthError`` on 401.
        Raises ``JellyfinConnectionError`` on transport failure.
        Raises ``JellyfinError`` on other non-2xx responses.
        """
        try:
            resp = await self.client.request(
                method,
                f"{self.base_url}{path}",
                headers=self.headers(token),
                **kwargs,
            )
        except httpx.TransportError as exc:
            raise JellyfinConnectionError(
                f"Cannot reach Jellyfin at {self.base_url}"
            ) from exc

        if resp.status_code == 401:
            raise JellyfinAuthError(auth_error_message)

        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise JellyfinError(
                f"Unexpected response from Jellyfin: {resp.status_code}"
            ) from exc

        return resp
