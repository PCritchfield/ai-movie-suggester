"""Unit tests for auth endpoints (login, me, logout)."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING
from unittest.mock import patch

if TYPE_CHECKING:
    from collections.abc import Iterator
    from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.auth.crypto import fernet_decrypt
from app.auth.session_store import SessionStore
from app.jellyfin.errors import JellyfinAuthError, JellyfinConnectionError
from tests.conftest import TEST_COLUMN_KEY, TEST_COOKIE_KEY, TEST_SECRET

# mock_jf fixture is inherited from conftest.py


@pytest.fixture
def auth_app(tmp_path: object, mock_jf: AsyncMock) -> Iterator[TestClient]:
    """Create a minimal test app with auth routes (no CSRF middleware)."""
    import asyncio
    import pathlib
    from unittest.mock import MagicMock

    from fastapi import FastAPI

    from app.auth.router import create_auth_router
    from app.auth.service import AuthService
    from app.chat.conversation_store import ConversationStore
    from app.config import Settings

    db_path = pathlib.Path(str(tmp_path)) / "test_sessions.db"

    settings = Settings(
        jellyfin_url="http://jellyfin-test:8096",
        session_secret=TEST_SECRET,
        session_secure_cookie=False,
        log_level="debug",
    )  # type: ignore[call-arg]

    store = SessionStore(str(db_path), TEST_COLUMN_KEY)
    service = AuthService(
        session_store=store,
        jellyfin_client=mock_jf,
        session_expiry_hours=settings.session_expiry_hours,
        max_sessions_per_user=settings.max_sessions_per_user,
    )

    rewrite_cache_mock = MagicMock()
    app = FastAPI()
    auth_router = create_auth_router(
        auth_service=service,
        session_store=store,
        settings=settings,
        cookie_key=TEST_COOKIE_KEY,
        rewrite_cache=rewrite_cache_mock,
    )
    app.include_router(auth_router)
    app.state.session_store = store
    app.state.cookie_key = TEST_COOKIE_KEY
    app.state.jellyfin_client = mock_jf
    app.state.rewrite_cache = rewrite_cache_mock
    conversation_store = ConversationStore(
        max_turns=10, ttl_seconds=7200, max_sessions=100
    )
    app.state.conversation_store = conversation_store

    # chat_service mock — logout handler delegates purge_session through it
    chat_service_mock = MagicMock()
    chat_service_mock.purge_session = conversation_store.purge_session
    app.state.chat_service = chat_service_mock

    asyncio.get_event_loop().run_until_complete(store.init())

    # Patch out the constant-time login floor so tests don't pay 0.5s each
    with (
        patch("app.auth.router.asyncio.sleep", return_value=None),
        TestClient(app) as client,
    ):
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
        decrypted = fernet_decrypt(TEST_COOKIE_KEY, cookie.encode("utf-8"))
        assert len(decrypted) > 20  # token_urlsafe(32) is ~43 chars

    def test_cookie_attributes(self, auth_app: TestClient, mock_jf: AsyncMock) -> None:
        resp = auth_app.post(
            "/api/auth/login",
            json={"username": "alice", "password": "pass123"},
        )
        # Find the primary session_id cookie (path=/, not the old-path cleanup)
        session_cookies = [
            c for c in resp.headers.get_list("set-cookie") if "session_id" in c
        ]
        primary = [
            c
            for c in session_cookies
            if "path=/" in c.lower() and "path=/api" not in c.lower()
        ]
        assert len(primary) >= 1, "No session_id cookie at path=/ found"
        sc = primary[0].lower()
        assert "httponly" in sc
        assert "samesite=lax" in sc
        assert "path=/" in sc
        # max-age should be session_expiry_hours * 3600 = 86400
        assert "max-age=86400" in sc


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


class TestLoginTimingFloor:
    """Verify the constant-time floor prevents timing side-channels."""

    def test_sleep_called_on_fast_auth_failure(
        self, mock_jf: AsyncMock, tmp_path: object
    ) -> None:
        """Auth failure completes fast — sleep should pad to the floor."""
        import asyncio
        import pathlib
        from unittest.mock import AsyncMock as AsyncMockLocal
        from unittest.mock import MagicMock

        from fastapi import FastAPI

        from app.auth.router import create_auth_router
        from app.auth.service import AuthService
        from app.chat.conversation_store import ConversationStore
        from app.config import Settings

        db_path = pathlib.Path(str(tmp_path)) / "timing_sessions.db"
        settings = Settings(
            jellyfin_url="http://jellyfin-test:8096",
            session_secret=TEST_SECRET,
            session_secure_cookie=False,
            log_level="debug",
        )  # type: ignore[call-arg]
        store = SessionStore(str(db_path), TEST_COLUMN_KEY)
        service = AuthService(
            session_store=store,
            jellyfin_client=mock_jf,
            session_expiry_hours=settings.session_expiry_hours,
            max_sessions_per_user=settings.max_sessions_per_user,
        )
        app = FastAPI()
        router = create_auth_router(
            auth_service=service,
            session_store=store,
            settings=settings,
            cookie_key=TEST_COOKIE_KEY,
        )
        app.include_router(router)
        app.state.session_store = store
        app.state.cookie_key = TEST_COOKIE_KEY
        app.state.jellyfin_client = mock_jf
        conv = ConversationStore(max_turns=10, ttl_seconds=7200, max_sessions=100)
        app.state.conversation_store = conv
        chat_mock = MagicMock()
        chat_mock.purge_session = conv.purge_session
        app.state.chat_service = chat_mock

        asyncio.get_event_loop().run_until_complete(store.init())

        mock_jf.authenticate.side_effect = JellyfinAuthError("bad")
        sleep_mock = AsyncMockLocal(return_value=None)

        with (
            patch("app.auth.router.asyncio.sleep", sleep_mock),
            TestClient(app) as client,
        ):
            resp = client.post(
                "/api/auth/login",
                json={"username": "alice", "password": "wrong"},
            )
        assert resp.status_code == 401
        # sleep must have been called with a positive remainder
        sleep_mock.assert_called_once()
        pad_duration = sleep_mock.call_args[0][0]
        assert 0 < pad_duration <= 0.5

        asyncio.get_event_loop().run_until_complete(store.close())


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

    def test_missing_cookie_returns_401(self, auth_app: TestClient) -> None:
        resp = auth_app.get("/api/auth/me")
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Not authenticated"

    def test_tampered_cookie_returns_401(self, auth_app: TestClient) -> None:
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
            TEST_COOKIE_KEY, cookies["session_id"].encode("utf-8")
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
        mock_jf.logout.side_effect = JellyfinConnectionError("Cannot reach Jellyfin")
        resp = auth_app.post("/api/auth/logout", cookies=cookies)
        assert resp.status_code == 200
        assert resp.json()["detail"] == "Logged out"

    def test_logout_no_session_returns_200(self, auth_app: TestClient) -> None:
        """Logout without a session is idempotent."""
        resp = auth_app.post("/api/auth/logout")
        assert resp.status_code == 200
        assert resp.json()["detail"] == "Logged out"

    def test_logout_clears_rewrite_cache(
        self, auth_app: TestClient, mock_jf: AsyncMock
    ) -> None:
        """Spec 24 Task 4.14 — logout cascades a clear() onto the rewrite
        cache after the conversation purge and permission invalidation."""
        cookies = self._login(auth_app)
        rewrite_cache = auth_app.app.state.rewrite_cache
        resp = auth_app.post("/api/auth/logout", cookies=cookies)
        assert resp.status_code == 200
        rewrite_cache.clear.assert_called_once()


class TestCookieFixes:
    """Tests for Spec 04 Task 1.0 — cookie path widening and csrf max-age."""

    def test_csrf_cookie_has_max_age(
        self, auth_app: TestClient, mock_jf: AsyncMock
    ) -> None:
        resp = auth_app.post(
            "/api/auth/login",
            json={"username": "alice", "password": "pass123"},
        )
        assert resp.status_code == 200
        # Find the csrf_token Set-Cookie header
        csrf_cookies = [
            c for c in resp.headers.get_list("set-cookie") if "csrf_token" in c
        ]
        assert len(csrf_cookies) >= 1, "csrf_token cookie not found"
        csrf_cookie = csrf_cookies[0].lower()
        # session_expiry_hours defaults to 24, so max-age = 86400
        assert "max-age=86400" in csrf_cookie

    def test_login_deletes_old_path_session_cookie(
        self, auth_app: TestClient, mock_jf: AsyncMock
    ) -> None:
        resp = auth_app.post(
            "/api/auth/login",
            json={"username": "alice", "password": "pass123"},
        )
        assert resp.status_code == 200
        # Should include a Set-Cookie that deletes session_id at the old path=/api
        session_cookies = [
            c for c in resp.headers.get_list("set-cookie") if "session_id" in c
        ]
        # Should have both: new (path=/) and delete (path=/api)
        old_path_cookies = [c for c in session_cookies if "path=/api" in c.lower()]
        assert len(old_path_cookies) >= 1, (
            "No session_id delete cookie at path=/api found"
        )
        # The old-path cookie should have max-age=0 or an expired date
        old_cookie = old_path_cookies[0].lower()
        assert "max-age=0" in old_cookie or "01 jan 1970" in old_cookie

    def test_csrf_cookie_path_is_root(
        self, auth_app: TestClient, mock_jf: AsyncMock
    ) -> None:
        resp = auth_app.post(
            "/api/auth/login",
            json={"username": "alice", "password": "pass123"},
        )
        assert resp.status_code == 200
        raw_headers = resp.headers.raw
        csrf_cookies = [
            v.decode()
            for k, v in raw_headers
            if k == b"set-cookie" and b"csrf_token" in v
        ]
        # The primary csrf_token cookie should have path=/
        root_path_cookies = [
            c
            for c in csrf_cookies
            if "path=/" in c.lower() and "path=/api" not in c.lower()
        ]
        assert len(root_path_cookies) >= 1, "No csrf_token cookie at path=/ found"

    def test_login_deletes_old_path_csrf_cookie(
        self, auth_app: TestClient, mock_jf: AsyncMock
    ) -> None:
        resp = auth_app.post(
            "/api/auth/login",
            json={"username": "alice", "password": "pass123"},
        )
        assert resp.status_code == 200
        raw_headers = resp.headers.raw
        csrf_cookies = [
            v.decode()
            for k, v in raw_headers
            if k == b"set-cookie" and b"csrf_token" in v
        ]
        # Should include a delete for csrf_token at the old path=/api
        old_path_cookies = [c for c in csrf_cookies if "path=/api" in c.lower()]
        assert len(old_path_cookies) >= 1, (
            "No csrf_token delete cookie at path=/api found"
        )
        old_cookie = old_path_cookies[0].lower()
        assert "max-age=0" in old_cookie or "01 jan 1970" in old_cookie

    def test_logout_clears_csrf_at_root_path(
        self, auth_app: TestClient, mock_jf: AsyncMock
    ) -> None:
        resp = auth_app.post(
            "/api/auth/login",
            json={"username": "alice", "password": "pass123"},
        )
        cookies = dict(resp.cookies)
        resp = auth_app.post("/api/auth/logout", cookies=cookies)
        assert resp.status_code == 200
        raw_headers = resp.headers.raw
        csrf_cookies = [
            v.decode()
            for k, v in raw_headers
            if k == b"set-cookie" and b"csrf_token" in v
        ]
        # Should delete csrf_token at path=/ (primary)
        root_path_cookies = [
            c
            for c in csrf_cookies
            if "path=/" in c.lower() and "path=/api" not in c.lower()
        ]
        assert len(root_path_cookies) >= 1, (
            "No csrf_token delete cookie at path=/ found on logout"
        )

    def test_session_cookie_path_is_root(
        self, auth_app: TestClient, mock_jf: AsyncMock
    ) -> None:
        resp = auth_app.post(
            "/api/auth/login",
            json={"username": "alice", "password": "pass123"},
        )
        assert resp.status_code == 200
        session_cookies = [
            c for c in resp.headers.get_list("set-cookie") if "session_id" in c
        ]
        # The primary session cookie should have path=/
        root_path_cookies = [
            c
            for c in session_cookies
            if "path=/" in c.lower() and "path=/api" not in c.lower()
        ]
        assert len(root_path_cookies) >= 1, "No session_id cookie at path=/ found"


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
