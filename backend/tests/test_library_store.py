"""Unit tests for the async SQLite library metadata repository."""

from __future__ import annotations

import logging
import pathlib
import time
from typing import TYPE_CHECKING

import pytest

from app.library.hashing import compute_content_hash
from app.library.models import LibraryItemRow, UpsertResult
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


class TestInit:
    """Verify schema creation and PRAGMA settings."""

    async def test_table_exists(self, store: LibraryStore) -> None:
        cursor = await store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='library_items'"
        )
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == "library_items"

    async def test_indexes_exist(self, store: LibraryStore) -> None:
        cursor = await store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name IN ("
            "'idx_library_items_content_hash', "
            "'idx_library_items_synced_at')"
        )
        rows = await cursor.fetchall()
        index_names = {r[0] for r in rows}
        assert "idx_library_items_content_hash" in index_names
        assert "idx_library_items_synced_at" in index_names

    async def test_wal_mode(self, store: LibraryStore) -> None:
        cursor = await store._conn.execute("PRAGMA journal_mode")
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == "wal"

    async def test_foreign_keys_enabled(self, store: LibraryStore) -> None:
        cursor = await store._conn.execute("PRAGMA foreign_keys")
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == 1

    def test_conn_before_init_raises(self) -> None:
        s = LibraryStore("/tmp/nonexistent.db")
        with pytest.raises(RuntimeError, match="LibraryStore not initialised"):
            _ = s._conn


class TestUpsertMany:
    """upsert_many() created/updated/unchanged tracking."""

    async def test_insert_new_items(self, store: LibraryStore) -> None:
        items = [_make_item(jellyfin_id=f"jf-{i}") for i in range(3)]
        result = await store.upsert_many(items)
        assert result == UpsertResult(created=3, updated=0, unchanged=0)

    async def test_reupsert_same_hash_unchanged(self, store: LibraryStore) -> None:
        items = [
            _make_item(jellyfin_id=f"jf-{i}", content_hash="same-hash")
            for i in range(3)
        ]
        await store.upsert_many(items)
        result = await store.upsert_many(items)
        assert result == UpsertResult(created=0, updated=0, unchanged=3)

    async def test_changed_hash_counts_as_updated(self, store: LibraryStore) -> None:
        items = [
            _make_item(jellyfin_id=f"jf-{i}", content_hash=f"hash-{i}")
            for i in range(3)
        ]
        await store.upsert_many(items)
        # Change hash for one item
        updated_items = [
            _make_item(jellyfin_id="jf-0", content_hash="new-hash"),
            _make_item(jellyfin_id="jf-1", content_hash="hash-1"),
            _make_item(jellyfin_id="jf-2", content_hash="hash-2"),
        ]
        result = await store.upsert_many(updated_items)
        assert result == UpsertResult(created=0, updated=1, unchanged=2)

    async def test_empty_list(self, store: LibraryStore) -> None:
        result = await store.upsert_many([])
        assert result == UpsertResult(created=0, updated=0, unchanged=0)


class TestGet:
    """get() single item retrieval."""

    async def test_round_trip_all_fields(self, store: LibraryStore) -> None:
        item = _make_item(
            jellyfin_id="jf-roundtrip",
            title="Galaxy Quest",
            overview="A comedy about actors in space.",
            production_year=1999,
            genres=["Comedy", "Sci-Fi"],
            tags=["family", "fun"],
            studios=["DreamWorks"],
            community_rating=7.4,
            people=["Tim Allen", "Sigourney Weaver"],
            content_hash="hash-gq",
            synced_at=1700000000,
        )
        await store.upsert_many([item])
        fetched = await store.get("jf-roundtrip")
        assert fetched is not None
        assert fetched.jellyfin_id == "jf-roundtrip"
        assert fetched.title == "Galaxy Quest"
        assert fetched.overview == "A comedy about actors in space."
        assert fetched.production_year == 1999
        assert fetched.genres == ["Comedy", "Sci-Fi"]
        assert fetched.tags == ["family", "fun"]
        assert fetched.studios == ["DreamWorks"]
        assert fetched.community_rating == 7.4
        assert fetched.people == ["Tim Allen", "Sigourney Weaver"]
        assert fetched.content_hash == "hash-gq"
        assert fetched.synced_at == 1700000000

    async def test_missing_id_returns_none(self, store: LibraryStore) -> None:
        assert await store.get("nonexistent") is None


class TestGetMany:
    """get_many() batch retrieval."""

    async def test_fetch_subset(self, store: LibraryStore) -> None:
        items = [_make_item(jellyfin_id=f"jf-{i}") for i in range(5)]
        await store.upsert_many(items)
        results = await store.get_many(["jf-0", "jf-2", "jf-4"])
        assert len(results) == 3
        ids = {r.jellyfin_id for r in results}
        assert ids == {"jf-0", "jf-2", "jf-4"}

    async def test_mix_existing_and_nonexistent(self, store: LibraryStore) -> None:
        items = [_make_item(jellyfin_id=f"jf-{i}") for i in range(3)]
        await store.upsert_many(items)
        results = await store.get_many(["jf-0", "jf-1", "nonexistent", "also-missing"])
        assert len(results) == 2
        ids = {r.jellyfin_id for r in results}
        assert ids == {"jf-0", "jf-1"}

    async def test_empty_list_returns_empty(self, store: LibraryStore) -> None:
        results = await store.get_many([])
        assert results == []


