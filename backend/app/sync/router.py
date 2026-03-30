"""Admin API endpoints for library sync management."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Request

from app.sync.dependencies import require_admin
from app.sync.models import (
    SyncAlreadyRunningError,
    SyncConfigError,
    SyncLastRunResponse,
    SyncProgressResponse,
    SyncStatusResponse,
    SyncTriggerResponse,
)

if TYPE_CHECKING:
    from app.auth.models import SessionMeta

_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/sync", tags=["admin"])


@router.post("/", status_code=202, response_model=SyncTriggerResponse)
async def trigger_sync(
    request: Request,
    _: SessionMeta = Depends(require_admin),  # noqa: B008
) -> SyncTriggerResponse:
    """Trigger a library sync as a background task.

    Returns 202 if sync started successfully.
    Returns 409 if a sync is already in progress.
    Returns 503 if sync configuration is missing.
    """
    sync_engine = request.app.state.sync_engine

    # Validate config BEFORE creating the task — otherwise the error
    # is raised inside the task and never reaches the HTTP response.
    try:
        sync_engine.validate_config()
    except SyncConfigError:
        raise HTTPException(status_code=503, detail="Sync not configured") from None

    # Check if already running (fast path)
    if sync_engine.is_running:
        raise HTTPException(status_code=409, detail="Sync already in progress")

    async def _run_sync() -> None:
        try:
            await sync_engine.run_sync()
        except SyncAlreadyRunningError:
            _logger.info("sync_already_running (race condition in trigger)")
        except Exception:
            _logger.error("background sync failed", exc_info=True)

    asyncio.create_task(_run_sync())
    return SyncTriggerResponse(message="Sync started", status="running")


@router.get("/status", response_model=SyncStatusResponse)
async def sync_status(
    request: Request,
    _: SessionMeta = Depends(require_admin),  # noqa: B008
) -> SyncStatusResponse:
    """Return current sync status: running progress or last completed run."""
    sync_engine = request.app.state.sync_engine

    # If a sync is currently running, return progress
    state = sync_engine.current_state
    if state is not None:
        return SyncStatusResponse(
            status="running",
            started_at=state.started_at,
            progress=SyncProgressResponse(
                pages_processed=state.pages_processed,
                items_processed=state.items_processed,
                items_created=state.items_created,
                items_updated=state.items_updated,
                items_unchanged=state.items_unchanged,
                items_failed=state.items_failed,
            ),
        )

    # Otherwise return the last completed run
    last_run = await sync_engine.get_last_run()
    if last_run is not None:
        return SyncStatusResponse(
            status=last_run.status,
            started_at=last_run.started_at,
            last_run=SyncLastRunResponse(
                id=last_run.id,
                started_at=last_run.started_at,
                completed_at=last_run.completed_at,
                status=last_run.status,
                total_items=last_run.total_items,
                items_created=last_run.items_created,
                items_updated=last_run.items_updated,
                items_deleted=last_run.items_deleted,
                items_unchanged=last_run.items_unchanged,
                items_failed=last_run.items_failed,
                error_message=last_run.error_message,
            ),
        )

    # No sync has ever run
    return SyncStatusResponse(status="idle")
