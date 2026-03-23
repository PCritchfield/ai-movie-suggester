"""Unit tests for get_current_session FastAPI dependency."""

from __future__ import annotations

import time

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.auth.crypto import derive_keys, fernet_encrypt
from app.auth.dependencies import get_current_session
from app.auth.session_store import SessionStore

_SECRET = "kG7xP2mN9qR4wL8jT3vF6yA5dH0sE1cB"
_COOKIE_KEY, _COLUMN_KEY = derive_keys(_SECRET)


@pytest.fixture
def dep_app(tmp_path: object) -> TestClient:
    """Minimal app with a protected endpoint using get_current_session."""
    import asyncio
    import pathlib

    db_path = pathlib.Path(str(tmp_path)) / "dep_sessions.db"
    store = SessionStore(str(db_path), _COLUMN_KEY)

    app = FastAPI()
    app.state.cookie_key = _COOKIE_KEY
    app.state.session_store = store

    @app.get("/protected")
    async def protected(  # noqa: B008
        session: object = Depends(get_current_session),
    ) -> dict[str, str]:
        return {"user_id": session.user_id, "username": session.username}  # type: ignore[union-attr]

    asyncio.get_event_loop().run_until_complete(store.init())
    client = TestClient(app)
    yield client  # type: ignore[misc]
    asyncio.get_event_loop().run_until_complete(store.close())


def _make_session_cookie(session_id: str) -> str:
    return fernet_encrypt(_COOKIE_KEY, session_id).decode("utf-8")


class TestGetCurrentSession:
    def test_valid_session_returns_meta(self, dep_app: TestClient) -> None:
        import asyncio

        store: SessionStore = dep_app.app.state.session_store  # type: ignore[union-attr]
        asyncio.get_event_loop().run_until_complete(
            store.create(
                session_id="sid-dep",
                user_id="uid-1",
                username="alice",
                server_name="MyJellyfin",
                token="tok",
                csrf_token="csrf",
                expires_at=int(time.time()) + 3600,
            )
        )
        cookie = _make_session_cookie("sid-dep")
        resp = dep_app.get(
            "/protected", cookies={"session_id": cookie}
        )
        assert resp.status_code == 200
        assert resp.json()["user_id"] == "uid-1"

    def test_missing_cookie_returns_401(self, dep_app: TestClient) -> None:
        resp = dep_app.get("/protected")
        assert resp.status_code == 401

    def test_tampered_cookie_returns_401(self, dep_app: TestClient) -> None:
        resp = dep_app.get(
            "/protected", cookies={"session_id": "not-fernet"}
        )
        assert resp.status_code == 401

    def test_expired_session_returns_401(self, dep_app: TestClient) -> None:
        import asyncio

        store: SessionStore = dep_app.app.state.session_store  # type: ignore[union-attr]
        asyncio.get_event_loop().run_until_complete(
            store.create(
                session_id="sid-exp",
                user_id="uid-1",
                username="alice",
                server_name="MyJellyfin",
                token="tok",
                csrf_token="csrf",
                expires_at=int(time.time()) - 100,
            )
        )
        cookie = _make_session_cookie("sid-exp")
        resp = dep_app.get(
            "/protected", cookies={"session_id": cookie}
        )
        assert resp.status_code == 401

    def test_nonexistent_session_returns_401(
        self, dep_app: TestClient
    ) -> None:
        cookie = _make_session_cookie("sid-does-not-exist")
        resp = dep_app.get(
            "/protected", cookies={"session_id": cookie}
        )
        assert resp.status_code == 401
