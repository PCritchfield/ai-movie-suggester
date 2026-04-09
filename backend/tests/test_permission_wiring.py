"""Tests for permission wiring: lifespan, dependency, logout, session destruction."""

from __future__ import annotations

import pathlib
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.auth.router import create_auth_router
from app.auth.service import AuthService
from app.auth.session_store import SessionStore
from app.config import Settings
from app.permissions.dependencies import (
    get_permission_service,
    handle_permission_auth_error,
)
from app.permissions.service import PermissionService
from tests.conftest import (
    TEST_COLUMN_KEY,
    TEST_COOKIE_KEY,
    TEST_SECRET,
    make_test_client,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from unittest.mock import AsyncMock

import pytest


class TestLifespan:
    """Verify PermissionService is created and stored on app.state."""

    def test_permission_service_on_app_state(self) -> None:
        client = make_test_client()
        try:
            svc = client.app.state.permission_service  # type: ignore[union-attr]
            assert isinstance(svc, PermissionService)
        finally:
            client.close()


class TestDependency:
    """get_permission_service retrieves the service from app.state."""

    async def test_returns_service_from_state(self) -> None:
        mock_service = MagicMock(spec=PermissionService)
        app = FastAPI()
        app.state.permission_service = mock_service

        request = Request(scope={"type": "http", "app": app})
        result = await get_permission_service(request)
        assert result is mock_service


@pytest.fixture
async def auth_app_with_perms(
    tmp_path: object, mock_jf: AsyncMock
) -> AsyncIterator[tuple[TestClient, PermissionService]]:
    """Minimal test app with auth routes + permission service (no CSRF)."""
    db_path = pathlib.Path(str(tmp_path)) / "test_sessions.db"

    settings = Settings(
        jellyfin_url="http://jellyfin-test:8096",
        session_secret=TEST_SECRET,
        session_secure_cookie=False,
        log_level="debug",
    )  # type: ignore[call-arg]

    store = SessionStore(str(db_path), TEST_COLUMN_KEY)

    jf_client = mock_jf
    perm_service = PermissionService(jellyfin_client=jf_client, cache_ttl_seconds=300)

    service = AuthService(
        session_store=store,
        jellyfin_client=jf_client,
        session_expiry_hours=settings.session_expiry_hours,
        max_sessions_per_user=settings.max_sessions_per_user,
    )

    app = FastAPI()
    auth_router = create_auth_router(
        auth_service=service,
        session_store=store,
        settings=settings,
        cookie_key=TEST_COOKIE_KEY,
        permission_service=perm_service,
    )
    app.include_router(auth_router)
    from app.chat.conversation_store import ConversationStore

    app.state.session_store = store
    app.state.cookie_key = TEST_COOKIE_KEY
    app.state.jellyfin_client = jf_client
    app.state.permission_service = perm_service
    conversation_store = ConversationStore(
        max_turns=10, ttl_seconds=7200, max_sessions=100
    )
    app.state.conversation_store = conversation_store

    # chat_service mock — logout handler delegates purge_session through it
    chat_service_mock = MagicMock()
    chat_service_mock.purge_session = conversation_store.purge_session
    app.state.chat_service = chat_service_mock

    await store.init()

    client = TestClient(app)
    try:
        yield client, perm_service
    finally:
        client.close()
        await store.close()


class TestLogoutIntegration:
    """Logout endpoint invalidates permission cache."""

    def test_logout_calls_invalidate_user_cache(
        self,
        auth_app_with_perms: tuple[TestClient, PermissionService],
    ) -> None:
        """Logout with valid session calls invalidate_user_cache(user_id)."""
        client, perm_service = auth_app_with_perms

        # Login to get a session
        resp = client.post(
            "/api/auth/login",
            json={"username": "alice", "password": "pass123"},
        )
        assert resp.status_code == 200
        cookies = dict(resp.cookies)

        with patch.object(perm_service, "invalidate_user_cache") as mock_inv:
            resp = client.post("/api/auth/logout", cookies=cookies)
            assert resp.status_code == 200
            mock_inv.assert_called_once_with("uid-1")

    def test_logout_without_session_skips_invalidation(
        self,
        auth_app_with_perms: tuple[TestClient, PermissionService],
    ) -> None:
        """Logout without a session doesn't call invalidate_user_cache."""
        client, perm_service = auth_app_with_perms

        with patch.object(perm_service, "invalidate_user_cache") as mock_inv:
            resp = client.post("/api/auth/logout")
            assert resp.status_code == 200
            mock_inv.assert_not_called()


@pytest.fixture
async def session_destruction_parts(
    tmp_path: object, mock_jf: AsyncMock
) -> AsyncIterator[tuple[SessionStore, PermissionService, Settings]]:
    """Create standalone store + permission service for session destruction tests."""
    db_path = pathlib.Path(str(tmp_path)) / "test_sessions.db"

    settings = Settings(
        jellyfin_url="http://jellyfin-test:8096",
        session_secret=TEST_SECRET,
        session_secure_cookie=False,
        log_level="debug",
    )  # type: ignore[call-arg]

    store = SessionStore(str(db_path), TEST_COLUMN_KEY)
    perm_service = PermissionService(jellyfin_client=mock_jf, cache_ttl_seconds=300)

    await store.init()
    yield store, perm_service, settings
    await store.close()


class TestSessionDestruction:
    """handle_permission_auth_error destroys session and returns 401."""

    async def test_returns_401_with_session_expired(
        self,
        session_destruction_parts: tuple[SessionStore, PermissionService, Settings],
    ) -> None:
        store, perm_service, settings = session_destruction_parts

        # Create a session first
        await store.create(
            session_id="sess-1",
            user_id="uid-1",
            username="alice",
            server_name="MyJellyfin",
            token="jf-tok-123",
            csrf_token="csrf-1",
            expires_at=9999999999,
        )

        resp = await handle_permission_auth_error(
            session_id="sess-1",
            session_store=store,
            permission_service=perm_service,
            user_id="uid-1",
            settings=settings,
        )

        assert resp.status_code == 401
        assert resp.body == b'{"detail":"Session expired"}'

        # Session should be deleted
        session = await store.get("sess-1")
        assert session is None

    async def test_cache_invalidated(
        self,
        session_destruction_parts: tuple[SessionStore, PermissionService, Settings],
    ) -> None:
        store, perm_service, settings = session_destruction_parts

        await store.create(
            session_id="sess-2",
            user_id="uid-2",
            username="bob",
            server_name="MyJellyfin",
            token="jf-tok-456",
            csrf_token="csrf-2",
            expires_at=9999999999,
        )

        with patch.object(perm_service, "invalidate_user_cache") as mock_inv:
            await handle_permission_auth_error(
                session_id="sess-2",
                session_store=store,
                permission_service=perm_service,
                user_id="uid-2",
                settings=settings,
            )
            mock_inv.assert_called_once_with("uid-2")

    async def test_idempotent_session_already_gone(
        self,
        session_destruction_parts: tuple[SessionStore, PermissionService, Settings],
    ) -> None:
        """Calling with a nonexistent session still returns 401 without error."""
        store, perm_service, settings = session_destruction_parts

        resp = await handle_permission_auth_error(
            session_id="nonexistent",
            session_store=store,
            permission_service=perm_service,
            user_id="uid-1",
            settings=settings,
        )

        assert resp.status_code == 401
