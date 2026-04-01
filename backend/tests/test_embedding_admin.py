"""Tests for admin embedding API endpoints and lifespan wiring."""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.crypto import derive_keys, fernet_encrypt
from app.auth.models import SessionMeta, SessionRow
from app.embedding.router import router as embedding_router
from app.jellyfin.models import UserInfo
from tests.conftest import TEST_SECRET, make_test_client

# --- Test fixtures ---

_COOKIE_KEY, _COLUMN_KEY = derive_keys(TEST_SECRET)
_SESSION_ID = "test-session-id-embed"
_USER_ID = "uid-embed-admin-1"
_CSRF = "csrf-tok-embed"
_JF_TOKEN = "jf-embed-admin-tok-123"
_NOW = int(time.time())


def _make_session_row(*, is_expired: bool = False) -> SessionRow:
    return SessionRow(
        session_id=_SESSION_ID,
        user_id=_USER_ID,
        username="admin_user",
        server_name="TestJellyfin",
        token=_JF_TOKEN,
        csrf_token=_CSRF,
        created_at=_NOW,
        expires_at=_NOW - 100 if is_expired else _NOW + 3600,
    )


def _make_session_meta(*, is_expired: bool = False) -> SessionMeta:
    return SessionMeta(
        session_id=_SESSION_ID,
        user_id=_USER_ID,
        username="admin_user",
        server_name="TestJellyfin",
        expires_at=_NOW - 100 if is_expired else _NOW + 3600,
    )


def _make_user_info(*, is_admin: bool = True) -> UserInfo:
    return UserInfo.model_validate(
        {
            "Id": _USER_ID,
            "Name": "admin_user",
            "ServerId": "server-1",
            "HasPassword": True,
            "Policy": {"IsAdministrator": is_admin},
        }
    )


def _encrypted_cookie() -> str:
    return fernet_encrypt(_COOKIE_KEY, _SESSION_ID).decode("utf-8")


def _make_app(
    *,
    session_store: Any = None,
    jf_client: Any = None,
    library_store: Any = None,
    vec_repo: Any = None,
    embedding_worker: Any = None,
    app_settings: Any = None,
) -> FastAPI:
    """Build a minimal FastAPI app with embedding router and mocked state."""
    app = FastAPI()
    app.include_router(embedding_router)

    # Wire up app.state for the dependency chain
    app.state.cookie_key = _COOKIE_KEY
    app.state.session_store = session_store or AsyncMock()
    app.state.jellyfin_client = jf_client or AsyncMock()

    # Embedding-specific state
    if library_store is not None:
        app.state.library_store = library_store
    else:
        mock_lib = AsyncMock()
        mock_lib.get_queue_counts.return_value = {
            "pending": 0,
            "processing": 0,
            "failed": 0,
        }
        mock_lib.get_failed_items.return_value = []
        app.state.library_store = mock_lib

    if vec_repo is not None:
        app.state.vec_repo = vec_repo
    else:
        mock_vec = AsyncMock()
        mock_vec.count.return_value = 0
        app.state.vec_repo = mock_vec

    if embedding_worker is not None:
        app.state.embedding_worker = embedding_worker
    else:
        mock_worker = MagicMock()
        mock_worker.status = "idle"
        mock_worker.last_batch_at = None
        mock_worker.last_error = None
        app.state.embedding_worker = mock_worker

    if app_settings is not None:
        app.state.settings = app_settings
    else:
        mock_settings = MagicMock()
        mock_settings.embedding_batch_size = 10
        app.state.settings = mock_settings

    return app


def _make_admin_app(**overrides: Any) -> tuple[FastAPI, TestClient]:
    """Build an app with admin auth mocked and return (app, client)."""
    session_store = AsyncMock()
    session_store.get_metadata.return_value = _make_session_meta()
    session_store.get.return_value = _make_session_row()

    jf_client = AsyncMock()
    jf_client.get_user.return_value = _make_user_info(is_admin=True)

    app = _make_app(
        session_store=session_store,
        jf_client=jf_client,
        **overrides,
    )
    client = TestClient(app)
    return app, client


# --- Tests: GET /api/admin/embedding/status ---


