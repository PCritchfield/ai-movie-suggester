"""Tests for LibraryStore schema extensions (Spec 08).

Covers new tables (embedding_queue, sync_runs), the deleted_at column,
and all new store methods added for the sync engine.
"""

from __future__ import annotations

import os
import tempfile

import pytest

from app.library.models import LibraryItemRow
from app.library.store import LibraryStore
from app.sync.models import SyncResult


@pytest.fixture
async def store():
    with tempfile.TemporaryDirectory() as tmp:
        s = LibraryStore(os.path.join(tmp, "test.db"))
        await s.init()
        yield s
        await s.close()


def _make_item(jid: str, title: str = "Test") -> LibraryItemRow:
    return LibraryItemRow(
        jellyfin_id=jid,
        title=title,
        overview=None,
        production_year=2020,
        genres=[],
        tags=[],
        studios=[],
        community_rating=None,
        people=[],
        content_hash=f"hash-{jid}",
        synced_at=1000000,
    )


# --- Schema existence tests (Task 1.0) ---


@pytest.mark.asyncio
async def test_embedding_queue_table_exists(store: LibraryStore) -> None:
    """embedding_queue table should exist after init."""
    cursor = await store._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='embedding_queue'"
    )
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == "embedding_queue"


@pytest.mark.asyncio
async def test_embedding_queue_index_exists(store: LibraryStore) -> None:
    """idx_embedding_queue_status_enqueued index should exist after init."""
    cursor = await store._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index'"
        " AND name='idx_embedding_queue_status_enqueued'"
    )
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == "idx_embedding_queue_status_enqueued"


@pytest.mark.asyncio
async def test_sync_runs_table_exists(store: LibraryStore) -> None:
    """sync_runs table should exist after init."""
    cursor = await store._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='sync_runs'"
    )
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == "sync_runs"


@pytest.mark.asyncio
async def test_deleted_at_column_defaults_to_null(store: LibraryStore) -> None:
    """deleted_at column should default to NULL on insert via upsert_many."""
    item = _make_item("item-1", "Test Movie")
    await store.upsert_many([item])

    cursor = await store._conn.execute(
        "SELECT deleted_at FROM library_items WHERE jellyfin_id = ?",
        ("item-1",),
    )
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] is None


# --- get_all_ids tests (Task 2.0) ---


@pytest.mark.asyncio
async def test_get_all_ids_returns_active_ids(store: LibraryStore) -> None:
    """get_all_ids returns only non-deleted item IDs."""
    items = [_make_item(f"id-{i}") for i in range(5)]
    await store.upsert_many(items)
    result = await store.get_all_ids()
    assert result == {f"id-{i}" for i in range(5)}


@pytest.mark.asyncio
async def test_get_all_ids_excludes_soft_deleted(store: LibraryStore) -> None:
    """get_all_ids excludes soft-deleted items."""
    items = [_make_item(f"id-{i}") for i in range(3)]
    await store.upsert_many(items)
    await store.soft_delete_many(["id-1"])
    result = await store.get_all_ids()
    assert result == {"id-0", "id-2"}


@pytest.mark.asyncio
async def test_get_all_ids_empty_store(store: LibraryStore) -> None:
    """get_all_ids returns empty set for empty store."""
    result = await store.get_all_ids()
    assert result == set()


# --- soft_delete_many tests ---


@pytest.mark.asyncio
async def test_soft_delete_many_sets_deleted_at(store: LibraryStore) -> None:
    """soft_delete_many sets deleted_at timestamp on target items."""
    items = [_make_item(f"id-{i}") for i in range(3)]
    await store.upsert_many(items)
    count = await store.soft_delete_many(["id-0", "id-2"])
    assert count == 2

    cursor = await store._conn.execute(
        "SELECT deleted_at FROM library_items WHERE jellyfin_id = ?",
        ("id-0",),
    )
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] is not None  # deleted_at should be set

    cursor = await store._conn.execute(
        "SELECT deleted_at FROM library_items WHERE jellyfin_id = ?",
        ("id-1",),
    )
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] is None  # id-1 should NOT be deleted


@pytest.mark.asyncio
async def test_soft_delete_many_nonexistent_ids(store: LibraryStore) -> None:
    """soft_delete_many returns 0 for non-existent IDs."""
    count = await store.soft_delete_many(["no-such-id"])
    assert count == 0


