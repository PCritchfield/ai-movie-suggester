"""Async SQLite library metadata repository.

Stores Jellyfin library item metadata with content hashing for incremental
sync. Follows the same init()/close()/_conn pattern as SessionStore.
Uses aiosqlite in WAL mode for concurrent read access.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import aiosqlite

from app.library.models import LibraryItemRow, UpsertResult

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
    synced_at         INTEGER NOT NULL
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
        await self._db.execute(_CREATE_TABLE)
        await self._db.execute(_CREATE_INDEX_HASH)
        await self._db.execute(_CREATE_INDEX_SYNCED)
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
                )
            )

        if params_list:
            await self._conn.executemany(
                """INSERT INTO library_items
                   (jellyfin_id, title, overview, production_year,
                    genres, tags, studios, community_rating,
                    people, content_hash, synced_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    synced_at = excluded.synced_at""",
                params_list,
            )

        await self._conn.commit()
        return UpsertResult(created=created, updated=updated, unchanged=unchanged)

    async def get(self, jellyfin_id: str) -> LibraryItemRow | None:
        """Fetch a single item by primary key."""
        cursor = await self._conn.execute(
            """SELECT jellyfin_id, title, overview, production_year,
                      genres, tags, studios, community_rating,
                      people, content_hash, synced_at
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
                          people, content_hash, synced_at
                   FROM library_items WHERE jellyfin_id IN ({placeholders})""",
                batch,
            )
            rows = await cursor.fetchall()
            results.extend(self._row_to_item(r) for r in rows)

        return results

    async def get_all_hashes(self) -> dict[str, str]:
        """Return {jellyfin_id: content_hash} mapping for all items."""
        cursor = await self._conn.execute(
            "SELECT jellyfin_id, content_hash FROM library_items"
        )
        rows = await cursor.fetchall()
        return {row[0]: row[1] for row in rows}

    async def count(self) -> int:
        """Return total number of items in the store."""
        cursor = await self._conn.execute("SELECT COUNT(*) FROM library_items")
        row = await cursor.fetchone()
        return row[0] if row else 0
