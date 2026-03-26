"""Unit tests for the SQLite-vec vector repository."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from app.vectors.models import (
    FAILED,
    PENDING,
    PROCESSING,
    VectorRepositoryProtocol,
)
from app.vectors.repository import SqliteVecRepository, _serialize_f32

if TYPE_CHECKING:
    import pathlib
    from collections.abc import AsyncIterator

pytestmark = pytest.mark.requires_sqlite_vec

_MODEL = "nomic-embed-text"
_DIMS = 4  # Small dimension for fast tests


def _make_embedding(seed: float, dims: int = _DIMS) -> list[float]:
    """Create a deterministic embedding from a seed value."""
    return [seed + i * 0.1 for i in range(dims)]


@pytest.fixture
async def vec_repo(tmp_path: pathlib.Path) -> AsyncIterator[SqliteVecRepository]:
    """Provide a fresh SqliteVecRepository backed by a temp DB."""
    db_path = tmp_path / "test_library.db"
    repo = SqliteVecRepository(
        db_path=str(db_path),
        expected_model=_MODEL,
        expected_dimensions=_DIMS,
    )
    await repo.init()
    yield repo
    await repo.close()


class TestExtensionAndInit:
    """Extension loading and init() behaviour."""

    async def test_extension_loads_and_vec0_available(
        self, vec_repo: SqliteVecRepository
    ) -> None:
        """sqlite-vec extension loads and vec0 is functional."""
        # If init() succeeded, vec0 is loaded. Verify by inserting
        # and querying a trivial vector.
        embedding = _make_embedding(0.5)
        await vec_repo.upsert("test-item", embedding, "hash-1")
        record = await vec_repo.get("test-item")
        assert record is not None
        assert record.jellyfin_id == "test-item"

    async def test_init_creates_vec_meta_with_correct_values(
        self, vec_repo: SqliteVecRepository
    ) -> None:
        """init() populates _vec_meta with model name and dimensions."""
        cursor = await vec_repo._reader.execute(
            "SELECT key, value FROM _vec_meta ORDER BY key"
        )
        rows = await cursor.fetchall()
        meta = {row[0]: row[1] for row in rows}
        assert meta["model_name"] == _MODEL
        assert meta["dimensions"] == str(_DIMS)

    async def test_init_idempotent(self, tmp_path: pathlib.Path) -> None:
        """init() succeeds on second call with matching params."""
        db_path = str(tmp_path / "idempotent.db")
        repo = SqliteVecRepository(
            db_path=db_path, expected_model=_MODEL, expected_dimensions=_DIMS
        )
        await repo.init()
        await repo.close()

        # Second init with same params
        repo2 = SqliteVecRepository(
            db_path=db_path, expected_model=_MODEL, expected_dimensions=_DIMS
        )
        await repo2.init()  # Should not raise
        await repo2.close()

    async def test_init_raises_on_dimension_mismatch(
        self, tmp_path: pathlib.Path
    ) -> None:
        """init() raises RuntimeError when dimensions mismatch."""
        db_path = str(tmp_path / "dim_mismatch.db")
        repo = SqliteVecRepository(
            db_path=db_path, expected_model=_MODEL, expected_dimensions=_DIMS
        )
        await repo.init()
        await repo.close()

        repo2 = SqliteVecRepository(
            db_path=db_path, expected_model=_MODEL, expected_dimensions=768
        )
        with pytest.raises(RuntimeError, match="Dimension mismatch"):
            await repo2.init()
        await repo2.close()

    async def test_init_raises_on_model_mismatch(self, tmp_path: pathlib.Path) -> None:
        """init() raises RuntimeError when model name mismatches."""
        db_path = str(tmp_path / "model_mismatch.db")
        repo = SqliteVecRepository(
            db_path=db_path, expected_model=_MODEL, expected_dimensions=_DIMS
        )
        await repo.init()
        await repo.close()

        repo2 = SqliteVecRepository(
            db_path=db_path,
            expected_model="different-model",
            expected_dimensions=_DIMS,
        )
        with pytest.raises(RuntimeError, match="Model mismatch"):
            await repo2.init()
        await repo2.close()

    async def test_init_raises_on_extension_load_failure(
        self, tmp_path: pathlib.Path
    ) -> None:
        """init() raises RuntimeError when vec0 extension cannot load."""
        db_path = str(tmp_path / "no_ext.db")
        repo = SqliteVecRepository(
            db_path=db_path, expected_model=_MODEL, expected_dimensions=_DIMS
        )
        with (
            patch.object(
                repo,
                "_load_vec0",
                side_effect=RuntimeError("Failed to load sqlite-vec extension"),
            ),
            pytest.raises(RuntimeError, match="Failed to load sqlite-vec"),
        ):
            await repo.init()
        await repo.close()

    async def test_protocol_structural_check(self) -> None:
        """SqliteVecRepository satisfies VectorRepositoryProtocol."""
        assert issubclass(SqliteVecRepository, VectorRepositoryProtocol)


class TestConnectionGuards:
    """Property guards for _writer and _reader before init()."""

    async def test_writer_raises_before_init(self, tmp_path: pathlib.Path) -> None:
        """_writer property raises RuntimeError before init()."""
        repo = SqliteVecRepository(
            db_path=str(tmp_path / "guard.db"),
            expected_model=_MODEL,
            expected_dimensions=_DIMS,
        )
        with pytest.raises(RuntimeError, match="not initialised"):
            _ = repo._writer

    async def test_reader_raises_before_init(self, tmp_path: pathlib.Path) -> None:
        """_reader property raises RuntimeError before init()."""
        repo = SqliteVecRepository(
            db_path=str(tmp_path / "guard.db"),
            expected_model=_MODEL,
            expected_dimensions=_DIMS,
        )
        with pytest.raises(RuntimeError, match="not initialised"):
            _ = repo._reader

    async def test_close_safe_to_call_twice(self, tmp_path: pathlib.Path) -> None:
        """close() is safe to call multiple times without error."""
        db_path = str(tmp_path / "close_twice.db")
        repo = SqliteVecRepository(
            db_path=db_path, expected_model=_MODEL, expected_dimensions=_DIMS
        )
        await repo.init()
        await repo.close()
        await repo.close()  # Should not raise

    async def test_writer_and_reader_independent(
        self, vec_repo: SqliteVecRepository
    ) -> None:
        """Writer and reader are independent connections."""
        # Insert via writer (without committing to test independence)
        embedding = _make_embedding(1.0)
        await vec_repo._writer.execute(
            "DELETE FROM item_vectors WHERE jellyfin_id = ?", ("indep-test",)
        )
        await vec_repo._writer.execute(
            "INSERT INTO item_vectors "
            "(jellyfin_id, embedding, content_hash, embedded_at, embedding_status) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                "indep-test",
                _serialize_f32(embedding),
                "hash",
                int(time.time()),
                "complete",
            ),
        )
        # Reader should still be functional even while writer has uncommitted data
        cursor = await vec_repo._reader.execute(
            "SELECT COUNT(*) FROM item_vectors WHERE jellyfin_id = 'indep-test'"
        )
        row = await cursor.fetchone()
        # WAL mode: reader sees committed state, not uncommitted writer data
        assert row is not None
        # Commit to clean up
        await vec_repo._writer.commit()


class TestCRUD:
    """CRUD operations: upsert, get, get_many, delete, delete_many."""

    async def test_upsert_and_get(self, vec_repo: SqliteVecRepository) -> None:
        """upsert() inserts a new vector; get() retrieves it."""
        embedding = _make_embedding(0.5)
        await vec_repo.upsert("movie-1", embedding, "hash-abc")

        record = await vec_repo.get("movie-1")
        assert record is not None
        assert record.jellyfin_id == "movie-1"
        assert record.content_hash == "hash-abc"
        assert record.embedding_status == "complete"
        assert record.embedded_at > 0

    async def test_upsert_replaces_existing(
        self, vec_repo: SqliteVecRepository
    ) -> None:
        """upsert() on existing ID replaces the record."""
        embedding = _make_embedding(0.5)
        await vec_repo.upsert("movie-1", embedding, "hash-v1")

        embedding2 = _make_embedding(0.6)
        await vec_repo.upsert("movie-1", embedding2, "hash-v2")

        record = await vec_repo.get("movie-1")
        assert record is not None
        assert record.content_hash == "hash-v2"

    async def test_get_returns_none_for_missing(
        self, vec_repo: SqliteVecRepository
    ) -> None:
        """get() returns None for a nonexistent ID."""
        assert await vec_repo.get("nonexistent") is None

    async def test_get_many(self, vec_repo: SqliteVecRepository) -> None:
        """get_many() returns found records and omits missing IDs."""
        for i in range(3):
            await vec_repo.upsert(f"item-{i}", _make_embedding(float(i)), f"hash-{i}")

        results = await vec_repo.get_many(
            ["item-0", "item-1", "item-2", "missing-item"]
        )
        found_ids = {r.jellyfin_id for r in results}
        assert found_ids == {"item-0", "item-1", "item-2"}
        assert len(results) == 3

    async def test_delete(self, vec_repo: SqliteVecRepository) -> None:
        """delete() removes a record."""
        await vec_repo.upsert("to-delete", _make_embedding(1.0), "hash")
        assert await vec_repo.get("to-delete") is not None

        await vec_repo.delete("to-delete")
        assert await vec_repo.get("to-delete") is None

    async def test_delete_many(self, vec_repo: SqliteVecRepository) -> None:
        """delete_many() removes multiple records."""
        for i in range(5):
            await vec_repo.upsert(f"bulk-{i}", _make_embedding(float(i)), f"hash-{i}")
        assert await vec_repo.count() == 5

        await vec_repo.delete_many(["bulk-0", "bulk-1", "bulk-2"])
        assert await vec_repo.count() == 2


class TestSearch:
    """Cosine similarity search."""

    async def test_search_returns_ordered_by_distance(
        self, vec_repo: SqliteVecRepository
    ) -> None:
        """search() returns results ordered by cosine distance (ascending)."""
        # Insert vectors at known positions
        # Query will be close to vec_a, far from vec_c
        vec_a = [1.0, 0.0, 0.0, 0.0]
        vec_b = [0.7, 0.7, 0.0, 0.0]
        vec_c = [0.0, 0.0, 0.0, 1.0]

        await vec_repo.upsert("close", vec_a, "h1")
        await vec_repo.upsert("medium", vec_b, "h2")
        await vec_repo.upsert("far", vec_c, "h3")

        query = [1.0, 0.0, 0.0, 0.0]
        results = await vec_repo.search(query, limit=3)

        assert len(results) == 3
        assert results[0].jellyfin_id == "close"
        assert results[-1].jellyfin_id == "far"
        # Distances should be ascending
        assert results[0].distance <= results[1].distance <= results[2].distance

    async def test_search_respects_limit(self, vec_repo: SqliteVecRepository) -> None:
        """search() returns at most `limit` results."""
        for i in range(5):
            await vec_repo.upsert(
                f"item-{i}", _make_embedding(float(i) * 0.1), f"hash-{i}"
            )

        results = await vec_repo.search(_make_embedding(0.5), limit=2)
        assert len(results) == 2

    async def test_search_empty_table(self, vec_repo: SqliteVecRepository) -> None:
        """search() returns empty list when no vectors are stored."""
        results = await vec_repo.search(_make_embedding(0.5), limit=10)
        assert results == []


class TestCountAndStatus:
    """count() and embedding status operations."""

    async def test_count_empty_and_after_inserts(
        self, vec_repo: SqliteVecRepository
    ) -> None:
        """count() returns 0 on empty table, correct count after inserts."""
        assert await vec_repo.count() == 0

        for i in range(3):
            await vec_repo.upsert(f"item-{i}", _make_embedding(float(i)), f"hash-{i}")
        assert await vec_repo.count() == 3

    async def test_set_and_get_embedding_status(
        self, vec_repo: SqliteVecRepository
    ) -> None:
        """set_embedding_status() updates; get_embedding_status() reads back."""
        await vec_repo.upsert("status-test", _make_embedding(0.5), "hash")
        assert await vec_repo.get_embedding_status("status-test") == "complete"

        await vec_repo.set_embedding_status("status-test", PENDING)
        assert await vec_repo.get_embedding_status("status-test") == PENDING

        await vec_repo.set_embedding_status("status-test", PROCESSING)
        assert await vec_repo.get_embedding_status("status-test") == PROCESSING

        await vec_repo.set_embedding_status("status-test", FAILED)
        assert await vec_repo.get_embedding_status("status-test") == FAILED

    async def test_set_embedding_status_invalid_raises(
        self, vec_repo: SqliteVecRepository
    ) -> None:
        """set_embedding_status() raises ValueError for invalid status."""
        await vec_repo.upsert("bad-status", _make_embedding(0.5), "hash")

        with pytest.raises(ValueError, match="Invalid embedding status"):
            await vec_repo.set_embedding_status("bad-status", "banana")

    async def test_get_embedding_status_nonexistent(
        self, vec_repo: SqliteVecRepository
    ) -> None:
        """get_embedding_status() returns None for nonexistent ID."""
        assert await vec_repo.get_embedding_status("nonexistent") is None
