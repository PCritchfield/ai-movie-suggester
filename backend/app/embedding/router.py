"""Admin API endpoints for embedding worker observability."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Request

from app.embedding.models import EmbeddingFailedItem, EmbeddingStatusResponse
from app.sync.dependencies import require_admin

if TYPE_CHECKING:
    from app.auth.models import SessionMeta

_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/embedding", tags=["admin"])


@router.get("/status", response_model=EmbeddingStatusResponse)
async def embedding_status(
    request: Request,
    _: SessionMeta = Depends(require_admin),  # noqa: B008
) -> EmbeddingStatusResponse:
    """Return embedding worker status: queue counts, worker state, failed items."""
    # Read worker state
    try:
        worker = request.app.state.embedding_worker
        worker_status = worker.status
        last_batch_at = worker.last_batch_at
        last_error = worker.last_error
    except AttributeError:
        worker_status = "idle"
        last_batch_at = None
        last_error = None

    # Read queue counts
    lib_store = request.app.state.library_store
    queue_counts = await lib_store.get_queue_counts()

    # Read failed items
    failed_rows = await lib_store.get_failed_items()
    failed_items = [
        EmbeddingFailedItem(
            jellyfin_id=row["jellyfin_id"],
            error_message=row["error_message"],
            retry_count=row["retry_count"],
            last_attempted_at=row["last_attempted_at"],
        )
        for row in failed_rows
    ]

    # Read total vector count
    try:
        vec_repo = request.app.state.vec_repo
        total_vectors = await vec_repo.count()
    except Exception:
        total_vectors = 0

    # Read batch size from settings
    try:
        settings = request.app.state.settings
        batch_size = settings.embedding_batch_size
    except AttributeError:
        batch_size = 10  # default fallback

    return EmbeddingStatusResponse(
        status=worker_status,
        pending=queue_counts.get("pending", 0),
        processing=queue_counts.get("processing", 0),
        failed=queue_counts.get("failed", 0),
        total_vectors=total_vectors,
        last_batch_at=last_batch_at,
        last_error=last_error,
        batch_size=batch_size,
        failed_items=failed_items,
    )