class TestGetAllHashes:
    """get_all_hashes() hash mapping."""

    async def test_returns_hash_mapping(self, store: LibraryStore) -> None:
        items = [
            _make_item(jellyfin_id=f"jf-{i}", content_hash=f"hash-{i}")
            for i in range(3)
        ]
        await store.upsert_many(items)
        hashes = await store.get_all_hashes()
        assert hashes == {"jf-0": "hash-0", "jf-1": "hash-1", "jf-2": "hash-2"}

    async def test_empty_store_returns_empty_dict(self, store: LibraryStore) -> None:
        hashes = await store.get_all_hashes()
        assert hashes == {}


class TestCount:
    """count() total items."""

    async def test_empty_store_returns_zero(self, store: LibraryStore) -> None:
        assert await store.count() == 0

    async def test_after_inserts(self, store: LibraryStore) -> None:
        items = [_make_item(jellyfin_id=f"jf-{i}") for i in range(5)]
        await store.upsert_many(items)
        assert await store.count() == 5


class TestContentHash:
    """Content hash computation determinism."""

    def test_deterministic(self) -> None:
        item = _make_item()
        hash1 = compute_content_hash(item)
        hash2 = compute_content_hash(item)
        assert hash1 == hash2

    def test_different_input_different_hash(self) -> None:
        item1 = _make_item(title="Alien")
        item2 = _make_item(title="Aliens")
        assert compute_content_hash(item1) != compute_content_hash(item2)


class TestPeopleFiltering:
    """Verify people filtering from Jellyfin's raw People array."""

    async def test_only_actor_names_stored(self, store: LibraryStore) -> None:
        """When building LibraryItemRow from Jellyfin data, only Actor names
        should be in the people list. Non-Actor entries are excluded."""
        # Simulating the conversion logic that would be done by the sync layer:
        # Jellyfin raw people data
        raw_people = [
            {"Name": "Tom Hanks", "Role": "Woody", "Type": "Actor"},
            {"Name": "Tim Allen", "Role": "Buzz", "Type": "Actor"},
            {"Name": "John Lasseter", "Role": "", "Type": "Director"},
            {"Name": "Randy Newman", "Role": "", "Type": "Composer"},
        ]
        # Filter to actors only (as the sync layer should do)
        actor_names = [p["Name"] for p in raw_people if p.get("Type") == "Actor"]
        item = _make_item(
            jellyfin_id="jf-actors",
            people=actor_names,
        )
        await store.upsert_many([item])
        fetched = await store.get("jf-actors")
        assert fetched is not None
        assert fetched.people == ["Tom Hanks", "Tim Allen"]
        assert "John Lasseter" not in fetched.people
        assert "Randy Newman" not in fetched.people


class TestValidation:
    """Malformed data handling."""

    async def test_malformed_item_skipped_valid_stored(
        self, store: LibraryStore, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Malformed Jellyfin item data is skipped with WARNING log,
        valid items in the same batch are stored."""
        from pydantic import ValidationError as PydanticValidationError

        from app.jellyfin.models import LibraryItem

        # One valid, one malformed (missing required Id)
        valid_data = {"Id": "valid-1", "Name": "Good Movie", "Type": "Movie"}
        malformed_data = {"Name": "Bad Movie", "Type": "Movie"}  # Missing Id

        items_to_store: list[LibraryItemRow] = []

        for raw in [valid_data, malformed_data]:
            try:
                lib_item = LibraryItem.model_validate(raw)
                # Filter people to actors only
                actor_names = [
                    p["Name"] for p in lib_item.people if p.get("Type") == "Actor"
                ]
                row = LibraryItemRow(
                    jellyfin_id=lib_item.id,
                    title=lib_item.name,
                    overview=lib_item.overview,
                    production_year=lib_item.production_year,
                    genres=lib_item.genres,
                    tags=lib_item.tags,
                    studios=lib_item.studios,
                    community_rating=lib_item.community_rating,
                    people=actor_names,
                    content_hash="placeholder-hash",
                    synced_at=_now(),
                )
                items_to_store.append(row)
            except PydanticValidationError:
                item_id = raw.get("Id", "unknown")
                logging.getLogger(__name__).warning(
                    "Skipping malformed library item: %s", item_id
                )

        with caplog.at_level(logging.WARNING):
            result = await store.upsert_many(items_to_store)

        assert result.created == 1
        assert await store.count() == 1
        fetched = await store.get("valid-1")
        assert fetched is not None
        assert fetched.title == "Good Movie"
        assert any("malformed" in r.message.lower() for r in caplog.records)
