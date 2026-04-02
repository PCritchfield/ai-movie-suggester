"""SQLite-vec vector repository implementation.

Stores 768-dimensional (or configurable) float vectors using the vec0
virtual table extension. Provides cosine-similarity search, CRUD
operations, and embedding status tracking.

Uses separate reader/writer aiosqlite connections in WAL mode for
concurrent search-while-embedding without write lock contention.
"""

from __future__ import annotations

import logging
import struct
import time

import aiosqlite
import sqlite_vec

from app.vectors.models import (
    COMPLETE,
    VALID_STATUSES,
    SearchResult,
    VectorRecord,
)

_logger = logging.getLogger(__name__)

_CREATE_VEC_META = """
CREATE TABLE IF NOT EXISTS _vec_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
)
"""


def _serialize_f32(vector: list[float]) -> bytes:
    """Serialize a list of floats to compact binary format for sqlite-vec."""
    return struct.pack(f"{len(vector)}f", *vector)


class SqliteVecRepository:
    """Async vector repository backed by SQLite-vec (vec0 extension)."""

    def __init__(
        self,
        db_path: str,
        expected_model: str,
        expected_dimensions: int,
    ) -> None:
        self._db_path = db_path
        self._expected_model = expected_model
        self._expected_dimensions = expected_dimensions
        self._writer_db: aiosqlite.Connection | None = None
        self._reader_db: aiosqlite.Connection | None = None

    @property
    def _writer(self) -> aiosqlite.Connection:
        if self._writer_db is None:
            msg = "SqliteVecRepository not initialised — call init() first"
            raise RuntimeError(msg)
        return self._writer_db

    @property
    def _reader(self) -> aiosqlite.Connection:
        if self._reader_db is None:
            msg = "SqliteVecRepository not initialised — call init() first"
            raise RuntimeError(msg)
        return self._reader_db

    async def _load_vec0(self, conn: aiosqlite.Connection) -> None:
        """Load the vec0 extension on an aiosqlite connection.

        Extension loading is disabled immediately after vec0 is loaded
        to reduce the attack surface — no further extensions can be
        injected via this connection.
        """
        try:
            await conn.enable_load_extension(True)
            await conn.load_extension(sqlite_vec.loadable_path())
            # Close extension loading capability now that vec0 is loaded
            await conn.enable_load_extension(False)
            _logger.info("sqlite-vec extension loaded: %s", sqlite_vec.loadable_path())
        except Exception as exc:
            msg = (
                "Failed to load sqlite-vec extension (vec0). "
                "Ensure the sqlite-vec package is installed: "
                "pip install sqlite-vec"
            )
            raise RuntimeError(msg) from exc

    async def _setup_connection(self, conn: aiosqlite.Connection) -> None:
        """Apply standard pragmas and load vec0 on a connection."""
        await self._load_vec0(conn)
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("PRAGMA foreign_keys=ON")
        # Prevent "database is locked" errors when reader and writer
        # contend — wait up to 5 s before raising instead of failing
        # immediately.
        await conn.execute("PRAGMA busy_timeout=5000")

    async def init(self) -> None:
        """Open connections, load vec0, create schema, validate metadata.

        If any step after opening connections fails (extension load,
        metadata validation, table creation), partially-opened connections
        are closed before re-raising so callers don't leak resources.
        """
        try:
            # Open writer connection
            self._writer_db = await aiosqlite.connect(self._db_path)
            await self._setup_connection(self._writer)

            # Open reader connection
            self._reader_db = await aiosqlite.connect(self._db_path)
            await self._setup_connection(self._reader)

            # Create _vec_meta table
            await self._writer.execute(_CREATE_VEC_META)
            await self._writer.commit()

            # Validate or store model/dimension metadata
            await self._validate_or_store_meta()

            # Create vec0 virtual table for vectors
            create_vec_table = (
                "CREATE VIRTUAL TABLE IF NOT EXISTS item_vectors USING vec0("
                "    jellyfin_id TEXT PRIMARY KEY,"
                f"    embedding float[{self._expected_dimensions}]"
                " distance_metric=cosine,"
                "    content_hash TEXT,"
                "    embedded_at INTEGER,"
                "    embedding_status TEXT"
                ")"
            )
            await self._writer.execute(create_vec_table)
            await self._writer.commit()
        except Exception:
            await self.close()
            raise

    async def _validate_or_store_meta(self) -> None:
        """Check _vec_meta for model/dimensions; store on first run."""
        cursor = await self._writer.execute(
            "SELECT key, value FROM _vec_meta WHERE key IN ('model_name', 'dimensions')"
        )
        rows = await cursor.fetchall()
        stored: dict[str, str] = {row[0]: row[1] for row in rows}

        if not stored:
            # First run — insert metadata
            await self._writer.execute(
                "INSERT INTO _vec_meta (key, value) VALUES (?, ?)",
                ("model_name", self._expected_model),
            )
            await self._writer.execute(
                "INSERT INTO _vec_meta (key, value) VALUES (?, ?)",
                ("dimensions", str(self._expected_dimensions)),
            )
            await self._writer.commit()
            return

        # Subsequent run — validate
        stored_model = stored.get("model_name", "")
        stored_dims = stored.get("dimensions", "")

        if stored_dims != str(self._expected_dimensions):
            msg = (
                f"Dimension mismatch: DB has {stored_dims} ({stored_model}), "
                f"expected {self._expected_dimensions} ({self._expected_model}). "
                "Re-embed or use a new DB."
            )
            raise RuntimeError(msg)

        if stored_model != self._expected_model:
            msg = (
                f"Model mismatch: DB has '{stored_model}', "
                f"expected '{self._expected_model}'. "
                "Re-embed or use a new DB."
            )
            raise RuntimeError(msg)

    def _check_dims(self, embedding: list[float]) -> None:
        """Raise ValueError if embedding length doesn't match expected dimensions."""
        if len(embedding) != self._expected_dimensions:
            msg = (
                f"Embedding dimension mismatch: got {len(embedding)},"
                f" expected {self._expected_dimensions}"
            )
            raise ValueError(msg)

    async def upsert(
        self, jellyfin_id: str, embedding: list[float], content_hash: str
    ) -> None:
        """Insert or update a vector (DELETE + INSERT pattern).

        Wrapped in an explicit transaction so a crash between DELETE and
        INSERT rolls back cleanly — no data loss.
        """
        self._check_dims(embedding)
        serialized = _serialize_f32(embedding)
        try:
            await self._writer.execute("BEGIN")
            await self._writer.execute(
                "DELETE FROM item_vectors WHERE jellyfin_id = ?",
                (jellyfin_id,),
            )
            await self._writer.execute(
                "INSERT INTO item_vectors "
                "(jellyfin_id, embedding, content_hash, embedded_at, embedding_status) "
                "VALUES (?, ?, ?, ?, ?)",
                (jellyfin_id, serialized, content_hash, int(time.time()), COMPLETE),
            )
            await self._writer.commit()
        except Exception:
            await self._writer.rollback()
            raise

    async def upsert_many(self, items: list[tuple[str, list[float], str]]) -> None:
        """Batch insert or update vectors (DELETE + INSERT per item).

        Each tuple is ``(jellyfin_id, embedding, content_hash)``.
        All operations are wrapped in a single explicit transaction —
        if any item fails, the entire batch is rolled back.

        Empty input is a no-op (no transaction opened).
        """
        if not items:
            return

        now = int(time.time())
        for _, embedding, _ in items:
            self._check_dims(embedding)
        try:
            await self._writer.execute("BEGIN")
            for jellyfin_id, embedding, content_hash in items:
                serialized = _serialize_f32(embedding)
                await self._writer.execute(
                    "DELETE FROM item_vectors WHERE jellyfin_id = ?",
                    (jellyfin_id,),
                )
                await self._writer.execute(
                    "INSERT INTO item_vectors "
                    "(jellyfin_id, embedding, content_hash,"
                    " embedded_at, embedding_status) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (jellyfin_id, serialized, content_hash, now, COMPLETE),
                )
            await self._writer.commit()
        except Exception:
            await self._writer.rollback()
            raise

    async def get(self, jellyfin_id: str) -> VectorRecord | None:
        """Retrieve a single record's metadata (not the embedding)."""
        cursor = await self._reader.execute(
            "SELECT jellyfin_id, content_hash, embedded_at, embedding_status "
            "FROM item_vectors WHERE jellyfin_id = ?",
            (jellyfin_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return VectorRecord(
            jellyfin_id=row[0],
            content_hash=row[1],
            embedded_at=row[2],
            embedding_status=row[3],
        )

    async def get_many(self, ids: list[str]) -> list[VectorRecord]:
        """Retrieve multiple records by jellyfin IDs. Missing IDs are omitted."""
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        cursor = await self._reader.execute(
            "SELECT jellyfin_id, content_hash, embedded_at, embedding_status "
            f"FROM item_vectors WHERE jellyfin_id IN ({placeholders})",
            ids,
        )
        rows = await cursor.fetchall()
        return [
            VectorRecord(
                jellyfin_id=row[0],
                content_hash=row[1],
                embedded_at=row[2],
                embedding_status=row[3],
            )
            for row in rows
        ]

    async def delete(self, jellyfin_id: str) -> None:
        """Remove a single vector by jellyfin ID."""
        await self._writer.execute(
            "DELETE FROM item_vectors WHERE jellyfin_id = ?",
            (jellyfin_id,),
        )
        await self._writer.commit()

    async def delete_many(self, ids: list[str]) -> None:
        """Remove multiple vectors in a single transaction."""
        if not ids:
            return
        placeholders = ",".join("?" for _ in ids)
        await self._writer.execute(
            f"DELETE FROM item_vectors WHERE jellyfin_id IN ({placeholders})",
            ids,
        )
        await self._writer.commit()

    async def search(
        self, query_embedding: list[float], limit: int = 20
    ) -> list[SearchResult]:
        """Cosine similarity search, returning top-N results.

        Returns results ordered by similarity (highest first).
        The ``score`` field is ``1 - cosine_distance`` so that
        higher values indicate greater similarity.
        """
        self._check_dims(query_embedding)
        serialized = _serialize_f32(query_embedding)
        cursor = await self._reader.execute(
            "SELECT jellyfin_id, distance, content_hash "
            "FROM item_vectors "
            "WHERE embedding MATCH ? AND k = ? "
            "ORDER BY distance",
            (serialized, limit),
        )
        rows = await cursor.fetchall()
        return [
            SearchResult(
                jellyfin_id=row[0],
                score=max(0.0, min(1.0, 1.0 - row[1])),
                content_hash=row[2],
            )
            for row in rows
        ]

    async def count(self) -> int:
        """Return total number of stored vectors."""
        cursor = await self._reader.execute("SELECT COUNT(*) FROM item_vectors")
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def get_embedding_status(self, jellyfin_id: str) -> str | None:
        """Return the embedding status for an item, or None if not found."""
        cursor = await self._reader.execute(
            "SELECT embedding_status FROM item_vectors WHERE jellyfin_id = ?",
            (jellyfin_id,),
        )
        row = await cursor.fetchone()
        return row[0] if row else None

    async def set_embedding_status(self, jellyfin_id: str, status: str) -> None:
        """Update the embedding status for an item.

        Raises ValueError for invalid status strings.
        Raises KeyError if no vector record exists for the given jellyfin_id.
        """
        if status not in VALID_STATUSES:
            msg = (
                f"Invalid embedding status '{status}'. "
                f"Must be one of: {', '.join(sorted(VALID_STATUSES))}"
            )
            raise ValueError(msg)
        cursor = await self._writer.execute(
            "UPDATE item_vectors SET embedding_status = ? WHERE jellyfin_id = ?",
            (status, jellyfin_id),
        )
        if cursor.rowcount == 0:
            msg = f"No vector record for jellyfin_id={jellyfin_id}"
            raise KeyError(msg)
        await self._writer.commit()

    async def get_template_version(self) -> int | None:
        """Read the stored template version from _vec_meta.

        Returns the version as an int, or None if no template_version
        has been stored yet (first run / pre-Spec-10 database).
        """
        cursor = await self._reader.execute(
            "SELECT value FROM _vec_meta WHERE key = ?",
            ("template_version",),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return int(row[0])

    async def set_template_version(self, version: int) -> None:
        """Store (or update) the template version in _vec_meta."""
        await self._writer.execute(
            "INSERT INTO _vec_meta (key, value) VALUES ('template_version', ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(version),),
        )
        await self._writer.commit()

    async def close(self) -> None:
        """Close both connections. Safe to call multiple times."""
        if self._writer_db:
            await self._writer_db.close()
            self._writer_db = None
        if self._reader_db:
            await self._reader_db.close()
            self._reader_db = None
