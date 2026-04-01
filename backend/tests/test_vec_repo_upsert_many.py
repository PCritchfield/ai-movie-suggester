# backend/tests/test_vec_repo_upsert_many.py
"""Unit tests for SqliteVecRepository.upsert_many() (real SQLite-vec)."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import pytest

from app.vectors.models import COMPLETE
from app.vectors.repository import SqliteVecRepository

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


class TestUpsertManyBasic:
    """Basic upsert_many() behaviour."""

    async def test_batch_upsert_stores_all_items(
        self, vec_repo: SqliteVecRepository
    ) -> None:
        """Batch upsert of 5 items: all stored, count() returns 5."""
        items = [
            (f"item-{i}", _make_embedding(float(i)), f"hash-{i}") for i in range(5)
        ]
        await vec_repo.upsert_many(items)
        assert await vec_repo.count() == 5

    async def test_batch_upsert_records_retrievable(
        self, vec_repo: SqliteVecRepository
    ) -> None:
        """Each item from a batch upsert is individually retrievable."""
        items = [
            ("movie-a", _make_embedding(1.0), "hash-a"),
            ("movie-b", _make_embedding(2.0), "hash-b"),
            ("movie-c", _make_embedding(3.0), "hash-c"),
        ]
        await vec_repo.upsert_many(items)

        for jid, _, chash in items:
            record = await vec_repo.get(jid)
            assert record is not None
            assert record.jellyfin_id == jid
            assert record.content_hash == chash
            assert record.embedding_status == COMPLETE

    async def test_duplicate_ids_in_batch_last_wins(
        self, vec_repo: SqliteVecRepository
    ) -> None:
        """Duplicate IDs in the same batch: last write wins, no error."""
        items = [
            ("dup-id", _make_embedding(1.0), "hash-v1"),
            ("dup-id", _make_embedding(2.0), "hash-v2"),
        ]
        await vec_repo.upsert_many(items)
        assert await vec_repo.count() == 1

        record = await vec_repo.get("dup-id")
        assert record is not None
        assert record.content_hash == "hash-v2"

    async def test_upsert_many_overwrites_existing(
        self, vec_repo: SqliteVecRepository
    ) -> None:
        """upsert_many overwrites existing vectors for the same jellyfin_id."""
        # Pre-populate with single upsert
        await vec_repo.upsert("existing", _make_embedding(1.0), "hash-old")
        record_old = await vec_repo.get("existing")
        assert record_old is not None
        assert record_old.content_hash == "hash-old"

        # Overwrite via batch
        items = [("existing", _make_embedding(2.0), "hash-new")]
        await vec_repo.upsert_many(items)
        assert await vec_repo.count() == 1

        record_new = await vec_repo.get("existing")
        assert record_new is not None
        assert record_new.content_hash == "hash-new"


class TestUpsertManyEdgeCases:
    """Edge cases for upsert_many()."""

    async def test_empty_input_is_noop(self, vec_repo: SqliteVecRepository) -> None:
        """Empty input returns immediately without error."""
        await vec_repo.upsert_many([])
        assert await vec_repo.count() == 0

    async def test_content_hash_set_correctly(
        self, vec_repo: SqliteVecRepository
    ) -> None:
        """Verify content_hash is set correctly on each record."""
        items = [
            ("item-x", _make_embedding(1.0), "sha256-abc"),
            ("item-y", _make_embedding(2.0), "sha256-def"),
        ]
        await vec_repo.upsert_many(items)

        record_x = await vec_repo.get("item-x")
        assert record_x is not None
        assert record_x.content_hash == "sha256-abc"

        record_y = await vec_repo.get("item-y")
        assert record_y is not None
        assert record_y.content_hash == "sha256-def"

    async def test_embedded_at_set_correctly(
        self, vec_repo: SqliteVecRepository
    ) -> None:
        """Verify embedded_at is set to a recent timestamp on each record."""
        before = int(time.time())
        items = [
            ("ts-1", _make_embedding(1.0), "hash-1"),
            ("ts-2", _make_embedding(2.0), "hash-2"),
        ]
        await vec_repo.upsert_many(items)
        after = int(time.time())

        for jid in ("ts-1", "ts-2"):
            record = await vec_repo.get(jid)
            assert record is not None
            assert before <= record.embedded_at <= after

    async def test_embedding_status_is_complete(
        self, vec_repo: SqliteVecRepository
    ) -> None:
        """All items from upsert_many have embedding_status = COMPLETE."""
        items = [
            (f"status-{i}", _make_embedding(float(i)), f"hash-{i}") for i in range(3)
        ]
        await vec_repo.upsert_many(items)

        for i in range(3):
            status = await vec_repo.get_embedding_status(f"status-{i}")
            assert status == COMPLETE


class TestUpsertManyValidation:
    """Dimension validation and no-partial-write behaviour for upsert_many()."""

    async def test_wrong_dimensions_rejected_before_transaction(
        self, vec_repo: SqliteVecRepository
    ) -> None:
        """Wrong-dimension vector raises ValueError before any DB writes."""
        # Pre-populate with one known good item
        await vec_repo.upsert("pre-existing", _make_embedding(0.5), "hash-pre")
        assert await vec_repo.count() == 1

        good_embedding = _make_embedding(1.0)
        wrong_dims_embedding = [1.0, 2.0]  # _DIMS is 4, so 2 is wrong

        items = [
            ("batch-ok-1", good_embedding, "hash-1"),
            ("batch-ok-2", good_embedding, "hash-2"),
            ("batch-bad", wrong_dims_embedding, "hash-bad"),
        ]

        with pytest.raises(ValueError, match="dimension mismatch"):
            await vec_repo.upsert_many(items)

        # Nothing written — pre-existing item still the only one
        assert await vec_repo.count() == 1
        assert await vec_repo.get("pre-existing") is not None
        assert await vec_repo.get("batch-ok-1") is None
