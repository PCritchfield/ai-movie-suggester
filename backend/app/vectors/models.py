"""Data models for vector repository.

Defines the VectorRepositoryProtocol (structural subtyping), dataclasses
for vector records and search results, and embedding status constants.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

# Embedding status constants
PENDING = "pending"
PROCESSING = "processing"
COMPLETE = "complete"
FAILED = "failed"
VALID_STATUSES: frozenset[str] = frozenset({PENDING, PROCESSING, COMPLETE, FAILED})


@dataclass(frozen=True, slots=True)
class VectorRecord:
    """Metadata for a stored vector (excludes the embedding itself)."""

    jellyfin_id: str
    content_hash: str
    embedded_at: int
    embedding_status: str


@dataclass(frozen=True, slots=True)
class SearchResult:
    """A single result from a cosine-similarity search.

    ``score`` is a similarity score (higher = better) computed as
    ``1 - cosine_distance``.  Typical range for nomic-embed-text
    is 0.3–0.7.
    """

    jellyfin_id: str
    score: float
    content_hash: str


@runtime_checkable
class VectorRepositoryProtocol(Protocol):
    """Structural interface for vector storage backends."""

    async def init(self) -> None: ...

    async def close(self) -> None: ...

    async def upsert(
        self, jellyfin_id: str, embedding: list[float], content_hash: str
    ) -> None: ...

    async def upsert_many(self, items: list[tuple[str, list[float], str]]) -> None: ...

    async def get(self, jellyfin_id: str) -> VectorRecord | None: ...

    async def get_many(self, ids: list[str]) -> list[VectorRecord]: ...

    async def delete(self, jellyfin_id: str) -> None: ...

    async def delete_many(self, ids: list[str]) -> None: ...

    async def search(
        self, query_embedding: list[float], limit: int = 20
    ) -> list[SearchResult]: ...

    async def count(self) -> int: ...

    async def get_embedding_status(self, jellyfin_id: str) -> str | None: ...

    async def set_embedding_status(self, jellyfin_id: str, status: str) -> None: ...
