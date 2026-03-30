"""Pydantic response models for API endpoints.

These drive OpenAPI schema generation.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

ServiceStatus = Literal["ok", "error"]


class EmbeddingsStatus(BaseModel):
    total: int = 0
    pending: int = 0


class LibrarySyncStatus(BaseModel):
    """Library sync status section of the health response."""

    last_run_at: int | None
    last_run_status: str | None
    items_in_library: int
    items_pending_embedding: int


class HealthResponse(BaseModel):
    """Response model for GET /health."""

    jellyfin: ServiceStatus
    ollama: ServiceStatus
    embeddings: EmbeddingsStatus
    library_sync: LibrarySyncStatus | None = None
