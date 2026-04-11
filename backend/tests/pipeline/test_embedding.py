"""Pipeline pre-flight and embedding verification tests.

These tests validate Ollama reachability, model availability, and that
all fixture items are successfully embedded with real inference.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import pytest

from tests.integration.conftest import EXPECTED_TOTAL
from tests.pipeline.conftest import OLLAMA_HOST, REQUIRED_MODELS

if TYPE_CHECKING:
    from app.library.store import LibraryStore
    from app.vectors.repository import SqliteVecRepository


@pytest.mark.pipeline
async def test_ollama_reachable() -> None:
    """Ollama health endpoint returns 200."""
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(f"{OLLAMA_HOST}/")
        assert resp.status_code == 200, (
            f"Ollama not reachable at {OLLAMA_HOST} (status {resp.status_code})"
        )


@pytest.mark.pipeline
async def test_models_available(_ensure_models: None) -> None:
    """Both required models (nomic-embed-text, llama3.1:8b) are available."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{OLLAMA_HOST}/api/tags")
        resp.raise_for_status()
        available = {m["name"] for m in resp.json().get("models", [])}

        for model in REQUIRED_MODELS:
            assert model in available or f"{model}:latest" in available, (
                f"Model {model} not available in Ollama. Available: {sorted(available)}"
            )


@pytest.mark.pipeline
async def test_all_items_embedded(
    embedded_library: SqliteVecRepository,
    pipeline_library_store: LibraryStore,
) -> None:
    """All 35 fixture items produce vectors with 0 pending in queue."""
    vec_count = await embedded_library.count()
    assert vec_count >= EXPECTED_TOTAL, (
        f"Expected >= {EXPECTED_TOTAL} vectors, got {vec_count}"
    )

    pending = await pipeline_library_store.count_pending_embeddings()
    assert pending == 0, f"Expected 0 pending embeddings, got {pending}"
