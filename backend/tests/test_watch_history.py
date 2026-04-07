# backend/tests/test_watch_history.py
"""Unit tests for WatchHistoryEntry model and get_watched_items / get_favorite_items."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import httpx
import pytest

from app.jellyfin.client import JellyfinClient
from app.jellyfin.errors import (
    JellyfinAuthError,
    JellyfinConnectionError,
    JellyfinError,
)
from app.jellyfin.models import WatchHistoryEntry


@pytest.fixture
def mock_http() -> AsyncMock:
    """Mock httpx.AsyncClient for unit tests."""
    return AsyncMock(spec=httpx.AsyncClient)


@pytest.fixture
def jf_client(mock_http: AsyncMock) -> JellyfinClient:
    return JellyfinClient(
        base_url="http://jellyfin:8096",
        http_client=mock_http,
    )


_FAKE_REQUEST = httpx.Request("GET", "http://fake")


# ---------------------------------------------------------------------------
# WatchHistoryEntry model tests
# ---------------------------------------------------------------------------


class TestWatchHistoryEntry:
    def test_watch_history_entry_is_frozen(self) -> None:
        """WatchHistoryEntry is immutable (frozen=True)."""
        entry = WatchHistoryEntry(
            jellyfin_id="item-1",
            last_played_date=None,
            play_count=1,
            is_favorite=False,
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            entry.jellyfin_id = "item-2"  # type: ignore[misc]

    def test_watch_history_entry_fields_and_types(self) -> None:
        """All fields have correct types; last_played_date accepts datetime and None."""
        played_date = datetime(2025, 12, 15, 20, 30, 0, tzinfo=UTC)
        entry = WatchHistoryEntry(
            jellyfin_id="item-1",
            last_played_date=played_date,
            play_count=3,
            is_favorite=True,
        )
        assert entry.jellyfin_id == "item-1"
        assert isinstance(entry.jellyfin_id, str)
        assert entry.last_played_date == played_date
        assert isinstance(entry.last_played_date, datetime)
        assert entry.play_count == 3
        assert isinstance(entry.play_count, int)
        assert entry.is_favorite is True
        assert isinstance(entry.is_favorite, bool)

        # last_played_date=None is valid
        entry_none = WatchHistoryEntry(
            jellyfin_id="item-2",
            last_played_date=None,
            play_count=0,
            is_favorite=False,
        )
        assert entry_none.last_played_date is None


# ---------------------------------------------------------------------------
# get_watched_items tests
# ---------------------------------------------------------------------------


class TestGetWatchedItems:
    async def test_get_watched_items_sends_correct_request(
        self, jf_client: JellyfinClient, mock_http: AsyncMock
    ) -> None:
        """Correct URL, params, token header, no Fields param."""
        mock_http.request.return_value = httpx.Response(
            200,
            json={"Items": [], "TotalRecordCount": 0},
            request=_FAKE_REQUEST,
        )
        await jf_client.get_watched_items("tok-123", "uid-1")

        mock_http.request.assert_called_once()
        call_args = mock_http.request.call_args
        assert call_args.args[0] == "GET"
        assert "/Users/uid-1/Items" in call_args.args[1]
        params = call_args.kwargs["params"]
        assert params["IsPlayed"] is True
        assert params["IncludeItemTypes"] == "Movie"
        assert params["SortBy"] == "DatePlayed"
        assert params["SortOrder"] == "Descending"
        assert params["Recursive"] is True
        assert "Fields" not in params
        assert "Token=tok-123" in call_args.kwargs["headers"]["Authorization"]

    async def test_get_watched_items_parses_response(
        self, jf_client: JellyfinClient, mock_http: AsyncMock
    ) -> None:
        """Realistic UserData parsed into correct WatchHistoryEntry fields."""
        mock_http.request.return_value = httpx.Response(
            200,
            json={
                "Items": [
                    {
                        "Id": "item-1",
                        "Name": "Alien",
                        "Type": "Movie",
                        "UserData": {
                            "PlayCount": 3,
                            "IsFavorite": True,
                            "Played": True,
                            "LastPlayedDate": "2025-12-15T20:30:00.0000000Z",
                        },
                    },
                    {
                        "Id": "item-2",
                        "Name": "Aliens",
                        "Type": "Movie",
                        "UserData": {
                            "PlayCount": 1,
                            "IsFavorite": False,
                            "Played": True,
                            "LastPlayedDate": "2025-11-01T10:00:00.0000000Z",
                        },
                    },
                ],
                "TotalRecordCount": 2,
            },
            request=_FAKE_REQUEST,
        )
        entries = await jf_client.get_watched_items("tok-123", "uid-1")
        assert len(entries) == 2

        assert entries[0].jellyfin_id == "item-1"
        assert isinstance(entries[0].last_played_date, datetime)
        assert entries[0].play_count == 3
        assert entries[0].is_favorite is True

        assert entries[1].jellyfin_id == "item-2"
        assert isinstance(entries[1].last_played_date, datetime)
        assert entries[1].play_count == 1
        assert entries[1].is_favorite is False

    async def test_get_watched_items_paginates_two_pages(
        self, jf_client: JellyfinClient, mock_http: AsyncMock
    ) -> None:
        """Auto-pagination: 200 + 50 items across two pages."""
        page1_items = [
            {
                "Id": f"item-{i}",
                "Name": f"Movie {i}",
                "Type": "Movie",
                "UserData": {"PlayCount": 1, "IsFavorite": False, "Played": True},
            }
            for i in range(200)
        ]
        page2_items = [
            {
                "Id": f"item-{i}",
                "Name": f"Movie {i}",
                "Type": "Movie",
                "UserData": {"PlayCount": 1, "IsFavorite": False, "Played": True},
            }
            for i in range(200, 250)
        ]

        mock_http.request.side_effect = [
            httpx.Response(
                200,
                json={"Items": page1_items, "TotalRecordCount": 250},
                request=_FAKE_REQUEST,
            ),
            httpx.Response(
                200,
                json={"Items": page2_items, "TotalRecordCount": 250},
                request=_FAKE_REQUEST,
            ),
        ]

        entries = await jf_client.get_watched_items("tok-123", "uid-1")
        assert len(entries) == 250
        assert mock_http.request.call_count == 2

        # Verify second call has correct StartIndex
        second_call_params = mock_http.request.call_args_list[1].kwargs["params"]
        assert second_call_params["StartIndex"] == 200

    async def test_get_watched_items_empty_history(
        self, jf_client: JellyfinClient, mock_http: AsyncMock
    ) -> None:
        """Empty watch history returns []."""
        mock_http.request.return_value = httpx.Response(
            200,
            json={"Items": [], "TotalRecordCount": 0},
            request=_FAKE_REQUEST,
        )
        entries = await jf_client.get_watched_items("tok-123", "uid-1")
        assert entries == []

    async def test_get_watched_items_missing_user_data(
        self, jf_client: JellyfinClient, mock_http: AsyncMock
    ) -> None:
        """Item with no UserData key yields safe defaults."""
        mock_http.request.return_value = httpx.Response(
            200,
            json={
                "Items": [{"Id": "item-1", "Name": "NoData", "Type": "Movie"}],
                "TotalRecordCount": 1,
            },
            request=_FAKE_REQUEST,
        )
        entries = await jf_client.get_watched_items("tok-123", "uid-1")
        assert len(entries) == 1
        assert entries[0].last_played_date is None
        assert entries[0].play_count == 0
        assert entries[0].is_favorite is False

    async def test_get_watched_items_empty_user_data(
        self, jf_client: JellyfinClient, mock_http: AsyncMock
    ) -> None:
        """Item with UserData={} yields safe defaults."""
        mock_http.request.return_value = httpx.Response(
            200,
            json={
                "Items": [
                    {
                        "Id": "item-1",
                        "Name": "EmptyUD",
                        "Type": "Movie",
                        "UserData": {},
                    }
                ],
                "TotalRecordCount": 1,
            },
            request=_FAKE_REQUEST,
        )
        entries = await jf_client.get_watched_items("tok-123", "uid-1")
        assert len(entries) == 1
        assert entries[0].last_played_date is None
        assert entries[0].play_count == 0
        assert entries[0].is_favorite is False

    async def test_get_watched_items_null_last_played_date(
        self, jf_client: JellyfinClient, mock_http: AsyncMock
    ) -> None:
        """UserData present but LastPlayedDate is null -> None."""
        mock_http.request.return_value = httpx.Response(
            200,
            json={
                "Items": [
                    {
                        "Id": "item-1",
                        "Name": "NullDate",
                        "Type": "Movie",
                        "UserData": {
                            "PlayCount": 2,
                            "IsFavorite": True,
                            "LastPlayedDate": None,
                        },
                    }
                ],
                "TotalRecordCount": 1,
            },
            request=_FAKE_REQUEST,
        )
        entries = await jf_client.get_watched_items("tok-123", "uid-1")
        assert entries[0].last_played_date is None

    async def test_get_watched_items_auth_error(
        self, jf_client: JellyfinClient, mock_http: AsyncMock
    ) -> None:
        """401 response raises JellyfinAuthError."""
        mock_http.request.return_value = httpx.Response(401, request=_FAKE_REQUEST)
        with pytest.raises(JellyfinAuthError):
            await jf_client.get_watched_items("bad-tok", "uid-1")

    async def test_get_watched_items_connection_error(
        self, jf_client: JellyfinClient, mock_http: AsyncMock
    ) -> None:
        """Transport error raises JellyfinConnectionError."""
        mock_http.request.side_effect = httpx.ConnectError("Connection refused")
        with pytest.raises(JellyfinConnectionError):
            await jf_client.get_watched_items("tok-123", "uid-1")

    async def test_get_watched_items_unexpected_status(
        self, jf_client: JellyfinClient, mock_http: AsyncMock
    ) -> None:
        """500 response raises JellyfinError."""
        mock_http.request.return_value = httpx.Response(500, request=_FAKE_REQUEST)
        with pytest.raises(JellyfinError):
            await jf_client.get_watched_items("tok-123", "uid-1")


# ---------------------------------------------------------------------------
# get_favorite_items tests
# ---------------------------------------------------------------------------


class TestGetFavoriteItems:
    async def test_get_favorite_items_sends_correct_request(
        self, jf_client: JellyfinClient, mock_http: AsyncMock
    ) -> None:
        """Correct URL, params, no SortBy/SortOrder/Fields."""
        mock_http.request.return_value = httpx.Response(
            200,
            json={"Items": [], "TotalRecordCount": 0},
            request=_FAKE_REQUEST,
        )
        await jf_client.get_favorite_items("tok-123", "uid-1")

        mock_http.request.assert_called_once()
        call_args = mock_http.request.call_args
        assert call_args.args[0] == "GET"
        assert "/Users/uid-1/Items" in call_args.args[1]
        params = call_args.kwargs["params"]
        assert params["IsFavorite"] is True
        assert params["IncludeItemTypes"] == "Movie"
        assert params["Recursive"] is True
        assert "SortBy" not in params
        assert "SortOrder" not in params
        assert "Fields" not in params
        assert "Token=tok-123" in call_args.kwargs["headers"]["Authorization"]

    async def test_get_favorite_items_parses_response(
        self, jf_client: JellyfinClient, mock_http: AsyncMock
    ) -> None:
        """Parses favorites into WatchHistoryEntry with correct fields."""
        mock_http.request.return_value = httpx.Response(
            200,
            json={
                "Items": [
                    {
                        "Id": "item-1",
                        "Name": "Alien",
                        "Type": "Movie",
                        "UserData": {
                            "PlayCount": 5,
                            "IsFavorite": True,
                            "Played": True,
                            "LastPlayedDate": "2025-12-15T20:30:00.0000000Z",
                        },
                    },
                    {
                        "Id": "item-2",
                        "Name": "Aliens",
                        "Type": "Movie",
                        "UserData": {
                            "PlayCount": 2,
                            "IsFavorite": True,
                            "Played": True,
                            "LastPlayedDate": "2025-10-01T08:00:00.0000000Z",
                        },
                    },
                ],
                "TotalRecordCount": 2,
            },
            request=_FAKE_REQUEST,
        )
        entries = await jf_client.get_favorite_items("tok-123", "uid-1")
        assert len(entries) == 2
        assert entries[0].jellyfin_id == "item-1"
        assert entries[0].is_favorite is True
        assert entries[1].jellyfin_id == "item-2"

    async def test_get_favorite_items_paginates_two_pages(
        self, jf_client: JellyfinClient, mock_http: AsyncMock
    ) -> None:
        """Auto-pagination across two pages."""
        page1_items = [
            {
                "Id": f"item-{i}",
                "Name": f"Movie {i}",
                "Type": "Movie",
                "UserData": {"IsFavorite": True},
            }
            for i in range(200)
        ]
        page2_items = [
            {
                "Id": f"item-{i}",
                "Name": f"Movie {i}",
                "Type": "Movie",
                "UserData": {"IsFavorite": True},
            }
            for i in range(200, 250)
        ]

        mock_http.request.side_effect = [
            httpx.Response(
                200,
                json={"Items": page1_items, "TotalRecordCount": 250},
                request=_FAKE_REQUEST,
            ),
            httpx.Response(
                200,
                json={"Items": page2_items, "TotalRecordCount": 250},
                request=_FAKE_REQUEST,
            ),
        ]

        entries = await jf_client.get_favorite_items("tok-123", "uid-1")
        assert len(entries) == 250
        assert mock_http.request.call_count == 2

    async def test_get_favorite_items_empty_favorites(
        self, jf_client: JellyfinClient, mock_http: AsyncMock
    ) -> None:
        """No favorites returns []."""
        mock_http.request.return_value = httpx.Response(
            200,
            json={"Items": [], "TotalRecordCount": 0},
            request=_FAKE_REQUEST,
        )
        entries = await jf_client.get_favorite_items("tok-123", "uid-1")
        assert entries == []

    async def test_get_favorite_items_unplayed_favorite(
        self, jf_client: JellyfinClient, mock_http: AsyncMock
    ) -> None:
        """Favorite that was never played: last_played_date=None, play_count=0."""
        mock_http.request.return_value = httpx.Response(
            200,
            json={
                "Items": [
                    {
                        "Id": "item-1",
                        "Name": "Unplayed Fave",
                        "Type": "Movie",
                        "UserData": {
                            "IsFavorite": True,
                            "Played": False,
                            "PlayCount": 0,
                        },
                    }
                ],
                "TotalRecordCount": 1,
            },
            request=_FAKE_REQUEST,
        )
        entries = await jf_client.get_favorite_items("tok-123", "uid-1")
        assert len(entries) == 1
        assert entries[0].is_favorite is True
        assert entries[0].last_played_date is None
        assert entries[0].play_count == 0

    async def test_get_favorite_items_auth_error(
        self, jf_client: JellyfinClient, mock_http: AsyncMock
    ) -> None:
        """401 response raises JellyfinAuthError."""
        mock_http.request.return_value = httpx.Response(401, request=_FAKE_REQUEST)
        with pytest.raises(JellyfinAuthError):
            await jf_client.get_favorite_items("bad-tok", "uid-1")

    async def test_get_favorite_items_connection_error(
        self, jf_client: JellyfinClient, mock_http: AsyncMock
    ) -> None:
        """Transport error raises JellyfinConnectionError."""
        mock_http.request.side_effect = httpx.ConnectError("Connection refused")
        with pytest.raises(JellyfinConnectionError):
            await jf_client.get_favorite_items("tok-123", "uid-1")

    async def test_get_favorite_items_unexpected_status(
        self, jf_client: JellyfinClient, mock_http: AsyncMock
    ) -> None:
        """500 response raises JellyfinError."""
        mock_http.request.return_value = httpx.Response(500, request=_FAKE_REQUEST)
        with pytest.raises(JellyfinError):
            await jf_client.get_favorite_items("tok-123", "uid-1")
