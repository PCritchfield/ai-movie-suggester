"""Embedding worker — background loop that processes the embedding queue.

Pulls pending items from the embedding queue, generates embeddings via
Ollama, stores vectors in SQLite-vec, and handles transient/permanent
errors with retry and cooldown logic.

Error messages are sanitized — raw exception strings from unexpected
errors are never stored. Only type name + docstring are persisted.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import TYPE_CHECKING

from app.library.text_builder import build_sections
from app.ollama.errors import (
    OllamaConnectionError,
    OllamaError,
    OllamaModelError,
    OllamaTimeoutError,
)
from app.search.models import DOCUMENT_PREFIX

if TYPE_CHECKING:
    from app.config import Settings
    from app.library.models import LibraryItemRow
    from app.library.store import LibraryStore
    from app.ollama.client import OllamaEmbeddingClient
    from app.vectors.repository import SqliteVecRepository

logger = logging.getLogger(__name__)


class EmbeddingWorker:
    """Background worker that processes the embedding queue.

    Wakes on either a sync_event signal or a periodic interval, claims
    a batch of pending items, embeds them via Ollama, and stores the
    resulting vectors.  Errors are classified as transient (retry) or
    permanent (mark failed).
    """

    def __init__(
        self,
        library_store: LibraryStore,
        vec_repo: SqliteVecRepository,
        ollama_client: OllamaEmbeddingClient,
        settings: Settings,
        sync_event: asyncio.Event,
        pause_event: asyncio.Event | None = None,
    ) -> None:
        self._library_store = library_store
        self._vec_repo = vec_repo
        self._ollama_client = ollama_client
        self._settings = settings
        self._sync_event = sync_event
        self._pause_event = pause_event or asyncio.Event()
        if pause_event is None:
            self._pause_event.set()  # Default: not paused
        self._lock = asyncio.Lock()

        # State tracking
        self._status: str = "idle"
        self._last_batch_at: int | None = None
        self._last_error: str | None = None

    @property
    def status(self) -> str:
        """Current worker status."""
        return self._status

    @property
    def last_batch_at(self) -> int | None:
        """Unix timestamp of last completed batch, or None."""
        return self._last_batch_at

    @property
    def last_error(self) -> str | None:
        """Last error message, or None."""
        return self._last_error

    # ------------------------------------------------------------------
    # Text building from LibraryItemRow
    # ------------------------------------------------------------------

    @staticmethod
    def _build_text(item: LibraryItemRow) -> str:
        """Build composite text for embedding from a LibraryItemRow.

        Delegates to the shared ``build_sections`` core so template
        logic stays in one place — changes propagate automatically.

        Prepends the ``search_document:`` prefix required by
        nomic-embed-text for asymmetric retrieval.  The prefix is
        applied here (the embedding call-site), NOT inside
        ``build_sections()``, which remains a shared utility.
        """
        return DOCUMENT_PREFIX + build_sections(
            title=item.title,
            overview=item.overview,
            genres=item.genres,
            production_year=item.production_year,
        )

    # ------------------------------------------------------------------
    # Error handling helpers
    # ------------------------------------------------------------------

    async def _handle_retryable(
        self, jellyfin_id: str, retry_count: int, exc: BaseException
    ) -> None:
        """Handle a transient or unexpected error for a single item.

        Sanitizes the error message (never ``str(exc)``), then either
        marks the item as permanently failed (retries exhausted) or
        records the attempt for a later retry.
        """
        max_retries = self._settings.embedding_max_retries
        msg = f"{type(exc).__name__}: {type(exc).__doc__ or 'embedding failed'}"
        if retry_count >= max_retries:
            await self._library_store.mark_failed_permanent(jellyfin_id, msg)
            logger.error(
                "embedding_retries_exhausted jellyfin_id=%s retry_count=%d reason=%s",
                jellyfin_id,
                retry_count,
                msg,
            )
        else:
            await self._library_store.mark_attempt(jellyfin_id, msg)
            logger.warning(
                "embedding_transient_failure jellyfin_id=%s retry_count=%d reason=%s",
                jellyfin_id,
                retry_count,
                msg,
            )

    # ------------------------------------------------------------------
    # Individual item processing (fallback path)
    # ------------------------------------------------------------------

    async def _process_item(
        self,
        jellyfin_id: str,
        retry_count: int,
        text: str,
        content_hash: str,
    ) -> None:
        """Embed and store a single item with error classification."""
        try:
            result = await self._ollama_client.embed(text)
            await self._vec_repo.upsert(jellyfin_id, result.vector, content_hash)
            await self._library_store.mark_embedded(jellyfin_id)
            logger.info(
                "embedding_success jellyfin_id=%s dims=%d",
                jellyfin_id,
                result.dimensions,
            )
        except OllamaModelError:
            # Permanent — model not found, no point retrying
            model = self._settings.ollama_embed_model
            reason = f"OllamaModelError: model not found — run 'ollama pull {model}'"
            await self._library_store.mark_failed_permanent(jellyfin_id, reason)
            logger.error(
                "embedding_permanent_failure jellyfin_id=%s reason=%s",
                jellyfin_id,
                reason,
            )
        except (OllamaTimeoutError, OllamaConnectionError, OllamaError) as exc:
            await self._handle_retryable(jellyfin_id, retry_count, exc)
        except Exception as exc:
            await self._handle_retryable(jellyfin_id, retry_count, exc)

    # ------------------------------------------------------------------
    # Main processing cycle
    # ------------------------------------------------------------------

    async def process_cycle(self) -> None:
        """Run one embedding cycle: fetch queue, health check, embed, store."""
        # 0. Pause checkpoint — yield to chat when it has GPU priority
        batch_size = self._settings.embedding_batch_size
        cooldown = self._settings.embedding_cooldown_seconds
        max_retries = self._settings.embedding_max_retries

        if not self._pause_event.is_set():
            logger.info("embedding_cycle_skip reason=chat_priority")
            return

        # 1. Fetch retryable items (cheap DB query — check before Ollama)
        items = await self._library_store.get_retryable_items(
            cooldown, max_retries, batch_size
        )
        if not items:
            logger.debug("embedding_cycle_skip reason=empty_queue")
            return

        # 2. Health check (only when there's work to do)
        healthy = await self._ollama_client.health()
        if not healthy:
            logger.warning("embedding_cycle_skip reason=ollama_unhealthy")
            return

        # 3. Claim batch
        ids = [jid for jid, _ in items]
        claimed = await self._library_store.claim_batch(ids)
        if claimed == 0:
            logger.debug("embedding_cycle_skip reason=no_items_claimed")
            return

        logger.info("embedding_cycle_start claimed=%d", claimed)

        # Build a mapping of id -> (retry_count, text, content_hash)
        item_data: dict[str, tuple[int, str, str]] = {}
        retry_map = dict(items)
        rows = await self._library_store.get_many(ids)
        rows_by_id = {row.jellyfin_id: row for row in rows}
        missing_ids: list[str] = []
        for jid in ids:
            row = rows_by_id.get(jid)
            if row is None:
                logger.warning("embedding_item_missing jellyfin_id=%s", jid)
                missing_ids.append(jid)
                continue
            text = self._build_text(row)
            item_data[jid] = (retry_map[jid], text, row.content_hash)

        # Clean up queue rows for IDs whose library rows no longer exist —
        # they were claimed (status='processing') but have nothing to embed.
        if missing_ids:
            await self._library_store.mark_embedded_many(missing_ids)

        if not item_data:
            return

        # 4. Try batch embedding first
        texts = [text for _, text, _ in item_data.values()]
        ordered_ids = list(item_data.keys())
        content_hashes = [item_data[jid][2] for jid in ordered_ids]

        try:
            results = await self._ollama_client.embed_batch(texts)
            # Success — batch upsert vectors
            upsert_tuples: list[tuple[str, list[float], str]] = [
                (ordered_ids[i], results[i].vector, content_hashes[i])
                for i in range(len(results))
            ]
            await self._vec_repo.upsert_many(upsert_tuples)
            await self._library_store.mark_embedded_many(ordered_ids)
            logger.info("embedding_batch_success count=%d", len(results))
        except Exception:
            # 5. Batch failed — fall back to individual processing
            logger.warning(
                "embedding_batch_failed count=%d fallback=individual",
                len(ordered_ids),
            )
            for jid in ordered_ids:
                if not self._pause_event.is_set():
                    logger.info("embedding_fallback_skip reason=chat_priority")
                    break
                retry_count, text, content_hash = item_data[jid]
                await self._process_item(jid, retry_count, text, content_hash)

        self._last_batch_at = int(time.time())

    # ------------------------------------------------------------------
    # Template version detection
    # ------------------------------------------------------------------

    async def check_template_version(self) -> None:
        """Detect stale embeddings when TEMPLATE_VERSION changes.

        Compares the stored template version in _vec_meta against the
        current TEMPLATE_VERSION constant.  If the stored version is
        absent (None, treated as 0) or less than current, all active
        library items are re-enqueued for embedding and the stored
        version is updated.

        If stored >= current (match or downgrade), this is a no-op.
        """
        from app.library.text_builder import TEMPLATE_VERSION

        stored = await self._vec_repo.get_template_version()
        effective_stored = stored if stored is not None else 0

        if effective_stored >= TEMPLATE_VERSION:
            logger.info(
                "template_version_current stored=%s current=%d",
                stored,
                TEMPLATE_VERSION,
            )
            return

        logger.info(
            "template_version_stale stored=%s current=%d — re-enqueuing all items",
            stored,
            TEMPLATE_VERSION,
        )

        all_ids = await self._library_store.get_all_ids()
        if all_ids:
            count = await self._library_store.enqueue_for_embedding(list(all_ids))
            logger.info("template_version_re_enqueued count=%d", count)

        await self._vec_repo.set_template_version(TEMPLATE_VERSION)

    # ------------------------------------------------------------------
    # Startup reset + template check
    # ------------------------------------------------------------------

    async def startup(self) -> None:
        """Run one-time startup tasks before the processing loop.

        Resets stale 'processing' items from a previous crash, then
        checks whether the template version has changed (triggering
        a full re-embed if needed).
        """
        count = await self._library_store.reset_stale_processing()
        logger.info("embedding_startup_reset count=%d", count)

        await self.check_template_version()

    # ------------------------------------------------------------------
    # Run loop
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Long-running loop: wake on sync_event or interval, process."""
        interval = self._settings.embedding_worker_interval_seconds
        logger.info("embedding_worker_start interval_seconds=%d", interval)

        while True:
            # Wait for either sync_event or interval timeout
            event_task = asyncio.ensure_future(self._sync_event.wait())
            sleep_task = asyncio.ensure_future(asyncio.sleep(interval))
            done, pending = await asyncio.wait(
                {event_task, sleep_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

            if self._sync_event.is_set():
                self._sync_event.clear()

            # Try to acquire lock (non-blocking)
            if self._lock.locked():
                logger.debug("embedding_cycle_skip reason=already_processing")
                continue

            async with self._lock:
                try:
                    self._status = "processing"
                    await self.process_cycle()
                except asyncio.CancelledError:
                    logger.info("embedding_worker_cancelled")
                    raise
                except Exception as exc:
                    self._last_error = (
                        f"{type(exc).__name__}:"
                        f" {type(exc).__doc__ or 'unexpected error'}"
                    )
                    logger.exception(
                        "embedding_cycle_error reason=%s",
                        self._last_error,
                    )
                finally:
                    self._status = "idle"
