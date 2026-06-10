"""Unit tests for ``LibraryStore.get_title_index`` (Spec 26 Task 1.0).

The eval golden-set loader resolves labelled titles to jellyfin_ids via this
index. Because titles are not unique, the index must expose *all* ids per
title so the loader can reject ambiguous matches.
"""

from __future__ import annotations

import pathlib
from typing import TYPE_CHECKING

import pytest

from app.library.store import LibraryStore
from tests.factories import make_library_item

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@pytest.fixture
async def store(tmp_path: object) -> AsyncIterator[LibraryStore]:
    db_path = pathlib.Path(str(tmp_path)) / "title_index.db"
    s = LibraryStore(str(db_path))
    await s.init()
    yield s  # type: ignore[misc]
    await s.close()


class TestGetTitleIndex:
    async def test_maps_titles_to_ids(self, store: LibraryStore) -> None:
        await store.upsert_many(
            [
                make_library_item(jellyfin_id="a1", title="Alien"),
                make_library_item(jellyfin_id="b1", title="Blade Runner"),
            ]
        )
        index = await store.get_title_index()
        assert index["Alien"] == ["a1"]
        assert index["Blade Runner"] == ["b1"]

    async def test_collision_exposes_all_ids(self, store: LibraryStore) -> None:
        """Two items sharing a title (a remake) must both appear under it."""
        await store.upsert_many(
            [
                make_library_item(jellyfin_id="thing-1982", title="The Thing"),
                make_library_item(jellyfin_id="thing-2011", title="The Thing"),
            ]
        )
        index = await store.get_title_index()
        assert sorted(index["The Thing"]) == ["thing-1982", "thing-2011"]

    async def test_empty_store_returns_empty_index(self, store: LibraryStore) -> None:
        assert await store.get_title_index() == {}
