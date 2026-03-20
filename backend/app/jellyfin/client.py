"""Async HTTP client for the Jellyfin API.

Uses an injected httpx.AsyncClient for connection pooling and testability.
MediaBrowser authorization headers follow Jellyfin's own integration test
format (Authorization header, not X-Emby-Authorization; no quotes on Token).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import httpx

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
