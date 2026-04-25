"""Tests for sync engine models, import paths, and SyncEngine (Spec 08)."""

from __future__ import annotations

import asyncio
import dataclasses
import tempfile
import unittest.mock
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.jellyfin.errors import JellyfinConnectionError
from app.jellyfin.models import LibraryItem, PaginatedItems
from app.library.hashing import compute_content_hash
from app.sync.engine import SyncEngine, to_library_row
from app.sync.models import (
    SYNC_STATUS_COMPLETED,
    SYNC_STATUS_FAILED,
    SyncAlreadyRunningError,
    SyncConfigError,
)


def test_sync_models_importable() -> None:
    """All sync models should be importable from app.sync.models."""
    from app.sync.models import (
        SyncAlreadyRunningError,
        SyncConfigError,
        SyncResult,
        SyncRunRow,
        SyncState,
    )

    # Verify dataclass fields
    result_fields = {f.name for f in dataclasses.fields(SyncResult)}
    assert "started_at" in result_fields
    assert "completed_at" in result_fields
    assert "status" in result_fields
    assert "total_items" in result_fields
    assert "items_created" in result_fields
    assert "items_updated" in result_fields
    assert "items_deleted" in result_fields
    assert "items_unchanged" in result_fields
    assert "items_failed" in result_fields
    assert "error_message" in result_fields

    row_fields = {f.name for f in dataclasses.fields(SyncRunRow)}
    assert "id" in row_fields
    assert "started_at" in row_fields
    assert "completed_at" in row_fields
    assert "status" in row_fields
    assert "error_message" in row_fields

    state_fields = {f.name for f in dataclasses.fields(SyncState)}
    assert "started_at" in state_fields
    assert "pages_processed" in state_fields
    assert "items_processed" in state_fields
    assert "items_created" in state_fields
    assert "items_updated" in state_fields
    assert "items_unchanged" in state_fields
    assert "items_failed" in state_fields

    # Verify exceptions are Exception subclasses
    assert issubclass(SyncAlreadyRunningError, Exception)
    assert issubclass(SyncConfigError, Exception)

    # Verify frozen/mutable
    result = SyncResult(
        started_at=1,
        completed_at=2,
        status="completed",
        total_items=10,
        items_created=5,
        items_updated=3,
        items_deleted=0,
        items_unchanged=2,
        items_failed=0,
    )
    assert result.error_message is None  # default

    state = SyncState(
        started_at=1,
        pages_processed=0,
        items_processed=0,
        items_created=0,
        items_updated=0,
        items_unchanged=0,
        items_failed=0,
    )
    state.pages_processed = 1  # mutable


def test_text_builder_same_object() -> None:
    """build_sections should be the same object from both import paths."""
    from app.library import text_builder as lib_tb
    from app.ollama import text_builder as ollama_tb

    assert lib_tb.build_sections is ollama_tb.build_sections
    assert lib_tb.TEMPLATE_VERSION is ollama_tb.TEMPLATE_VERSION


# ---------------------------------------------------------------------------
# Helpers for SyncEngine tests (Task 3.0 + Task 5.0)
# ---------------------------------------------------------------------------


def _make_library_item(
    item_id: str = "jf-001",
    name: str = "Test Movie",
    overview: str = "A test movie overview",
    genres: list[str] | None = None,
    production_year: int | None = 2024,
    people: list[dict[str, str]] | None = None,
    run_time_ticks: int | None = None,
) -> LibraryItem:
    """Create a LibraryItem for testing."""
    if genres is None:
        genres = ["Action", "Sci-Fi"]
    if people is None:
        people = [
            {"Name": "Actor One", "Type": "Actor"},
            {"Name": "Director One", "Type": "Director"},
        ]
    data: dict[str, object] = {
        "Id": item_id,
        "Name": name,
        "Type": "Movie",
        "Overview": overview,
        "Genres": genres,
        "ProductionYear": production_year,
        "Tags": [],
        "Studios": [],
        "CommunityRating": 7.5,
        "People": people,
    }
    if run_time_ticks is not None:
        data["RunTimeTicks"] = run_time_ticks
    return LibraryItem.model_validate(data)


