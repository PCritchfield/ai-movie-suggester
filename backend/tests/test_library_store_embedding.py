"""Unit tests for LibraryStore embedding queue methods (Spec 10, Task 1.0)."""

from __future__ import annotations

import pathlib
import time
from typing import TYPE_CHECKING

import pytest

from app.library.models import LibraryItemRow
from app.library.store import LibraryStore

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


def _now() -> int:
    return int(time.time())


def _make_item(
    jellyfin_id: str = "jf-1",
    title: str = "Alien",
    overview: str | None = "In space no one can hear you scream.",
    production_year: int | None = 1979,
    genres: list[str] | None = None,
    tags: list[str] | None = None,
    studios: list[str] | None = None,
    community_rating: float | None = 8.5,
    people: list[str] | None = None,
    content_hash: str = "abc123hash",
    synced_at: int | None = None,
) -> LibraryItemRow:
    """Helper to build LibraryItemRow with sensible defaults."""
    return LibraryItemRow(
        jellyfin_id=jellyfin_id,
        title=title,
        overview=overview,
        production_year=production_year,
        genres=genres if genres is not None else ["Sci-Fi", "Horror"],
        tags=tags if tags is not None else ["classic"],
        studios=studios if studios is not None else ["20th Century Fox"],
        community_rating=community_rating,
        people=people if people is not None else ["Sigourney Weaver", "Tom Skerritt"],
        content_hash=content_hash,
        synced_at=synced_at if synced_at is not None else _now(),
    )


@pytest.fixture
async def store(tmp_path: object) -> AsyncIterator[LibraryStore]:
    """Provide a fresh LibraryStore backed by a temp DB."""
    db_path = pathlib.Path(str(tmp_path)) / "test_library.db"
    s = LibraryStore(str(db_path))
    await s.init()
    yield s  # type: ignore[misc]
    await s.close()


async def _seed_items_and_enqueue(store: LibraryStore, ids: list[str]) -> None:
    """Insert library items and enqueue them for embedding."""
    items = [_make_item(jellyfin_id=jid, content_hash=f"hash-{jid}") for jid in ids]
    await store.upsert_many(items)
    await store.enqueue_for_embedding(ids)


class TestBusyTimeout:
    """Verify busy_timeout pragma is set."""

    async def test_busy_timeout_set(self, store: LibraryStore) -> None:
        cursor = await store._conn.execute("PRAGMA busy_timeout")
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == 5000


class TestLastAttemptedAtMigration:
    """Verify last_attempted_at column exists in embedding_queue."""

    async def test_last_attempted_at_column_exists(self, store: LibraryStore) -> None:
        cursor = await store._conn.execute("PRAGMA table_info(embedding_queue)")
        columns = {row[1] for row in await cursor.fetchall()}
        assert "last_attempted_at" in columns


class TestEnqueueOnConflictResetsLastAttemptedAt:
    """Verify enqueue_for_embedding ON CONFLICT resets last_attempted_at."""

    async def test_on_conflict_resets_last_attempted_at(
        self, store: LibraryStore
    ) -> None:
        await _seed_items_and_enqueue(store, ["jf-1"])

        # Simulate a failed attempt which sets last_attempted_at
        await store.mark_attempt("jf-1", "transient error")

        # Verify last_attempted_at is now set
        cursor = await store._conn.execute(
            "SELECT last_attempted_at FROM embedding_queue WHERE jellyfin_id = ?",
            ("jf-1",),
        )
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] is not None

        # Re-enqueue — should reset last_attempted_at to NULL
        await store.enqueue_for_embedding(["jf-1"])

        cursor = await store._conn.execute(
            "SELECT last_attempted_at, retry_count, status FROM embedding_queue"
            " WHERE jellyfin_id = ?",
            ("jf-1",),
        )
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] is None  # last_attempted_at reset to NULL
        assert row[1] == 0  # retry_count reset
        assert row[2] == "pending"  # status reset


