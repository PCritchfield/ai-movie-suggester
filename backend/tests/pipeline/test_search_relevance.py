"""Search relevance assertions against curated query pairings.

These tests validate that vector search returns contextually relevant
results for known queries using real Ollama embeddings and the 35
fixture items from Spec 22.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import pytest

from app.ollama.client import OllamaEmbeddingClient
from app.search.models import QUERY_PREFIX
from tests.pipeline.conftest import EMBED_MODEL, OLLAMA_HOST

if TYPE_CHECKING:
    from app.library.store import LibraryStore
    from app.vectors.repository import SqliteVecRepository


async def _search(
    query: str,
    embed_client: OllamaEmbeddingClient,
    vec_repo: SqliteVecRepository,
    library_store: LibraryStore,
    limit: int = 5,
) -> list[tuple[str, float]]:
    """Embed a query and search, returning (title, score) tuples."""
    result = await embed_client.embed(QUERY_PREFIX + query)
    search_results = await vec_repo.search(result.vector, limit=limit)
    items = await library_store.get_many([r.jellyfin_id for r in search_results])
    id_to_title = {item.jellyfin_id: item.title for item in items}
    return [
        (id_to_title.get(r.jellyfin_id, r.jellyfin_id), r.score) for r in search_results
    ]


@pytest.fixture
async def embed_client() -> OllamaEmbeddingClient:
    """Embedding client for search queries — function-scoped httpx client."""
    async with httpx.AsyncClient(timeout=120.0) as http:
        yield OllamaEmbeddingClient(  # type: ignore[misc]
            base_url=OLLAMA_HOST,
            http_client=http,
            embed_model=EMBED_MODEL,
        )


@pytest.mark.pipeline
async def test_search_alien_but_funny(
    embedded_library: SqliteVecRepository,
    pipeline_library_store: LibraryStore,
    embed_client: OllamaEmbeddingClient,
) -> None:
    """'something like Alien but funny' returns a sci-fi comedy in top 5."""
    expected = {"Galaxy Quest", "Mars Attacks!", "Shaun of the Dead"}
    results = await _search(
        "something like Alien but funny",
        embed_client,
        embedded_library,
        pipeline_library_store,
    )
    titles = {title for title, _score in results}
    assert titles & expected, (
        f"Expected one of {sorted(expected)} in top 5, got: "
        f"{[(t, f'{s:.4f}') for t, s in results]}"
    )


@pytest.mark.pipeline
async def test_search_space_opera(
    embedded_library: SqliteVecRepository,
    pipeline_library_store: LibraryStore,
    embed_client: OllamaEmbeddingClient,
) -> None:
    """'space opera TV show' returns at least one space opera series in top 5."""
    expected = {"Babylon 5", "Stargate SG-1", "Battlestar Galactica"}
    results = await _search(
        "space opera TV show",
        embed_client,
        embedded_library,
        pipeline_library_store,
    )
    titles = {title for title, _score in results}
    assert titles & expected, (
        f"Expected one of {sorted(expected)} in top 5, got: "
        f"{[(t, f'{s:.4f}') for t, s in results]}"
    )


@pytest.mark.pipeline
async def test_search_cozy_mystery(
    embedded_library: SqliteVecRepository,
    pipeline_library_store: LibraryStore,
    embed_client: OllamaEmbeddingClient,
) -> None:
    """'cozy murder mystery' returns at least one cozy mystery show in top 5."""
    expected = {"Midsomer Murders", "Death in Paradise"}
    results = await _search(
        "cozy murder mystery",
        embed_client,
        embedded_library,
        pipeline_library_store,
    )
    titles = {title for title, _score in results}
    assert titles & expected, (
        f"Expected one of {sorted(expected)} in top 5, got: "
        f"{[(t, f'{s:.4f}') for t, s in results]}"
    )
