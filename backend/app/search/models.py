"""Request/response models for the semantic search endpoint."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

# --- Embedding prefix constants (nomic-embed-text asymmetric retrieval) ---

DOCUMENT_PREFIX = "search_document: "
"""Prepended to library item text at the embedding call-site in the worker."""

QUERY_PREFIX = "search_query: "
"""Prepended to user query text before embedding in the search service."""


# --- Status enum ---


class SearchStatus(StrEnum):
    """Embedding completeness status returned with every search response."""

    OK = "ok"
    NO_EMBEDDINGS = "no_embeddings"
    PARTIAL_EMBEDDINGS = "partial_embeddings"


# --- Request / response models ---


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
    community_rating: float | None = None
    runtime_minutes: int | None = None
    jellyfin_web_url: str | None = None


class SearchResponse(BaseModel):
    """Full search response with results and metadata."""

    status: SearchStatus
    results: list[SearchResultItem]
    total_candidates: int
    filtered_count: int
    query_time_ms: int


class SearchUnavailableError(Exception):
    """Raised when the search pipeline cannot complete (e.g., Ollama down)."""
