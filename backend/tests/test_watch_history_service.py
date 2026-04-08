"""Unit tests for WatchHistoryService (Spec 20, Task 1.0)."""

from __future__ import annotations

import time
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.jellyfin.errors import JellyfinAuthError, JellyfinConnectionError
from app.jellyfin.models import WatchHistoryEntry
from app.watch_history.service import _MAX_CACHE_ENTRIES, WatchData, WatchHistoryService

# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _make_entry(
    jellyfin_id: str = "abc123",
    last_played_date: datetime | None = None,
    play_count: int = 1,
    is_favorite: bool = False,
) -> WatchHistoryEntry:
    return WatchHistoryEntry(
        jellyfin_id=jellyfin_id,
        last_played_date=last_played_date or datetime(2026, 1, 15, 20, 0),
        play_count=play_count,
        is_favorite=is_favorite,
    )


def _make_service(
    jf_client: AsyncMock | None = None,
    cache_ttl_seconds: int = 300,
) -> tuple[WatchHistoryService, AsyncMock]:
    client = jf_client or AsyncMock()
    if jf_client is None:
        client.get_watched_items.return_value = [
            _make_entry("watched-1"),
            _make_entry("watched-2"),
        ]
        client.get_favorite_items.return_value = [
            _make_entry("fav-1", is_favorite=True),
        ]
    service = WatchHistoryService(
        jellyfin_client=client,
        cache_ttl_seconds=cache_ttl_seconds,
    )
    return service, client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCacheMiss:
    @pytest.mark.asyncio
    async def test_get_fetches_on_cache_miss(self) -> None:
        """First call invokes both get_watched_items and get_favorite_items."""
        service, client = _make_service()

        result = await service.get("tok-1", "user-1")

        client.get_watched_items.assert_awaited_once_with("tok-1", "user-1")
        client.get_favorite_items.assert_awaited_once_with("tok-1", "user-1")
        assert isinstance(result, WatchData)
        assert len(result.watched) == 2
        assert len(result.favorites) == 1


class TestCacheHit:
    @pytest.mark.asyncio
    async def test_get_returns_cached_within_ttl(self) -> None:
        """Second call within TTL does NOT invoke Jellyfin client."""
        service, client = _make_service()

        first = await service.get("tok-1", "user-1")
        second = await service.get("tok-1", "user-1")

        assert first is second
        assert client.get_watched_items.await_count == 1
        assert client.get_favorite_items.await_count == 1

    @pytest.mark.asyncio
    async def test_cache_keyed_by_user_id(self) -> None:
        """Same user_id with different tokens gets cache hit."""
        service, client = _make_service()

        await service.get("tok-1", "user-1")
        result = await service.get("tok-different", "user-1")

        assert isinstance(result, WatchData)
        assert client.get_watched_items.await_count == 1


class TestCacheExpiry:
    @pytest.mark.asyncio
    async def test_get_refetches_after_ttl_expiry(self) -> None:
        """After TTL expires, next call re-fetches from Jellyfin."""
        service, client = _make_service(cache_ttl_seconds=1)

        await service.get("tok-1", "user-1")
        assert client.get_watched_items.await_count == 1

        # Patch monotonic to simulate time passing beyond TTL
        with patch("app.watch_history.service.time") as mock_time:
            mock_time.monotonic.return_value = time.monotonic() + 2
            await service.get("tok-1", "user-1")

        assert client.get_watched_items.await_count == 2
        assert client.get_favorite_items.await_count == 2


class TestInvalidation:
    @pytest.mark.asyncio
    async def test_invalidate_clears_cache(self) -> None:
        """After invalidate(), next get() fetches fresh."""
        service, client = _make_service()

        await service.get("tok-1", "user-1")
        assert client.get_watched_items.await_count == 1

        service.invalidate("user-1")

        await service.get("tok-1", "user-1")
        assert client.get_watched_items.await_count == 2

    def test_invalidate_nonexistent_user_is_noop(self) -> None:
        """Invalidating a user not in cache does not raise."""
        service, _ = _make_service()
        service.invalidate("no-such-user")  # should not raise


class TestErrorPropagation:
    @pytest.mark.asyncio
    async def test_jellyfin_auth_error_propagates(self) -> None:
        """JellyfinAuthError from get_watched_items propagates, not cached."""
        client = AsyncMock()
        client.get_watched_items.side_effect = JellyfinAuthError("expired")
        service = WatchHistoryService(jellyfin_client=client)

        with pytest.raises(JellyfinAuthError):
            await service.get("tok-1", "user-1")

        # Should not be cached — next call should also try to fetch
        client.get_watched_items.side_effect = None
        client.get_watched_items.return_value = []
        client.get_favorite_items.return_value = []
        result = await service.get("tok-1", "user-1")
        assert isinstance(result, WatchData)

    @pytest.mark.asyncio
    async def test_jellyfin_connection_error_propagates(self) -> None:
        """JellyfinConnectionError propagates, not cached."""
        client = AsyncMock()
        client.get_watched_items.side_effect = JellyfinConnectionError("down")
        service = WatchHistoryService(jellyfin_client=client)

        with pytest.raises(JellyfinConnectionError):
            await service.get("tok-1", "user-1")

    @pytest.mark.asyncio
    async def test_partial_fetch_failure_not_cached(self) -> None:
        """Partial fetch failure: favorites fails, nothing cached."""
        client = AsyncMock()
        client.get_watched_items.return_value = [_make_entry("w1")]
        client.get_favorite_items.side_effect = JellyfinConnectionError("down")
        service = WatchHistoryService(jellyfin_client=client)

        with pytest.raises(JellyfinConnectionError):
            await service.get("tok-1", "user-1")

        # Nothing should be cached — next call must re-fetch both
        client.get_watched_items.reset_mock()
        client.get_favorite_items.reset_mock()
        client.get_favorite_items.side_effect = None
        client.get_favorite_items.return_value = []
        await service.get("tok-1", "user-1")
        client.get_watched_items.assert_awaited_once()
        client.get_favorite_items.assert_awaited_once()


class TestCrossUserIsolation:
    @pytest.mark.asyncio
    async def test_different_users_get_independent_cache_entries(self) -> None:
        """user-1 and user-2 have separate cache entries — no cross-user leakage."""
        client = AsyncMock()
        user1_watched = [_make_entry("u1-movie")]
        user2_watched = [_make_entry("u2-movie")]

        async def _watched(token: str, user_id: str) -> list:
            return user1_watched if user_id == "user-1" else user2_watched

        client.get_watched_items.side_effect = _watched
        client.get_favorite_items.return_value = []

        service = WatchHistoryService(jellyfin_client=client)
        data1 = await service.get("tok-1", "user-1")
        data2 = await service.get("tok-2", "user-2")

        assert client.get_watched_items.await_count == 2
        assert data1.watched[0].jellyfin_id == "u1-movie"
        assert data2.watched[0].jellyfin_id == "u2-movie"
        assert data1 is not data2


class TestEviction:
    @pytest.mark.asyncio
    async def test_eviction_when_full(self) -> None:
        """Cache evicts oldest entry when exceeding _MAX_CACHE_ENTRIES."""
        service, client = _make_service()

        # Fill cache to max
        for i in range(_MAX_CACHE_ENTRIES):
            client.get_watched_items.return_value = []
            client.get_favorite_items.return_value = []
            await service.get("tok", f"user-{i}")

        assert len(service._cache) == _MAX_CACHE_ENTRIES

        # One more should trigger eviction
        await service.get("tok", "user-overflow")
        assert len(service._cache) == _MAX_CACHE_ENTRIES
