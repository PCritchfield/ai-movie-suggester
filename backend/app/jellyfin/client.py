"""Async HTTP client for the Jellyfin API.

Uses an injected httpx.AsyncClient for connection pooling and testability.
MediaBrowser authorization headers follow Jellyfin's own integration test
format (Authorization header, not X-Emby-Authorization; no quotes on Token).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any, TypeVar

import httpx

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

from app.jellyfin.errors import (
    JellyfinAuthError,
    JellyfinConnectionError,
    JellyfinError,
)
from app.jellyfin.models import AuthResult, PaginatedItems, UserInfo, WatchHistoryEntry

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
        if page_size <= 0:
            msg = f"page_size must be positive, got {page_size}"
            raise ValueError(msg)

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

            if not page.items:
                logger.warning(
                    "empty page from Jellyfin; stopping pagination "
                    "(page=%d, start_index=%d, total_count=%d)",
                    page_number,
                    start_index,
                    page.total_count,
                )
                break

            start_index += len(page.items)
            if start_index >= page.total_count:
                break

    @staticmethod
    def _parse_watch_entry(item: dict[str, Any]) -> WatchHistoryEntry:
        """Parse a single Jellyfin item dict into a WatchHistoryEntry.

        Handles missing/null UserData gracefully with safe defaults.
        """
        user_data = item.get("UserData") or {}
        last_played_raw = user_data.get("LastPlayedDate")
        last_played_date: datetime | None = None
        if last_played_raw:
            last_played_date = datetime.fromisoformat(last_played_raw)
        return WatchHistoryEntry(
            jellyfin_id=item["Id"],
            last_played_date=last_played_date,
            play_count=user_data.get("PlayCount", 0),
            is_favorite=user_data.get("IsFavorite", False),
        )

    async def _paginate_watch_entries(
        self,
        token: str,
        user_id: str,
        params: dict[str, str | int | bool],
        log_prefix: str,
    ) -> list[WatchHistoryEntry]:
        """Auto-paginate a watch-history style query, returning all entries.

        Shared pagination logic for get_watched_items and get_favorite_items.
        The caller supplies the filter-specific *params*; this method adds
        StartIndex/Limit and drives the pagination loop.

        Token is passed through to _request, never stored.
        """
        page_size = 200
        start_index = 0
        page_number = 0
        all_entries: list[WatchHistoryEntry] = []

        def _extract(data: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
            return data["Items"], data["TotalRecordCount"]

        while True:
            page_params = {**params, "StartIndex": start_index, "Limit": page_size}
            resp = await self._request(
                "GET",
                f"/Users/{user_id}/Items",
                token=token,
                params=page_params,
            )

            items, total_count = self._parse_response(resp, _extract)
            page_number += 1
            logger.debug("%s page=%d items=%d", log_prefix, page_number, len(items))

            for item in items:
                try:
                    all_entries.append(self._parse_watch_entry(item))
                except (KeyError, TypeError, ValueError) as exc:
                    raise JellyfinError(
                        "Unexpected Jellyfin response while parsing watch entry"
                    ) from exc

            if not items:
                break

            start_index += len(items)
            if start_index >= total_count:
                break

        return all_entries

    async def get_watched_items(
        self,
        token: str,
        user_id: str,
    ) -> list[WatchHistoryEntry]:
        """Fetch all played items for a user, auto-paginating.

        Uses the user's own token for per-user permission enforcement.
        Token is passed through to _request, never stored.
        """
        params: dict[str, str | int | bool] = {
            "IsPlayed": True,
            "IncludeItemTypes": "Movie",
            "SortBy": "DatePlayed",
            "SortOrder": "Descending",
            "Recursive": True,
        }
        return await self._paginate_watch_entries(
            token, user_id, params, "watched_items_fetch"
        )

    async def get_favorite_items(
        self,
        token: str,
        user_id: str,
    ) -> list[WatchHistoryEntry]:
        """Fetch all favorited items for a user, auto-paginating.

        Uses the user's own token for per-user permission enforcement.
        Token is passed through to _request, never stored.
        """
        params: dict[str, str | int | bool] = {
            "IsFavorite": True,
            "IncludeItemTypes": "Movie",
            "Recursive": True,
        }
        return await self._paginate_watch_entries(
            token, user_id, params, "favorite_items_fetch"
        )
