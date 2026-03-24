"""Unit tests for AuthService — session cap enforcement and expiry cleanup."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock

import pytest

from app.auth.crypto import derive_keys
from app.auth.service import AuthService, cleanup_expired_sessions
from app.auth.session_store import SessionStore
from app.jellyfin.errors import JellyfinConnectionError

_SECRET = "kG7xP2mN9qR4wL8jT3vF6yA5dH0sE1cB"
_COOKIE_KEY, _COLUMN_KEY = derive_keys(_SECRET)


@pytest.fixture
async def store(tmp_path: object) -> SessionStore:
    import pathlib

    db_path = pathlib.Path(str(tmp_path)) / "svc_sessions.db"
    s = SessionStore(str(db_path), _COLUMN_KEY)
    await s.init()
    yield s  # type: ignore[misc]
    await s.close()


@pytest.fixture
def mock_jf() -> AsyncMock:
    jf = AsyncMock()
    jf.authenticate.return_value = AsyncMock(
        access_token="jf-tok-new",
        user_id="uid-1",
        user_name="alice",
    )
    jf.get_server_name.return_value = "MyJellyfin"
    jf.logout.return_value = None
    return jf


@pytest.fixture
def service(store: SessionStore, mock_jf: AsyncMock) -> AuthService:
    return AuthService(
        session_store=store,
        jellyfin_client=mock_jf,
        session_expiry_hours=24,
        max_sessions_per_user=5,
    )


async def _create_sessions(store: SessionStore, user_id: str, count: int) -> list[str]:
    """Helper: create N sessions for a user, return session IDs."""
    now = int(time.time())
    ids = []
    for i in range(count):
        sid = f"sid-{user_id}-{i}"
        await store.create(
            session_id=sid,
            user_id=user_id,
            username="alice",
            server_name="MyJellyfin",
            token=f"tok-{i}",
            csrf_token=f"csrf-{i}",
            expires_at=now + 3600,
        )
        ids.append(sid)
    return ids


class TestSessionCapEnforcement:
    async def test_sixth_login_evicts_oldest(
        self, service: AuthService, store: SessionStore, mock_jf: AsyncMock
    ) -> None:
        """Create 5 sessions, login again, verify only 5 remain."""
        ids = await _create_sessions(store, "uid-1", 5)
        assert await store.count_by_user("uid-1") == 5

        # 6th login
        session_id, _, _ = await service.login("alice", "pass")
        assert await store.count_by_user("uid-1") == 5

        # Oldest session should be gone
        assert await store.get(ids[0]) is None
        # New session should exist
        assert await store.get(session_id) is not None

    async def test_eviction_revokes_jellyfin_token(
        self, service: AuthService, store: SessionStore, mock_jf: AsyncMock
    ) -> None:
        """Evicted session's Jellyfin token should be revoked."""
        await _create_sessions(store, "uid-1", 5)
        await service.login("alice", "pass")
        # logout called with oldest session's token
        mock_jf.logout.assert_called_once_with("tok-0")

    async def test_eviction_when_jellyfin_unreachable(
        self,
        service: AuthService,
        store: SessionStore,
        mock_jf: AsyncMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Cap enforcement continues even if Jellyfin is unreachable."""
        import logging

        mock_jf.logout.side_effect = JellyfinConnectionError("down")
        await _create_sessions(store, "uid-1", 5)

        with caplog.at_level(logging.INFO):
            session_id, _, _ = await service.login("alice", "pass")

        # Session still evicted locally
        assert await store.count_by_user("uid-1") == 5
        assert await store.get(session_id) is not None
        assert any("session_evicted" in r.message for r in caplog.records)
        assert any("jellyfin unreachable" in r.message for r in caplog.records)

    async def test_new_session_valid_after_eviction(
        self, service: AuthService, store: SessionStore, mock_jf: AsyncMock
    ) -> None:
        """The new (6th) session should be valid and retrievable."""
        await _create_sessions(store, "uid-1", 5)
        session_id, _, resp = await service.login("alice", "pass")
        session = await store.get(session_id)
        assert session is not None
        assert session.user_id == "uid-1"
        assert resp.user_id == "uid-1"


class TestExpiredSessionCleanup:
    async def test_cleanup_deletes_expired(
        self, store: SessionStore, mock_jf: AsyncMock
    ) -> None:
        now = int(time.time())
        await store.create(
            session_id="sid-exp",
            user_id="uid-1",
            username="alice",
            server_name="MyJellyfin",
            token="tok-exp",
            csrf_token="csrf",
            expires_at=now - 100,
        )
        await cleanup_expired_sessions(store, mock_jf)
        assert await store.get("sid-exp") is None

    async def test_cleanup_revokes_token(
        self, store: SessionStore, mock_jf: AsyncMock
    ) -> None:
        now = int(time.time())
        await store.create(
            session_id="sid-exp2",
            user_id="uid-1",
            username="alice",
            server_name="MyJellyfin",
            token="tok-exp2",
            csrf_token="csrf",
            expires_at=now - 100,
        )
        await cleanup_expired_sessions(store, mock_jf)
        mock_jf.logout.assert_called_once_with("tok-exp2")

    async def test_cleanup_jellyfin_unreachable(
        self,
        store: SessionStore,
        mock_jf: AsyncMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        import logging

        now = int(time.time())
        mock_jf.logout.side_effect = JellyfinConnectionError("down")
        await store.create(
            session_id="sid-exp3",
            user_id="uid-1",
            username="alice",
            server_name="MyJellyfin",
            token="tok-exp3",
            csrf_token="csrf",
            expires_at=now - 100,
        )
        with caplog.at_level(logging.WARNING):
            await cleanup_expired_sessions(store, mock_jf)

        # Session still deleted
        assert await store.get("sid-exp3") is None
        assert any("jellyfin unreachable" in r.message.lower() for r in caplog.records)
