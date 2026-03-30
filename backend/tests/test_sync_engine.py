"""Tests for sync engine models and import paths (Spec 08)."""

from __future__ import annotations

import dataclasses


def test_sync_models_importable() -> None:
    """All sync models should be importable from app.sync.models."""
    from app.sync.models import (
        SyncAlreadyRunningError,
        SyncConfigError,
        SyncResult,
        SyncRunRow,
        SyncState,
    )

    # Verify dataclass fields
    result_fields = {f.name for f in dataclasses.fields(SyncResult)}
    assert "started_at" in result_fields
    assert "completed_at" in result_fields
    assert "status" in result_fields
    assert "total_items" in result_fields
    assert "items_created" in result_fields
    assert "items_updated" in result_fields
    assert "items_deleted" in result_fields
    assert "items_unchanged" in result_fields
    assert "items_failed" in result_fields
    assert "error_message" in result_fields

    row_fields = {f.name for f in dataclasses.fields(SyncRunRow)}
    assert "id" in row_fields
    assert "started_at" in row_fields
    assert "completed_at" in row_fields
    assert "status" in row_fields
    assert "error_message" in row_fields

    state_fields = {f.name for f in dataclasses.fields(SyncState)}
    assert "started_at" in state_fields
    assert "pages_processed" in state_fields
    assert "items_processed" in state_fields
    assert "items_created" in state_fields
    assert "items_updated" in state_fields
    assert "items_unchanged" in state_fields
    assert "items_failed" in state_fields

    # Verify exceptions are Exception subclasses
    assert issubclass(SyncAlreadyRunningError, Exception)
    assert issubclass(SyncConfigError, Exception)

    # Verify frozen/mutable
    result = SyncResult(
        started_at=1,
        completed_at=2,
        status="completed",
        total_items=10,
        items_created=5,
        items_updated=3,
        items_deleted=0,
        items_unchanged=2,
        items_failed=0,
    )
    assert result.error_message is None  # default

    state = SyncState(
        started_at=1,
        pages_processed=0,
        items_processed=0,
        items_created=0,
        items_updated=0,
        items_unchanged=0,
        items_failed=0,
    )
    state.pages_processed = 1  # mutable


def test_text_builder_same_object() -> None:
    """build_composite_text should be the same object from both import paths."""
    from app.library import text_builder as lib_tb
    from app.ollama import text_builder as ollama_tb

    assert lib_tb.build_composite_text is ollama_tb.build_composite_text
    assert lib_tb.CompositeTextResult is ollama_tb.CompositeTextResult
    assert lib_tb.TEMPLATE_VERSION is ollama_tb.TEMPLATE_VERSION