def _make_paginated(
    items: list[LibraryItem], total_count: int | None = None
) -> PaginatedItems:
    """Wrap items in a PaginatedItems response."""
    total = total_count if total_count is not None else len(items)
    return PaginatedItems.model_validate(
        {
            "Items": [i.model_dump(by_alias=True) for i in items],
            "TotalRecordCount": total,
            "StartIndex": 0,
        }
    )


def _make_mock_settings(
    *,
    api_key: str = "test-api-key",
    admin_user_id: str = "admin-uid",
    page_size: int = 200,
    tombstone_ttl_days: int = 7,
    wal_threshold_mb: float = 50.0,
    library_db_path: str = "data/library.db",
) -> MagicMock:
    """Create a mock Settings with required sync fields."""
    settings = MagicMock()
    mock_secret: MagicMock = MagicMock()
    mock_secret.get_secret_value.return_value = api_key
    settings.jellyfin_api_key = mock_secret
    settings.jellyfin_admin_user_id = admin_user_id
    settings.library_sync_page_size = page_size
    settings.tombstone_ttl_days = tombstone_ttl_days
    settings.wal_checkpoint_threshold_mb = wal_threshold_mb
    settings.library_db_path = library_db_path
    return settings


def _make_mock_store() -> AsyncMock:
    """Create a mock LibraryStore with default return values."""
    store = AsyncMock()
    store.get_all_hashes.return_value = {}
    store.get_all_ids.return_value = set()
    store.upsert_many.return_value = MagicMock(created=0, updated=0, unchanged=0)
    store.enqueue_for_embedding.return_value = 0
    store.soft_delete_many.return_value = 0
    store.hard_delete_many.return_value = 0
    store.get_tombstoned_ids.return_value = []
    store.delete_from_embedding_queue.return_value = 0
    store.count.return_value = 0
    store.count_pending_embeddings.return_value = 0
    store.save_sync_run.return_value = None
    store.get_last_sync_run.return_value = None
    return store


async def _make_async_iter(
    pages: list[PaginatedItems],
):
    """Create an async iterator yielding pages."""
    for page in pages:
        yield page


def _make_mock_client(
    pages: list[PaginatedItems],
) -> MagicMock:
    """Create a mock JellyfinClient that yields the given pages."""
    client = MagicMock()

    def _get_all_items(*args, **kwargs):  # type: ignore[no-untyped-def]
        return _make_async_iter(pages)

    client.get_all_items = _get_all_items
    return client


# ---------------------------------------------------------------------------
# to_library_row — per-Type crew extraction
# ---------------------------------------------------------------------------


class TestToLibraryRowCrewExtraction:
    """Verify to_library_row extracts crew roles from Jellyfin's People array."""

    def test_extracts_actors_into_people(self) -> None:
        item = _make_library_item(
            people=[
                {"Name": "Sigourney Weaver", "Type": "Actor"},
                {"Name": "Ridley Scott", "Type": "Director"},
            ]
        )
        row = to_library_row(item)
        assert row.people == ["Sigourney Weaver"]

    def test_extracts_directors(self) -> None:
        item = _make_library_item(
            people=[
                {"Name": "Ridley Scott", "Type": "Director"},
                {"Name": "Sigourney Weaver", "Type": "Actor"},
            ]
        )
        row = to_library_row(item)
        assert row.directors == ["Ridley Scott"]

    def test_extracts_writers(self) -> None:
        item = _make_library_item(
            people=[
                {"Name": "Dan O'Bannon", "Type": "Writer"},
                {"Name": "Ronald Shusett", "Type": "Writer"},
            ]
        )
        row = to_library_row(item)
        assert row.writers == ["Dan O'Bannon", "Ronald Shusett"]

    def test_extracts_composers(self) -> None:
        item = _make_library_item(
            people=[
                {"Name": "Jerry Goldsmith", "Type": "Composer"},
            ]
        )
        row = to_library_row(item)
        assert row.composers == ["Jerry Goldsmith"]

    def test_unknown_types_discarded(self) -> None:
        """Types we don't bucket (e.g. Producer, GuestStar) don't land anywhere."""
        item = _make_library_item(
            people=[
                {"Name": "Some Producer", "Type": "Producer"},
                {"Name": "Guest Star", "Type": "GuestStar"},
            ]
        )
        row = to_library_row(item)
        assert row.people == []
        assert row.directors == []
        assert row.writers == []
        assert row.composers == []

    def test_empty_people_gives_empty_crew(self) -> None:
        item = _make_library_item(people=[])
        row = to_library_row(item)
        assert row.people == []
        assert row.directors == []
        assert row.writers == []
        assert row.composers == []

    def test_empty_name_excluded(self) -> None:
        """Entries with missing/empty Name are discarded from every bucket."""
        item = _make_library_item(
            people=[
                {"Name": "", "Type": "Actor"},
                {"Type": "Director"},
                {"Name": "Real Person", "Type": "Actor"},
            ]
        )
        row = to_library_row(item)
        assert row.people == ["Real Person"]
        assert row.directors == []

    def test_row_content_hash_matches_compute_content_hash(self) -> None:
        """to_library_row must compute content_hash via compute_content_hash."""
        item = _make_library_item()
        row = to_library_row(item)
        assert row.content_hash == compute_content_hash(row)


