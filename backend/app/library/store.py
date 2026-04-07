"""Async SQLite library metadata repository.

Stores Jellyfin library item metadata with content hashing for incremental
sync. Follows the same init()/close()/_conn pattern as SessionStore.
Uses aiosqlite in WAL mode for concurrent read access.
"""

from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING, Any

import aiosqlite

from app.library.models import LibraryItemRow, UpsertResult

if TYPE_CHECKING:
    from app.sync.models import SyncResult, SyncRunRow

logger = logging.getLogger(__name__)

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS library_items (
    jellyfin_id       TEXT PRIMARY KEY,
    title             TEXT NOT NULL,
    overview          TEXT,
    production_year   INTEGER,
    genres            TEXT NOT NULL DEFAULT '[]',
    tags              TEXT NOT NULL DEFAULT '[]',
    studios           TEXT NOT NULL DEFAULT '[]',
    community_rating  REAL,
    people            TEXT NOT NULL DEFAULT '[]',
    content_hash      TEXT NOT NULL,
    synced_at         INTEGER NOT NULL,
    deleted_at        INTEGER
)
"""

_CREATE_INDEX_HASH = """
CREATE INDEX IF NOT EXISTS idx_library_items_content_hash
ON library_items(content_hash)
"""

_CREATE_INDEX_SYNCED = """
CREATE INDEX IF NOT EXISTS idx_library_items_synced_at
ON library_items(synced_at)
"""

_CREATE_INDEX_DELETED = """
CREATE INDEX IF NOT EXISTS idx_library_items_deleted_at
ON library_items(deleted_at)
"""

_CREATE_EMBEDDING_QUEUE = """
CREATE TABLE IF NOT EXISTS embedding_queue (
    jellyfin_id    TEXT PRIMARY KEY,
    enqueued_at    INTEGER NOT NULL,
    status         TEXT NOT NULL DEFAULT 'pending',
    retry_count    INTEGER NOT NULL DEFAULT 0,
    error_message  TEXT
)
"""

_CREATE_INDEX_EMBEDDING_QUEUE = """
CREATE INDEX IF NOT EXISTS idx_embedding_queue_status_enqueued
ON embedding_queue(status, enqueued_at)
"""

_CREATE_SYNC_RUNS = """
CREATE TABLE IF NOT EXISTS sync_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at      INTEGER NOT NULL,
    completed_at    INTEGER,
    status          TEXT NOT NULL,
    total_items     INTEGER NOT NULL DEFAULT 0,
    items_created   INTEGER NOT NULL DEFAULT 0,
    items_updated   INTEGER NOT NULL DEFAULT 0,
    items_deleted   INTEGER NOT NULL DEFAULT 0,
    items_unchanged INTEGER NOT NULL DEFAULT 0,
    items_failed    INTEGER NOT NULL DEFAULT 0,
    error_message   TEXT
)
"""

_CREATE_INDEX_SYNC_RUNS_STARTED = """
CREATE INDEX IF NOT EXISTS idx_sync_runs_started_at
ON sync_runs(started_at)
"""

# Maximum number of IDs per SQL IN clause batch
_BATCH_SIZE = 500


class LibraryStore:
    """Async library metadata repository backed by SQLite."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def init(self) -> None:
        """Open the database connection and create the schema."""
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA foreign_keys = ON")
        await self._db.execute("PRAGMA busy_timeout=5000")
        await self._db.execute(_CREATE_TABLE)
        await self._db.execute(_CREATE_INDEX_HASH)
        await self._db.execute(_CREATE_INDEX_SYNCED)

        # Migration: add deleted_at column if table predates Spec 08
        cursor = await self._db.execute("PRAGMA table_info(library_items)")
        existing_columns = {row[1] for row in await cursor.fetchall()}
        if "deleted_at" not in existing_columns:
            await self._db.execute(
                "ALTER TABLE library_items ADD COLUMN deleted_at INTEGER"
            )
            await self._db.commit()

        await self._db.execute(_CREATE_INDEX_DELETED)
        await self._db.execute(_CREATE_EMBEDDING_QUEUE)
        await self._db.execute(_CREATE_INDEX_EMBEDDING_QUEUE)

        # Migration: add runtime_minutes column if table predates Spec 19
        if "runtime_minutes" not in existing_columns:
            await self._db.execute(
                "ALTER TABLE library_items ADD COLUMN runtime_minutes INTEGER"
            )
            await self._db.commit()

        # Migration: add last_attempted_at column if table predates Spec 10
        eq_cursor = await self._db.execute("PRAGMA table_info(embedding_queue)")
        eq_columns = {row[1] for row in await eq_cursor.fetchall()}
        if "last_attempted_at" not in eq_columns:
            await self._db.execute(
                "ALTER TABLE embedding_queue ADD COLUMN last_attempted_at INTEGER"
            )
            await self._db.commit()
        await self._db.execute(_CREATE_SYNC_RUNS)
        await self._db.execute(_CREATE_INDEX_SYNC_RUNS_STARTED)
        await self._db.commit()

    async def close(self) -> None:
        """Close the database connection."""
        if self._db:
            await self._db.close()
            self._db = None

    @property
    def _conn(self) -> aiosqlite.Connection:
        if self._db is None:
            msg = "LibraryStore not initialised — call init() first"
            raise RuntimeError(msg)
        return self._db

    @staticmethod
    def _row_to_item(row: Any) -> LibraryItemRow:
        """Deserialize a database row into a LibraryItemRow.

        Column mapping (must match SELECT order in all queries):
          0: jellyfin_id   TEXT PK
          1: title          TEXT NOT NULL
          2: overview       TEXT (nullable)
          3: production_year INTEGER (nullable)
          4: genres         TEXT (JSON array)
          5: tags           TEXT (JSON array)
          6: studios        TEXT (JSON array)
          7: community_rating REAL (nullable)
          8: people         TEXT (JSON array)
          9: content_hash   TEXT NOT NULL
         10: synced_at      INTEGER NOT NULL
         11: runtime_minutes INTEGER (nullable)
        """
        return LibraryItemRow(
            jellyfin_id=row[0],
            title=row[1],
            overview=row[2],
            production_year=row[3],
            genres=json.loads(row[4]),
            tags=json.loads(row[5]),
            studios=json.loads(row[6]),
            community_rating=row[7],
            people=json.loads(row[8]),
            content_hash=row[9],
            synced_at=row[10],
            runtime_minutes=row[11],
        )

    async def _get_hashes_for_ids(self, ids: list[str]) -> dict[str, str]:
        """Return {jellyfin_id: content_hash} for the given IDs only."""
        if not ids:
            return {}

        result: dict[str, str] = {}
        for i in range(0, len(ids), _BATCH_SIZE):
            batch = ids[i : i + _BATCH_SIZE]
            placeholders = ",".join("?" * len(batch))
            cursor = await self._conn.execute(
                f"SELECT jellyfin_id, content_hash FROM library_items "
                f"WHERE jellyfin_id IN ({placeholders})",
                batch,
            )
            rows = await cursor.fetchall()
            for row in rows:
                result[row[0]] = row[1]
        return result

    async def upsert_many(self, items: list[LibraryItemRow]) -> UpsertResult:
        """Bulk upsert library items with created/updated/unchanged tracking.

        Wraps the entire batch in a single transaction. Fetches existing
        hashes for the batch IDs to classify each item as created, updated,
        or unchanged. Unchanged items are skipped entirely. Uses executemany()
        for a single batch SQL call. Uses INSERT ... ON CONFLICT(jellyfin_id)
        DO UPDATE SET ... — never INSERT OR REPLACE.
        """
        if not items:
            return UpsertResult(created=0, updated=0, unchanged=0)

        # Fetch existing hashes only for IDs in this batch
        batch_ids = [item.jellyfin_id for item in items]
        existing_hashes = await self._get_hashes_for_ids(batch_ids)

        created = 0
        updated = 0
        unchanged = 0
        params_list: list[tuple[object, ...]] = []

        for item in items:
            old_hash = existing_hashes.get(item.jellyfin_id)
            if old_hash is None:
                created += 1
            elif old_hash != item.content_hash:
                updated += 1
            else:
                unchanged += 1
                continue  # Skip unchanged items — no SQL needed

            params_list.append(
                (
                    item.jellyfin_id,
                    item.title,
                    item.overview,
                    item.production_year,
                    json.dumps(item.genres),
                    json.dumps(item.tags),
                    json.dumps(item.studios),
                    item.community_rating,
                    json.dumps(item.people),
                    item.content_hash,
                    item.synced_at,
                    item.runtime_minutes,
                )
            )

        if params_list:
            await self._conn.execute("BEGIN")
            try:
                await self._conn.executemany(
                    """INSERT INTO library_items
                       (jellyfin_id, title, overview, production_year,
                        genres, tags, studios, community_rating,
                        people, content_hash, synced_at, runtime_minutes)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(jellyfin_id) DO UPDATE SET
                        title = excluded.title,
                        overview = excluded.overview,
                        production_year = excluded.production_year,
                        genres = excluded.genres,
                        tags = excluded.tags,
                        studios = excluded.studios,
                        community_rating = excluded.community_rating,
                        people = excluded.people,
                        content_hash = excluded.content_hash,
                        synced_at = excluded.synced_at,
                        runtime_minutes = excluded.runtime_minutes""",
                    params_list,
                )
            except Exception:
                await self._conn.rollback()
                raise
            else:
                await self._conn.commit()
        return UpsertResult(created=created, updated=updated, unchanged=unchanged)

    async def get(self, jellyfin_id: str) -> LibraryItemRow | None:
        """Fetch a single item by primary key."""
        cursor = await self._conn.execute(
            """SELECT jellyfin_id, title, overview, production_year,
                      genres, tags, studios, community_rating,
                      people, content_hash, synced_at, runtime_minutes
               FROM library_items WHERE jellyfin_id = ?""",
            (jellyfin_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return self._row_to_item(row)

    async def get_many(self, ids: list[str]) -> list[LibraryItemRow]:
        """Fetch multiple items by Jellyfin IDs.

        Uses parameterized queries (no string interpolation). Chunks into
        batches of 500 for safety against SQLITE_MAX_VARIABLE_NUMBER.
        Returns items in no guaranteed order.
        """
        if not ids:
            return []

        results: list[LibraryItemRow] = []

        for i in range(0, len(ids), _BATCH_SIZE):
            batch = ids[i : i + _BATCH_SIZE]
            placeholders = ",".join("?" * len(batch))
            cursor = await self._conn.execute(
                f"""SELECT jellyfin_id, title, overview, production_year,
                          genres, tags, studios, community_rating,
                          people, content_hash, synced_at, runtime_minutes
                   FROM library_items WHERE jellyfin_id IN ({placeholders})""",
                batch,
            )
            rows = await cursor.fetchall()
            results.extend(self._row_to_item(r) for r in rows)

        return results

    async def get_all_hashes(self) -> dict[str, str]:
        """Return {jellyfin_id: content_hash} mapping for active (non-deleted) items."""
        cursor = await self._conn.execute(
            "SELECT jellyfin_id, content_hash FROM library_items"
            " WHERE deleted_at IS NULL"
        )
        rows = await cursor.fetchall()
        return {row[0]: row[1] for row in rows}

    async def count(self) -> int:
        """Return total number of active (non-deleted) items in the store."""
        cursor = await self._conn.execute(
            "SELECT COUNT(*) FROM library_items WHERE deleted_at IS NULL"
        )
        row = await cursor.fetchone()
        return row[0] if row else 0

    # --- Sync engine methods (Spec 08, Task 2.0) ---

    async def get_all_ids(self) -> set[str]:
        """Return the set of all active (non-deleted) jellyfin_ids."""
        cursor = await self._conn.execute(
            "SELECT jellyfin_id FROM library_items WHERE deleted_at IS NULL"
        )
        rows = await cursor.fetchall()
        return {row[0] for row in rows}

    async def soft_delete_many(self, ids: list[str]) -> int:
        """Mark items as deleted by setting deleted_at timestamp.

        Chunks at _BATCH_SIZE. Wrapped in a single transaction for atomicity.
        Returns the total number of rows affected.
        """
        if not ids:
            return 0

        now = int(time.time())
        total = 0
        await self._conn.execute("BEGIN")
        try:
            for i in range(0, len(ids), _BATCH_SIZE):
                batch = ids[i : i + _BATCH_SIZE]
                placeholders = ",".join("?" * len(batch))
                cursor = await self._conn.execute(
                    f"UPDATE library_items SET deleted_at = ?"
                    f" WHERE jellyfin_id IN ({placeholders})",
                    [now, *batch],
                )
                total += cursor.rowcount
        except Exception:
            await self._conn.rollback()
            raise
        else:
            await self._conn.commit()
        return total

    async def hard_delete_many(self, ids: list[str]) -> int:
        """Permanently remove items from the store.

        Chunks at _BATCH_SIZE. Wrapped in a single transaction for atomicity.
        Returns the total number of rows deleted.
        """
        if not ids:
            return 0

        total = 0
        await self._conn.execute("BEGIN")
        try:
            for i in range(0, len(ids), _BATCH_SIZE):
                batch = ids[i : i + _BATCH_SIZE]
                placeholders = ",".join("?" * len(batch))
                cursor = await self._conn.execute(
                    f"DELETE FROM library_items WHERE jellyfin_id IN ({placeholders})",
                    batch,
                )
                total += cursor.rowcount
        except Exception:
            await self._conn.rollback()
            raise
        else:
            await self._conn.commit()
        return total

    async def get_tombstoned_ids(self, older_than: int) -> list[str]:
        """Return IDs of items soft-deleted before the given timestamp."""
        cursor = await self._conn.execute(
            "SELECT jellyfin_id FROM library_items"
            " WHERE deleted_at IS NOT NULL AND deleted_at < ?",
            (older_than,),
        )
        rows = await cursor.fetchall()
        return [row[0] for row in rows]

    async def enqueue_for_embedding(self, ids: list[str]) -> int:
        """Insert or reset items in the embedding queue as 'pending'.

        Uses ON CONFLICT to reset status, retry_count, and error_message
        for items that are already queued. Wrapped in a single transaction
        for atomicity. Returns the number of IDs submitted (input count).
        """
        if not ids:
            return 0

        now = int(time.time())
        total = 0
        await self._conn.execute("BEGIN")
        try:
            for i in range(0, len(ids), _BATCH_SIZE):
                batch = ids[i : i + _BATCH_SIZE]
                params = [(jid, now) for jid in batch]
                await self._conn.executemany(
                    "INSERT INTO embedding_queue (jellyfin_id, enqueued_at, status)"
                    " VALUES (?, ?, 'pending')"
                    " ON CONFLICT(jellyfin_id) DO UPDATE SET"
                    " status='pending', enqueued_at=excluded.enqueued_at,"
                    " retry_count=0, error_message=NULL,"
                    " last_attempted_at=NULL",
                    params,
                )
                total += len(batch)
        except Exception:
            await self._conn.rollback()
            raise
        else:
            await self._conn.commit()
        return total

    async def count_pending_embeddings(self) -> int:
        """Return the number of items with 'pending' status in the queue."""
        cursor = await self._conn.execute(
            "SELECT COUNT(*) FROM embedding_queue WHERE status = 'pending'"
        )
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def save_sync_run(self, run: SyncResult) -> None:
        """Persist a SyncResult as a row in the sync_runs table."""
        await self._conn.execute(
            "INSERT INTO sync_runs"
            " (started_at, completed_at, status, total_items,"
            "  items_created, items_updated, items_deleted,"
            "  items_unchanged, items_failed, error_message)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run.started_at,
                run.completed_at,
                run.status,
                run.total_items,
                run.items_created,
                run.items_updated,
                run.items_deleted,
                run.items_unchanged,
                run.items_failed,
                run.error_message,
            ),
        )
        await self._conn.commit()

    async def get_last_sync_run(self) -> SyncRunRow | None:
        """Return the most recent sync run, or None if no runs exist."""
        cursor = await self._conn.execute(
            "SELECT id, started_at, completed_at, status, total_items,"
            " items_created, items_updated, items_deleted,"
            " items_unchanged, items_failed, error_message"
            " FROM sync_runs ORDER BY started_at DESC, id DESC LIMIT 1"
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return self._row_to_sync_run(row)

    @staticmethod
    def _row_to_sync_run(row: Any) -> SyncRunRow:
        """Deserialize a database row into a SyncRunRow."""
        from app.sync.models import SyncRunRow as _SyncRunRow

        return _SyncRunRow(
            id=row[0],
            started_at=row[1],
            completed_at=row[2],
            status=row[3],
            total_items=row[4],
            items_created=row[5],
            items_updated=row[6],
            items_deleted=row[7],
            items_unchanged=row[8],
            items_failed=row[9],
            error_message=row[10],
        )

    async def delete_from_embedding_queue(self, ids: list[str]) -> int:
        """Remove items from the embedding queue by jellyfin_id.

        Chunks at _BATCH_SIZE. Wrapped in a single transaction for atomicity.
        Returns the total number of rows deleted.
        """
        if not ids:
            return 0

        total = 0
        await self._conn.execute("BEGIN")
        try:
            for i in range(0, len(ids), _BATCH_SIZE):
                batch = ids[i : i + _BATCH_SIZE]
                placeholders = ",".join("?" * len(batch))
                sql = (
                    f"DELETE FROM embedding_queue WHERE jellyfin_id IN ({placeholders})"
                )
                cursor = await self._conn.execute(sql, batch)
                total += cursor.rowcount
        except Exception:
            await self._conn.rollback()
            raise
        else:
            await self._conn.commit()
        return total

    # --- Embedding worker methods (Spec 10, Task 1.0) ---

    async def get_retryable_items(
        self, cooldown_seconds: int, max_retries: int, batch_size: int
    ) -> list[tuple[str, int]]:
        """Return (jellyfin_id, retry_count) pairs eligible for embedding.

        Selects items that are 'pending' with retry_count <= max_retries
        and whose last_attempted_at is either NULL or older than the
        cooldown window. Ordered by enqueued_at ASC, limited to batch_size.
        """
        now = int(time.time())
        cutoff = now - cooldown_seconds
        cursor = await self._conn.execute(
            "SELECT jellyfin_id, retry_count FROM embedding_queue"
            " WHERE status = 'pending'"
            " AND (last_attempted_at IS NULL OR last_attempted_at < ?)"
            " AND retry_count <= ?"
            " ORDER BY enqueued_at ASC"
            " LIMIT ?",
            (cutoff, max_retries, batch_size),
        )
        rows = await cursor.fetchall()
        return [(row[0], row[1]) for row in rows]

    async def claim_batch(self, ids: list[str]) -> int:
        """Atomically transition pending queue items to 'processing'.

        Returns the number of rows actually transitioned. Items not in
        'pending' status are silently skipped.
        """
        if not ids:
            return 0

        now = int(time.time())
        placeholders = ",".join("?" * len(ids))
        cursor = await self._conn.execute(
            f"UPDATE embedding_queue SET status='processing', last_attempted_at=?"
            f" WHERE jellyfin_id IN ({placeholders}) AND status='pending'",
            [now, *ids],
        )
        await self._conn.commit()
        return cursor.rowcount

    async def mark_embedded(self, jellyfin_id: str) -> None:
        """Remove a successfully embedded item from the queue."""
        await self._conn.execute(
            "DELETE FROM embedding_queue WHERE jellyfin_id = ?",
            (jellyfin_id,),
        )
        await self._conn.commit()

    async def mark_embedded_many(self, ids: list[str]) -> int:
        """Batch-delete successfully embedded items from the queue.

        Delegates to ``delete_from_embedding_queue`` — same semantics,
        different name for the caller's domain vocabulary.
        """
        return await self.delete_from_embedding_queue(ids)

    async def mark_attempt(self, jellyfin_id: str, error_message: str) -> None:
        """Record a failed embedding attempt — increment retry, stay pending."""
        now = int(time.time())
        await self._conn.execute(
            "UPDATE embedding_queue SET status='pending',"
            " retry_count=retry_count+1, error_message=?,"
            " last_attempted_at=?"
            " WHERE jellyfin_id=?",
            (error_message, now, jellyfin_id),
        )
        await self._conn.commit()

    async def mark_failed_permanent(self, jellyfin_id: str, reason: str) -> None:
        """Mark an item as permanently failed — no further retries."""
        now = int(time.time())
        await self._conn.execute(
            "UPDATE embedding_queue SET status='failed',"
            " error_message=?, last_attempted_at=?"
            " WHERE jellyfin_id=?",
            (reason, now, jellyfin_id),
        )
        await self._conn.commit()

    async def reset_stale_processing(self) -> int:
        """Reset all 'processing' items back to 'pending' for crash recovery.

        Called at startup to reclaim items that were mid-flight when the
        process was interrupted. Returns the number of rows reset.
        """
        cursor = await self._conn.execute(
            "UPDATE embedding_queue SET status='pending' WHERE status='processing'"
        )
        await self._conn.commit()
        return cursor.rowcount

    async def get_failed_items(self) -> list[dict[str, Any]]:
        """Return details for all permanently failed queue items."""
        cursor = await self._conn.execute(
            "SELECT jellyfin_id, error_message, retry_count, last_attempted_at"
            " FROM embedding_queue WHERE status='failed'"
        )
        rows = await cursor.fetchall()
        return [
            {
                "jellyfin_id": row[0],
                "error_message": row[1],
                "retry_count": row[2],
                "last_attempted_at": row[3],
            }
            for row in rows
        ]

    async def get_queue_counts(self) -> dict[str, int]:
        """Return {pending, processing, failed} counts from the embedding queue."""
        cursor = await self._conn.execute(
            "SELECT status, COUNT(*) FROM embedding_queue GROUP BY status"
        )
        rows = await cursor.fetchall()
        counts: dict[str, int] = {"pending": 0, "processing": 0, "failed": 0}
        for row in rows:
            if row[0] in counts:
                counts[row[0]] = row[1]
        return counts

    async def run_wal_checkpoint(self) -> None:
        """Execute a WAL checkpoint to reclaim disk space.

        Uses PASSIVE mode which never blocks readers or writers — it
        checkpoints only frames that are not in use by any reader.
        """
        await self._conn.execute("PRAGMA wal_checkpoint(PASSIVE)")

    # count_active() is intentionally not defined — use count() instead,
    # which already filters to active (non-deleted) items.
