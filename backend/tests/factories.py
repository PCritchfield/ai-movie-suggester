"""Shared test factories for library items, search results, and embeddings.

Centralises object construction so that test modules don't each maintain
their own near-identical helpers.
"""

from __future__ import annotations

from app.library.models import LibraryItemRow
from app.ollama.models import EmbeddingResult
from app.vectors.models import SearchResult


def make_library_item(
    jellyfin_id: str = "test-id",
    title: str = "Test Movie",
    overview: str | None = "A test movie.",
    production_year: int | None = 2020,
    genres: list[str] | None = None,
    tags: list[str] | None = None,
    studios: list[str] | None = None,
    people: list[str] | None = None,
    community_rating: float | None = 7.0,
    content_hash: str = "hash",
    synced_at: int = 1700000000,
    runtime_minutes: int | None = 120,
    directors: list[str] | None = None,
    writers: list[str] | None = None,
    composers: list[str] | None = None,
    official_rating: str | None = None,
) -> LibraryItemRow:
    return LibraryItemRow(
        jellyfin_id=jellyfin_id,
        title=title,
        overview=overview,
        production_year=production_year,
        genres=genres if genres is not None else ["Drama"],
        tags=tags if tags is not None else [],
        studios=studios if studios is not None else [],
        people=people if people is not None else [],
        community_rating=community_rating,
        content_hash=content_hash,
        synced_at=synced_at,
        runtime_minutes=runtime_minutes,
        directors=directors if directors is not None else [],
        writers=writers if writers is not None else [],
        composers=composers if composers is not None else [],
        official_rating=official_rating,
    )


def make_vector(seed: float = 0.1, dims: int = 768) -> list[float]:
    """Build a deterministic float vector for embedding tests."""
    return [seed + i * 0.001 for i in range(dims)]


def make_embedding_result(
    seed: float = 0.1,
    dims: int = 768,
    model: str = "nomic-embed-text",
) -> EmbeddingResult:
    return EmbeddingResult(
        vector=make_vector(seed, dims),
        dimensions=dims,
        model=model,
    )


def make_search_result(
    jellyfin_id: str = "test-id",
    score: float = 0.7,
    content_hash: str = "hash",
) -> SearchResult:
    return SearchResult(
        jellyfin_id=jellyfin_id,
        score=score,
        content_hash=content_hash,
    )