@pytest.mark.asyncio
async def test_soft_delete_many_empty_list(store: LibraryStore) -> None:
    """soft_delete_many returns 0 for empty list."""
    count = await store.soft_delete_many([])
    assert count == 0


@pytest.mark.asyncio
async def test_soft_delete_many_chunking(store: LibraryStore) -> None:
    """soft_delete_many handles >500 IDs by chunking."""
    items = [_make_item(f"id-{i:04d}") for i in range(600)]
    await store.upsert_many(items)
    count = await store.soft_delete_many([f"id-{i:04d}" for i in range(600)])
    assert count == 600

    # All should be soft-deleted
    active = await store.get_all_ids()
    assert len(active) == 0


# --- hard_delete_many tests ---


@pytest.mark.asyncio
async def test_hard_delete_many_removes_rows(store: LibraryStore) -> None:
    """hard_delete_many permanently removes rows."""
    items = [_make_item(f"id-{i}") for i in range(3)]
    await store.upsert_many(items)
    count = await store.hard_delete_many(["id-0", "id-2"])
    assert count == 2

    # Should only have id-1 left
    cursor = await store._conn.execute("SELECT COUNT(*) FROM library_items")
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == 1


@pytest.mark.asyncio
async def test_hard_delete_many_nonexistent_ids(store: LibraryStore) -> None:
    """hard_delete_many returns 0 for non-existent IDs."""
    count = await store.hard_delete_many(["no-such-id"])
    assert count == 0


@pytest.mark.asyncio
async def test_hard_delete_many_empty_list(store: LibraryStore) -> None:
    """hard_delete_many returns 0 for empty list."""
    count = await store.hard_delete_many([])
    assert count == 0


@pytest.mark.asyncio
async def test_hard_delete_many_chunking(store: LibraryStore) -> None:
    """hard_delete_many handles >500 IDs by chunking."""
    items = [_make_item(f"id-{i:04d}") for i in range(600)]
    await store.upsert_many(items)
    count = await store.hard_delete_many([f"id-{i:04d}" for i in range(600)])
    assert count == 600

    cursor = await store._conn.execute("SELECT COUNT(*) FROM library_items")
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == 0


# --- get_tombstoned_ids tests ---


@pytest.mark.asyncio
async def test_get_tombstoned_ids_returns_old_deletions(
    store: LibraryStore,
) -> None:
    """get_tombstoned_ids returns items deleted before the threshold."""
    items = [_make_item(f"id-{i}") for i in range(3)]
    await store.upsert_many(items)

    # Soft-delete two items, then manually backdate one
    await store.soft_delete_many(["id-0", "id-1"])
    await store._conn.execute(
        "UPDATE library_items SET deleted_at = ? WHERE jellyfin_id = ?",
        (1000, "id-0"),
    )
    await store._conn.commit()

    # Threshold of 2000: id-0 (deleted_at=1000) should be returned
    result = await store.get_tombstoned_ids(older_than=2000)
    assert result == ["id-0"]


@pytest.mark.asyncio
async def test_get_tombstoned_ids_excludes_recent(store: LibraryStore) -> None:
    """get_tombstoned_ids excludes items deleted after the threshold."""
    items = [_make_item("id-0")]
    await store.upsert_many(items)
    await store.soft_delete_many(["id-0"])

    # Use a threshold in the past — nothing should be returned
    result = await store.get_tombstoned_ids(older_than=1)
    assert result == []


@pytest.mark.asyncio
async def test_get_tombstoned_ids_empty(store: LibraryStore) -> None:
    """get_tombstoned_ids returns empty list when no items are deleted."""
    result = await store.get_tombstoned_ids(older_than=999999999)
    assert result == []


# --- enqueue_for_embedding tests ---


@pytest.mark.asyncio
async def test_enqueue_for_embedding_inserts_pending(
    store: LibraryStore,
) -> None:
    """enqueue_for_embedding creates pending entries."""
    count = await store.enqueue_for_embedding(["id-1", "id-2"])
    assert count == 2

    pending = await store.count_pending_embeddings()
    assert pending == 2


