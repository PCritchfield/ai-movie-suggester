"""Integration tests for SyncEngine against populated Jellyfin.

Requires: make jellyfin-up (disposable Jellyfin with fixture media).
Uses the fixture chain: jellyfin -> admin_auth_token -> test_users -> populated_library.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import pytest
import pytest_asyncio

from app.config import Settings
from app.jellyfin.client import JellyfinClient
from app.library.store import LibraryStore
from app.sync.engine import SyncEngine

if TYPE_CHECKING:
    import pathlib
    from collections.abc import AsyncGenerator

    from tests.integration.conftest import JellyfinInstance

from tests.integration.conftest import (
    EXPECTED_TOTAL,
    TEST_ADMIN_PASS,
)


@pytest_asyncio.fixture
async def jf_client(
    jellyfin: JellyfinInstance,
) -> AsyncGenerator[JellyfinClient, None]:
    """JellyfinClient pointed at the test instance."""
    async with httpx.AsyncClient(timeout=30.0) as http:
        yield JellyfinClient(base_url=jellyfin.url, http_client=http)


@pytest_asyncio.fixture
async def library_store(
    tmp_path: pathlib.Path,
) -> AsyncGenerator[LibraryStore, None]:
    """Temporary LibraryStore for sync tests."""
    db_path = tmp_path / "sync_test_library.db"
    store = LibraryStore(str(db_path))
    await store.init()
    yield store
    await store.close()


def _make_sync_settings(
    jellyfin_url: str, admin_token: str, admin_user_id: str
) -> Settings:
    """Build minimal Settings for SyncEngine with required fields."""
    return Settings(
        jellyfin_url=jellyfin_url,
        session_secret="a" * 32 + "-test-not-real-secret-12345678",
        session_secure_cookie=False,
        jellyfin_api_key=admin_token,
        jellyfin_admin_user_id=admin_user_id,
        log_level="debug",
    )  # type: ignore[call-arg]


@pytest_asyncio.fixture
async def sync_settings(
    jellyfin: JellyfinInstance,
    admin_auth_token: str,
) -> Settings:
    """Settings configured for sync against the test Jellyfin."""
    # We need the admin user ID — authenticate to get it
    async with httpx.AsyncClient(timeout=10.0) as http:
        client = JellyfinClient(base_url=jellyfin.url, http_client=http)
        auth = await client.authenticate("root", TEST_ADMIN_PASS)
    return _make_sync_settings(jellyfin.url, admin_auth_token, auth.user_id)


@pytest.mark.integration
async def test_sync_stores_all_items(
    jf_client: JellyfinClient,
    library_store: LibraryStore,
    sync_settings: Settings,
    populated_library: int,
) -> None:
    """SyncEngine stores all fixture items with zero failures."""
    engine = SyncEngine(library_store, jf_client, sync_settings)
    result = await engine.run_sync()

    count = await library_store.count()
    assert count >= EXPECTED_TOTAL, f"Expected >= {EXPECTED_TOTAL} items, got {count}"
    assert result.items_failed == 0, f"Sync had {result.items_failed} failures"


@pytest.mark.integration
async def test_sync_enqueues_for_embedding(
    jf_client: JellyfinClient,
    library_store: LibraryStore,
    sync_settings: Settings,
    populated_library: int,
) -> None:
    """All synced items are enqueued for embedding."""
    engine = SyncEngine(library_store, jf_client, sync_settings)
    await engine.run_sync()

    pending = await library_store.count_pending_embeddings()
    assert pending >= EXPECTED_TOTAL, (
        f"Expected >= {EXPECTED_TOTAL} pending embeddings, got {pending}"
    )


@pytest.mark.integration
async def test_synced_items_have_metadata(
    jf_client: JellyfinClient,
    library_store: LibraryStore,
    sync_settings: Settings,
    populated_library: int,
) -> None:
    """Synced items have non-empty overview, genres, and people from NFO."""
    engine = SyncEngine(library_store, jf_client, sync_settings)
    await engine.run_sync()

    # Read a few items and check metadata
    all_ids = await library_store.get_all_ids()
    assert len(all_ids) >= EXPECTED_TOTAL

    # Fetch a batch — get_many returns LibraryItemRow objects
    sample_ids = list(all_ids)[:5]
    items = await library_store.get_many(sample_ids)

    found_rich_item = False
    for item in items:
        if item.overview is not None and len(item.genres) > 0 and len(item.people) > 0:
            found_rich_item = True
            break

    assert found_rich_item, (
        "No sampled item has overview + genres + people. "
        "NFO metadata may not be flowing through the sync pipeline."
    )


@pytest.mark.integration
async def test_sync_is_idempotent(
    jf_client: JellyfinClient,
    library_store: LibraryStore,
    sync_settings: Settings,
    populated_library: int,
) -> None:
    """Running sync twice produces the same count; second run creates 0."""
    engine = SyncEngine(library_store, jf_client, sync_settings)

    await engine.run_sync()
    count1 = await library_store.count()

    result2 = await engine.run_sync()
    count2 = await library_store.count()

    assert count1 == count2, f"Count changed between syncs: {count1} → {count2}"
    assert result2.items_created == 0, (
        f"Second sync created {result2.items_created} items (expected 0)"
    )
