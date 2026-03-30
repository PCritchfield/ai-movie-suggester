"""Data models and exceptions for the incremental sync engine."""

from __future__ import annotations

from dataclasses import dataclass


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
