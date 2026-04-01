"""Tests for EmbeddingWorker.check_template_version().

Verifies that the worker detects stale template versions and re-enqueues
all library items for embedding when the stored version is behind the
current TEMPLATE_VERSION constant.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from app.embedding.worker import EmbeddingWorker
from app.library.store import LibraryStore
from app.ollama.client import OllamaEmbeddingClient
from app.vectors.repository import SqliteVecRepository
from tests.conftest import make_test_settings

_SETTINGS = make_test_settings()


def _make_worker(
    *,
    library_store: AsyncMock | None = None,
    vec_repo: AsyncMock | None = None,
) -> EmbeddingWorker:
    """Build an EmbeddingWorker with mocked dependencies."""
    ls = library_store or AsyncMock(spec=LibraryStore)
    vr = vec_repo or AsyncMock(spec=SqliteVecRepository)
    oc = AsyncMock(spec=OllamaEmbeddingClient)
    event = asyncio.Event()
    return EmbeddingWorker(
        library_store=ls,
        vec_repo=vr,
        ollama_client=oc,
        settings=_SETTINGS,
        sync_event=event,
    )


class TestCheckTemplateVersion:
    """check_template_version() behaviour under various stored versions."""

    async def test_absent_version_triggers_full_enqueue(self) -> None:
        """When no template version is stored (None), treat as 0 and re-enqueue all."""
        vec_repo = AsyncMock(spec=SqliteVecRepository)
        vec_repo.get_template_version.return_value = None

        lib_store = AsyncMock(spec=LibraryStore)
        lib_store.get_all_ids.return_value = {"id-1", "id-2", "id-3"}
        lib_store.enqueue_for_embedding.return_value = 3

        worker = _make_worker(library_store=lib_store, vec_repo=vec_repo)

        with patch("app.library.text_builder.TEMPLATE_VERSION", 1):
            await worker.check_template_version()

        lib_store.get_all_ids.assert_awaited_once()
        lib_store.enqueue_for_embedding.assert_awaited_once()

        enqueued_ids = lib_store.enqueue_for_embedding.call_args[0][0]
        assert sorted(enqueued_ids) == ["id-1", "id-2", "id-3"]

        vec_repo.set_template_version.assert_awaited_once_with(1)

    async def test_matching_version_is_noop(self) -> None:
        """When stored == current, no enqueue and no meta update."""
        vec_repo = AsyncMock(spec=SqliteVecRepository)
        vec_repo.get_template_version.return_value = 1

        lib_store = AsyncMock(spec=LibraryStore)
        worker = _make_worker(library_store=lib_store, vec_repo=vec_repo)

        with patch("app.library.text_builder.TEMPLATE_VERSION", 1):
            await worker.check_template_version()

        lib_store.enqueue_for_embedding.assert_not_awaited()
        vec_repo.set_template_version.assert_not_awaited()

    async def test_stale_version_triggers_full_enqueue(self) -> None:
        """When stored < current, all items re-enqueued and version updated."""
        vec_repo = AsyncMock(spec=SqliteVecRepository)
        vec_repo.get_template_version.return_value = 1

        lib_store = AsyncMock(spec=LibraryStore)
        lib_store.get_all_ids.return_value = {"a", "b"}
        lib_store.enqueue_for_embedding.return_value = 2

        worker = _make_worker(library_store=lib_store, vec_repo=vec_repo)

        with patch("app.library.text_builder.TEMPLATE_VERSION", 2):
            await worker.check_template_version()

        lib_store.get_all_ids.assert_awaited_once()
        lib_store.enqueue_for_embedding.assert_awaited_once()

        enqueued_ids = lib_store.enqueue_for_embedding.call_args[0][0]
        assert sorted(enqueued_ids) == ["a", "b"]

        vec_repo.set_template_version.assert_awaited_once_with(2)

    async def test_downgrade_is_noop(self) -> None:
        """When stored > current (downgrade), no enqueue and no meta update."""
        vec_repo = AsyncMock(spec=SqliteVecRepository)
        vec_repo.get_template_version.return_value = 5

        lib_store = AsyncMock(spec=LibraryStore)
        worker = _make_worker(library_store=lib_store, vec_repo=vec_repo)

        with patch("app.library.text_builder.TEMPLATE_VERSION", 3):
            await worker.check_template_version()

        lib_store.enqueue_for_embedding.assert_not_awaited()
        vec_repo.set_template_version.assert_not_awaited()

    async def test_idempotent_when_matching(self) -> None:
        """Calling check_template_version twice with matching version never enqueues."""
        vec_repo = AsyncMock(spec=SqliteVecRepository)
        vec_repo.get_template_version.return_value = 2

        lib_store = AsyncMock(spec=LibraryStore)
        worker = _make_worker(library_store=lib_store, vec_repo=vec_repo)

        with patch("app.library.text_builder.TEMPLATE_VERSION", 2):
            await worker.check_template_version()
            await worker.check_template_version()

        lib_store.enqueue_for_embedding.assert_not_awaited()
        vec_repo.set_template_version.assert_not_awaited()

    async def test_empty_library_still_updates_version(self) -> None:
        """When the library is empty, version is still updated (no items to enqueue)."""
        vec_repo = AsyncMock(spec=SqliteVecRepository)
        vec_repo.get_template_version.return_value = None

        lib_store = AsyncMock(spec=LibraryStore)
        lib_store.get_all_ids.return_value = set()

        worker = _make_worker(library_store=lib_store, vec_repo=vec_repo)

        with patch("app.library.text_builder.TEMPLATE_VERSION", 1):
            await worker.check_template_version()

        lib_store.enqueue_for_embedding.assert_not_awaited()
        vec_repo.set_template_version.assert_awaited_once_with(1)
