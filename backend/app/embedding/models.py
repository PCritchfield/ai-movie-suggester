"""Pydantic response models for embedding admin endpoints."""

from __future__ import annotations

from pydantic import BaseModel


class EmbeddingFailedItem(BaseModel):
    """Detail for a single permanently-failed embedding queue item."""

    jellyfin_id: str
    error_message: str | None
    retry_count: int
    last_attempted_at: int | None


class EmbeddingStatusResponse(BaseModel):
    """Response model for GET /api/admin/embedding/status."""

    status: str
    pending: int
    processing: int
    failed: int
    total_vectors: int
    last_batch_at: int | None
    last_error: str | None
    batch_size: int
    failed_items: list[EmbeddingFailedItem]
