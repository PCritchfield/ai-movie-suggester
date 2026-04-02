"""Unit tests for the async SQLite session repository."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import pytest

from app.auth.crypto import derive_keys
from app.auth.session_store import SessionStore

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

_SECRET = "test-secret-at-least-32-characters-long"
_COOKIE_KEY, _COLUMN_KEY = derive_keys(_SECRET)


@pytest.fixture
async def store(tmp_path: object) -> AsyncIterator[SessionStore]:
    """Provide a fresh SessionStore backed by a temp DB."""
    # tmp_path is a pathlib.Path — pytest provides it
    import pathlib

    db_path = pathlib.Path(str(tmp_path)) / "test_sessions.db"
    s = SessionStore(str(db_path), _COLUMN_KEY)
    await s.init()
    yield s  # type: ignore[misc]
    await s.close()


def _now() -> int:
    return int(time.time())


class TestSessionLifecycle:
    """create / get / delete round-trip."""

    async def test_create_and_get(self, store: SessionStore) -> None:
        await store.create(
            session_id="sid-1",
            user_id="uid-1",
            username="alice",
            server_name="MyJellyfin",
            token="jf-token-abc",
            csrf_token="csrf-123",
            expires_at=_now() + 3600,
        )
        row = await store.get("sid-1")
        assert row is not None
        assert row.session_id == "sid-1"
        assert row.user_id == "uid-1"
        assert row.username == "alice"
        assert row.server_name == "MyJellyfin"
        assert row.token == "jf-token-abc"
        assert row.csrf_token == "csrf-123"

    async def test_get_returns_none_for_missing(self, store: SessionStore) -> None:
        assert await store.get("nonexistent") is None

    async def test_delete_removes_session(self, store: SessionStore) -> None:
        await store.create(
            session_id="sid-del",
            user_id="uid-1",
            username="alice",
            server_name="MyJellyfin",
            token="tok",
            csrf_token="csrf",
            expires_at=_now() + 3600,
        )
        await store.delete("sid-del")
        assert await store.get("sid-del") is None


class TestGetMetadata:
    """get_metadata returns SessionMeta without decrypting token."""

    async def test_returns_metadata(self, store: SessionStore) -> None:
        await store.create(
            session_id="sid-m",
            user_id="uid-1",
            username="alice",
            server_name="MyJellyfin",
            token="secret-token",
            csrf_token="csrf-abc",
            expires_at=_now() + 3600,
        )
        meta = await store.get_metadata("sid-m")
        assert meta is not None
        assert meta.session_id == "sid-m"
        assert meta.user_id == "uid-1"
        assert meta.username == "alice"
        assert meta.server_name == "MyJellyfin"
        assert not hasattr(meta, "token")

    async def test_returns_none_for_missing(self, store: SessionStore) -> None:
        assert await store.get_metadata("nope") is None


class TestGetToken:
    """get_token returns decrypted token with expiry check."""

    async def test_returns_decrypted_token(self, store: SessionStore) -> None:
        await store.create(
            session_id="sid-tok",
            user_id="uid-1",
            username="alice",
            server_name="MyJellyfin",
            token="jf-secret-token",
            csrf_token="csrf-123",
            expires_at=_now() + 3600,
        )
        token = await store.get_token("sid-tok")
        assert token == "jf-secret-token"

    async def test_returns_none_for_expired(self, store: SessionStore) -> None:
        await store.create(
            session_id="sid-exp",
            user_id="uid-1",
            username="alice",
            server_name="MyJellyfin",
            token="expired-token",
            csrf_token="csrf-123",
            expires_at=_now() - 100,
        )
        assert await store.get_token("sid-exp") is None

    async def test_returns_none_for_missing(self, store: SessionStore) -> None:
        assert await store.get_token("nonexistent") is None


class TestCountAndOldest:
    """count_by_user and oldest_by_user."""

    async def test_count_by_user(self, store: SessionStore) -> None:
        now = _now()
        for i in range(3):
            await store.create(
                session_id=f"sid-{i}",
                user_id="uid-1",
                username="alice",
                server_name="MyJellyfin",
                token=f"tok-{i}",
                csrf_token=f"csrf-{i}",
                expires_at=now + 3600,
            )
        assert await store.count_by_user("uid-1") == 3
        assert await store.count_by_user("uid-other") == 0

    async def test_oldest_by_user(
        self, store: SessionStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        now = _now()
        # Ensure distinct created_at values so ordering is deterministic
        monkeypatch.setattr(time, "time", lambda: now - 100)
        await store.create(
            session_id="sid-old",
            user_id="uid-1",
            username="alice",
            server_name="MyJellyfin",
            token="tok-old",
            csrf_token="csrf-old",
            expires_at=now + 3600,
        )
        monkeypatch.setattr(time, "time", lambda: now)
        await store.create(
            session_id="sid-new",
            user_id="uid-1",
            username="alice",
            server_name="MyJellyfin",
            token="tok-new",
            csrf_token="csrf-new",
            expires_at=now + 7200,
        )
        monkeypatch.undo()
        oldest = await store.oldest_by_user("uid-1")
        assert oldest is not None
        assert oldest.session_id == "sid-old"

    async def test_oldest_by_user_tiebreak_by_session_id(
        self, store: SessionStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When created_at is identical, tie-break by session_id ASC."""
        now = _now()
        monkeypatch.setattr(time, "time", lambda: now)
        await store.create(
            session_id="sid-zebra",
            user_id="uid-1",
            username="alice",
            server_name="MyJellyfin",
            token="tok-z",
            csrf_token="csrf-z",
            expires_at=now + 3600,
        )
        await store.create(
            session_id="sid-alpha",
            user_id="uid-1",
            username="alice",
            server_name="MyJellyfin",
            token="tok-a",
            csrf_token="csrf-a",
            expires_at=now + 3600,
        )
        monkeypatch.undo()
        oldest = await store.oldest_by_user("uid-1")
        assert oldest is not None
        assert oldest.session_id == "sid-alpha"  # 'a' < 'z' in ASC order

    async def test_oldest_by_user_returns_none_when_empty(
        self, store: SessionStore
    ) -> None:
        assert await store.oldest_by_user("uid-nobody") is None


