"""Per-user TTL cache for Jellyfin watch history and favorites.

Mirrors the PermissionService pattern: in-memory dict keyed by user_id,
short TTL, invalidated on logout. Token is passed through to JellyfinClient
on each fetch — never stored in the cache.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.jellyfin.client import JellyfinClient
    from app.jellyfin.models import WatchHistoryEntry

logger = logging.getLogger(__name__)

_MAX_CACHE_ENTRIES = 500


@dataclass(frozen=True, slots=True)
class WatchData:
    """Cached watch history for a single user."""

    watched: tuple[WatchHistoryEntry, ...] = ()
    favorites: tuple[WatchHistoryEntry, ...] = ()


@dataclass(frozen=True, slots=True)
class _CacheEntry:
    data: WatchData
    expires_at: float


class WatchHistoryService:
    """In-memory TTL cache for Jellyfin watch history.

    Fetches watched items and favorites for a user, caches them
    for ``cache_ttl_seconds``, and provides invalidation on logout.
    Cache is bounded to ``_MAX_CACHE_ENTRIES`` to prevent unbounded
    memory growth on multi-user instances.
    """

    def __init__(
        self,
        jellyfin_client: JellyfinClient,
        cache_ttl_seconds: int = 300,
    ) -> None:
        self._jf_client = jellyfin_client
        self._cache_ttl = cache_ttl_seconds
        self._cache: dict[str, _CacheEntry] = {}

    async def get(self, token: str, user_id: str) -> WatchData:
        """Return cached watch data or fetch from Jellyfin.

        Token is passed through to JellyfinClient — never stored.
        Raises JellyfinAuthError or JellyfinConnectionError on fetch failure.
        """
        entry = self._cache.get(user_id)
        if entry is not None and time.monotonic() < entry.expires_at:
            logger.debug("watch_history_cache_hit user_id=%s", user_id)
            return entry.data

        logger.debug("watch_history_cache_miss user_id=%s", user_id)
        watched, favorites = await asyncio.gather(
            self._jf_client.get_watched_items(token, user_id),
            self._jf_client.get_favorite_items(token, user_id),
        )

        data = WatchData(watched=tuple(watched), favorites=tuple(favorites))
        self._cache[user_id] = _CacheEntry(
            data=data,
            expires_at=time.monotonic() + self._cache_ttl,
        )
        self._evict_if_full()
        return data

    def invalidate(self, user_id: str) -> None:
        """Remove cached watch data for a user. Safe no-op if not cached."""
        self._cache.pop(user_id, None)
        logger.debug("watch_history_cache_invalidated user_id=%s", user_id)

    def _evict_if_full(self) -> None:
        """Evict the oldest cache entries if cache exceeds max size."""
        if len(self._cache) <= _MAX_CACHE_ENTRIES:
            return
        entries = sorted(self._cache.items(), key=lambda kv: kv[1].expires_at)
        to_remove = len(self._cache) - _MAX_CACHE_ENTRIES
        for uid, _ in entries[:to_remove]:
            del self._cache[uid]
        logger.debug("watch_history_cache_evicted count=%d", to_remove)