# ---------------------------------------------------------------------------
# Task 3.0 tests — SyncEngine core
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_basic_two_pages() -> None:
    """Basic sync: 2 pages of items are upserted and enqueued."""
    items_p1 = [_make_library_item("jf-001", "Movie One")]
    items_p2 = [_make_library_item("jf-002", "Movie Two")]
    page1 = _make_paginated(items_p1, total_count=2)
    page2 = _make_paginated(items_p2, total_count=2)

    store = _make_mock_store()
    client = _make_mock_client([page1, page2])
    settings = _make_mock_settings()

    engine = SyncEngine(store, client, settings)
    result = await engine.run_sync()

    assert result.status == SYNC_STATUS_COMPLETED
    assert result.items_created == 2
    assert result.total_items == 2
    assert store.upsert_many.call_count == 2
    assert store.enqueue_for_embedding.call_count == 2


@pytest.mark.asyncio
async def test_sync_fetches_movies_and_series() -> None:
    """run_sync calls get_all_items with item_types=["Movie", "Series"]."""
    page = _make_paginated([])
    store = _make_mock_store()
    settings = _make_mock_settings()

    # Use a MagicMock so we can inspect call kwargs
    client = MagicMock()
    client.get_all_items = MagicMock(return_value=_make_async_iter([page]))

    engine = SyncEngine(store, client, settings)
    await engine.run_sync()

    client.get_all_items.assert_called_once()
    call_kwargs = client.get_all_items.call_args
    assert call_kwargs.kwargs.get("item_types") == ["Movie", "Series"]


@pytest.mark.asyncio
async def test_sync_unchanged_items() -> None:
    """Unchanged items: same hash means no upsert/enqueue calls for them."""
    item = _make_library_item("jf-001", "Movie One")
    page = _make_paginated([item])

    # Pre-compute the hash the engine will produce from the row
    expected_hash = to_library_row(item).content_hash

    store = _make_mock_store()
    store.get_all_hashes.return_value = {"jf-001": expected_hash}
    store.get_all_ids.return_value = {"jf-001"}
    client = _make_mock_client([page])
    settings = _make_mock_settings()

    engine = SyncEngine(store, client, settings)
    result = await engine.run_sync()

    assert result.items_unchanged == 1
    assert result.items_created == 0
    assert result.items_updated == 0
    # upsert_many should not be called (no changed items in the page)
    store.upsert_many.assert_not_called()
    store.enqueue_for_embedding.assert_not_called()


@pytest.mark.asyncio
async def test_sync_changed_item() -> None:
    """Changed item: metadata changed -> re-upserted and re-enqueued."""
    item = _make_library_item("jf-001", "Movie One Updated")
    page = _make_paginated([item])

    store = _make_mock_store()
    store.get_all_hashes.return_value = {"jf-001": "old-stale-hash"}
    store.get_all_ids.return_value = {"jf-001"}
    client = _make_mock_client([page])
    settings = _make_mock_settings()

    engine = SyncEngine(store, client, settings)
    result = await engine.run_sync()

    assert result.items_updated == 1
    assert result.items_created == 0
    store.upsert_many.assert_called_once()
    store.enqueue_for_embedding.assert_called_once()