class TestExpired:
    """get_expired returns sessions past expires_at."""

    async def test_get_expired(self, store: SessionStore) -> None:
        now = _now()
        # Expired session
        await store.create(
            session_id="sid-exp",
            user_id="uid-1",
            username="alice",
            server_name="MyJellyfin",
            token="tok-exp",
            csrf_token="csrf-exp",
            expires_at=now - 100,
        )
        # Valid session
        await store.create(
            session_id="sid-valid",
            user_id="uid-1",
            username="alice",
            server_name="MyJellyfin",
            token="tok-valid",
            csrf_token="csrf-valid",
            expires_at=now + 3600,
        )
        expired = await store.get_expired()
        assert len(expired) == 1
        assert expired[0].session_id == "sid-exp"


class TestDeleteAllByUser:
    """delete_all_by_user removes all sessions for a user."""

    async def test_delete_all_by_user(self, store: SessionStore) -> None:
        now = _now()
        for i in range(3):
            await store.create(
                session_id=f"sid-u1-{i}",
                user_id="uid-1",
                username="alice",
                server_name="MyJellyfin",
                token=f"tok-{i}",
                csrf_token=f"csrf-{i}",
                expires_at=now + 3600,
            )
        await store.create(
            session_id="sid-u2",
            user_id="uid-2",
            username="bob",
            server_name="MyJellyfin",
            token="tok-bob",
            csrf_token="csrf-bob",
            expires_at=now + 3600,
        )
        count = await store.delete_all_by_user("uid-1")
        assert count == 3
        assert await store.count_by_user("uid-1") == 0
        assert await store.count_by_user("uid-2") == 1
