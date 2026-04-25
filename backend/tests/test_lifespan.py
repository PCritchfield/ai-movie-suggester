# backend/tests/test_lifespan.py
"""Tests for application lifespan: Ollama client wiring and shutdown order."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING
from unittest.mock import patch

import httpx
import pytest

from app.ollama.client import OllamaEmbeddingClient
from app.ollama.text_builder import build_sections
from tests.conftest import make_test_client

if TYPE_CHECKING:
    from app.jellyfin.models import LibraryItem


def _item_to_text(item: LibraryItem) -> str:
    """Build composite text from a LibraryItem's metadata fields."""
    return build_sections(
        title=item.name,
        overview=item.overview,
        genres=item.genres,
        production_year=item.production_year,
        runtime_minutes=item.runtime_minutes,
    )


class TestLifespanOllamaWiring:
    """Verify Ollama client is wired into app.state during lifespan."""

    def test_ollama_client_set_on_app_state(self) -> None:
        """After lifespan startup, app.state.ollama_client is set."""
        client = make_test_client()
        try:
            app = client.app
            assert hasattr(app, "state")
            assert hasattr(app.state, "ollama_client")  # type: ignore[union-attr]
            assert isinstance(app.state.ollama_client, OllamaEmbeddingClient)  # type: ignore[union-attr]
        finally:
            client.close()


class TestLifespanShutdownOrder:
    """Verify LIFO shutdown order: Ollama httpx closed before Jellyfin."""

    def test_lifo_shutdown_order(self) -> None:
        """Ollama httpx.aclose() is called before Jellyfin httpx.aclose()."""
        close_order: list[str] = []
        # Track long-lived clients by their timeout signature.
        # Jellyfin: scalar timeout (e.g. 10). Ollama: httpx.Timeout object.
        # Health-check clients are created via `async with` and auto-close —
        # they don't go through the shutdown path, so we skip them.

        original_async_client = httpx.AsyncClient

        def _make_tracked_client(*args, **kwargs):  # noqa: ANN002, ANN003
            real_client = original_async_client(*args, **kwargs)
            original_aclose = real_client.aclose

            # Identify by timeout type: Ollama uses httpx.Timeout object,
            # Jellyfin uses a scalar int/float. Health-check clients use
            # the default timeout (no explicit kwarg) — label them for
            # tracking but they won't appear in shutdown since they
            # auto-close via `async with`.
            timeout_arg = kwargs.get("timeout")
            if isinstance(timeout_arg, httpx.Timeout):
                label = "ollama"
            elif timeout_arg is not None:
                label = "jellyfin"
            else:
                label = "healthcheck"

            async def tracked_aclose() -> None:
                close_order.append(label)
                await original_aclose()

            real_client.aclose = tracked_aclose  # type: ignore[assignment]
            return real_client

        with patch("app.main.httpx.AsyncClient", side_effect=_make_tracked_client):
            test_client = make_test_client()
            # Trigger lifespan shutdown via __exit__ (close() alone doesn't do it)
            test_client.__exit__(None, None, None)

        # Verify both long-lived clients were closed during shutdown
        assert "ollama" in close_order, f"ollama not found in {close_order}"
        assert "jellyfin" in close_order, f"jellyfin not found in {close_order}"

        # Verify Ollama closed before Jellyfin (LIFO)
        ollama_idx = close_order.index("ollama")
        jellyfin_idx = close_order.index("jellyfin")
        assert ollama_idx < jellyfin_idx, (
            f"Expected LIFO order: Ollama before Jellyfin, got order: {close_order}"
        )


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


@pytest.mark.ollama_integration
class TestFullPipelineIntegration:
    """Full pipeline: LibraryItem -> composite text -> embed -> 768-dim vector."""

    async def test_full_pipeline_returns_768_dims(self) -> None:
        from app.jellyfin.models import LibraryItem

        item = LibraryItem.model_validate(
            {
                "Id": "alien-1979",
                "Name": "Alien",
                "Type": "Movie",
                "Overview": (
                    "In space, no one can hear you scream. A crew aboard a "
                    "deep-space vessel encounters a terrifying alien lifeform."
                ),
                "Genres": ["Science Fiction", "Horror"],
                "ProductionYear": 1979,
            }
        )

        text = _item_to_text(item)

        async with httpx.AsyncClient(timeout=120) as http:
            client = OllamaEmbeddingClient(
                base_url="http://localhost:11434",
                http_client=http,
            )
            embedding = await client.embed(text)

        assert embedding.dimensions == 768
        assert len(embedding.vector) == 768

    async def test_semantic_similarity_scifi_vs_romcom(self) -> None:
        """Similar movies produce higher cosine similarity than dissimilar."""
        from app.jellyfin.models import LibraryItem

        alien = LibraryItem.model_validate(
            {
                "Id": "alien-1979",
                "Name": "Alien",
                "Type": "Movie",
                "Overview": (
                    "In space, no one can hear you scream. A terrifying "
                    "alien lifeform stalks a crew aboard a deep-space vessel."
                ),
                "Genres": ["Science Fiction", "Horror"],
                "ProductionYear": 1979,
            }
        )
        aliens = LibraryItem.model_validate(
            {
                "Id": "aliens-1986",
                "Name": "Aliens",
                "Type": "Movie",
                "Overview": (
                    "This time it's war. Ellen Ripley returns to the planet "
                    "where the alien creatures were first found, now overrun."
                ),
                "Genres": ["Action", "Science Fiction", "Horror"],
                "ProductionYear": 1986,
            }
        )
        romcom = LibraryItem.model_validate(
            {
                "Id": "notting-hill-1999",
                "Name": "Notting Hill",
                "Type": "Movie",
                "Overview": (
                    "A bookshop owner in Notting Hill falls in love with a "
                    "famous American actress."
                ),
                "Genres": ["Romance", "Comedy"],
                "ProductionYear": 1999,
            }
        )

        text_alien = _item_to_text(alien)
        text_aliens = _item_to_text(aliens)
        text_romcom = _item_to_text(romcom)

        async with httpx.AsyncClient(timeout=120) as http:
            client = OllamaEmbeddingClient(
                base_url="http://localhost:11434",
                http_client=http,
            )
            vec_alien = (await client.embed(text_alien)).vector
            vec_aliens = (await client.embed(text_aliens)).vector
            vec_romcom = (await client.embed(text_romcom)).vector

        sim_scifi = _cosine_similarity(vec_alien, vec_aliens)
        sim_cross = _cosine_similarity(vec_alien, vec_romcom)

        assert sim_scifi > sim_cross, (
            f"Sci-fi pair similarity ({sim_scifi:.4f}) should be higher "
            f"than sci-fi vs romcom ({sim_cross:.4f})"
        )


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
