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


class HealthResponse(BaseModel):
    """Response model for GET /health."""

    jellyfin: ServiceStatus
    ollama: ServiceStatus
    embeddings: EmbeddingsStatus