@pytest.mark.asyncio
async def test_sync_deletion_detected() -> None:
    """Deleted items: items in store but not in Jellyfin get soft-deleted."""
    item = _make_library_item("jf-001", "Movie One")
    page = _make_paginated([item])

    store = _make_mock_store()
    # jf-002 is in the store but NOT in Jellyfin
    store.get_all_ids.return_value = {"jf-001", "jf-002"}
    store.count.return_value = 2
    client = _make_mock_client([page])
    settings = _make_mock_settings()

    engine = SyncEngine(store, client, settings)
    result = await engine.run_sync()

    assert result.items_deleted == 1
    store.soft_delete_many.assert_called_once()
    deleted_ids = store.soft_delete_many.call_args[0][0]
    assert "jf-002" in deleted_ids


@pytest.mark.asyncio
async def test_sync_deletion_safety_threshold() -> None:
    """Safety threshold: <50% items seen -> no soft deletes."""
    # Jellyfin returns only 1 item, but store has 10
    item = _make_library_item("jf-001", "Movie One")
    page = _make_paginated([item])

    store = _make_mock_store()
    known_ids = {f"jf-{i:03d}" for i in range(1, 11)}
    store.get_all_ids.return_value = known_ids
    store.count.return_value = 10
    # Last sync saw 10 items
    last_run = MagicMock()
    last_run.total_items = 10
    store.get_last_sync_run.return_value = last_run
    client = _make_mock_client([page])
    settings = _make_mock_settings()

    engine = SyncEngine(store, client, settings)
    result = await engine.run_sync()

    assert result.items_deleted == 0
    store.soft_delete_many.assert_not_called()


@pytest.mark.asyncio
async def test_sync_per_item_failure() -> None:
    """Per-item failure: one item fails, others still processed."""
    item_good = _make_library_item("jf-001", "Good Movie")
    item_bad = _make_library_item("jf-002", "Bad Movie")
    page = _make_paginated([item_good, item_bad])

    store = _make_mock_store()
    client = _make_mock_client([page])
    settings = _make_mock_settings()

    engine = SyncEngine(store, client, settings)

    # Make row construction fail for the second item; delegate to the
    # real function (bound via module-level import) for the others.
    _real_to_row = to_library_row

    def _patched_to_row(item: LibraryItem):  # type: ignore[type-arg]
        if item.id == "jf-002":
            msg = "Simulated failure"
            raise ValueError(msg)
        return _real_to_row(item)

    with patch("app.sync.engine.to_library_row", side_effect=_patched_to_row):
        result = await engine.run_sync()

    assert result.items_failed == 1
    assert result.items_created == 1
    assert result.status == SYNC_STATUS_COMPLETED


@pytest.mark.asyncio
async def test_sync_page_level_failure() -> None:
    """Page-level failure: page 2 fails, page 1 still committed, status=failed."""
    items_p1 = [_make_library_item("jf-001", "Movie One")]
    page1 = _make_paginated(items_p1, total_count=4)

    store = _make_mock_store()
    settings = _make_mock_settings()

    # Client yields page 1, then raises on page 2
    async def _failing_iter(*args, **kwargs):  # type: ignore[no-untyped-def]
        yield page1
        raise JellyfinConnectionError("Connection lost on page 2")

    client = MagicMock()
    client.get_all_items = _failing_iter

    engine = SyncEngine(store, client, settings)
    result = await engine.run_sync()

    assert result.status == SYNC_STATUS_FAILED
    assert result.error_message is not None
    assert "JellyfinConnectionError" in result.error_message
    # Page 1 items should still have been upserted
    store.upsert_many.assert_called_once()


@pytest.mark.asyncio
async def test_sync_concurrent_rejection() -> None:
    """Concurrent sync: lock held -> SyncAlreadyRunningError."""
    store = _make_mock_store()

    # Make get_all_hashes block so we can test the lock
    hold_event = asyncio.Event()
    release_event = asyncio.Event()

    async def _blocking_get_all_hashes():  # type: ignore[no-untyped-def]
        hold_event.set()
        await release_event.wait()
        return {}

    store.get_all_hashes.side_effect = _blocking_get_all_hashes

    settings = _make_mock_settings()
    client = _make_mock_client([])

    engine = SyncEngine(store, client, settings)

    # Start a sync that blocks
    task = asyncio.create_task(engine.run_sync())
    await hold_event.wait()

    # Try to start another sync
    with pytest.raises(SyncAlreadyRunningError):
        await engine.run_sync()

    # Release the blocked sync
    release_event.set()
    await task


