"""Unit tests for rate limiting on POST /api/auth/login."""

from __future__ import annotations

import asyncio
import pathlib
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.auth.crypto import derive_keys
from app.auth.router import create_auth_router
from app.auth.service import AuthService
from app.auth.session_store import SessionStore
from app.config import Settings
from app.middleware.rate_limit import create_limiter

_SECRET = "kG7xP2mN9qR4wL8jT3vF6yA5dH0sE1cB"
_COOKIE_KEY, _COLUMN_KEY = derive_keys(_SECRET)


@pytest.fixture
def rate_app(tmp_path: object) -> TestClient:
    """App with rate limiting enabled (2/minute for fast testing)."""
    db_path = pathlib.Path(str(tmp_path)) / "rate_sessions.db"

    mock_jf = AsyncMock()
    mock_jf.authenticate.return_value = AsyncMock(
        access_token="jf-tok",
        user_id="uid-1",
        user_name="alice",
    )
    mock_jf.get_server_name.return_value = "MyJellyfin"

    settings = Settings(
        jellyfin_url="http://jellyfin-test:8096",
        session_secret=_SECRET,
        session_secure_cookie=False,
        log_level="debug",
        login_rate_limit="2/minute",
    )  # type: ignore[call-arg]

    store = SessionStore(str(db_path), _COLUMN_KEY)
    limiter = create_limiter()

    service = AuthService(
        session_store=store,
        jellyfin_client=mock_jf,
        session_expiry_hours=24,
        max_sessions_per_user=5,
    )

    app = FastAPI()
    app.state.limiter = limiter
    app.state.session_store = store
    app.state.cookie_key = _COOKIE_KEY
    app.add_exception_handler(
        RateLimitExceeded,
        _rate_limit_exceeded_handler,  # type: ignore[arg-type]
    )

    auth_router = create_auth_router(
        auth_service=service,
        session_store=store,
        settings=settings,
        cookie_key=_COOKIE_KEY,
        limiter=limiter,
    )
    app.include_router(auth_router)

    asyncio.get_event_loop().run_until_complete(store.init())
    client = TestClient(app)
    yield client  # type: ignore[misc]
    asyncio.get_event_loop().run_until_complete(store.close())


class TestRateLimiting:
    def test_within_limit_succeeds(self, rate_app: TestClient) -> None:
        """Requests within the rate limit succeed."""
        for _ in range(2):
            resp = rate_app.post(
                "/api/auth/login",
                json={"username": "alice", "password": "pass"},
            )
            assert resp.status_code in (200, 401)

    def test_exceeds_limit_returns_429(self, rate_app: TestClient) -> None:
        """Exceeding the rate limit returns 429."""
        for _ in range(2):
            rate_app.post(
                "/api/auth/login",
                json={"username": "alice", "password": "pass"},
            )
        resp = rate_app.post(
            "/api/auth/login",
            json={"username": "alice", "password": "pass"},
        )
        assert resp.status_code == 429
