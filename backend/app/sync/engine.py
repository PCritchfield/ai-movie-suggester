"""Incremental sync engine.

Fetches Jellyfin library, diffs against store, enqueues changes.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import os
import time
from typing import TYPE_CHECKING

from app.jellyfin.errors import JellyfinConnectionError, JellyfinError
from app.library.hashing import compute_content_hash
from app.library.models import LibraryItemRow
from app.sync.models import (
    SYNC_STATUS_COMPLETED,
    SYNC_STATUS_FAILED,
    SyncAlreadyRunningError,
    SyncConfigError,
    SyncResult,
    SyncRunRow,
    SyncState,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from app.config import Settings
    from app.jellyfin.client import JellyfinClient
    from app.jellyfin.models import LibraryItem
    from app.library.store import LibraryStore
    from app.vectors.repository import SqliteVecRepository

    SyncCompleteCallback = Callable[[], Awaitable[None]]

_logger = logging.getLogger(__name__)


_CREW_ROLE_MAP = {
    "Actor": "people",
    "Director": "directors",
    "Writer": "writers",
    "Composer": "composers",
}


def to_library_row(item: LibraryItem) -> LibraryItemRow:
    """Convert a Jellyfin LibraryItem to a LibraryItemRow for storage.

    Buckets `item.people` by ``Type`` into ``people`` (actors), ``directors``,
    ``writers``, and ``composers``. Other crew roles are discarded. The
    returned row's ``content_hash`` is computed internally via
    ``compute_content_hash`` so callers never have to keep hash derivation
    and row construction in sync.
    """
    buckets: dict[str, list[str]] = {
        "people": [],
        "directors": [],
        "writers": [],
        "composers": [],
    }
    for person in item.people:
        name = person.get("Name")
        if not name:
            continue
        bucket = _CREW_ROLE_MAP.get(person.get("Type", ""))
        if bucket is not None:
            buckets[bucket].append(name)

    row = LibraryItemRow(
        jellyfin_id=item.id,
        title=item.name,
        overview=item.overview,
        production_year=item.production_year,
        genres=item.genres,
        tags=item.tags,
        studios=item.studios,
        community_rating=item.community_rating,
        people=buckets["people"],
        content_hash="",
        synced_at=int(time.time()),
        runtime_minutes=item.runtime_minutes,
        directors=buckets["directors"],
        writers=buckets["writers"],
        composers=buckets["composers"],
        official_rating=item.official_rating,
    )
    return dataclasses.replace(row, content_hash=compute_content_hash(row))


class SyncEngine:
    """Incremental sync engine that diffs Jellyfin library against the store.

    Pages through Jellyfin items, computes content hashes from composite text,
    classifies items as new/changed/unchanged, upserts changed items,
    enqueues them for embedding, and handles deletion detection with a
    50% safety threshold.
    """

    def __init__(
        self,
        library_store: LibraryStore,
        jellyfin_client: JellyfinClient,
        settings: Settings,
        vector_repository: SqliteVecRepository | None = None,
        embedding_event: asyncio.Event | None = None,
        on_sync_complete: list[SyncCompleteCallback] | None = None,
    ) -> None:
        self._library_store = library_store
        self._jellyfin_client = jellyfin_client
        self._settings = settings
        self._vector_repo = vector_repository
        self._embedding_event = embedding_event
        self._on_sync_complete: list[SyncCompleteCallback] = list(
            on_sync_complete or []
        )
        self._lock = asyncio.Lock()
        self._current_state: SyncState | None = None

    @property
    def current_state(self) -> SyncState | None:
        """Return the current sync state, or None if no sync is in progress."""
        return self._current_state

    @property
    def is_running(self) -> bool:
        """Return True if a sync is currently in progress."""
        return self._lock.locked()

    def validate_config(self) -> None:
        """Ensure required sync configuration is present.

        Raises SyncConfigError if JELLYFIN_API_KEY or
        JELLYFIN_ADMIN_USER_ID is not configured.
        """
        if self._settings.jellyfin_api_key is None:
            raise SyncConfigError("Sync engine not configured")
        if self._settings.jellyfin_admin_user_id is None:
            raise SyncConfigError("Sync engine not configured")

    async def get_last_run(self) -> SyncRunRow | None:
        """Return the most recent sync run, or None."""
        return await self._library_store.get_last_sync_run()

    async def run_sync(self) -> SyncResult:
        """Execute an incremental library sync.

        1. Validates config, acquires lock
        2. Fetches existing hashes and IDs from the store
        3. Pages through Jellyfin items, computing content hashes
        4. Classifies items as new/changed/unchanged
        5. Upserts changed items and enqueues for embedding
        6. Detects deletions (with 50% safety threshold)
        7. Runs WAL checkpoint if needed
        8. Saves sync result and purges tombstones

        Raises SyncAlreadyRunningError if another sync is in progress.
        Raises SyncConfigError if required config is missing.
        """
        # Fast-path rejection if lock is already held
        if self._lock.locked():
            raise SyncAlreadyRunningError("A sync is already in progress")

        # Acquire with a tiny timeout to close the TOCTOU window
        try:
            await asyncio.wait_for(self._lock.acquire(), timeout=1.0)
        except TimeoutError:
            raise SyncAlreadyRunningError("A sync is already in progress") from None

        try:
            self.validate_config()

            started_at = int(time.time())
            state = SyncState(
                started_at=started_at,
                pages_processed=0,
                items_processed=0,
                items_created=0,
                items_updated=0,
                items_unchanged=0,
                items_failed=0,
            )
            self._current_state = state

            error_message: str | None = None
            status = SYNC_STATUS_COMPLETED
            items_deleted = 0
            seen_ids: set[str] = set()
            known_ids: set[str] = set()

            # Validated above — safe to assert for pyright narrowing
            assert self._settings.jellyfin_api_key is not None
            assert self._settings.jellyfin_admin_user_id is not None
            token = self._settings.jellyfin_api_key.get_secret_value()
            user_id: str = self._settings.jellyfin_admin_user_id

            try:
                # Fetch existing state from the store
                existing_hashes = await self._library_store.get_all_hashes()
                known_ids = await self._library_store.get_all_ids()

                async for page in self._jellyfin_client.get_all_items(
                    token=token,
                    user_id=user_id,
                    item_types=["Movie", "Series"],
                    page_size=self._settings.library_sync_page_size,
                ):
                    rows_to_upsert: list[LibraryItemRow] = []
                    ids_to_enqueue: list[str] = []

                    for item in page.items:
                        # Track as seen regardless of processing success —
                        # an item present in Jellyfin should not be tombstoned
                        # just because row construction failed on it
                        seen_ids.add(item.id)
                        try:
                            row = to_library_row(item)
                            state.items_processed += 1

                            old_hash = existing_hashes.get(item.id)
                            if old_hash is None:
                                state.items_created += 1
                                rows_to_upsert.append(row)
                                ids_to_enqueue.append(item.id)
                            elif old_hash != row.content_hash:
                                state.items_updated += 1
                                rows_to_upsert.append(row)
                                ids_to_enqueue.append(item.id)
                            else:
                                state.items_unchanged += 1
                        except Exception:
                            _logger.warning(
                                "sync_item_failed jellyfin_id=%s",
                                item.id,
                            )
                            state.items_failed += 1

                    # Commit page results
                    if rows_to_upsert:
                        await self._library_store.upsert_many(rows_to_upsert)
                    if ids_to_enqueue:
                        await self._library_store.enqueue_for_embedding(ids_to_enqueue)

                    state.pages_processed += 1
                    _logger.info(
                        "sync page=%d new=%d changed=%d unchanged=%d failed=%d",
                        state.pages_processed,
                        state.items_created,
                        state.items_updated,
                        state.items_unchanged,
                        state.items_failed,
                    )

            except (JellyfinConnectionError, JellyfinError) as exc:
                _logger.error(
                    "sync_page_failed page=%d error_type=%s",
                    state.pages_processed + 1,
                    type(exc).__name__,
                )
                status = SYNC_STATUS_FAILED
                # Sanitize: type + docstring only, never raw URL/token
                doc = type(exc).__doc__ or "sync failed"
                error_message = f"{type(exc).__name__}: {doc}"

            except Exception as exc:
                _logger.error(
                    "sync_unexpected_error error_type=%s",
                    type(exc).__name__,
                )
                status = SYNC_STATUS_FAILED
                error_message = f"{type(exc).__name__}: unexpected sync error"

            # Deletion detection (runs even on partial sync)
            deleted_ids = known_ids - seen_ids
            if deleted_ids:
                # Safety threshold: only tombstone if we saw >= 50%
                last_run = await self._library_store.get_last_sync_run()
                last_total = last_run.total_items if last_run else 0
                # Only query count if no previous run as baseline
                active_count = await self._library_store.count() if not last_run else 0
                threshold_base = max(last_total, active_count)

                if threshold_base > 0 and len(seen_ids) >= 0.5 * threshold_base:
                    await self._library_store.soft_delete_many(list(deleted_ids))
                    items_deleted = len(deleted_ids)
                    _logger.info("sync_soft_deleted count=%d", items_deleted)
                else:
                    _logger.warning(
                        "sync_deletion_skipped seen=%d "
                        "threshold_base=%d "
                        "(below 50%% safety threshold)",
                        len(seen_ids),
                        threshold_base,
                    )

            # WAL checkpoint
            await self._maybe_wal_checkpoint()

            completed_at = int(time.time())
            total_items = (
                state.items_created
                + state.items_updated
                + state.items_unchanged
                + state.items_failed
            )

            result = SyncResult(
                started_at=started_at,
                completed_at=completed_at,
                status=status,
                total_items=total_items,
                items_created=state.items_created,
                items_updated=state.items_updated,
                items_deleted=items_deleted,
                items_unchanged=state.items_unchanged,
                items_failed=state.items_failed,
                error_message=error_message,
            )

            await self._library_store.save_sync_run(result)

            # Fire on-sync-complete hooks (e.g. PersonIndex rebuild). Each
            # hook is awaited in registration order; failures are logged
            # and swallowed so a broken listener never wedges sync.
            for cb in self._on_sync_complete:
                try:
                    await cb()
                except Exception:
                    _logger.warning(
                        "sync_completion_hook_failed callback=%s",
                        getattr(cb, "__name__", repr(cb)),
                        exc_info=True,
                    )

            # Wake embedding worker after sync completes
            if self._embedding_event:
                self._embedding_event.set()

            # Purge runs after save_sync_run intentionally —
            # items_deleted in SyncResult tracks soft-deletes detected
            # in THIS run, not tombstone purges from prior runs.
            try:
                await self.purge_tombstones()
            except Exception:
                _logger.warning("purge_tombstones_failed", exc_info=True)

            return result
        finally:
            self._current_state = None
            self._lock.release()

    async def _maybe_wal_checkpoint(self) -> None:
        """Run a WAL checkpoint if the WAL sidecar file exceeds the threshold."""
        try:
            db_path = self._settings.library_db_path
            threshold_bytes = self._settings.wal_checkpoint_threshold_mb * 1024 * 1024
            wal_path = f"{db_path}-wal"
            if os.path.exists(wal_path):
                wal_size = os.path.getsize(wal_path)
                if wal_size >= threshold_bytes:
                    _logger.info(
                        "wal_checkpoint wal_size_mb=%.1f threshold_mb=%.1f",
                        wal_size / (1024 * 1024),
                        self._settings.wal_checkpoint_threshold_mb,
                    )
                    await self._library_store.run_wal_checkpoint()
        except Exception:
            _logger.warning("wal_checkpoint_failed", exc_info=True)

    async def purge_tombstones(self) -> int:
        """Remove expired soft-deleted items in the correct order.

        Deletion order (Vimes-mandated):
          1. vectors (if vector repository is available)
          2. embedding_queue entries
          3. library_items rows

        Returns the number of items purged.
        """
        older_than = int(time.time()) - (self._settings.tombstone_ttl_days * 86400)
        ids = await self._library_store.get_tombstoned_ids(older_than)
        if not ids:
            _logger.info("purge_tombstones: no expired tombstones")
            return 0

        # Vimes-mandated deletion order: vectors -> embedding_queue -> library_items
        if self._vector_repo is not None:
            await self._vector_repo.delete_many(ids)
        await self._library_store.delete_from_embedding_queue(ids)
        count = await self._library_store.hard_delete_many(ids)
        _logger.info(
            "purge_tombstones: purged %d items older than %d days",
            count,
            self._settings.tombstone_ttl_days,
        )
        return count