@pytest.mark.asyncio
async def test_enqueue_for_embedding_conflict_resets_status(
    store: LibraryStore,
) -> None:
    """enqueue_for_embedding resets status on conflict."""
    await store.enqueue_for_embedding(["id-1"])

    # Manually mark as 'failed'
    await store._conn.execute(
        "UPDATE embedding_queue SET status = 'failed', retry_count = 3"
        " WHERE jellyfin_id = 'id-1'"
    )
    await store._conn.commit()

    # Re-enqueue should reset
    count = await store.enqueue_for_embedding(["id-1"])
    assert count == 1

    cursor = await store._conn.execute(
        "SELECT status, retry_count, error_message FROM embedding_queue"
        " WHERE jellyfin_id = 'id-1'"
    )
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == "pending"
    assert row[1] == 0
    assert row[2] is None


@pytest.mark.asyncio
async def test_enqueue_for_embedding_empty_list(store: LibraryStore) -> None:
    """enqueue_for_embedding returns 0 for empty list."""
    count = await store.enqueue_for_embedding([])
    assert count == 0


# --- count_pending_embeddings tests ---


@pytest.mark.asyncio
async def test_count_pending_embeddings_mixed_statuses(
    store: LibraryStore,
) -> None:
    """count_pending_embeddings only counts 'pending' status."""
    await store.enqueue_for_embedding(["id-1", "id-2", "id-3"])

    # Mark one as 'completed'
    await store._conn.execute(
        "UPDATE embedding_queue SET status = 'completed' WHERE jellyfin_id = 'id-2'"
    )
    await store._conn.commit()

    pending = await store.count_pending_embeddings()
    assert pending == 2


# --- save_sync_run + get_last_sync_run tests ---


@pytest.mark.asyncio
async def test_save_and_get_last_sync_run_roundtrip(
    store: LibraryStore,
) -> None:
    """save_sync_run + get_last_sync_run should round-trip correctly."""
    run = SyncResult(
        started_at=1000,
        completed_at=2000,
        status="completed",
        total_items=100,
        items_created=50,
        items_updated=30,
        items_deleted=5,
        items_unchanged=10,
        items_failed=5,
        error_message=None,
    )
    await store.save_sync_run(run)

    last = await store.get_last_sync_run()
    assert last is not None
    assert last.started_at == 1000
    assert last.completed_at == 2000
    assert last.status == "completed"
    assert last.total_items == 100
    assert last.items_created == 50
    assert last.items_updated == 30
    assert last.items_deleted == 5
    assert last.items_unchanged == 10
    assert last.items_failed == 5
    assert last.error_message is None


@pytest.mark.asyncio
async def test_get_last_sync_run_returns_most_recent(
    store: LibraryStore,
) -> None:
    """get_last_sync_run returns the run with the highest started_at."""
    run1 = SyncResult(
        started_at=1000,
        completed_at=1500,
        status="completed",
        total_items=10,
        items_created=10,
        items_updated=0,
        items_deleted=0,
        items_unchanged=0,
        items_failed=0,
    )
    run2 = SyncResult(
        started_at=2000,
        completed_at=2500,
        status="failed",
        total_items=20,
        items_created=5,
        items_updated=0,
        items_deleted=0,
        items_unchanged=0,
        items_failed=15,
        error_message="something broke",
    )
    await store.save_sync_run(run1)
    await store.save_sync_run(run2)

    last = await store.get_last_sync_run()
    assert last is not None
    assert last.started_at == 2000
    assert last.status == "failed"
    assert last.error_message == "something broke"


@pytest.mark.asyncio
async def test_get_last_sync_run_returns_none_when_empty(
    store: LibraryStore,
) -> None:
    """get_last_sync_run returns None when no runs exist."""
    last = await store.get_last_sync_run()
    assert last is None


# --- get_all_hashes filters soft-deleted (Task 1.0 update) ---


@pytest.mark.asyncio
async def test_get_all_hashes_excludes_soft_deleted(
    store: LibraryStore,
) -> None:
    """get_all_hashes should exclude soft-deleted items."""
    items = [_make_item(f"id-{i}") for i in range(3)]
    await store.upsert_many(items)
    await store.soft_delete_many(["id-1"])

    hashes = await store.get_all_hashes()
    assert "id-1" not in hashes
    assert len(hashes) == 2


# --- count filters soft-deleted (Task 1.0 update) ---


@pytest.mark.asyncio
async def test_count_excludes_soft_deleted(store: LibraryStore) -> None:
    """count should exclude soft-deleted items."""
    items = [_make_item(f"id-{i}") for i in range(4)]
    await store.upsert_many(items)
    await store.soft_delete_many(["id-0"])
    assert await store.count() == 3
