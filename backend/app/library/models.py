"""Data models for library metadata storage."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from app.sync.models import SyncResult, SyncRunRow


@dataclass(frozen=True, slots=True)
class LibraryItemRow:
    """A library item row as stored in the database.

    People contains actor names only (filtered from Jellyfin's full People list).
    JSON array fields (genres, tags, studios, people) are serialized to/from
    JSON strings by the store layer.
    """

    jellyfin_id: str
    title: str
    overview: str | None
    production_year: int | None
    genres: list[str]
    tags: list[str]
    studios: list[str]
    community_rating: float | None
    people: list[str]  # Actor names only
    content_hash: str  # SHA-256 hex digest
    synced_at: int  # Unix epoch seconds


@dataclass(frozen=True, slots=True)
class UpsertResult:
    """Result of a bulk upsert operation."""

    created: int
    updated: int
    unchanged: int


# --- Library store protocol ---


class LibraryStoreProtocol(Protocol):
    """Structural interface for library storage backends."""

    async def init(self) -> None: ...

    async def close(self) -> None: ...

    async def upsert_many(self, items: list[LibraryItemRow]) -> UpsertResult: ...

    async def get(self, jellyfin_id: str) -> LibraryItemRow | None: ...

    async def get_many(self, ids: list[str]) -> list[LibraryItemRow]: ...

    async def get_all_hashes(self) -> dict[str, str]: ...

    async def count(self) -> int: ...

    async def get_all_ids(self) -> set[str]: ...

    async def soft_delete_many(self, ids: list[str]) -> int: ...

    async def hard_delete_many(self, ids: list[str]) -> int: ...

    async def get_tombstoned_ids(self, older_than: int) -> list[str]: ...

    async def enqueue_for_embedding(self, ids: list[str]) -> int: ...

    async def count_pending_embeddings(self) -> int: ...

    async def get_last_sync_run(self) -> SyncRunRow | None: ...

    async def save_sync_run(self, run: SyncResult) -> None: ...
