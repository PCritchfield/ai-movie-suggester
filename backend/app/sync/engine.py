"""Incremental sync engine.

Fetches Jellyfin library, diffs against store, enqueues changes.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
from typing import TYPE_CHECKING

from app.jellyfin.errors import JellyfinConnectionError, JellyfinError
from app.library.models import LibraryItemRow
from app.ollama.text_builder import build_composite_text
from app.sync.models import (
    SyncAlreadyRunningError,
    SyncConfigError,
    SyncResult,
    SyncState,
)

if TYPE_CHECKING:
    from app.config import Settings
    from app.jellyfin.client import JellyfinClient
    from app.jellyfin.models import LibraryItem
    from app.library.store import LibraryStore
    from app.vectors.repository import SqliteVecRepository

_logger = logging.getLogger(__name__)


def _to_row(item: LibraryItem, content_hash: str) -> LibraryItemRow:
    """Convert a Jellyfin LibraryItem to a LibraryItemRow for storage.

    Extracts actor names from the people list (filtering by Type == "Actor").
    """
    people = [
        p["Name"] for p in item.people if p.get("Type") == "Actor" and "Name" in p
    ]
    return LibraryItemRow(
        jellyfin_id=item.id,
        title=item.name,
        overview=item.overview,
        production_year=item.production_year,
        genres=item.genres,
        tags=item.tags,
        studios=item.studios,
        community_rating=item.community_rating,
        people=people,
        content_hash=content_hash,
        synced_at=int(time.time()),
    )


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
    ) -> None:
        self._library_store = library_store
        self._jellyfin_client = jellyfin_client
        self._settings = settings
        self._vector_repo = vector_repository
        self._lock = asyncio.Lock()
        self._current_state: SyncState | None = None

    @property
    def current_state(self) -> SyncState | None:
        """Return the current sync state, or None if no sync is in progress."""
        return self._current_state

    def _validate_config(self) -> None:
        """Ensure required sync configuration is present."""
        if self._settings.jellyfin_api_key is None:
            msg = "JELLYFIN_API_KEY is required for library sync"
            raise SyncConfigError(msg)
        if self._settings.jellyfin_admin_user_id is None:
            msg = "JELLYFIN_ADMIN_USER_ID is required for library sync"
            raise SyncConfigError(msg)

    @staticmethod
    def _compute_hash(text: str) -> str:
        """Compute a SHA-256 hex digest from the given text."""
        return hashlib.sha256(text.encode()).hexdigest()

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
        if self._lock.locked():
            raise SyncAlreadyRunningError("A sync is already in progress")

        async with self._lock:
            self._validate_config()

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
            status = "completed"
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
                    item_types=["Movie"],
                    page_size=self._settings.library_sync_page_size,
                ):
                    rows_to_upsert: list[LibraryItemRow] = []
                    ids_to_enqueue: list[str] = []

                    for item in page.items:
                        try:
                            composite_result = build_composite_text(item)
                            content_hash = self._compute_hash(composite_result.text)
                            seen_ids.add(item.id)
                            state.items_processed += 1

                            old_hash = existing_hashes.get(item.id)
                            if old_hash is None:
                                # New item
                                state.items_created += 1
                                row = _to_row(item, content_hash)
                                rows_to_upsert.append(row)
                                ids_to_enqueue.append(item.id)
                            elif old_hash != content_hash:
                                # Changed item
                                state.items_updated += 1
                                row = _to_row(item, content_hash)
                                rows_to_upsert.append(row)
                                ids_to_enqueue.append(item.id)
                            else:
                                # Unchanged
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

            except (JellyfinConnectionError, JellyfinError) as exc:
                _logger.error(
                    "sync_page_failed page=%d error=%s",
                    state.pages_processed + 1,
                    str(exc),
                )
                status = "failed"
                error_message = str(exc)

            except Exception as exc:
                _logger.error("sync_unexpected_error error=%s", str(exc))
                status = "failed"
                error_message = str(exc)

            # Deletion detection (runs even on partial sync)
            deleted_ids = known_ids - seen_ids
            if deleted_ids:
                # Safety threshold: only tombstone if we saw >= 50% of expected items
                last_run = await self._library_store.get_last_sync_run()
                active_count = await self._library_store.count()
                last_total = last_run.total_items if last_run else 0
                threshold_base = max(last_total, active_count)

                if threshold_base == 0 or len(seen_ids) >= 0.5 * threshold_base:
                    await self._library_store.soft_delete_many(list(deleted_ids))
                    items_deleted = len(deleted_ids)
                    _logger.info("sync_soft_deleted count=%d", items_deleted)
                else:
                    _logger.warning(
                        "sync_deletion_skipped seen=%d threshold_base=%d "
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

            # Purge expired tombstones (failure does not affect sync result)
            try:
                await self.purge_tombstones()
            except Exception:
                _logger.warning("purge_tombstones_failed", exc_info=True)

            self._current_state = None
            return result

    async def _maybe_wal_checkpoint(self) -> None:
        """Run a WAL checkpoint if the database file exceeds the threshold."""
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
                    await self._library_store._conn.execute(  # noqa: SLF001
                        "PRAGMA wal_checkpoint(TRUNCATE)"
                    )
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
