"""Permission service — caches Jellyfin user permissions and filters candidates."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.jellyfin.errors import (
    JellyfinAuthError,
    JellyfinConnectionError,
    JellyfinError,
)
from app.permissions.errors import (
    PermissionAuthError,
    PermissionCheckError,
    PermissionTimeoutError,
)

if TYPE_CHECKING:
    from app.jellyfin.client import JellyfinClient

logger = logging.getLogger(__name__)

# Maximum number of user permission sets to keep in memory.
# When exceeded, the oldest entries (by expiry time) are evicted.
_MAX_CACHE_ENTRIES = 500


@dataclass(frozen=True, slots=True)
class _CacheEntry:
    permitted_ids: frozenset[str]
    expires_at: float


class PermissionService:
    """In-memory TTL cache for Jellyfin user permissions.

    Fetches the full set of item IDs a user can access, caches them
    for ``cache_ttl_seconds``, and provides order-preserving filtering
    of candidate item IDs. Cache is bounded to ``_MAX_CACHE_ENTRIES``
    to prevent unbounded memory growth on multi-user instances.
    """

    def __init__(
        self, jellyfin_client: JellyfinClient, cache_ttl_seconds: int = 300
    ) -> None:
        self._jf_client = jellyfin_client
        self._cache_ttl = cache_ttl_seconds
        self._cache: dict[str, _CacheEntry] = {}

    async def _fetch_permitted_ids(self, user_id: str, token: str) -> frozenset[str]:
        """Fetch all item IDs the user can access from Jellyfin.

        Only fetches Movie items. Requests ``fields=""`` so Jellyfin omits
        Overview/Genres/Tags/Studios/People — payload we never read here and
        which dominates parse latency on large libraries.

        Returns a frozenset for immutable cache storage.
        """
        ids: set[str] = set()
        async for page in self._jf_client.get_all_items(
            token=token, user_id=user_id, item_types=["Movie"], fields=""
        ):
            for item in page.items:
                ids.add(item.id)
        logger.debug("permission_fetch user_id=%s items=%d", user_id, len(ids))
        return frozenset(ids)

    async def filter_permitted(
        self, user_id: str, token: str, candidate_ids: list[str]
    ) -> list[str]:
        """Filter candidates to only those the user can access. Order-preserving."""
        entry = self._cache.get(user_id)
        if entry is not None and time.monotonic() < entry.expires_at:
            logger.debug("permission_cache_hit user_id=%s", user_id)
            permitted = entry.permitted_ids
        else:
            logger.debug("permission_cache_miss user_id=%s", user_id)
            try:
                permitted = await self._fetch_permitted_ids(user_id, token)
            except JellyfinAuthError as exc:
                self._cache.pop(user_id, None)
                raise PermissionAuthError(str(exc)) from exc
            except JellyfinConnectionError as exc:
                logger.warning(
                    "permission_fetch_failed user_id=%s error_type=%s",
                    user_id,
                    type(exc).__name__,
                )
                raise PermissionTimeoutError(str(exc)) from exc
            except JellyfinError as exc:
                logger.warning(
                    "permission_fetch_failed user_id=%s error_type=%s",
                    user_id,
                    type(exc).__name__,
                )
                raise PermissionCheckError(str(exc)) from exc
            self._cache[user_id] = _CacheEntry(
                permitted_ids=permitted,
                expires_at=time.monotonic() + self._cache_ttl,
            )
            self._evict_if_full()

        return [cid for cid in candidate_ids if cid in permitted]

    def _evict_if_full(self) -> None:
        """Evict the oldest cache entries if cache exceeds max size."""
        if len(self._cache) <= _MAX_CACHE_ENTRIES:
            return
        # Sort by expiry (soonest-expiring first) and remove excess
        entries = sorted(self._cache.items(), key=lambda kv: kv[1].expires_at)
        to_remove = len(self._cache) - _MAX_CACHE_ENTRIES
        for uid, _ in entries[:to_remove]:
            del self._cache[uid]
        logger.debug("permission_cache_evicted count=%d", to_remove)

    def invalidate_user_cache(self, user_id: str) -> None:
        """Remove cached permissions for a user. Safe no-op if not cached."""
        self._cache.pop(user_id, None)
        logger.debug("permission_cache_invalidated user_id=%s", user_id)
