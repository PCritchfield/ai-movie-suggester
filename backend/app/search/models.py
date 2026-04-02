"""Request/response models for the semantic search endpoint."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    """POST /api/search request body."""

    query: str = Field(min_length=1, max_length=1000)
    limit: int = Field(default=10, ge=1, le=50)


class SearchResultItem(BaseModel):
    """A single search result with enriched metadata."""

    jellyfin_id: str
    title: str
    overview: str | None
    genres: list[str]
    year: int | None
    score: float
    poster_url: str


class SearchResponse(BaseModel):
    """Full search response with results and metadata."""

    status: Literal["ok", "no_embeddings", "partial_embeddings"]
    results: list[SearchResultItem]
    total_candidates: int
    filtered_count: int
    query_time_ms: int


class SearchUnavailableError(Exception):
    """Raised when the search pipeline cannot complete (e.g., Ollama down)."""