class TestGetRetryableItems:
    """get_retryable_items() filtering and ordering."""

    async def test_returns_pending_items(self, store: LibraryStore) -> None:
        await _seed_items_and_enqueue(store, ["jf-1", "jf-2", "jf-3"])
        result = await store.get_retryable_items(
            cooldown_seconds=60, max_retries=3, batch_size=10
        )
        assert len(result) == 3
        ids = [r[0] for r in result]
        assert set(ids) == {"jf-1", "jf-2", "jf-3"}

    async def test_skips_items_within_cooldown(self, store: LibraryStore) -> None:
        await _seed_items_and_enqueue(store, ["jf-1", "jf-2"])

        # Mark jf-1 as attempted recently
        await store.mark_attempt("jf-1", "some error")

        # With a large cooldown, jf-1 should be skipped
        result = await store.get_retryable_items(
            cooldown_seconds=3600, max_retries=3, batch_size=10
        )
        ids = [r[0] for r in result]
        assert "jf-1" not in ids
        assert "jf-2" in ids

    async def test_includes_items_past_cooldown(self, store: LibraryStore) -> None:
        await _seed_items_and_enqueue(store, ["jf-1"])

        # Set last_attempted_at to a time well in the past
        old_time = int(time.time()) - 7200
        await store._conn.execute(
            "UPDATE embedding_queue SET last_attempted_at = ?, retry_count = 1"
            " WHERE jellyfin_id = ?",
            (old_time, "jf-1"),
        )
        await store._conn.commit()

        result = await store.get_retryable_items(
            cooldown_seconds=60, max_retries=3, batch_size=10
        )
        assert len(result) == 1
        assert result[0] == ("jf-1", 1)

    async def test_skips_items_exceeding_max_retries(self, store: LibraryStore) -> None:
        await _seed_items_and_enqueue(store, ["jf-1", "jf-2"])

        # Set jf-1 retry_count above max_retries
        await store._conn.execute(
            "UPDATE embedding_queue SET retry_count = 5 WHERE jellyfin_id = ?",
            ("jf-1",),
        )
        await store._conn.commit()

        result = await store.get_retryable_items(
            cooldown_seconds=60, max_retries=3, batch_size=10
        )
        ids = [r[0] for r in result]
        assert "jf-1" not in ids
        assert "jf-2" in ids

    async def test_respects_batch_size(self, store: LibraryStore) -> None:
        await _seed_items_and_enqueue(store, [f"jf-{i}" for i in range(10)])
        result = await store.get_retryable_items(
            cooldown_seconds=60, max_retries=3, batch_size=3
        )
        assert len(result) == 3


class TestClaimBatch:
    """claim_batch() status transitions."""

    async def test_transitions_pending_to_processing(self, store: LibraryStore) -> None:
        await _seed_items_and_enqueue(store, ["jf-1", "jf-2"])
        claimed = await store.claim_batch(["jf-1", "jf-2"])
        assert claimed == 2

        cursor = await store._conn.execute(
            "SELECT status FROM embedding_queue WHERE jellyfin_id = ?",
            ("jf-1",),
        )
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == "processing"

    async def test_returns_zero_for_non_pending(self, store: LibraryStore) -> None:
        await _seed_items_and_enqueue(store, ["jf-1"])

        # Claim first
        await store.claim_batch(["jf-1"])

        # Try to claim again — already 'processing'
        claimed = await store.claim_batch(["jf-1"])
        assert claimed == 0

    async def test_empty_ids_returns_zero(self, store: LibraryStore) -> None:
        claimed = await store.claim_batch([])
        assert claimed == 0


class TestMarkEmbedded:
    """mark_embedded() single item deletion."""

    async def test_deletes_queue_row(self, store: LibraryStore) -> None:
        await _seed_items_and_enqueue(store, ["jf-1"])
        await store.mark_embedded("jf-1")

        cursor = await store._conn.execute(
            "SELECT COUNT(*) FROM embedding_queue WHERE jellyfin_id = ?",
            ("jf-1",),
        )
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == 0


class TestMarkEmbeddedMany:
    """mark_embedded_many() batch deletion."""

    async def test_deletes_multiple_rows(self, store: LibraryStore) -> None:
        await _seed_items_and_enqueue(store, ["jf-1", "jf-2", "jf-3"])
        deleted = await store.mark_embedded_many(["jf-1", "jf-3"])
        assert deleted == 2

        # jf-2 should still be in queue
        cursor = await store._conn.execute(
            "SELECT COUNT(*) FROM embedding_queue WHERE jellyfin_id = 'jf-2'"
        )
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == 1

    async def test_empty_list_returns_zero(self, store: LibraryStore) -> None:
        deleted = await store.mark_embedded_many([])
        assert deleted == 0


