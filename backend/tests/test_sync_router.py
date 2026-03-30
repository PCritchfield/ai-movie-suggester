"""Tests for admin sync API endpoints and require_admin dependency."""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.auth.crypto import derive_keys, fernet_encrypt
from app.auth.models import SessionMeta, SessionRow
from app.jellyfin.models import UserInfo
from app.sync.dependencies import require_admin
from app.sync.models import (
    SyncConfigError,
    SyncRunRow,
    SyncState,
)
from app.sync.router import router as sync_router
from tests.conftest import TEST_SECRET

# --- Test fixtures ---

_COOKIE_KEY, _COLUMN_KEY = derive_keys(TEST_SECRET)
_SESSION_ID = "test-session-id-abc"
_USER_ID = "uid-admin-1"
_CSRF = "csrf-tok"
_JF_TOKEN = "jf-admin-tok-123"
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


_admin_dep = Depends(require_admin)


def _make_app(
    *,
    sync_engine: Any = None,
    session_store: Any = None,
    jf_client: Any = None,
) -> FastAPI:
    """Build a minimal FastAPI app with sync router and mocked state."""
    app = FastAPI()
    app.include_router(sync_router)

    # Wire up app.state for the dependency chain
    app.state.cookie_key = _COOKIE_KEY
    app.state.session_store = session_store or AsyncMock()
    app.state.jellyfin_client = jf_client or AsyncMock()
    app.state.sync_engine = sync_engine or MagicMock()

    return app


# --- Tests: require_admin dependency ---


class TestRequireAdmin:
    """Tests for the require_admin dependency."""

    def test_returns_session_for_admin_user(self) -> None:
        """Admin user gets through require_admin successfully."""
        session_store = AsyncMock()
        session_store.get_metadata.return_value = _make_session_meta()
        session_store.get.return_value = _make_session_row()

        jf_client = AsyncMock()
        jf_client.get_user.return_value = _make_user_info(is_admin=True)

        app = _make_app(session_store=session_store, jf_client=jf_client)

        @app.get("/test-admin")
        async def _test_endpoint(
            session: SessionMeta = _admin_dep,  # noqa: B008
        ) -> dict[str, str]:
            return {"user_id": session.user_id}

        client = TestClient(app)
        resp = client.get(
            "/test-admin",
            cookies={"session_id": _encrypted_cookie()},
        )
        assert resp.status_code == 200
        assert resp.json()["user_id"] == _USER_ID

    def test_rejects_non_admin_user(self) -> None:
        """Non-admin user gets 403."""
        session_store = AsyncMock()
        session_store.get_metadata.return_value = _make_session_meta()
        session_store.get.return_value = _make_session_row()

        jf_client = AsyncMock()
        jf_client.get_user.return_value = _make_user_info(is_admin=False)

        app = _make_app(session_store=session_store, jf_client=jf_client)

        @app.get("/test-admin")
        async def _test_endpoint(
            session: SessionMeta = _admin_dep,  # noqa: B008
        ) -> dict[str, str]:
            return {"user_id": session.user_id}

        client = TestClient(app)
        resp = client.get(
            "/test-admin",
            cookies={"session_id": _encrypted_cookie()},
        )
        assert resp.status_code == 403
        assert "Admin access required" in resp.json()["detail"]

    def test_rejects_unauthenticated_user(self) -> None:
        """No session cookie -> 401."""
        app = _make_app()

        @app.get("/test-admin")
        async def _test_endpoint(
            session: SessionMeta = _admin_dep,  # noqa: B008
        ) -> dict[str, str]:
            return {"user_id": session.user_id}

        client = TestClient(app)
        resp = client.get("/test-admin")
        assert resp.status_code == 401

    def test_rejects_when_session_row_missing(self) -> None:
        """Valid cookie but session row gone from store -> 401."""
        session_store = AsyncMock()
        session_store.get_metadata.return_value = _make_session_meta()
        session_store.get.return_value = None  # Row deleted

        app = _make_app(session_store=session_store)

        @app.get("/test-admin")
        async def _test_endpoint(
            session: SessionMeta = _admin_dep,  # noqa: B008
        ) -> dict[str, str]:
            return {"user_id": session.user_id}

        client = TestClient(app)
        resp = client.get(
            "/test-admin",
            cookies={"session_id": _encrypted_cookie()},
        )
        assert resp.status_code == 401


# --- Tests: POST /api/admin/sync/ ---


