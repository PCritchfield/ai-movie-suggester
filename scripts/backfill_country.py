#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# ///
"""One-shot backfill — populate ``library_items.production_countries`` for
existing rows from Jellyfin's ``ProductionLocations`` field (Spec 25).

Reads rows where ``country_synced_at IS NULL AND deleted_at IS NULL``,
fetches metadata in batches of 50 IDs via ``JellyfinClient.get_items_by_ids``,
maps each ``ProductionLocations`` entry through ``app.library.country_codes``,
and updates each row in a per-batch transaction setting both
``production_countries`` (sorted ISO 3166-1 alpha-2 array) and
``country_synced_at`` (current epoch).

Prerequisites
-------------
**Run with `SYNC_INTERVAL_HOURS=0` set** (disabling the periodic sync engine)
to avoid concurrent writes to the same ``jellyfin_id``. The script asserts
this at startup and exits with code 1 if violated, naming the env var.

Idempotency
-----------
Re-runnable. Processes only rows with ``country_synced_at IS NULL``. Killing
the script mid-run leaves a coherent half-populated state; re-invoke to
resume.

Verification (run after script completes)
-----------------------------------------
::

    -- Sentinel coverage (expected: equals total active items, i.e. 100%):
    SELECT COUNT(*) FROM library_items WHERE country_synced_at IS NOT NULL;

    -- Country coverage (varies by library metadata quality; ≥95% target for
    -- well-tagged libraries. Live observation on a 1806-item library: 85.2%.
    -- Residual rows are items where Jellyfin returned no ProductionLocations
    -- — a metadata-quality gap at the Jellyfin layer, not a backfill bug.
    -- Fix path: refresh Jellyfin metadata for affected items, then re-run):
    SELECT COUNT(*) FROM library_items WHERE production_countries != '[]';

    -- ISO sanity (expected: rows like ["US"], ["JP"], ["DE","US"]; if you
    -- see full English names like ["United States of America"], the
    -- conversion did not run — abort and investigate):
    SELECT production_countries, COUNT(*) FROM library_items
    GROUP BY production_countries ORDER BY 2 DESC LIMIT 20;

Expected log output
-------------------
On a successful run, expect one INFO log per batch
(``processed batch N of M, X rows updated``) plus a final summary line.
Items where Jellyfin returns empty ``ProductionLocations`` are stamped with
``country_synced_at`` and an empty array (no warning). Unmappable country
names produce a single deduped WARNING per name per script run, e.g.
``Unmappable country name from Jellyfin: Atlantis``.

Restore step
------------
After the script exits cleanly, restore ``SYNC_INTERVAL_HOURS`` to its
prior value in your ``.env`` / docker-compose override and restart the
backend service.

Security
--------
**The script must not print, log, or include ``JELLYFIN_API_KEY`` in any
output, including startup banner, dry-run summary, error messages, or
exception tracebacks.** The value is accessed only via the existing
``Settings`` object; treat it like a root password (per
``ARCHITECTURE.md`` credential distinction).

Usage
-----
::

    # From the backend directory:
    SYNC_INTERVAL_HOURS=0 uv run python ../scripts/backfill_country.py [--dry-run]

    # Or via Make (T3.12):
    make backfill-country
    make backfill-country-dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time

import httpx

from app.config import Settings
from app.jellyfin.client import JellyfinClient
from app.library.country_codes import name_to_iso
from app.library.store import LibraryStore

_logger = logging.getLogger("backfill_country")

# Number of jellyfin_ids per /Users/{userId}/Items?Ids=... call. Tuned for
# Jellyfin's typical request-size limits and the script's per-batch
# transaction granularity. Vimes' migration ruling: per-item is too fragile
# under transient network failure; batch boundaries become natural
# checkpoints.
BATCH_SIZE = 50


async def _fetch_pending_ids(store: LibraryStore) -> list[str]:
    """Return jellyfin_ids that need country backfill, ordered deterministically."""
    cursor = await store._conn.execute(
        "SELECT jellyfin_id FROM library_items "
        "WHERE country_synced_at IS NULL AND deleted_at IS NULL "
        "ORDER BY jellyfin_id"
    )
    rows = await cursor.fetchall()
    return [row[0] for row in rows]


async def _update_row_country_fields(
    store: LibraryStore,
    *,
    jellyfin_id: str,
    iso_codes: list[str],
    now: int,
) -> None:
    """Update a single row with backfilled country data + sentinel timestamp."""
    import json

    await store._conn.execute(
        "UPDATE library_items SET production_countries = ?, country_synced_at = ? "
        "WHERE jellyfin_id = ?",
        (json.dumps(iso_codes), now, jellyfin_id),
    )


def _map_locations(names: list[str], unmappable_seen: set[str]) -> list[str]:
    """Map ProductionLocations strings to sorted ISO codes, dedup-warn unmappable."""
    iso_codes: list[str] = []
    for name in names:
        iso = name_to_iso(name)
        if iso is None:
            if name not in unmappable_seen:
                _logger.warning("Unmappable country name from Jellyfin: %s", name)
                unmappable_seen.add(name)
            continue
        iso_codes.append(iso)
    return sorted(iso_codes)


async def run_backfill(
    *,
    store: LibraryStore,
    client: JellyfinClient,
    token: str,
    user_id: str,
    dry_run: bool,
) -> tuple[int, int]:
    """Execute the backfill main loop. Returns (rows_processed, batches_run)."""
    pending = await _fetch_pending_ids(store)
    total = len(pending)
    if total == 0:
        _logger.info(
            "No rows to backfill — country_synced_at is non-null for all items."
        )
        return (0, 0)

    batches = [pending[i : i + BATCH_SIZE] for i in range(0, total, BATCH_SIZE)]

    if dry_run:
        _logger.info(
            "Dry-run: would process %d rows across %d batches of %d (~%d API calls)",
            total,
            len(batches),
            BATCH_SIZE,
            len(batches),
        )
        return (total, len(batches))

    unmappable_seen: set[str] = set()
    rows_processed = 0
    for batch_idx, batch_ids in enumerate(batches, start=1):
        items = await client.get_items_by_ids(
            token=token, user_id=user_id, ids=batch_ids
        )
        # Items deleted upstream don't appear in the response; we still
        # mark the row's country_synced_at so it doesn't get retried forever.
        items_by_id = {item.id: item for item in items}
        now = int(time.time())
        await store._conn.execute("BEGIN")
        try:
            for jellyfin_id in batch_ids:
                item = items_by_id.get(jellyfin_id)
                iso_codes = (
                    _map_locations(item.production_locations, unmappable_seen)
                    if item is not None
                    else []
                )
                await _update_row_country_fields(
                    store,
                    jellyfin_id=jellyfin_id,
                    iso_codes=iso_codes,
                    now=now,
                )
        except Exception:
            await store._conn.rollback()
            raise
        else:
            await store._conn.commit()
        rows_processed += len(batch_ids)
        _logger.info(
            "processed batch %d of %d, %d rows updated",
            batch_idx,
            len(batches),
            len(batch_ids),
        )

    _logger.info(
        "Backfill complete: %d rows processed across %d batches",
        rows_processed,
        len(batches),
    )
    return (rows_processed, len(batches))


async def main_async(*, dry_run: bool) -> int:
    settings = Settings()  # type: ignore[call-arg]

    # Spec 25 — Vimes' Mod #3 belt-and-braces: refuse to run if the periodic
    # sync engine is enabled (which would race the backfill on shared rows).
    if settings.sync_interval_hours != 0:
        _logger.error(
            "Refusing to run: SYNC_INTERVAL_HOURS=%s (must be 0). "
            "Disable the periodic sync engine before backfilling — see the "
            "module docstring for the operator runbook.",
            settings.sync_interval_hours,
        )
        return 1

    if settings.jellyfin_api_key is None:
        _logger.error(
            "Refusing to run: JELLYFIN_API_KEY is not configured. "
            "(Note: the value itself is never logged.)"
        )
        return 1
    if settings.jellyfin_admin_user_id is None:
        _logger.error("Refusing to run: JELLYFIN_ADMIN_USER_ID is not configured.")
        return 1

    store = LibraryStore(settings.library_db_path)
    await store.init()
    try:
        async with httpx.AsyncClient(timeout=settings.jellyfin_timeout) as http:
            client = JellyfinClient(base_url=settings.jellyfin_url, http_client=http)
            await run_backfill(
                store=store,
                client=client,
                token=settings.jellyfin_api_key.get_secret_value(),
                user_id=settings.jellyfin_admin_user_id,
                dry_run=dry_run,
            )
    finally:
        await store.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill production_countries for existing library rows (Spec 25)."
        ),
        epilog=(
            "Prerequisite: run with SYNC_INTERVAL_HOURS=0. "
            "After completion, restore the prior value and restart the backend."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report row counts and projected API calls without mutating any data.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    return asyncio.run(main_async(dry_run=args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
