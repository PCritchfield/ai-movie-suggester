"""Data models and exceptions for the incremental sync engine."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel


@dataclass(frozen=True, slots=True)
class SyncResult:
    """Immutable summary of a completed sync run."""

    started_at: int
    completed_at: int
    status: str
    total_items: int
    items_created: int
    items_updated: int
    items_deleted: int
    items_unchanged: int
    items_failed: int
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class SyncRunRow:
    """A sync run record as stored in the database."""

    id: int
    started_at: int
    completed_at: int | None
    status: str
    total_items: int
    items_created: int
    items_updated: int
    items_deleted: int
    items_unchanged: int
    items_failed: int
    error_message: str | None


# Sync run status constants
SYNC_STATUS_COMPLETED = "completed"
SYNC_STATUS_FAILED = "failed"


class SyncAlreadyRunningError(Exception):
    """Raised when a sync is requested while another is already in progress."""


class SyncConfigError(Exception):
    """Raised when sync engine configuration is invalid or missing."""


@dataclass(slots=True)
class SyncState:
    """Mutable accumulator for tracking progress during a sync run."""

    started_at: int
    pages_processed: int
    items_processed: int
    items_created: int
    items_updated: int
    items_unchanged: int
    items_failed: int


# --- Pydantic API response models (Task 4.0) ---


class SyncTriggerResponse(BaseModel):
    """Response body for POST /api/admin/sync."""

    message: str
    status: str


class SyncProgressResponse(BaseModel):
    """In-flight sync progress snapshot."""

    pages_processed: int
    items_processed: int
    items_created: int
    items_updated: int
    items_unchanged: int
    items_failed: int


class SyncLastRunResponse(BaseModel):
    """Serialized last sync run for the status endpoint."""

    id: int
    started_at: int
    completed_at: int | None = None
    status: str
    total_items: int
    items_created: int
    items_updated: int
    items_deleted: int
    items_unchanged: int
    items_failed: int
    error_message: str | None = None


class SyncStatusResponse(BaseModel):
    """Response body for GET /api/admin/sync/status."""

    status: str
    started_at: int | None = None
    progress: SyncProgressResponse | None = None
    last_run: SyncLastRunResponse | None = None