class TestTriggerSync:
    """Tests for POST /api/admin/sync/."""

    def _make_admin_app(self, sync_engine: Any = None) -> tuple[FastAPI, TestClient]:
        session_store = AsyncMock()
        session_store.get_metadata.return_value = _make_session_meta()
        session_store.get.return_value = _make_session_row()

        jf_client = AsyncMock()
        jf_client.get_user.return_value = _make_user_info(is_admin=True)

        engine = sync_engine or MagicMock()
        app = _make_app(
            sync_engine=engine,
            session_store=session_store,
            jf_client=jf_client,
        )
        client = TestClient(app)
        return app, client

    def test_trigger_returns_202(self) -> None:
        """Successful trigger returns 202 with running status."""
        engine = MagicMock()
        engine.validate_config.return_value = None
        engine.is_running = False
        engine.run_sync = AsyncMock()

        _, client = self._make_admin_app(sync_engine=engine)
        resp = client.post(
            "/api/admin/sync/",
            cookies={"session_id": _encrypted_cookie()},
        )
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "running"
        assert data["message"] == "Sync started"

    def test_trigger_returns_409_when_already_running(self) -> None:
        """Returns 409 when sync lock is held."""
        engine = MagicMock()
        engine.validate_config.return_value = None
        engine.is_running = True

        _, client = self._make_admin_app(sync_engine=engine)
        resp = client.post(
            "/api/admin/sync/",
            cookies={"session_id": _encrypted_cookie()},
        )
        assert resp.status_code == 409
        assert "already in progress" in resp.json()["detail"]

    def test_trigger_returns_503_when_config_missing(self) -> None:
        """Returns 503 when sync config is invalid."""
        engine = MagicMock()
        engine.validate_config.side_effect = SyncConfigError(
            "Sync engine not configured"
        )

        _, client = self._make_admin_app(sync_engine=engine)
        resp = client.post(
            "/api/admin/sync/",
            cookies={"session_id": _encrypted_cookie()},
        )
        assert resp.status_code == 503

    def test_trigger_requires_admin(self) -> None:
        """Non-admin gets 403 on trigger."""
        session_store = AsyncMock()
        session_store.get_metadata.return_value = _make_session_meta()
        session_store.get.return_value = _make_session_row()

        jf_client = AsyncMock()
        jf_client.get_user.return_value = _make_user_info(is_admin=False)

        app = _make_app(session_store=session_store, jf_client=jf_client)
        client = TestClient(app)
        resp = client.post(
            "/api/admin/sync/",
            cookies={"session_id": _encrypted_cookie()},
        )
        assert resp.status_code == 403


# --- Tests: GET /api/admin/sync/status ---


class TestSyncStatus:
    """Tests for GET /api/admin/sync/status."""

    def _make_admin_app(self, sync_engine: Any = None) -> tuple[FastAPI, TestClient]:
        session_store = AsyncMock()
        session_store.get_metadata.return_value = _make_session_meta()
        session_store.get.return_value = _make_session_row()

        jf_client = AsyncMock()
        jf_client.get_user.return_value = _make_user_info(is_admin=True)

        engine = sync_engine or MagicMock()
        app = _make_app(
            sync_engine=engine,
            session_store=session_store,
            jf_client=jf_client,
        )
        client = TestClient(app)
        return app, client

    def test_status_idle_when_no_sync_ever(self) -> None:
        """Returns idle when no sync has ever run."""
        engine = MagicMock()
        engine.current_state = None
        engine.get_last_run = AsyncMock()
        engine.get_last_run.return_value = None

        _, client = self._make_admin_app(sync_engine=engine)
        resp = client.get(
            "/api/admin/sync/status",
            cookies={"session_id": _encrypted_cookie()},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "idle"
        assert data["progress"] is None
        assert data["last_run"] is None

    def test_status_running_with_progress(self) -> None:
        """Returns running status with progress when sync is active."""
        state = SyncState(
            started_at=_NOW,
            pages_processed=3,
            items_processed=150,
            items_created=50,
            items_updated=10,
            items_unchanged=85,
            items_failed=5,
        )
        engine = MagicMock()
        engine.current_state = state

        _, client = self._make_admin_app(sync_engine=engine)
        resp = client.get(
            "/api/admin/sync/status",
            cookies={"session_id": _encrypted_cookie()},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "running"
        assert data["started_at"] == _NOW
        assert data["progress"]["pages_processed"] == 3
        assert data["progress"]["items_created"] == 50
        assert data["progress"]["items_failed"] == 5

    def test_status_shows_last_completed_run(self) -> None:
        """Returns last run details when no sync is active."""
        last_run = SyncRunRow(
            id=1,
            started_at=_NOW - 3600,
            completed_at=_NOW - 3500,
            status="completed",
            total_items=200,
            items_created=200,
            items_updated=0,
            items_deleted=0,
            items_unchanged=0,
            items_failed=0,
            error_message=None,
        )
        engine = MagicMock()
        engine.current_state = None
        engine.get_last_run = AsyncMock()
        engine.get_last_run.return_value = last_run

        _, client = self._make_admin_app(sync_engine=engine)
        resp = client.get(
            "/api/admin/sync/status",
            cookies={"session_id": _encrypted_cookie()},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert data["last_run"]["total_items"] == 200
        assert data["last_run"]["items_created"] == 200

    def test_status_shows_failed_last_run(self) -> None:
        """Returns failed status with error message from last run."""
        last_run = SyncRunRow(
            id=2,
            started_at=_NOW - 1800,
            completed_at=_NOW - 1750,
            status="failed",
            total_items=50,
            items_created=30,
            items_updated=0,
            items_deleted=0,
            items_unchanged=15,
            items_failed=5,
            error_message="JellyfinConnectionError: sync failed",
        )
        engine = MagicMock()
        engine.current_state = None
        engine.get_last_run = AsyncMock()
        engine.get_last_run.return_value = last_run

        _, client = self._make_admin_app(sync_engine=engine)
        resp = client.get(
            "/api/admin/sync/status",
            cookies={"session_id": _encrypted_cookie()},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "failed"
        assert (
            data["last_run"]["error_message"] == "JellyfinConnectionError: sync failed"
        )

    def test_status_requires_admin(self) -> None:
        """Non-admin gets 403 on status."""
        session_store = AsyncMock()
        session_store.get_metadata.return_value = _make_session_meta()
        session_store.get.return_value = _make_session_row()

        jf_client = AsyncMock()
        jf_client.get_user.return_value = _make_user_info(is_admin=False)

        app = _make_app(session_store=session_store, jf_client=jf_client)
        client = TestClient(app)
        resp = client.get(
            "/api/admin/sync/status",
            cookies={"session_id": _encrypted_cookie()},
        )
        assert resp.status_code == 403
