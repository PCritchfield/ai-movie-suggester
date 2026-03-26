"""Vector storage package — Protocol, models, and SQLite-vec implementation."""

from app.vectors.models import (
    COMPLETE,
    FAILED,
    PENDING,
    PROCESSING,
    VALID_STATUSES,
    SearchResult,
    VectorRecord,
    VectorRepositoryProtocol,
)
from app.vectors.repository import SqliteVecRepository

__all__ = [
    "COMPLETE",
    "FAILED",
    "PENDING",
    "PROCESSING",
    "SearchResult",
    "SqliteVecRepository",
    "VALID_STATUSES",
    "VectorRecord",
    "VectorRepositoryProtocol",
]
