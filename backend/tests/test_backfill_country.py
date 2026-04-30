"""Tests for scripts/backfill_country.py — Spec 25 backfill script.

The script lives in ``scripts/`` (one level above ``backend/``) but its
runtime imports come from the backend (``app.config``, ``app.jellyfin.client``,
``app.library.store``, ``app.library.country_codes``). To test it we add the
``scripts/`` directory to ``sys.path`` lazily inside the test module.
"""

from __future__ import annotations

import pathlib
import sys
import time
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest

from app.library.models import LibraryItemRow
from app.library.store import LibraryStore

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

# Add scripts/ to sys.path so tests can import the script as a module.
_SCRIPTS_DIR = pathlib.Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import backfill_country  # type: ignore[import-not-found]  # noqa: E402 — sys.path mutation above; scripts/ resolved at runtime, not in pyright's analysis paths


@pytest.fixture
async def store(tmp_path: pathlib.Path) -> AsyncIterator[LibraryStore]:
    db_path = tmp_path / "test_backfill.db"
    s = LibraryStore(str(db_path))
    await s.init()
    yield s  # type: ignore[misc]
    await s.close()


def _make_row(
    jellyfin_id: str,
    *,
    country_synced_at: int | None = None,
) -> LibraryItemRow:
    """Helper — minimal LibraryItemRow with deterministic content_hash."""
    return LibraryItemRow(
        jellyfin_id=jellyfin_id,
        title=f"Movie {jellyfin_id}",
        overview=None,
        production_year=2020,
        genres=[],
        tags=[],
        studios=[],
        community_rating=None,
        people=[],
        content_hash=f"hash-{jellyfin_id}",
        synced_at=int(time.time()),
        country_synced_at=country_synced_at,
    )


def _mock_client_returning(items: list[dict]) -> AsyncMock:
    """Build an AsyncMock JellyfinClient whose get_items_by_ids returns ``items``.

    Each ``items`` entry is a dict shaped like ``LibraryItem.model_validate``
    expects. The mock honours batch ID filtering — items not in the requested
    ID set are dropped from the response (mimics Jellyfin's behaviour).
    """
    from app.jellyfin.models import LibraryItem

    parsed = [LibraryItem.model_validate(d) for d in items]

    async def _get_items_by_ids(
        *,
        token: str,
        user_id: str,
        ids: list[str],
        fields: str | None = None,
    ) -> list[LibraryItem]:
        id_set = set(ids)
        return [item for item in parsed if item.id in id_set]

    client = AsyncMock()
    client.get_items_by_ids = AsyncMock(side_effect=_get_items_by_ids)
    return client


class TestRunBackfillHappyPath:
    """Spec 25 T3.0 — basic backfill of pending rows."""

    async def test_updates_two_pending_rows_with_iso_codes(
        self, store: LibraryStore
    ) -> None:
        await store.upsert_many(
            [
                _make_row("jf-1", country_synced_at=None),
                _make_row("jf-2", country_synced_at=None),
            ]
        )
        client = _mock_client_returning(
            [
                {
                    "Id": "jf-1",
                    "Name": "Spirited Away",
                    "Type": "Movie",
                    "ProductionLocations": ["Japan"],
                },
                {
                    "Id": "jf-2",
                    "Name": "Alien",
                    "Type": "Movie",
                    "ProductionLocations": ["United States of America"],
                },
            ]
        )

        rows_processed, batches_run = await backfill_country.run_backfill(
            store=store,
            client=client,
            token="dummy-token",
            user_id="dummy-uid",
            dry_run=False,
        )

        assert rows_processed == 2
        assert batches_run == 1

        row1 = await store.get("jf-1")
        assert row1 is not None
        assert row1.production_countries == ["JP"]
        assert row1.country_synced_at is not None

        row2 = await store.get("jf-2")
        assert row2 is not None
        assert row2.production_countries == ["US"]

    async def test_re_invocation_processes_zero_rows(self, store: LibraryStore) -> None:
        """After a successful backfill, re-running selects 0 pending rows."""
        await store.upsert_many([_make_row("jf-1", country_synced_at=None)])
        client = _mock_client_returning(
            [
                {
                    "Id": "jf-1",
                    "Name": "Spirited Away",
                    "Type": "Movie",
                    "ProductionLocations": ["Japan"],
                }
            ]
        )

        await backfill_country.run_backfill(
            store=store, client=client, token="t", user_id="u", dry_run=False
        )

        # Second invocation
        rows_processed_second, batches_second = await backfill_country.run_backfill(
            store=store, client=client, token="t", user_id="u", dry_run=False
        )
        assert rows_processed_second == 0
        assert batches_second == 0

    async def test_co_production_stored_sorted(self, store: LibraryStore) -> None:
        await store.upsert_many([_make_row("jf-coprod", country_synced_at=None)])
        client = _mock_client_returning(
            [
                {
                    "Id": "jf-coprod",
                    "Name": "2 Fast 2 Furious",
                    "Type": "Movie",
                    "ProductionLocations": [
                        "United States of America",
                        "Germany",
                    ],
                }
            ]
        )

        await backfill_country.run_backfill(
            store=store, client=client, token="t", user_id="u", dry_run=False
        )
        row = await store.get("jf-coprod")
        assert row is not None
        assert row.production_countries == ["DE", "US"]


