"""Unit tests for CSRF protection."""

from __future__ import annotations

import asyncio
import pathlib
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

if TYPE_CHECKING:
    from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.auth.crypto import derive_keys
from app.auth.router import create_auth_router
from app.auth.service import AuthService
from app.auth.session_store import SessionStore
from app.config import Settings
from app.middleware.csrf import CSRFMiddleware

_SECRET = "kG7xP2mN9qR4wL8jT3vF6yA5dH0sE1cB"
_COOKIE_KEY, _COLUMN_KEY = derive_keys(_SECRET)


@pytest.fixture
def csrf_app(tmp_path: object) -> Iterator[TestClient]:
    """App with CSRF middleware enabled."""
    from fastapi import FastAPI

    db_path = pathlib.Path(str(tmp_path)) / "csrf_sessions.db"

    mock_jf = AsyncMock()
    mock_jf.authenticate.return_value = AsyncMock(
        access_token="jf-tok",
        user_id="uid-1",
        user_name="alice",
    )
    mock_jf.get_server_name.return_value = "MyJellyfin"
    mock_jf.logout.return_value = None

    settings = Settings(
        jellyfin_url="http://jellyfin-test:8096",
        session_secret=_SECRET,
        session_secure_cookie=False,
        log_level="debug",
    )  # type: ignore[call-arg]

    store = SessionStore(str(db_path), _COLUMN_KEY)
    service = AuthService(
        session_store=store,
        jellyfin_client=mock_jf,
        session_expiry_hours=24,
        max_sessions_per_user=5,
    )

    app = FastAPI()
    app.add_middleware(CSRFMiddleware)
    app.state.session_store = store
    app.state.cookie_key = _COOKIE_KEY
    app.state.jellyfin_client = mock_jf

    auth_router = create_auth_router(
        auth_service=service,
        session_store=store,
        settings=settings,
        cookie_key=_COOKIE_KEY,
    )
    app.include_router(auth_router)

    asyncio.get_event_loop().run_until_complete(store.init())
    client = TestClient(app)
    yield client  # type: ignore[misc]
    asyncio.get_event_loop().run_until_complete(store.close())


def _login(csrf_app: TestClient) -> dict[str, str]:
    """Login and return cookies dict."""
    resp = csrf_app.post(
        "/api/auth/login",
        json={"username": "alice", "password": "pass"},
    )
    assert resp.status_code == 200
    return dict(resp.cookies)


class TestCSRFProtection:
    def test_login_exempt_from_csrf(self, csrf_app: TestClient) -> None:
        """POST /api/auth/login works without CSRF token."""
        resp = csrf_app.post(
            "/api/auth/login",
            json={"username": "alice", "password": "pass"},
        )
        assert resp.status_code == 200

    def test_logout_without_csrf_returns_403(self, csrf_app: TestClient) -> None:
        """POST /api/auth/logout without X-CSRF-Token returns 403."""
        cookies = _login(csrf_app)
        resp = csrf_app.post("/api/auth/logout", cookies=cookies)
        assert resp.status_code == 403
        assert resp.json()["detail"] == "CSRF token missing or invalid"

    def test_logout_with_valid_csrf_succeeds(self, csrf_app: TestClient) -> None:
        """POST /api/auth/logout with valid CSRF token succeeds."""
        cookies = _login(csrf_app)
        csrf_token = cookies.get("csrf_token", "")
        resp = csrf_app.post(
            "/api/auth/logout",
            cookies=cookies,
            headers={"X-CSRF-Token": csrf_token},
        )
        assert resp.status_code == 200

    def test_logout_with_mismatched_csrf_returns_403(
        self, csrf_app: TestClient
    ) -> None:
        """POST with mismatched X-CSRF-Token returns 403."""
        cookies = _login(csrf_app)
        resp = csrf_app.post(
            "/api/auth/logout",
            cookies=cookies,
            headers={"X-CSRF-Token": "wrong-token"},
        )
        assert resp.status_code == 403


class TestCSRFTokenLifecycle:
    def test_login_sets_csrf_cookie(self, csrf_app: TestClient) -> None:
        """Login sets a csrf_token cookie."""
        resp = csrf_app.post(
            "/api/auth/login",
            json={"username": "alice", "password": "pass"},
        )
        assert "csrf_token" in resp.cookies
        # Verify NOT httponly (JS must read it)
        set_cookies = resp.headers.get_list("set-cookie")
        csrf_cookie = [c for c in set_cookies if "csrf_token" in c]
        assert len(csrf_cookie) == 1
        assert "httponly" not in csrf_cookie[0].lower()

    def test_logout_clears_csrf_cookie(self, csrf_app: TestClient) -> None:
        """Logout clears the csrf_token cookie."""
        cookies = _login(csrf_app)
        csrf_token = cookies.get("csrf_token", "")
        resp = csrf_app.post(
            "/api/auth/logout",
            cookies=cookies,
            headers={"X-CSRF-Token": csrf_token},
        )
        set_cookies = resp.headers.get_list("set-cookie")
        csrf_clears = [c for c in set_cookies if "csrf_token" in c]
        assert len(csrf_clears) >= 1

    def test_relogin_generates_new_csrf_token(self, csrf_app: TestClient) -> None:
        """Re-login generates a different CSRF token."""
        cookies1 = _login(csrf_app)
        csrf1 = cookies1.get("csrf_token", "")
        cookies2 = _login(csrf_app)
        csrf2 = cookies2.get("csrf_token", "")
        assert csrf1 != csrf2
