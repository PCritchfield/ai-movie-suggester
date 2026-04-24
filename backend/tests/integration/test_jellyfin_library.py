"""Integration tests for Jellyfin library client + store cycle.

Requires: make jellyfin-up (disposable Jellyfin on localhost:8096).
Uses the existing fixture chain: jellyfin -> admin_auth_token -> test_users.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from app.sync.engine import to_library_row

if TYPE_CHECKING:
    from app.jellyfin.client import JellyfinClient
    from app.jellyfin.models import AuthResult, PaginatedItems
    from app.library.models import LibraryItemRow
    from app.library.store import LibraryStore

from tests.integration.conftest import (
    EXPECTED_MOVIES,
    EXPECTED_SHOWS,
)


@pytest.mark.integration
async def test_get_all_items_returns_pages(
    jf_client: JellyfinClient,
    alice_auth: AuthResult,
) -> None:
    """get_all_items returns pages — may be 0 items on fresh Jellyfin."""

    pages: list[PaginatedItems] = []
    async for page in jf_client.get_all_items(
        alice_auth.access_token,
        alice_auth.user_id,
        item_types=["Movie"],
    ):
        pages.append(page)

    assert len(pages) >= 1
    # First page always exists (even if empty)
    assert pages[0].total_count >= 0


@pytest.mark.integration
async def test_fetch_and_store_cycle(
    jf_client: JellyfinClient,
    alice_auth: AuthResult,
    library_store: LibraryStore,
) -> None:
    """Fetch items via get_all_items, store in LibraryStore, verify count."""

    total_items = 0
    all_rows: list[LibraryItemRow] = []

    async for page in jf_client.get_all_items(
        alice_auth.access_token,
        alice_auth.user_id,
        item_types=["Movie"],
    ):
        total_items = page.total_count
        for item in page.items:
            all_rows.append(to_library_row(item))

    if all_rows:
        await library_store.upsert_many(all_rows)

    count = await library_store.count()
    assert count == len(all_rows)
    # On a fresh Jellyfin with no movies, both should be 0
    assert count == total_items


@pytest.mark.integration
async def test_extended_fields_no_validation_errors(
    jf_client: JellyfinClient,
    alice_auth: AuthResult,
) -> None:
    """Extended fields parse without Pydantic validation errors."""

    async for page in jf_client.get_all_items(
        alice_auth.access_token,
        alice_auth.user_id,
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


# ---------------------------------------------------------------------------
# Populated library tests — require the populated_library fixture
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_populated_library_has_movies(
    jf_client: JellyfinClient,
    populated_library: int,
    alice_auth: AuthResult,
) -> None:
    """Populated Jellyfin has at least the expected number of movies."""

    total = 0
    async for page in jf_client.get_all_items(
        alice_auth.access_token, alice_auth.user_id, item_types=["Movie"]
    ):
        total = page.total_count
    assert total >= EXPECTED_MOVIES


@pytest.mark.integration
async def test_populated_library_has_shows(
    jf_client: JellyfinClient,
    populated_library: int,
    alice_auth: AuthResult,
) -> None:
    """Populated Jellyfin has at least the expected number of shows."""

    total = 0
    async for page in jf_client.get_all_items(
        alice_auth.access_token, alice_auth.user_id, item_types=["Series"]
    ):
        total = page.total_count
    assert total >= EXPECTED_SHOWS


@pytest.mark.integration
async def test_movie_metadata_from_nfo(
    jf_client: JellyfinClient,
    populated_library: int,
    alice_auth: AuthResult,
) -> None:
    """At least one movie has overview, genres, and year from NFO."""

    async for page in jf_client.get_all_items(
        alice_auth.access_token, alice_auth.user_id, item_types=["Movie"]
    ):
        for item in page.items:
            if item.overview and item.genres and item.production_year:
                return  # Found one with full metadata — pass
    pytest.fail("No movie item has overview + genres + production_year")


@pytest.mark.integration
async def test_show_metadata_from_nfo(
    jf_client: JellyfinClient,
    populated_library: int,
    alice_auth: AuthResult,
) -> None:
    """At least one show has overview and genres from NFO."""

    async for page in jf_client.get_all_items(
        alice_auth.access_token, alice_auth.user_id, item_types=["Series"]
    ):
        for item in page.items:
            if item.overview and item.genres:
                return  # Found one with metadata — pass
    pytest.fail("No show item has overview + genres")