class TestRunBackfillResumeFromPartial:
    """Spec 25 T3.5 — resume-safety against partial completion."""

    async def test_only_pending_rows_touched(self, store: LibraryStore) -> None:
        already_synced_at = 1_700_000_000
        await store.upsert_many(
            [
                _make_row("jf-pending-1", country_synced_at=None),
                _make_row("jf-pending-2", country_synced_at=None),
                _make_row("jf-pending-3", country_synced_at=None),
                _make_row("jf-already-1", country_synced_at=already_synced_at),
                _make_row("jf-already-2", country_synced_at=already_synced_at),
            ]
        )
        client = _mock_client_returning(
            [
                {
                    "Id": f"jf-pending-{i}",
                    "Name": f"Pending {i}",
                    "Type": "Movie",
                    "ProductionLocations": ["Japan"],
                }
                for i in (1, 2, 3)
            ]
        )

        await backfill_country.run_backfill(
            store=store, client=client, token="t", user_id="u", dry_run=False
        )

        # Already-synced rows are untouched (timestamp preserved exactly)
        already_1 = await store.get("jf-already-1")
        assert already_1 is not None
        assert already_1.country_synced_at == already_synced_at
        assert already_1.production_countries == []

        # Pending rows are now backfilled
        pending_1 = await store.get("jf-pending-1")
        assert pending_1 is not None
        assert pending_1.production_countries == ["JP"]
        assert pending_1.country_synced_at is not None
        assert pending_1.country_synced_at != already_synced_at

        # Mock was called exactly once with only the pending IDs
        assert client.get_items_by_ids.call_count == 1
        call_kwargs = client.get_items_by_ids.call_args.kwargs
        assert set(call_kwargs["ids"]) == {
            "jf-pending-1",
            "jf-pending-2",
            "jf-pending-3",
        }


class TestRunBackfillMissingFromUpstream:
    """Spec 25 T3.6 — Jellyfin returns fewer items than requested
    (deleted upstream after our last full sync)."""

    async def test_missing_items_marked_synced_with_empty_array(
        self, store: LibraryStore
    ) -> None:
        await store.upsert_many(
            [
                _make_row("jf-still-there", country_synced_at=None),
                _make_row("jf-deleted-upstream", country_synced_at=None),
            ]
        )
        # Jellyfin only returns the still-there item
        client = _mock_client_returning(
            [
                {
                    "Id": "jf-still-there",
                    "Name": "Still There",
                    "Type": "Movie",
                    "ProductionLocations": ["Japan"],
                }
            ]
        )

        await backfill_country.run_backfill(
            store=store, client=client, token="t", user_id="u", dry_run=False
        )

        # Still-there row gets ISO codes
        present = await store.get("jf-still-there")
        assert present is not None
        assert present.production_countries == ["JP"]
        assert present.country_synced_at is not None

        # Deleted-upstream row STILL gets country_synced_at stamped (with []).
        # This prevents the script from re-hitting Jellyfin every run for an
        # item that simply isn't there anymore — the operator's full-sync
        # tombstone path will eventually clean these up.
        gone = await store.get("jf-deleted-upstream")
        assert gone is not None
        assert gone.production_countries == []
        assert gone.country_synced_at is not None


class TestRunBackfillDryRun:
    """Spec 25 T3.4 — --dry-run reports counts without mutating data."""

    async def test_dry_run_no_writes(self, store: LibraryStore) -> None:
        await store.upsert_many(
            [
                _make_row("jf-1", country_synced_at=None),
                _make_row("jf-2", country_synced_at=None),
            ]
        )
        client = AsyncMock()
        # client should not be called in dry-run mode
        client.get_items_by_ids = AsyncMock(
            side_effect=AssertionError("dry-run must not call Jellyfin")
        )

        rows_processed, batches_run = await backfill_country.run_backfill(
            store=store, client=client, token="t", user_id="u", dry_run=True
        )
        assert rows_processed == 2
        assert batches_run == 1
        client.get_items_by_ids.assert_not_called()

        # Rows are unchanged — country_synced_at is still NULL
        row1 = await store.get("jf-1")
        assert row1 is not None
        assert row1.country_synced_at is None


class TestUpdateBatchTransaction:
    """Spec 25 — atomicity check: a per-batch transaction commits both
    production_countries and country_synced_at together."""

    async def test_update_persists_both_columns(self, store: LibraryStore) -> None:
        await store.upsert_many([_make_row("jf-1", country_synced_at=None)])
        await backfill_country._update_row_country_fields(
            store, jellyfin_id="jf-1", iso_codes=["JP"], now=12345
        )
        await store._conn.commit()
        row = await store.get("jf-1")
        assert row is not None
        assert row.production_countries == ["JP"]
        assert row.country_synced_at == 12345


class TestMapLocations:
    """Spec 25 — script's local helper mirrors the engine's per-sync-run dedup."""

    def test_maps_known_country(self) -> None:
        seen: set[str] = set()
        result = backfill_country._map_locations(["Japan"], seen)
        assert result == ["JP"]
        assert seen == set()

    def test_co_production_sorted(self) -> None:
        seen: set[str] = set()
        result = backfill_country._map_locations(
            ["United States of America", "Germany"], seen
        )
        assert result == ["DE", "US"]

    def test_unmappable_skipped_and_recorded_in_seen(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        seen: set[str] = set()
        with caplog.at_level(logging.WARNING):
            result = backfill_country._map_locations(["Atlantis"], seen)
        assert result == []
        assert "Atlantis" in seen
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1

    def test_dedup_within_run(self, caplog: pytest.LogCaptureFixture) -> None:
        import logging

        seen: set[str] = set()
        with caplog.at_level(logging.WARNING):
            backfill_country._map_locations(["Atlantis"], seen)
            backfill_country._map_locations(["Atlantis"], seen)
            backfill_country._map_locations(["Atlantis", "Japan"], seen)
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
