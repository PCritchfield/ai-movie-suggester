"""Tests for PermissionService — cache, fetch, filter, exception wrapping."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.jellyfin.errors import (
    JellyfinAuthError,
    JellyfinConnectionError,
    JellyfinError,
)
from app.jellyfin.models import LibraryItem, PaginatedItems
from app.permissions.errors import (
    PermissionAuthError,
    PermissionCheckError,
    PermissionTimeoutError,
)
from app.permissions.service import PermissionService


def _make_item(item_id: str) -> LibraryItem:
    """Create a minimal LibraryItem for testing."""
    return LibraryItem.model_validate(
        {"Id": item_id, "Name": f"Movie {item_id}", "Type": "Movie"}
    )


def _make_page(item_ids: list[str]) -> PaginatedItems:
    """Create a PaginatedItems page from a list of IDs."""
    return PaginatedItems.model_validate(
        {
            "Items": [
                {"Id": iid, "Name": f"Movie {iid}", "Type": "Movie"} for iid in item_ids
            ],
            "TotalRecordCount": len(item_ids),
            "StartIndex": 0,
        }
    )


async def _mock_get_all_items_factory(
    item_ids: list[str],
):
    """Return an async generator function that yields a single page."""

    async def _gen(*args, **kwargs):
        yield _make_page(item_ids)

    return _gen


@pytest.fixture
def mock_jf_client() -> AsyncMock:
    """Mock JellyfinClient with get_all_items returning known items."""
    client = AsyncMock()
    known_ids = ["a", "b", "c", "d"]

    async def _get_all_items(*args, **kwargs):
        yield _make_page(known_ids)

    client.get_all_items = _get_all_items
    return client


@pytest.fixture
def service(mock_jf_client: AsyncMock) -> PermissionService:
    """PermissionService with a mock Jellyfin client and 300s TTL."""
    return PermissionService(jellyfin_client=mock_jf_client, cache_ttl_seconds=300)


class TestCacheHitMiss:
    """Verify caching behaviour — first call fetches, second uses cache."""

    async def test_first_call_fetches(self, service: PermissionService) -> None:
        result = await service.filter_permitted("user1", "tok", ["a", "b"])
        assert result == ["a", "b"]

    async def test_second_call_uses_cache(self) -> None:
        """Second call should not re-fetch from Jellyfin."""
        call_count = 0
        known_ids = ["a", "b", "c"]

        async def _counting_get_all_items(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            yield _make_page(known_ids)

        client = AsyncMock()
        client.get_all_items = _counting_get_all_items
        svc = PermissionService(jellyfin_client=client, cache_ttl_seconds=300)

        await svc.filter_permitted("user1", "tok", ["a"])
        assert call_count == 1

        await svc.filter_permitted("user1", "tok", ["b"])
        assert call_count == 1  # Still 1 — cache hit

    async def test_different_users_fetch_separately(self) -> None:
        """Each user gets their own cache entry."""
        call_count = 0

        async def _counting_get_all_items(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            yield _make_page(["a", "b"])

        client = AsyncMock()
        client.get_all_items = _counting_get_all_items
        svc = PermissionService(jellyfin_client=client, cache_ttl_seconds=300)

        await svc.filter_permitted("user1", "tok1", ["a"])
        await svc.filter_permitted("user2", "tok2", ["a"])
        assert call_count == 2


class TestCacheExpiry:
    """Verify TTL expiration triggers re-fetch."""

    async def test_expired_cache_re_fetches(self) -> None:
        call_count = 0

        async def _counting_get_all_items(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            yield _make_page(["a", "b"])

        client = AsyncMock()
        client.get_all_items = _counting_get_all_items
        svc = PermissionService(jellyfin_client=client, cache_ttl_seconds=300)

        # First fetch
        with patch("app.permissions.service.time") as mock_time:
            mock_time.monotonic.return_value = 1000.0
            await svc.filter_permitted("user1", "tok", ["a"])
        assert call_count == 1

        # Cache is still valid at 1200 (< 1000 + 300)
        with patch("app.permissions.service.time") as mock_time:
            mock_time.monotonic.return_value = 1200.0
            await svc.filter_permitted("user1", "tok", ["a"])
        assert call_count == 1

        # Cache expired at 1301 (> 1000 + 300)
        with patch("app.permissions.service.time") as mock_time:
            mock_time.monotonic.return_value = 1301.0
            await svc.filter_permitted("user1", "tok", ["a"])
        assert call_count == 2


class TestOrderPreservation:
    """filter_permitted must preserve input order of candidate_ids."""

    async def test_order_preserved(self, service: PermissionService) -> None:
        result = await service.filter_permitted("user1", "tok", ["c", "a", "b"])
        assert result == ["c", "a", "b"]

    async def test_order_preserved_with_filtering(
        self, service: PermissionService
    ) -> None:
        # "x" not in permitted set; order of remaining should be preserved
        result = await service.filter_permitted("user1", "tok", ["c", "x", "a", "b"])
        assert result == ["c", "a", "b"]


class TestFiltering:
    """Various filter scenarios including edge cases."""

    async def test_all_permitted(self, service: PermissionService) -> None:
        result = await service.filter_permitted("user1", "tok", ["a", "b", "c", "d"])
        assert result == ["a", "b", "c", "d"]

    async def test_none_permitted(self, service: PermissionService) -> None:
        result = await service.filter_permitted("user1", "tok", ["x", "y", "z"])
        assert result == []

    async def test_empty_candidates(self, service: PermissionService) -> None:
        result = await service.filter_permitted("user1", "tok", [])
        assert result == []

    async def test_partial_filter(self, service: PermissionService) -> None:
        result = await service.filter_permitted("user1", "tok", ["a", "x", "c"])
        assert result == ["a", "c"]

    async def test_duplicates_in_candidates(self, service: PermissionService) -> None:
        result = await service.filter_permitted("user1", "tok", ["a", "a", "b"])
        assert result == ["a", "a", "b"]


class TestExceptionWrapping:
    """Each Jellyfin error maps to the correct permission error with __cause__."""

    async def test_auth_error_wrapping(self) -> None:
        cause = JellyfinAuthError("invalid token")

        async def _failing(*args, **kwargs):
            raise cause
            yield  # noqa: RET503 — make it an async generator

        client = AsyncMock()
        client.get_all_items = _failing
        svc = PermissionService(jellyfin_client=client)

        with pytest.raises(PermissionAuthError) as exc_info:
            await svc.filter_permitted("user1", "tok", ["a"])
        assert exc_info.value.__cause__ is cause

    async def test_connection_error_wrapping(self) -> None:
        cause = JellyfinConnectionError("timeout")

        async def _failing(*args, **kwargs):
            raise cause
            yield  # noqa: RET503

        client = AsyncMock()
        client.get_all_items = _failing
        svc = PermissionService(jellyfin_client=client)

        with pytest.raises(PermissionTimeoutError) as exc_info:
            await svc.filter_permitted("user1", "tok", ["a"])
        assert exc_info.value.__cause__ is cause

    async def test_generic_jellyfin_error_wrapping(self) -> None:
        cause = JellyfinError("unexpected")

        async def _failing(*args, **kwargs):
            raise cause
            yield  # noqa: RET503

        client = AsyncMock()
        client.get_all_items = _failing
        svc = PermissionService(jellyfin_client=client)

        with pytest.raises(PermissionCheckError) as exc_info:
            await svc.filter_permitted("user1", "tok", ["a"])
        assert exc_info.value.__cause__ is cause


class TestAuthErrorCacheClearing:
    """Auth errors should clear any stale cache for the user."""

    async def test_auth_error_clears_cache(self) -> None:
        call_count = 0

        async def _get_all_items(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                yield _make_page(["a", "b"])
            else:
                raise JellyfinAuthError("expired")
                yield  # noqa: RET503

        client = AsyncMock()
        client.get_all_items = _get_all_items
        svc = PermissionService(jellyfin_client=client, cache_ttl_seconds=300)

        # First call succeeds and caches
        with patch("app.permissions.service.time") as mock_time:
            mock_time.monotonic.return_value = 1000.0
            result = await svc.filter_permitted("user1", "tok", ["a"])
        assert result == ["a"]

        # Force cache expiry and trigger auth error
        with (
            patch("app.permissions.service.time") as mock_time,
            pytest.raises(PermissionAuthError),
        ):
            mock_time.monotonic.return_value = 2000.0
            await svc.filter_permitted("user1", "tok", ["a"])

        # Cache should be cleared — verify by checking internal state
        assert "user1" not in svc._cache


class TestInvalidateUserCache:
    """Explicit cache invalidation."""

    async def test_invalidation_triggers_fresh_fetch(self) -> None:
        call_count = 0

        async def _counting_get_all_items(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            yield _make_page(["a", "b"])

        client = AsyncMock()
        client.get_all_items = _counting_get_all_items
        svc = PermissionService(jellyfin_client=client, cache_ttl_seconds=300)

        await svc.filter_permitted("user1", "tok", ["a"])
        assert call_count == 1

        svc.invalidate_user_cache("user1")

        await svc.filter_permitted("user1", "tok", ["a"])
        assert call_count == 2  # Re-fetched after invalidation

    def test_invalidate_unknown_user_is_noop(self, service: PermissionService) -> None:
        """Invalidating a non-existent user shouldn't raise."""
        service.invalidate_user_cache("nonexistent")  # Should not raise
