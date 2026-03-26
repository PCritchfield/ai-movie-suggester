"""Pydantic models for Ollama embedding responses.

Defines the embedding result structure and the source enum used to
track whether an embedding was built from Jellyfin-only or
TMDb-enriched metadata.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


class EmbeddingSource(StrEnum):
    """Tracks the metadata source used to build the composite text."""

    JELLYFIN_ONLY = "jellyfin_only"
    TMDB_ENRICHED = "tmdb_enriched"


class EmbeddingResult(BaseModel):
    """Result of an Ollama embedding request."""

    vector: list[float]
    dimensions: int
    model: str
