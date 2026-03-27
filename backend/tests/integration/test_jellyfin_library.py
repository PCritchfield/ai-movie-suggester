"""Integration tests for Jellyfin library client + store cycle.

Requires: make jellyfin-up (disposable Jellyfin on localhost:8096).
Uses the existing fixture chain: jellyfin -> admin_auth_token -> test_users.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import httpx
import pytest
import pytest_asyncio

from app.jellyfin.client import JellyfinClient
from app.library.hashing import compute_content_hash
from app.library.models import LibraryItemRow
from app.library.store import LibraryStore

if TYPE_CHECKING:
    import pathlib
    from collections.abc import AsyncGenerator

    from app.jellyfin.models import LibraryItem, PaginatedItems
    from tests.integration.conftest import JellyfinInstance

from tests.integration.conftest import TEST_USER_ALICE, TEST_USER_ALICE_PASS


@pytest_asyncio.fixture
async def jf_client(
    jellyfin: JellyfinInstance,
) -> AsyncGenerator[JellyfinClient, None]:
    """JellyfinClient pointed at the test instance."""
    async with httpx.AsyncClient(timeout=10.0) as http:
        yield JellyfinClient(base_url=jellyfin.url, http_client=http)


@pytest_asyncio.fixture
async def library_store(tmp_path: pathlib.Path) -> AsyncGenerator[LibraryStore, None]:
    """Temporary LibraryStore for integration tests."""
    db_path = tmp_path / "test_library.db"
    store = LibraryStore(str(db_path))
    await store.init()
    yield store
    await store.close()


def _to_library_row(item: LibraryItem) -> LibraryItemRow:
    """Convert a LibraryItem to a LibraryItemRow for storage."""
    actor_names = [p["Name"] for p in item.people if p.get("Type") == "Actor"]
    row = LibraryItemRow(
        jellyfin_id=item.id,
        title=item.name,
        overview=item.overview,
        production_year=item.production_year,
        genres=item.genres,
        tags=item.tags,
        studios=item.studios,
        community_rating=item.community_rating,
        people=actor_names,
        content_hash="placeholder",
        synced_at=int(time.time()),
    )
    # Compute real hash
    return LibraryItemRow(
        jellyfin_id=row.jellyfin_id,
        title=row.title,
        overview=row.overview,
        production_year=row.production_year,
        genres=row.genres,
        tags=row.tags,
        studios=row.studios,
        community_rating=row.community_rating,
        people=row.people,
        content_hash=compute_content_hash(row),
        synced_at=row.synced_at,
    )


@pytest.mark.integration
async def test_get_all_items_returns_pages(
    jf_client: JellyfinClient,
    test_users: dict[str, str],
) -> None:
    """get_all_items returns pages — may be 0 items on fresh Jellyfin."""
    auth = await jf_client.authenticate(TEST_USER_ALICE, TEST_USER_ALICE_PASS)
    pages: list[PaginatedItems] = []
    async for page in jf_client.get_all_items(
        auth.access_token,
        auth.user_id,
        item_types=["Movie"],
    ):
        pages.append(page)

    assert len(pages) >= 1
    # First page always exists (even if empty)
    assert pages[0].total_count >= 0


@pytest.mark.integration
async def test_fetch_and_store_cycle(
    jf_client: JellyfinClient,
    test_users: dict[str, str],
    library_store: LibraryStore,
) -> None:
    """Fetch items via get_all_items, store in LibraryStore, verify count."""
    auth = await jf_client.authenticate(TEST_USER_ALICE, TEST_USER_ALICE_PASS)
    total_items = 0
    all_rows: list[LibraryItemRow] = []

    async for page in jf_client.get_all_items(
        auth.access_token,
        auth.user_id,
        item_types=["Movie"],
    ):
        total_items = page.total_count
        for item in page.items:
            all_rows.append(_to_library_row(item))

    if all_rows:
        await library_store.upsert_many(all_rows)

    count = await library_store.count()
    assert count == len(all_rows)
    # On a fresh Jellyfin with no movies, both should be 0
    assert count == total_items


@pytest.mark.integration
async def test_extended_fields_no_validation_errors(
    jf_client: JellyfinClient,
    test_users: dict[str, str],
) -> None:
    """Extended fields parse without Pydantic validation errors."""
    auth = await jf_client.authenticate(TEST_USER_ALICE, TEST_USER_ALICE_PASS)
    async for page in jf_client.get_all_items(
        auth.access_token,
        auth.user_id,
        item_types=["Movie"],
    ):
        for item in page.items:
            # These should not raise — Pydantic validates on construction
            assert isinstance(item.tags, list)
            assert isinstance(item.studios, list)
            assert isinstance(item.people, list)
            # community_rating can be None
            assert item.community_rating is None or isinstance(
                item.community_rating, float
            )
