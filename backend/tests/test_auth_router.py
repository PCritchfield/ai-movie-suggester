"""Unit tests for auth endpoints (login, me, logout)."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient

from app.auth.crypto import derive_keys, fernet_decrypt
from app.auth.session_store import SessionStore
from app.jellyfin.errors import JellyfinAuthError, JellyfinConnectionError

_SECRET = "kG7xP2mN9qR4wL8jT3vF6yA5dH0sE1cB"
_COOKIE_KEY, _COLUMN_KEY = derive_keys(_SECRET)
_FAKE_REQUEST = httpx.Request("GET", "http://fake")


@pytest.fixture
def mock_jf() -> AsyncMock:
    """Mock JellyfinClient."""
    jf = AsyncMock()
    jf.authenticate.return_value = AsyncMock(
        access_token="jf-tok-123",
        user_id="uid-1",
        user_name="alice",
    )
    jf.get_server_name.return_value = "MyJellyfin"
    jf.logout.return_value = None
    return jf


@pytest.fixture
def auth_app(tmp_path: object, mock_jf: AsyncMock) -> TestClient:
    """Create a test app with auth routes wired up."""
    import pathlib

    from app.auth.router import create_auth_router
    from app.auth.service import AuthService
    from app.config import Settings
    from app.main import create_app

    db_path = pathlib.Path(str(tmp_path)) / "test_sessions.db"

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
        session_secret=_SECRET,
        session_expiry_hours=settings.session_expiry_hours,
        max_sessions_per_user=settings.max_sessions_per_user,
    )

    app = create_app(settings)

    auth_router = create_auth_router(
        auth_service=service,
        session_store=store,
        settings=settings,
        cookie_key=service.cookie_key,
    )
    app.include_router(auth_router)
    app.state.session_store = store
    app.state.jellyfin_client = mock_jf

    import asyncio

    asyncio.get_event_loop().run_until_complete(store.init())

    client = TestClient(app)
    yield client  # type: ignore[misc]
    asyncio.get_event_loop().run_until_complete(store.close())


class TestLoginSuccess:
    def test_returns_200_with_user_info(
        self, auth_app: TestClient, mock_jf: AsyncMock
    ) -> None:
        resp = auth_app.post(
            "/api/auth/login",
            json={"username": "alice", "password": "pass123"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["user_id"] == "uid-1"
        assert body["username"] == "alice"
        assert body["server_name"] == "MyJellyfin"

    def test_sets_session_cookie(
        self, auth_app: TestClient, mock_jf: AsyncMock
    ) -> None:
        resp = auth_app.post(
            "/api/auth/login",
            json={"username": "alice", "password": "pass123"},
        )
        cookie = resp.cookies.get("session_id")
        assert cookie is not None
        # Cookie value should be Fernet-encrypted (not raw session ID)
        decrypted = fernet_decrypt(_COOKIE_KEY, cookie.encode("utf-8"))
        assert len(decrypted) > 20  # token_urlsafe(32) is ~43 chars

    def test_cookie_attributes(
        self, auth_app: TestClient, mock_jf: AsyncMock
    ) -> None:
        resp = auth_app.post(
            "/api/auth/login",
            json={"username": "alice", "password": "pass123"},
        )
        set_cookie = resp.headers.get("set-cookie", "")
        assert "httponly" in set_cookie.lower()
        assert "samesite=lax" in set_cookie.lower()
        assert "path=/api" in set_cookie.lower()
        # max-age should be session_expiry_hours * 3600 = 86400
        assert "max-age=86400" in set_cookie.lower()


class TestLoginErrors:
    def test_invalid_credentials_returns_401(
        self, auth_app: TestClient, mock_jf: AsyncMock
    ) -> None:
        mock_jf.authenticate.side_effect = JellyfinAuthError(
            "Invalid username or password"
        )
        resp = auth_app.post(
            "/api/auth/login",
            json={"username": "alice", "password": "wrong"},
        )
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid username or password"
        assert "set-cookie" not in resp.headers

    def test_jellyfin_unreachable_returns_502(
        self, auth_app: TestClient, mock_jf: AsyncMock
    ) -> None:
        mock_jf.authenticate.side_effect = JellyfinConnectionError(
            "Cannot reach Jellyfin"
        )
        resp = auth_app.post(
            "/api/auth/login",
            json={"username": "alice", "password": "pass123"},
        )
        assert resp.status_code == 502
        assert resp.json()["detail"] == "Jellyfin server is unreachable"


class TestMe:
    def _login(self, auth_app: TestClient) -> dict[str, str]:
        """Helper: login and return cookies dict."""
        resp = auth_app.post(
            "/api/auth/login",
            json={"username": "alice", "password": "pass123"},
        )
        assert resp.status_code == 200
        return dict(resp.cookies)

    def test_valid_session_returns_200(
        self, auth_app: TestClient, mock_jf: AsyncMock
    ) -> None:
        cookies = self._login(auth_app)
        resp = auth_app.get("/api/auth/me", cookies=cookies)
        assert resp.status_code == 200
        body = resp.json()
        assert body["user_id"] == "uid-1"
        assert body["username"] == "alice"
        assert body["server_name"] == "MyJellyfin"

    def test_missing_cookie_returns_401(
        self, auth_app: TestClient
    ) -> None:
        resp = auth_app.get("/api/auth/me")
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Not authenticated"

    def test_tampered_cookie_returns_401(
        self, auth_app: TestClient
    ) -> None:
        resp = auth_app.get(
            "/api/auth/me",
            cookies={"session_id": "garbage-not-fernet"},
        )
        assert resp.status_code == 401

    def test_expired_session_returns_401(
        self, auth_app: TestClient, mock_jf: AsyncMock
    ) -> None:
        """Login, manually expire the session, then /me should 401."""
        cookies = self._login(auth_app)

        # Decrypt cookie to get session_id
        session_id = fernet_decrypt(
            _COOKIE_KEY, cookies["session_id"].encode("utf-8")
        )

        # Manually expire the session in the DB
        import asyncio

        store = auth_app.app.state.session_store  # type: ignore[union-attr]

        async def expire_session() -> None:
            await store._conn.execute(
                "UPDATE sessions SET expires_at = ? WHERE session_id = ?",
                (int(time.time()) - 100, session_id),
            )
            await store._conn.commit()

        asyncio.get_event_loop().run_until_complete(expire_session())

        resp = auth_app.get("/api/auth/me", cookies=cookies)
        assert resp.status_code == 401


class TestLogout:
    def _login(self, auth_app: TestClient) -> dict[str, str]:
        resp = auth_app.post(
            "/api/auth/login",
            json={"username": "alice", "password": "pass123"},
        )
        assert resp.status_code == 200
        return dict(resp.cookies)

    def test_logout_returns_200_clears_cookie(
        self, auth_app: TestClient, mock_jf: AsyncMock
    ) -> None:
        cookies = self._login(auth_app)
        resp = auth_app.post("/api/auth/logout", cookies=cookies)
        assert resp.status_code == 200
        assert resp.json()["detail"] == "Logged out"
        # Cookie should be cleared (max-age=0 or empty)
        set_cookie = resp.headers.get("set-cookie", "")
        assert "session_id" in set_cookie
        # After logout, /me should fail
        resp2 = auth_app.get("/api/auth/me", cookies=cookies)
        assert resp2.status_code == 401

    def test_logout_jellyfin_unreachable_still_200(
        self, auth_app: TestClient, mock_jf: AsyncMock
    ) -> None:
        cookies = self._login(auth_app)
        mock_jf.logout.side_effect = JellyfinConnectionError(
            "Cannot reach Jellyfin"
        )
        resp = auth_app.post("/api/auth/logout", cookies=cookies)
        assert resp.status_code == 200
        assert resp.json()["detail"] == "Logged out"

    def test_logout_no_session_returns_200(
        self, auth_app: TestClient
    ) -> None:
        """Logout without a session is idempotent."""
        resp = auth_app.post("/api/auth/logout")
        assert resp.status_code == 200
        assert resp.json()["detail"] == "Logged out"


class TestLogMessages:
    def test_login_logs_user_id(
        self,
        auth_app: TestClient,
        mock_jf: AsyncMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        import logging

        with caplog.at_level(logging.INFO):
            auth_app.post(
                "/api/auth/login",
                json={"username": "alice", "password": "pass123"},
            )
        assert any("user_login user_id=uid-1" in r.message for r in caplog.records)
        # No PII in log
        assert not any("alice" in r.message for r in caplog.records)
        assert not any("jf-tok-123" in r.message for r in caplog.records)

    def test_logout_logs_user_id(
        self,
        auth_app: TestClient,
        mock_jf: AsyncMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        import logging

        resp = auth_app.post(
            "/api/auth/login",
            json={"username": "alice", "password": "pass123"},
        )
        cookies = dict(resp.cookies)
        with caplog.at_level(logging.INFO):
            auth_app.post("/api/auth/logout", cookies=cookies)
        assert any("user_logout user_id=uid-1" in r.message for r in caplog.records)
