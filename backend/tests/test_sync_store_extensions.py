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
