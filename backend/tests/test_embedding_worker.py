"""Unit tests for EmbeddingWorker (Spec 10, Task 3.0).

All dependencies are mocked — no real Ollama, SQLite, or sqlite-vec needed.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest

from app.chat.service import ChatPauseCounter
from app.embedding.worker import EmbeddingWorker
from app.library.store import LibraryStore
from app.ollama.client import OllamaEmbeddingClient
from app.ollama.errors import (
    OllamaConnectionError,
    OllamaError,
    OllamaModelError,
    OllamaTimeoutError,
)
from app.vectors.repository import SqliteVecRepository
from tests.conftest import make_test_settings
from tests.factories import make_embedding_result, make_library_item

if TYPE_CHECKING:
    from app.config import Settings
    from app.library.models import LibraryItemRow

# ---------------------------------------------------------------------------
# Local convenience wrapper — embedding worker tests use different defaults
# ---------------------------------------------------------------------------


def _make_row(**overrides: object) -> LibraryItemRow:
    """Thin wrapper around ``make_library_item`` with worker-specific defaults."""
    defaults: dict[str, object] = {
        "jellyfin_id": "jf-001",
        "title": "Galaxy Quest",
        "overview": "A comedy about sci-fi actors in space.",
        "production_year": 1999,
        "genres": ["Comedy", "Sci-Fi"],
        "community_rating": 7.4,
        "people": ["Tim Allen", "Sigourney Weaver"],
        "content_hash": "abc123",
    }
    defaults.update(overrides)
    return make_library_item(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def settings() -> Settings:
    return make_test_settings(
        embedding_batch_size=10,
        embedding_worker_interval_seconds=300,
        embedding_max_retries=3,
        embedding_cooldown_seconds=300,
    )


@pytest.fixture
def mock_library_store() -> AsyncMock:
    return AsyncMock(spec=LibraryStore)


@pytest.fixture
def mock_vec_repo() -> AsyncMock:
    return AsyncMock(spec=SqliteVecRepository)


@pytest.fixture
def mock_ollama() -> AsyncMock:
    return AsyncMock(spec=OllamaEmbeddingClient)


@pytest.fixture
def sync_event() -> asyncio.Event:
    return asyncio.Event()


@pytest.fixture
def pause_counter() -> ChatPauseCounter:
    return ChatPauseCounter()  # Default: not paused (count=0)


@pytest.fixture
def worker(
    mock_library_store: AsyncMock,
    mock_vec_repo: AsyncMock,
    mock_ollama: AsyncMock,
    settings: Settings,
    sync_event: asyncio.Event,
    pause_counter: ChatPauseCounter,
) -> EmbeddingWorker:
    return EmbeddingWorker(
        library_store=mock_library_store,
        vec_repo=mock_vec_repo,
        ollama_client=mock_ollama,
        settings=settings,
        sync_event=sync_event,
        pause_counter=pause_counter,
    )


# ---------------------------------------------------------------------------
# _build_text
# ---------------------------------------------------------------------------


class TestBuildText:
    def test_full_metadata(self) -> None:
        row = _make_row()
        text = EmbeddingWorker._build_text(row)
        assert text == (
            "search_document: Title: Galaxy Quest."
            " A comedy about sci-fi actors in space."
            " Genres: Comedy, Sci-Fi."
            " Year: 1999."
            " Runtime: 120 minutes."
            " Cast: Tim Allen, Sigourney Weaver."
        )

    def test_prepends_search_document_prefix(self) -> None:
        """The search_document: prefix is required by nomic-embed-text."""
        row = _make_row()
        text = EmbeddingWorker._build_text(row)
        assert text.startswith("search_document: ")

    def test_missing_overview(self) -> None:
        row = _make_row(overview=None)
        text = EmbeddingWorker._build_text(row)
        assert "Title: Galaxy Quest." in text
        assert "A comedy" not in text

    def test_empty_overview(self) -> None:
        row = _make_row(overview="   ")
        text = EmbeddingWorker._build_text(row)
        assert "Title: Galaxy Quest." in text
        # Whitespace-only overview is omitted
        parts = text.split(". ")
        assert not any(p.strip() == "" for p in parts if p)

    def test_missing_genres(self) -> None:
        row = _make_row(genres=[])
        text = EmbeddingWorker._build_text(row)
        assert "Genres:" not in text

    def test_missing_year(self) -> None:
        row = _make_row(production_year=None)
        text = EmbeddingWorker._build_text(row)
        assert "Year:" not in text

    def test_title_only(self) -> None:
        row = _make_row(
            overview=None,
            genres=[],
            production_year=None,
            runtime_minutes=None,
            people=[],
        )
        text = EmbeddingWorker._build_text(row)
        assert text == "search_document: Title: Galaxy Quest."

    def test_crew_and_tags_flow_through_from_row(self) -> None:
        """Worker wires directors/writers/composers/studios/tags into the text."""
        row = _make_row(
            directors=["Roger Corman"],
            writers=["Charles B. Griffith"],
            composers=["John Williams"],
            studios=["New World"],
            tags=["classic"],
        )
        text = EmbeddingWorker._build_text(row)
        assert "Directed by: Roger Corman." in text
        assert "Written by: Charles B. Griffith." in text
        assert "Music by: John Williams." in text
        assert "Studios: New World." in text
        assert "Tags: classic." in text


# ---------------------------------------------------------------------------
# process_cycle — happy path
# ---------------------------------------------------------------------------


class TestProcessCycleHappyPath:
    async def test_batch_embed_and_upsert(
        self,
        worker: EmbeddingWorker,
        mock_library_store: AsyncMock,
        mock_vec_repo: AsyncMock,
        mock_ollama: AsyncMock,
    ) -> None:
        """Happy path: 3 pending items are batch-embedded and upserted."""
        rows = [
            _make_row(jellyfin_id=f"jf-{i:03d}", content_hash=f"hash{i}")
            for i in range(3)
        ]
        items = [(r.jellyfin_id, 0) for r in rows]

        mock_ollama.health.return_value = True
        mock_library_store.get_retryable_items.return_value = items
        mock_library_store.claim_batch.return_value = 3
        mock_library_store.get_many.return_value = rows
        mock_ollama.embed_batch.return_value = [
            make_embedding_result(seed=i * 0.1) for i in range(3)
        ]
        mock_library_store.mark_embedded_many.return_value = 3

        await worker.process_cycle()

        mock_ollama.health.assert_awaited_once()
        mock_library_store.claim_batch.assert_awaited_once()
        mock_ollama.embed_batch.assert_awaited_once()
        mock_vec_repo.upsert_many.assert_awaited_once()
        mock_library_store.mark_embedded_many.assert_awaited_once_with(
            [r.jellyfin_id for r in rows]
        )
        assert worker.last_batch_at is not None


# ---------------------------------------------------------------------------
# process_cycle — early exits
# ---------------------------------------------------------------------------


class TestProcessCycleEarlyExit:
    async def test_ollama_unhealthy_skips_cycle(
        self,
        worker: EmbeddingWorker,
        mock_library_store: AsyncMock,
        mock_ollama: AsyncMock,
    ) -> None:
        """Ollama unhealthy -> cycle skipped, no queue modifications."""
        mock_library_store.get_retryable_items.return_value = [("jf-001", 0)]
        mock_ollama.health.return_value = False

        await worker.process_cycle()

        mock_library_store.get_retryable_items.assert_awaited_once()
        mock_library_store.claim_batch.assert_not_awaited()

    async def test_empty_queue_returns_early(
        self,
        worker: EmbeddingWorker,
        mock_library_store: AsyncMock,
        mock_ollama: AsyncMock,
    ) -> None:
        """Empty queue -> cycle returns early."""
        mock_ollama.health.return_value = True
        mock_library_store.get_retryable_items.return_value = []

        await worker.process_cycle()

        mock_library_store.claim_batch.assert_not_awaited()

    async def test_zero_claimed_returns_early(
        self,
        worker: EmbeddingWorker,
        mock_library_store: AsyncMock,
        mock_ollama: AsyncMock,
    ) -> None:
        """No items claimed (race condition) -> cycle returns early."""
        mock_ollama.health.return_value = True
        mock_library_store.get_retryable_items.return_value = [("jf-001", 0)]
        mock_library_store.claim_batch.return_value = 0

        await worker.process_cycle()

        mock_ollama.embed_batch.assert_not_awaited()


# ---------------------------------------------------------------------------
# process_cycle — batch failure -> individual fallback
# ---------------------------------------------------------------------------


class TestBatchFallback:
    async def test_batch_failure_falls_back_to_individual(
        self,
        worker: EmbeddingWorker,
        mock_library_store: AsyncMock,
        mock_vec_repo: AsyncMock,
        mock_ollama: AsyncMock,
    ) -> None:
        """embed_batch raises OllamaError -> each item processed individually."""
        rows = [
            _make_row(jellyfin_id="jf-001", content_hash="h1"),
            _make_row(jellyfin_id="jf-002", content_hash="h2"),
        ]
        items = [(r.jellyfin_id, 0) for r in rows]

        mock_ollama.health.return_value = True
        mock_library_store.get_retryable_items.return_value = items
        mock_library_store.claim_batch.return_value = 2
        mock_library_store.get_many.return_value = rows
        mock_ollama.embed_batch.side_effect = OllamaError("batch failed")
        mock_ollama.embed.return_value = make_embedding_result()

        await worker.process_cycle()

        # Batch was attempted and failed
        mock_ollama.embed_batch.assert_awaited_once()
        # Individual embeds were called for each item
        assert mock_ollama.embed.await_count == 2
        # Each item was upserted individually
        assert mock_vec_repo.upsert.await_count == 2
        # Each item was marked embedded individually
        assert mock_library_store.mark_embedded.await_count == 2


# ---------------------------------------------------------------------------
# Individual item processing — error classification
# ---------------------------------------------------------------------------


class TestErrorClassification:
    async def test_transient_error_marks_attempt(
        self,
        worker: EmbeddingWorker,
        mock_library_store: AsyncMock,
        mock_vec_repo: AsyncMock,
        mock_ollama: AsyncMock,
    ) -> None:
        """OllamaTimeoutError with retries remaining -> mark_attempt."""
        row = _make_row(jellyfin_id="jf-001")
        items = [("jf-001", 1)]  # retry_count=1, below max of 3

        mock_ollama.health.return_value = True
        mock_library_store.get_retryable_items.return_value = items
        mock_library_store.claim_batch.return_value = 1
        mock_library_store.get_many.return_value = [row]
        mock_ollama.embed_batch.side_effect = OllamaError("batch fail")
        mock_ollama.embed.side_effect = OllamaTimeoutError("timed out")

        await worker.process_cycle()

        mock_library_store.mark_attempt.assert_awaited_once()
        args = mock_library_store.mark_attempt.call_args
        assert args[0][0] == "jf-001"
        assert "OllamaTimeoutError" in args[0][1]
        mock_library_store.mark_failed_permanent.assert_not_awaited()

    async def test_permanent_error_model_not_found(
        self,
        worker: EmbeddingWorker,
        mock_library_store: AsyncMock,
        mock_vec_repo: AsyncMock,
        mock_ollama: AsyncMock,
    ) -> None:
        """OllamaModelError -> mark_failed_permanent immediately."""
        row = _make_row(jellyfin_id="jf-001")
        items = [("jf-001", 0)]

        mock_ollama.health.return_value = True
        mock_library_store.get_retryable_items.return_value = items
        mock_library_store.claim_batch.return_value = 1
        mock_library_store.get_many.return_value = [row]
        mock_ollama.embed_batch.side_effect = OllamaError("batch fail")
        mock_ollama.embed.side_effect = OllamaModelError("model not found")

        await worker.process_cycle()

        mock_library_store.mark_failed_permanent.assert_awaited_once()
        args = mock_library_store.mark_failed_permanent.call_args
        assert args[0][0] == "jf-001"
        assert "OllamaModelError" in args[0][1]
        assert "ollama pull nomic-embed-text" in args[0][1]
        mock_library_store.mark_attempt.assert_not_awaited()

    async def test_max_retries_exceeded_marks_permanent(
        self,
        worker: EmbeddingWorker,
        mock_library_store: AsyncMock,
        mock_vec_repo: AsyncMock,
        mock_ollama: AsyncMock,
    ) -> None:
        """Transient error with retry_count >= max_retries -> permanent."""
        row = _make_row(jellyfin_id="jf-001")
        items = [("jf-001", 3)]  # retry_count=3, equals max_retries

        mock_ollama.health.return_value = True
        mock_library_store.get_retryable_items.return_value = items
        mock_library_store.claim_batch.return_value = 1
        mock_library_store.get_many.return_value = [row]
        mock_ollama.embed_batch.side_effect = OllamaError("batch fail")
        mock_ollama.embed.side_effect = OllamaConnectionError("conn lost")

        await worker.process_cycle()

        mock_library_store.mark_failed_permanent.assert_awaited_once()
        args = mock_library_store.mark_failed_permanent.call_args
        assert "OllamaConnectionError" in args[0][1]
        mock_library_store.mark_attempt.assert_not_awaited()

    async def test_unexpected_exception_sanitized(
        self,
        worker: EmbeddingWorker,
        mock_library_store: AsyncMock,
        mock_vec_repo: AsyncMock,
        mock_ollama: AsyncMock,
    ) -> None:
        """Unexpected Exception -> stored message uses type name + docstring,
        never the raw str(exc)."""
        row = _make_row(jellyfin_id="jf-001")
        items = [("jf-001", 0)]

        mock_ollama.health.return_value = True
        mock_library_store.get_retryable_items.return_value = items
        mock_library_store.claim_batch.return_value = 1
        mock_library_store.get_many.return_value = [row]
        mock_ollama.embed_batch.side_effect = OllamaError("batch fail")
        mock_ollama.embed.side_effect = ValueError("secret path /foo/bar")

        await worker.process_cycle()

        mock_library_store.mark_attempt.assert_awaited_once()
        stored_msg = mock_library_store.mark_attempt.call_args[0][1]
        # Must NOT contain the raw secret message
        assert "secret path /foo/bar" not in stored_msg
        # Must contain the type name
        assert "ValueError" in stored_msg

    async def test_connection_error_transient(
        self,
        worker: EmbeddingWorker,
        mock_library_store: AsyncMock,
        mock_vec_repo: AsyncMock,
        mock_ollama: AsyncMock,
    ) -> None:
        """OllamaConnectionError with retries remaining -> mark_attempt."""
        row = _make_row(jellyfin_id="jf-001")
        items = [("jf-001", 0)]

        mock_ollama.health.return_value = True
        mock_library_store.get_retryable_items.return_value = items
        mock_library_store.claim_batch.return_value = 1
        mock_library_store.get_many.return_value = [row]
        mock_ollama.embed_batch.side_effect = OllamaError("batch fail")
        mock_ollama.embed.side_effect = OllamaConnectionError("cannot reach")

        await worker.process_cycle()

        mock_library_store.mark_attempt.assert_awaited_once()
        mock_library_store.mark_failed_permanent.assert_not_awaited()


# ---------------------------------------------------------------------------
# Lock prevents concurrent runs
# ---------------------------------------------------------------------------


class TestLockBehavior:
    async def test_lock_prevents_concurrent_processing(
        self,
        worker: EmbeddingWorker,
        mock_library_store: AsyncMock,
        mock_ollama: AsyncMock,
        sync_event: asyncio.Event,
    ) -> None:
        """When the lock is already held, the run loop skips the cycle."""
        # Pre-acquire the lock to simulate an in-flight cycle
        await worker._lock.acquire()

        mock_library_store.get_retryable_items.return_value = [("jf-001", 0)]
        mock_ollama.health.return_value = True

        # Start the run loop — it should see the lock and skip
        task = asyncio.create_task(worker.run())
        sync_event.set()
        await asyncio.sleep(0.05)

        # Queue methods should NOT have been called because lock was held
        mock_library_store.get_retryable_items.assert_not_awaited()

        # Clean up
        worker._lock.release()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


# ---------------------------------------------------------------------------
# Startup reset
# ---------------------------------------------------------------------------


class TestStartup:
    async def test_startup_resets_stale_processing(
        self,
        worker: EmbeddingWorker,
        mock_library_store: AsyncMock,
        mock_vec_repo: AsyncMock,
    ) -> None:
        """startup() calls reset_stale_processing and check_template_version."""
        mock_library_store.reset_stale_processing.return_value = 5
        # Task 4.0 added check_template_version() to startup — mock deps
        mock_vec_repo.get_template_version.return_value = 1

        await worker.startup()

        mock_library_store.reset_stale_processing.assert_awaited_once()
        mock_vec_repo.get_template_version.assert_awaited_once()


# ---------------------------------------------------------------------------
# Status tracking
# ---------------------------------------------------------------------------


class TestStatusTracking:
    def test_initial_status_is_idle(self, worker: EmbeddingWorker) -> None:
        assert worker.status == "idle"
        assert worker.last_batch_at is None
        assert worker.last_error is None

    async def test_status_updates_during_cycle(
        self,
        worker: EmbeddingWorker,
        mock_library_store: AsyncMock,
        mock_ollama: AsyncMock,
    ) -> None:
        """After a successful cycle, last_batch_at is set."""
        mock_ollama.health.return_value = True
        mock_library_store.get_retryable_items.return_value = []

        await worker.process_cycle()

        # Empty queue -> no batch processed, last_batch_at stays None
        assert worker.last_batch_at is None


# ---------------------------------------------------------------------------
# Run loop (unit-level, no real sleep)
# ---------------------------------------------------------------------------


class TestRunLoop:
    async def test_run_cancellation(
        self,
        worker: EmbeddingWorker,
        mock_library_store: AsyncMock,
        mock_ollama: AsyncMock,
        sync_event: asyncio.Event,
    ) -> None:
        """run() can be cancelled cleanly via CancelledError."""
        mock_ollama.health.return_value = True
        mock_library_store.get_retryable_items.return_value = []

        task = asyncio.create_task(worker.run())
        # Give the loop one iteration via the event
        sync_event.set()
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    async def test_run_processes_on_event(
        self,
        worker: EmbeddingWorker,
        mock_library_store: AsyncMock,
        mock_ollama: AsyncMock,
        sync_event: asyncio.Event,
    ) -> None:
        """run() wakes and processes when sync_event is set."""
        mock_ollama.health.return_value = True
        mock_library_store.get_retryable_items.return_value = []

        task = asyncio.create_task(worker.run())
        sync_event.set()
        await asyncio.sleep(0.05)

        # It should have checked the queue at least once
        assert mock_library_store.get_retryable_items.await_count >= 1

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    async def test_run_catches_cycle_exception(
        self,
        worker: EmbeddingWorker,
        mock_library_store: AsyncMock,
        mock_ollama: AsyncMock,
        sync_event: asyncio.Event,
    ) -> None:
        """run() catches unexpected exceptions in process_cycle and continues."""
        mock_library_store.get_retryable_items.side_effect = RuntimeError("boom")

        task = asyncio.create_task(worker.run())
        sync_event.set()
        await asyncio.sleep(0.05)

        # Worker should still be alive — not crashed
        assert not task.done()
        assert worker.last_error is not None
        assert "RuntimeError" in worker.last_error

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


# ---------------------------------------------------------------------------
# Missing item during processing
# ---------------------------------------------------------------------------


class TestMissingItem:
    async def test_missing_row_is_skipped_and_cleaned_up(
        self,
        worker: EmbeddingWorker,
        mock_library_store: AsyncMock,
        mock_vec_repo: AsyncMock,
        mock_ollama: AsyncMock,
    ) -> None:
        """If get_many() returns fewer rows than claimed, missing items are
        removed from the queue and the remaining items are still embedded."""
        items = [("jf-001", 0), ("jf-002", 0)]

        mock_ollama.health.return_value = True
        mock_library_store.get_retryable_items.return_value = items
        mock_library_store.claim_batch.return_value = 2
        # get_many returns only jf-002 (jf-001 deleted between claim and fetch)
        row2 = _make_row(jellyfin_id="jf-002", content_hash="h2")
        mock_library_store.get_many.return_value = [row2]
        mock_ollama.embed_batch.return_value = [make_embedding_result()]
        mock_library_store.mark_embedded_many.return_value = 1

        await worker.process_cycle()

        # Missing IDs cleaned up from queue; mark_embedded_many called
        # twice: once for missing IDs, once for batch success
        calls = mock_library_store.mark_embedded_many.call_args_list
        # First call: cleanup missing IDs
        assert calls[0][0][0] == ["jf-001"]
        # Second call: successful batch
        assert calls[1][0][0] == ["jf-002"]

        # Only 1 item should be in the embed batch (jf-002)
        mock_ollama.embed_batch.assert_awaited_once()
        texts_arg = mock_ollama.embed_batch.call_args[0][0]
        assert len(texts_arg) == 1


# ---------------------------------------------------------------------------
# Cooperative pause (chat priority)
# ---------------------------------------------------------------------------


class TestPauseCounter:
    async def test_embedding_worker_skips_on_pause(
        self,
        worker: EmbeddingWorker,
        mock_library_store: AsyncMock,
        pause_counter: ChatPauseCounter,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Paused counter -> process_cycle skips before queue fetch."""
        await pause_counter.acquire()  # count=1 -> paused

        import logging

        with caplog.at_level(logging.INFO, logger="app.embedding.worker"):
            await worker.process_cycle()

        mock_library_store.get_retryable_items.assert_not_awaited()
        assert any("chat_priority" in r.message for r in caplog.records)

    async def test_embedding_worker_resumes_on_unpause(
        self,
        worker: EmbeddingWorker,
        mock_library_store: AsyncMock,
        mock_ollama: AsyncMock,
        pause_counter: ChatPauseCounter,
    ) -> None:
        """Acquire then release counter -> next cycle processes normally."""
        # First: paused -> skip
        await pause_counter.acquire()
        await worker.process_cycle()
        mock_library_store.get_retryable_items.assert_not_awaited()

        # Second: unpaused -> normal processing
        await pause_counter.release()
        rows = [_make_row(jellyfin_id="jf-001", content_hash="h1")]
        items = [("jf-001", 0)]
        mock_ollama.health.return_value = True
        mock_library_store.get_retryable_items.return_value = items
        mock_library_store.claim_batch.return_value = 1
        mock_library_store.get_many.return_value = rows
        mock_ollama.embed_batch.return_value = [make_embedding_result()]
        mock_library_store.mark_embedded_many.return_value = 1

        await worker.process_cycle()

        mock_ollama.embed_batch.assert_awaited_once()

    async def test_embedding_fallback_breaks_on_pause(
        self,
        worker: EmbeddingWorker,
        mock_library_store: AsyncMock,
        mock_vec_repo: AsyncMock,
        mock_ollama: AsyncMock,
        pause_counter: ChatPauseCounter,
    ) -> None:
        """Pause counter acquired during fallback loop -> loop exits early."""
        rows = [
            _make_row(jellyfin_id="jf-001", content_hash="h1"),
            _make_row(jellyfin_id="jf-002", content_hash="h2"),
            _make_row(jellyfin_id="jf-003", content_hash="h3"),
        ]
        items = [(r.jellyfin_id, 0) for r in rows]

        mock_ollama.health.return_value = True
        mock_library_store.get_retryable_items.return_value = items
        mock_library_store.claim_batch.return_value = 3
        mock_library_store.get_many.return_value = rows

        # Batch embed fails -> triggers fallback loop
        # Side effect: acquire pause_counter when embed_batch is called
        async def _pause_and_fail(*args, **kwargs):
            await pause_counter.acquire()
            raise OllamaError("batch failed")

        mock_ollama.embed_batch.side_effect = _pause_and_fail

        await worker.process_cycle()

        # Batch was attempted
        mock_ollama.embed_batch.assert_awaited_once()
        # Individual embed was NOT called because counter is paused
        mock_ollama.embed.assert_not_awaited()