class TestMarkAttempt:
    """mark_attempt() retry tracking."""

    async def test_increments_retry_and_sets_error(self, store: LibraryStore) -> None:
        await _seed_items_and_enqueue(store, ["jf-1"])
        await store.mark_attempt("jf-1", "timeout connecting to Ollama")

        cursor = await store._conn.execute(
            "SELECT status, retry_count, error_message, last_attempted_at"
            " FROM embedding_queue WHERE jellyfin_id = ?",
            ("jf-1",),
        )
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == "pending"
        assert row[1] == 1
        assert row[2] == "timeout connecting to Ollama"
        assert row[3] is not None  # last_attempted_at set

    async def test_multiple_attempts_increment(self, store: LibraryStore) -> None:
        await _seed_items_and_enqueue(store, ["jf-1"])
        await store.mark_attempt("jf-1", "error 1")
        await store.mark_attempt("jf-1", "error 2")
        await store.mark_attempt("jf-1", "error 3")

        cursor = await store._conn.execute(
            "SELECT retry_count, error_message FROM embedding_queue"
            " WHERE jellyfin_id = ?",
            ("jf-1",),
        )
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == 3
        assert row[1] == "error 3"


class TestMarkFailedPermanent:
    """mark_failed_permanent() terminal status."""

    async def test_sets_status_to_failed(self, store: LibraryStore) -> None:
        await _seed_items_and_enqueue(store, ["jf-1"])
        await store.mark_failed_permanent("jf-1", "unsupported media type")

        cursor = await store._conn.execute(
            "SELECT status, error_message, last_attempted_at"
            " FROM embedding_queue WHERE jellyfin_id = ?",
            ("jf-1",),
        )
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == "failed"
        assert row[1] == "unsupported media type"
        assert row[2] is not None


class TestResetStaleProcessing:
    """reset_stale_processing() crash recovery."""

    async def test_resets_processing_to_pending(self, store: LibraryStore) -> None:
        await _seed_items_and_enqueue(store, ["jf-1", "jf-2"])
        await store.claim_batch(["jf-1", "jf-2"])

        reset = await store.reset_stale_processing()
        assert reset == 2

        cursor = await store._conn.execute(
            "SELECT status FROM embedding_queue WHERE jellyfin_id = ?",
            ("jf-1",),
        )
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == "pending"

    async def test_does_not_affect_pending_items(self, store: LibraryStore) -> None:
        await _seed_items_and_enqueue(store, ["jf-1"])
        reset = await store.reset_stale_processing()
        assert reset == 0

        # Item is still pending
        cursor = await store._conn.execute(
            "SELECT status FROM embedding_queue WHERE jellyfin_id = ?",
            ("jf-1",),
        )
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == "pending"

    async def test_does_not_affect_failed_items(self, store: LibraryStore) -> None:
        await _seed_items_and_enqueue(store, ["jf-1"])
        await store.mark_failed_permanent("jf-1", "permanent error")

        reset = await store.reset_stale_processing()
        assert reset == 0

        cursor = await store._conn.execute(
            "SELECT status FROM embedding_queue WHERE jellyfin_id = ?",
            ("jf-1",),
        )
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == "failed"


class TestGetFailedItems:
    """get_failed_items() reporting."""

    async def test_returns_failed_item_details(self, store: LibraryStore) -> None:
        await _seed_items_and_enqueue(store, ["jf-1", "jf-2"])
        await store.mark_failed_permanent("jf-1", "bad data")

        failed = await store.get_failed_items()
        assert len(failed) == 1
        assert failed[0]["jellyfin_id"] == "jf-1"
        assert failed[0]["error_message"] == "bad data"
        assert failed[0]["retry_count"] == 0
        assert failed[0]["last_attempted_at"] is not None

    async def test_empty_when_no_failures(self, store: LibraryStore) -> None:
        await _seed_items_and_enqueue(store, ["jf-1"])
        failed = await store.get_failed_items()
        assert failed == []


class TestGetQueueCounts:
    """get_queue_counts() aggregation."""

    async def test_correct_breakdown(self, store: LibraryStore) -> None:
        await _seed_items_and_enqueue(store, ["jf-1", "jf-2", "jf-3", "jf-4", "jf-5"])
        # jf-1, jf-2 → processing
        await store.claim_batch(["jf-1", "jf-2"])
        # jf-3 → failed
        await store.mark_failed_permanent("jf-3", "bad data")
        # jf-4, jf-5 remain pending

        counts = await store.get_queue_counts()
        assert counts == {"pending": 2, "processing": 2, "failed": 1}

    async def test_empty_queue(self, store: LibraryStore) -> None:
        counts = await store.get_queue_counts()
        assert counts == {"pending": 0, "processing": 0, "failed": 0}