@pytest.mark.asyncio
async def test_sync_missing_api_key() -> None:
    """Missing API key -> SyncConfigError."""
    store = _make_mock_store()
    client = _make_mock_client([])
    settings = _make_mock_settings()
    settings.jellyfin_api_key = None

    engine = SyncEngine(store, client, settings)

    with pytest.raises(SyncConfigError, match="not configured"):
        await engine.run_sync()


@pytest.mark.asyncio
async def test_sync_missing_admin_user_id() -> None:
    """Missing admin user ID -> SyncConfigError."""
    store = _make_mock_store()
    client = _make_mock_client([])
    settings = _make_mock_settings()
    settings.jellyfin_admin_user_id = None

    engine = SyncEngine(store, client, settings)

    with pytest.raises(SyncConfigError, match="not configured"):
        await engine.run_sync()


@pytest.mark.asyncio
async def test_sync_wal_checkpoint() -> None:
    """WAL checkpoint: triggered when WAL file exceeds threshold."""
    item = _make_library_item("jf-001", "Movie One")
    page = _make_paginated([item])

    store = _make_mock_store()
    store.run_wal_checkpoint = AsyncMock()
    client = _make_mock_client([page])
    settings = _make_mock_settings(wal_threshold_mb=0.001)  # Very low threshold

    engine = SyncEngine(store, client, settings)

    with (
        patch("os.path.exists", return_value=True),
        patch("os.path.getsize", return_value=10 * 1024 * 1024),  # 10 MB
    ):
        result = await engine.run_sync()

    assert result.status == SYNC_STATUS_COMPLETED
    store.run_wal_checkpoint.assert_called_once()


@pytest.mark.asyncio
async def test_sync_saves_sync_run() -> None:
    """sync_runs row is written with correct counts."""
    items = [
        _make_library_item("jf-001", "Movie One"),
        _make_library_item("jf-002", "Movie Two"),
    ]
    page = _make_paginated(items)

    store = _make_mock_store()
    client = _make_mock_client([page])
    settings = _make_mock_settings()

    engine = SyncEngine(store, client, settings)
    await engine.run_sync()

    store.save_sync_run.assert_called_once()
    saved_result = store.save_sync_run.call_args[0][0]
    assert saved_result.items_created == 2
    assert saved_result.total_items == 2
    assert saved_result.status == SYNC_STATUS_COMPLETED


# ---------------------------------------------------------------------------
# Task 5.0 tests — Tombstone purge
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_purge_expired_tombstones() -> None:
    """Purge with expired items: verify deletion ORDER (vectors -> queue -> library)."""
    store = _make_mock_store()
    store.get_tombstoned_ids.return_value = ["jf-del-1", "jf-del-2"]
    store.hard_delete_many.return_value = 2

    vector_repo = AsyncMock()
    settings = _make_mock_settings()
    client = _make_mock_client([])

    engine = SyncEngine(store, client, settings, vector_repository=vector_repo)
    count = await engine.purge_tombstones()

    assert count == 2

    # Verify deletion order: vectors -> queue -> library
    # Use a shared mock manager to track call sequence
    manager = MagicMock()
    manager.attach_mock(vector_repo.delete_many, "vec_delete")
    manager.attach_mock(store.delete_from_embedding_queue, "queue_delete")
    manager.attach_mock(store.hard_delete_many, "lib_delete")

    # Re-run to capture ordering on the manager
    store.get_tombstoned_ids.return_value = ["jf-del-1", "jf-del-2"]
    store.hard_delete_many.return_value = 2
    await engine.purge_tombstones()

    expected_ids = ["jf-del-1", "jf-del-2"]
    manager.assert_has_calls(
        [
            unittest.mock.call.vec_delete(expected_ids),
            unittest.mock.call.queue_delete(expected_ids),
            unittest.mock.call.lib_delete(expected_ids),
        ],
        any_order=False,
    )