class TestEmbeddingStatus:
    """Tests for GET /api/admin/embedding/status."""

    def test_returns_200_for_admin(self) -> None:
        """Admin user gets 200 with correct response shape."""
        _, client = _make_admin_app()
        resp = client.get(
            "/api/admin/embedding/status",
            cookies={"session_id": _encrypted_cookie()},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert "pending" in data
        assert "processing" in data
        assert "failed" in data
        assert "total_vectors" in data
        assert "last_batch_at" in data
        assert "last_error" in data
        assert "batch_size" in data
        assert "failed_items" in data
        assert isinstance(data["failed_items"], list)

    def test_returns_401_without_session(self) -> None:
        """No session cookie returns 401."""
        app = _make_app()
        client = TestClient(app)
        resp = client.get("/api/admin/embedding/status")
        assert resp.status_code == 401

    def test_returns_403_for_non_admin(self) -> None:
        """Non-admin user gets 403."""
        session_store = AsyncMock()
        session_store.get_metadata.return_value = _make_session_meta()
        session_store.get.return_value = _make_session_row()

        jf_client = AsyncMock()
        jf_client.get_user.return_value = _make_user_info(is_admin=False)

        app = _make_app(session_store=session_store, jf_client=jf_client)
        client = TestClient(app)
        resp = client.get(
            "/api/admin/embedding/status",
            cookies={"session_id": _encrypted_cookie()},
        )
        assert resp.status_code == 403

    def test_returns_real_queue_counts(self) -> None:
        """Response includes counts from the library store."""
        mock_lib = AsyncMock()
        mock_lib.get_queue_counts.return_value = {
            "pending": 5,
            "processing": 2,
            "failed": 1,
        }
        mock_lib.get_failed_items.return_value = [
            {
                "jellyfin_id": "item-fail-1",
                "error_message": "OllamaModelError: model not found",
                "retry_count": 3,
                "last_attempted_at": _NOW - 600,
            }
        ]

        mock_vec = AsyncMock()
        mock_vec.count.return_value = 42

        _, client = _make_admin_app(
            library_store=mock_lib,
            vec_repo=mock_vec,
        )
        resp = client.get(
            "/api/admin/embedding/status",
            cookies={"session_id": _encrypted_cookie()},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["pending"] == 5
        assert data["processing"] == 2
        assert data["failed"] == 1
        assert data["total_vectors"] == 42
        assert len(data["failed_items"]) == 1
        assert data["failed_items"][0]["jellyfin_id"] == "item-fail-1"

    def test_returns_worker_state(self) -> None:
        """Response includes worker status and last batch info."""
        mock_worker = MagicMock()
        mock_worker.status = "processing"
        mock_worker.last_batch_at = _NOW - 120
        mock_worker.last_error = "OllamaTimeoutError: timed out"

        _, client = _make_admin_app(embedding_worker=mock_worker)
        resp = client.get(
            "/api/admin/embedding/status",
            cookies={"session_id": _encrypted_cookie()},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "processing"
        assert data["last_batch_at"] == _NOW - 120
        assert data["last_error"] == "OllamaTimeoutError: timed out"

    def test_returns_batch_size_from_settings(self) -> None:
        """Response includes batch_size from settings."""
        mock_settings = MagicMock()
        mock_settings.embedding_batch_size = 25

        _, client = _make_admin_app(app_settings=mock_settings)
        resp = client.get(
            "/api/admin/embedding/status",
            cookies={"session_id": _encrypted_cookie()},
        )
        assert resp.status_code == 200
        assert resp.json()["batch_size"] == 25


# --- Tests: Lifespan wiring (Sub-task 5.13) ---


class TestLifespanEmbeddingWorker:
    """Verify embedding worker is created and registered during lifespan."""

    def test_embedding_worker_exists_on_app_state(self) -> None:
        """After app startup, app.state.embedding_worker is registered."""
        client = make_test_client()
        try:
            # The worker should be on app.state after lifespan startup
            worker = client.app.state.embedding_worker  # type: ignore[union-attr]
            assert worker is not None
            assert worker.status == "idle"
        finally:
            client.close()

    def test_embedding_worker_has_expected_properties(self) -> None:
        """The registered worker has the expected property interface."""
        client = make_test_client()
        try:
            worker = client.app.state.embedding_worker  # type: ignore[union-attr]
            # These properties must exist (per EmbeddingWorker interface)
            assert hasattr(worker, "status")
            assert hasattr(worker, "last_batch_at")
            assert hasattr(worker, "last_error")
            assert worker.last_batch_at is None
            assert worker.last_error is None
        finally:
            client.close()

    def test_settings_stored_on_app_state(self) -> None:
        """Settings are accessible via app.state.settings after startup."""
        client = make_test_client()
        try:
            s = client.app.state.settings  # type: ignore[union-attr]
            assert s is not None
            assert hasattr(s, "embedding_batch_size")
        finally:
            client.close()
