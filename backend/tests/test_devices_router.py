"""Unit tests for the GET /api/devices router.

Covers:

* unauthenticated -> 401
* authenticated happy path -> 200 with device list
* empty list -> 200 []
* 11th request within 60s -> 429

Mocks ``JellyfinSessionsClient`` via FastAPI dependency override;
the ``get_current_session`` dep is also overridden in authenticated
cases. The rate-limit test follows the pattern from
``test_rate_limit.py`` and per-endpoint exemplars in
``test_chat_router.py`` / ``test_search_router.py``.
"""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.auth.crypto import derive_keys
from app.auth.dependencies import get_current_session
from app.auth.models import SessionMeta
from app.devices.router import create_devices_router, get_sessions_client
from app.jellyfin.device_models import Device
from app.jellyfin.sessions import JellyfinSessionsClient
from app.middleware.rate_limit import create_limiter
from tests.conftest import TEST_SECRET, make_test_settings

_COOKIE_KEY, _ = derive_keys(TEST_SECRET)
_SESSION_ID = "test-session-devices"
_USER_ID = "uid-devices-1"
_NOW = int(time.time())


def _session_meta() -> SessionMeta:
    return SessionMeta(
        session_id=_SESSION_ID,
        user_id=_USER_ID,
        username="alice",
        server_name="TestJellyfin",
        expires_at=_NOW + 3600,
    )


def _make_devices_app(
    *,
    sessions_client: Any = None,
    limiter: Any = None,
    authenticated: bool = True,
    session_token: str | None = "jf-token-abc",
) -> tuple[FastAPI, TestClient]:
    """Build a FastAPI app with the devices router wired up and mocked deps."""
    settings = make_test_settings()
    app = FastAPI()
    app.state.cookie_key = _COOKIE_KEY
    app.state.settings = settings
    app.state.limiter = limiter

    if limiter is not None:
        app.add_exception_handler(
            RateLimitExceeded,
            _rate_limit_exceeded_handler,  # type: ignore[arg-type]
        )

    session_store = AsyncMock()
    session_store.get_token = AsyncMock(return_value=session_token)
    app.state.session_store = session_store

    router = create_devices_router(limiter=limiter)
    app.include_router(router)

    if authenticated:

        async def _mock_session() -> SessionMeta:
            return _session_meta()

        app.dependency_overrides[get_current_session] = _mock_session

    if sessions_client is not None:

        def _provide_sessions_client() -> JellyfinSessionsClient:
            return sessions_client

        app.dependency_overrides[get_sessions_client] = _provide_sessions_client

    return app, TestClient(app)


class TestDevicesRouterAuth:
    def test_unauthenticated_returns_401(self) -> None:
        _, client = _make_devices_app(authenticated=False)
        resp = client.get("/api/devices")
        assert resp.status_code == 401


class TestDevicesRouterHappyPath:
    def test_returns_device_list(self) -> None:
        mock = AsyncMock(spec=JellyfinSessionsClient)
        mock.list_controllable.return_value = [
            Device(
                session_id="sess-1",
                name="Living Room TV",
                client="Jellyfin Android TV",
                device_type="Tv",
            ),
            Device(
                session_id="sess-2",
                name="Phone",
                client="Jellyfin iOS",
                device_type="Mobile",
            ),
        ]
        _, client = _make_devices_app(sessions_client=mock)
        resp = client.get("/api/devices")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)
        assert len(body) == 2
        assert body[0]["session_id"] == "sess-1"
        assert body[0]["name"] == "Living Room TV"
        assert body[0]["client"] == "Jellyfin Android TV"
        assert body[0]["device_type"] == "Tv"
        assert body[1]["device_type"] == "Mobile"

        # Confirm the caller's token was forwarded
        mock.list_controllable.assert_awaited_once_with("jf-token-abc")

    def test_empty_list_returns_200(self) -> None:
        mock = AsyncMock(spec=JellyfinSessionsClient)
        mock.list_controllable.return_value = []
        _, client = _make_devices_app(sessions_client=mock)
        resp = client.get("/api/devices")
        assert resp.status_code == 200
        assert resp.json() == []


class TestDevicesRouterTokenMissing:
    def test_token_missing_returns_401(self) -> None:
        """If the session has no token, return 401 (matches chat/search)."""
        mock = AsyncMock(spec=JellyfinSessionsClient)
        _, client = _make_devices_app(sessions_client=mock, session_token=None)
        resp = client.get("/api/devices")
        assert resp.status_code == 401


class TestDevicesRouterRateLimit:
    def test_eleventh_request_within_window_returns_429(self) -> None:
        """10/min cap: 10 rapid requests OK, 11th returns 429."""
        limiter = create_limiter()
        # Reset limiter storage — ensure clean state between tests
        limiter.reset()

        mock = AsyncMock(spec=JellyfinSessionsClient)
        mock.list_controllable.return_value = []

        _, client = _make_devices_app(sessions_client=mock, limiter=limiter)

        statuses = [client.get("/api/devices").status_code for _ in range(11)]
        # First 10 are 200; the 11th is 429
        assert statuses[:10] == [200] * 10, f"first 10 must be 200, got {statuses[:10]}"
        assert statuses[10] == 429


class TestDevicesRouterOpenAPI:
    def test_openapi_documents_get_devices(self) -> None:
        """The OpenAPI spec exposes GET /api/devices with the tag 'devices'."""
        app, _ = _make_devices_app(
            sessions_client=AsyncMock(spec=JellyfinSessionsClient)
        )
        openapi = app.openapi()
        assert "/api/devices" in openapi["paths"]
        op = openapi["paths"]["/api/devices"]["get"]
        assert "devices" in op.get("tags", [])
