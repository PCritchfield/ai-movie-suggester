"""Async HTTP client for the Jellyfin API.

Uses an injected httpx.AsyncClient for connection pooling and testability.
MediaBrowser authorization headers follow Jellyfin's own integration test
format (Authorization header, not X-Emby-Authorization; no quotes on Token).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, TypeVar

import httpx

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

from app.jellyfin.errors import (
    JellyfinAuthError,
    JellyfinConnectionError,
    JellyfinError,
)
from app.jellyfin.models import AuthResult, PaginatedItems, UserInfo

logger = logging.getLogger(__name__)

_T = TypeVar("_T")

_APP_NAME = "ai-movie-suggester"
_APP_VERSION = "0.1.0"
_DEVICE = "Server"
_DEFAULT_DEVICE_ID = "ai-movie-suggester-server"
# Fields to request from Jellyfin — matches our LibraryItem model
_ITEM_FIELDS = "Overview,Genres,ProductionYear,Tags,Studios,CommunityRating,People"


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
        self._server_name: str | None = None
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
            else f"{self._auth_value}, Token={token.strip()}"
        )
        return {"Authorization": value}

    async def _request(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        auth_error_message: str = "Token is invalid or expired",
        **kwargs: Any,
    ) -> httpx.Response:
        """Send a request to Jellyfin with standard error handling.

        Raises JellyfinAuthError on 401.
        Raises JellyfinConnectionError on transport failure.
        Raises JellyfinError on other non-2xx responses.
        """
        try:
            resp = await self._client.request(
                method,
                f"{self._base_url}{path}",
                headers=self._headers(token),
                **kwargs,
            )
        except httpx.TransportError as exc:
            raise JellyfinConnectionError(
                f"Cannot reach Jellyfin at {self._base_url}"
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

    @staticmethod
    def _parse_response(resp: httpx.Response, parser: Callable[..., _T]) -> _T:
        """Decode JSON and parse via *parser*, wrapping errors as JellyfinError."""
        try:
            data = resp.json()
        except Exception as exc:
            raise JellyfinError("Invalid JSON in Jellyfin response") from exc
        try:
            return parser(data)
        except Exception as exc:
            raise JellyfinError("Unexpected response shape from Jellyfin") from exc

    async def logout(self, token: str) -> None:
        """Revoke a Jellyfin session token.

        Calls POST /Sessions/Logout. On 401 (already revoked), logs at
        DEBUG and returns normally. On transport error, raises
        JellyfinConnectionError for the caller to handle.
        """
        try:
            await self._request(
                "POST",
                "/Sessions/Logout",
                token=token,
            )
        except JellyfinAuthError:
            logger.debug("token already revoked during logout")

    async def get_server_name(self) -> str:
        """Return the Jellyfin server name (cached after first call).

        Calls GET /System/Info/Public (no auth required).
        """
        if self._server_name is not None:
            return self._server_name
        resp = await self._request("GET", "/System/Info/Public")
        data: dict[str, Any] = self._parse_response(resp, lambda d: d)
        name: str = data["ServerName"]
        self._server_name = name
        return name

    async def authenticate(self, username: str, password: str) -> AuthResult:
        """Authenticate a user against Jellyfin.

        Returns an AuthResult with the access token and user info.
        Caller is responsible for storing the returned token only in an
        encrypted server-side session — never persist to disk or expose
        to the frontend.

        Raises JellyfinAuthError on invalid credentials.
        Raises JellyfinConnectionError if Jellyfin is unreachable.
        """
        resp = await self._request(
            "POST",
            "/Users/AuthenticateByName",
            json={"Username": username, "Pw": password},
            auth_error_message="Invalid username or password",
        )
        return self._parse_response(resp, AuthResult.from_jellyfin)

    async def get_user(self, token: str) -> UserInfo:
        """Get the current user's info. Validates the token is still active.

        Calls /Users/Me which returns the user associated with the token.
        Raises JellyfinAuthError if the token is invalid/expired.
        Raises JellyfinConnectionError if Jellyfin is unreachable.
        """
        resp = await self._request("GET", "/Users/Me", token=token)
        return self._parse_response(resp, UserInfo.model_validate)

    async def get_items(
        self,
        token: str,
        user_id: str,
        *,
        item_types: list[str] | None = None,
        start_index: int = 0,
        limit: int = 50,
        recursive: bool = True,
    ) -> PaginatedItems:
        """Get library items for a user (paginated).

        Uses /Users/{userId}/Items so Jellyfin enforces per-user permissions.
        Raises JellyfinAuthError if the token is invalid/expired.
        Raises JellyfinConnectionError if Jellyfin is unreachable.
        """
        params: dict[str, str | int | bool] = {
            "StartIndex": start_index,
            "Limit": limit,
            "Recursive": recursive,
            "Fields": _ITEM_FIELDS,
        }
        if item_types:
            params["IncludeItemTypes"] = ",".join(item_types)

        resp = await self._request(
            "GET",
            f"/Users/{user_id}/Items",
            token=token,
            params=params,
        )
        return self._parse_response(resp, PaginatedItems.model_validate)

    async def get_all_items(
        self,
        token: str,
        user_id: str,
        *,
        item_types: list[str] | None = None,
        page_size: int = 200,
    ) -> AsyncIterator[PaginatedItems]:
        """Auto-paginate library items, yielding each page.

        Calls get_items() in a loop, yielding each PaginatedItems page.
        Stops when all items have been fetched (start_index >= total_count).
        Propagates JellyfinAuthError and JellyfinConnectionError without
        catching them — the caller handles partial failure.

        Token is passed through to get_items() on each call, never stored.
        """
        start_index = 0
        page_number = 0

        while True:
            page = await self.get_items(
                token,
                user_id,
                item_types=item_types,
                start_index=start_index,
                limit=page_size,
            )
            page_number += 1
            logger.debug(
                "library fetch page=%d items_on_page=%d",
                page_number,
                len(page.items),
            )
            yield page

            start_index += len(page.items)
            if start_index >= page.total_count:
                break
