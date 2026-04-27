"""Unit tests for ``PersonIndex`` — Spec 24, Unit 2.

Functional Requirements covered (per spec 24, Unit 2):
- FR-2.1 (build): index built from a frozenset of lowercased names
- FR-2.2 (multi-token strict): full-phrase regex on word boundaries
- FR-2.3 (single-token gating): single tokens require an intent token
  (``movie``, ``movies``, ``film``, ``films``, ``with``, ``starring``,
  ``stars``) elsewhere in the query — Q1-D resolution
- FR-2.4 (short-name skip): names <3 characters skipped at build time
- FR-2.5 (rebuild on sync): rebuild swaps the underlying frozenset
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

from app.library.models import LibraryItemRow
from app.library.store import LibraryStore
from app.search.person_index import PersonIndex

if TYPE_CHECKING:
    import pathlib

    import pytest


class TestPersonIndexBuild:
    """FR-2.1, FR-2.4 — build skips short names, returns frozenset state."""

    def test_contains_returns_true_for_known_name(self) -> None:
        idx = PersonIndex(names=frozenset({"eddie murphy"}))
        assert idx.contains("eddie murphy") is True

    def test_contains_returns_false_for_unknown_name(self) -> None:
        idx = PersonIndex(names=frozenset({"eddie murphy"}))
        assert idx.contains("ridley scott") is False

    def test_short_names_skipped_on_build(self) -> None:
        idx = PersonIndex(names=frozenset({"al", "tom", "ridley scott"}))
        # 'al' is two characters → skipped
        assert idx.contains("al") is False
        # 'tom' is exactly 3 → kept
        assert idx.contains("tom") is True
        # multi-word always kept
        assert idx.contains("ridley scott") is True


class TestPersonIndexMatch:
    """FR-2.2, FR-2.3 — multi-token strict, single-token gated."""

    def test_multi_token_full_phrase_match(self) -> None:
        idx = PersonIndex(names=frozenset({"eddie murphy"}))
        assert idx.match("Eddie Murphy films") == ["eddie murphy"]

    def test_multi_token_no_intent_word_required(self) -> None:
        # multi-token names match without the gating intent word
        idx = PersonIndex(names=frozenset({"john hughes"}))
        assert idx.match("a john hughes comedy") == ["john hughes"]

    def test_single_token_requires_intent_word(self) -> None:
        idx = PersonIndex(names=frozenset({"cher"}))
        # 'cher' in a query with NO intent token → no match
        assert idx.match("looks like cher in the photo") == []
        # 'cher movies' with the intent token → match
        assert idx.match("Cher movies") == ["cher"]
        # 'cher' in a biopic-style query also gates on the intent token
        # ('movie' here), which Q1-D explicitly allows
        assert idx.match("a movie about Cher") == ["cher"]

    def test_single_token_intent_words_all_recognised(self) -> None:
        idx = PersonIndex(names=frozenset({"cher"}))
        for intent in ("movie", "movies", "film", "films", "starring", "stars"):
            assert idx.match(f"Cher {intent}") == ["cher"], (
                f"intent token '{intent}' should gate single-token match"
            )

    def test_word_boundary_avoids_false_positives(self) -> None:
        # 'mary' should not match inside 'summary'
        idx = PersonIndex(names=frozenset({"mary"}))
        assert idx.match("a quick summary movie") == []

    def test_returns_empty_when_no_match(self) -> None:
        idx = PersonIndex(names=frozenset({"eddie murphy"}))
        assert idx.match("some unrelated query") == []

    def test_dedupes_repeated_names(self) -> None:
        idx = PersonIndex(names=frozenset({"eddie murphy"}))
        assert idx.match("Eddie Murphy and Eddie Murphy films") == ["eddie murphy"]

    def test_match_order_follows_query_appearance(self) -> None:
        """Pin the deterministic-order contract documented in the docstring.

        Without this pin, a frozenset-iteration regression would silently
        change the order across Python runs (Spec 24 / Carrot review).
        """
        idx = PersonIndex(
            names=frozenset({"eddie murphy", "john hughes", "ridley scott"})
        )
        assert idx.match("a Ridley Scott film with Eddie Murphy and John Hughes") == [
            "ridley scott",
            "eddie murphy",
            "john hughes",
        ]
        # Reversing the query reverses the match order.
        assert idx.match(
            "with John Hughes and Eddie Murphy in a Ridley Scott film"
        ) == [
            "john hughes",
            "eddie murphy",
            "ridley scott",
        ]


class TestPersonIndexRebuild:
    """FR-2.5 — rebuild swaps the underlying frozenset atomically."""

    async def test_rebuild_from_store_swaps_names(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        idx = PersonIndex(names=frozenset({"old name"}))
        store = AsyncMock()
        store.get_all_people_names = AsyncMock(
            return_value=frozenset({"new name", "ab"})  # 'ab' is too short
        )

        with caplog.at_level(logging.INFO):
            await idx.rebuild_from_store(store)

        assert idx.contains("old name") is False
        assert idx.contains("new name") is True
        assert idx.contains("ab") is False  # short-name skip
        # log line shape per Spec 24 task 1.5
        assert any(
            "person_index_built" in r.message and "count=" in r.message
            for r in caplog.records
        )


class TestPersonIndexAgainstRealStore:
    """Spec 24 Task 1.8 — booted ``LibraryStore`` + ``PersonIndex`` integration.

    Uses a real on-disk SQLite store (no mocks) so the build path covers
    the actual JSON deserialisation and column union logic.
    """

    async def test_match_after_rebuild_from_real_store(
        self,
        tmp_path: pathlib.Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        store = LibraryStore(str(tmp_path / "lib.db"))
        await store.init()
        try:
            await store.upsert_many(
                [
                    LibraryItemRow(
                        jellyfin_id="jf-1",
                        title="Beverly Hills Cop",
                        overview=None,
                        production_year=1984,
                        genres=["Action", "Comedy"],
                        tags=[],
                        studios=[],
                        community_rating=None,
                        people=["Eddie Murphy"],
                        content_hash="h1",
                        synced_at=int(time.time()),
                        directors=["Martin Brest"],
                        writers=[],
                        composers=[],
                    )
                ]
            )

            index = PersonIndex(names=frozenset())
            with caplog.at_level(logging.INFO):
                await index.rebuild_from_store(store)

            assert index.match("Eddie Murphy films") == ["eddie murphy"]
            assert any("person_index_built" in r.message for r in caplog.records)
        finally:
            await store.close()