@pytest.mark.asyncio
async def test_purge_no_expired_tombstones() -> None:
    """No expired tombstones -> returns 0."""
    store = _make_mock_store()
    store.get_tombstoned_ids.return_value = []

    settings = _make_mock_settings()
    client = _make_mock_client([])

    engine = SyncEngine(store, client, settings)
    count = await engine.purge_tombstones()

    assert count == 0
    store.hard_delete_many.assert_not_called()


@pytest.mark.asyncio
async def test_purge_respects_ttl() -> None:
    """Items newer than TTL are not purged.

    Verifies get_tombstoned_ids receives correct cutoff timestamp.
    """
    store = _make_mock_store()
    store.get_tombstoned_ids.return_value = []

    settings = _make_mock_settings(tombstone_ttl_days=7)
    client = _make_mock_client([])

    engine = SyncEngine(store, client, settings)
    await engine.purge_tombstones()

    # Verify the older_than timestamp is approximately now - 7 days
    import time

    called_older_than = store.get_tombstoned_ids.call_args[0][0]
    expected = int(time.time()) - (7 * 86400)
    # Allow 5 seconds of drift
    assert abs(called_older_than - expected) < 5


@pytest.mark.asyncio
async def test_purge_called_at_end_of_sync() -> None:
    """Purge is called at the end of run_sync."""
    item = _make_library_item("jf-001", "Movie One")
    page = _make_paginated([item])

    store = _make_mock_store()
    client = _make_mock_client([page])
    settings = _make_mock_settings()

    engine = SyncEngine(store, client, settings)

    with patch.object(engine, "purge_tombstones", new_callable=AsyncMock) as mock_purge:
        await engine.run_sync()
        mock_purge.assert_called_once()


@pytest.mark.asyncio
async def test_purge_without_vector_repo() -> None:
    """Purge with vector_repo=None skips vector deletion."""
    store = _make_mock_store()
    store.get_tombstoned_ids.return_value = ["jf-del-1"]
    store.hard_delete_many.return_value = 1

    settings = _make_mock_settings()
    client = _make_mock_client([])

    # No vector repo
    engine = SyncEngine(store, client, settings, vector_repository=None)
    count = await engine.purge_tombstones()

    assert count == 1
    store.delete_from_embedding_queue.assert_called_once()
    store.hard_delete_many.assert_called_once()


@pytest.mark.asyncio
async def test_sync_runtime_ticks_conversion() -> None:
    """RunTimeTicks is converted to runtime_minutes in the stored row."""
    # 54000000000 ticks = 90 minutes (54e9 / 600e6 = 90)
    item = _make_library_item("jf-001", "Movie One", run_time_ticks=54000000000)
    page = _make_paginated([item])

    store = _make_mock_store()
    client = _make_mock_client([page])
    settings = _make_mock_settings()

    engine = SyncEngine(store, client, settings)
    await engine.run_sync()

    store.upsert_many.assert_called_once()
    rows = store.upsert_many.call_args[0][0]
    assert len(rows) == 1
    assert rows[0].runtime_minutes == 90


@pytest.mark.asyncio
async def test_sync_runtime_ticks_none() -> None:
    """None RunTimeTicks produces None runtime_minutes."""
    item = _make_library_item("jf-001", "Movie One", run_time_ticks=None)
    page = _make_paginated([item])

    store = _make_mock_store()
    client = _make_mock_client([page])
    settings = _make_mock_settings()

    engine = SyncEngine(store, client, settings)
    await engine.run_sync()

    store.upsert_many.assert_called_once()
    rows = store.upsert_many.call_args[0][0]
    assert len(rows) == 1
    assert rows[0].runtime_minutes is None


@pytest.mark.asyncio
async def test_delete_from_embedding_queue() -> None:
    """delete_from_embedding_queue removes specified IDs from the queue."""
    from app.library.store import LibraryStore

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    store = LibraryStore(db_path)
    await store.init()

    try:
        # Enqueue some items
        await store.enqueue_for_embedding(["jf-001", "jf-002", "jf-003"])
        assert await store.count_pending_embeddings() == 3

        # Delete only two
        deleted = await store.delete_from_embedding_queue(["jf-001", "jf-003"])
        assert deleted == 2
        assert await store.count_pending_embeddings() == 1
    finally:
        await store.close()
        import os

        os.unlink(db_path)
