"""Tests for the POST /api/play router (Spec 24, sub-tasks 5.1 and 5.2).

Covers: unauth, missing CSRF, CSRF mismatch, rate limit + per-route isolation,
happy path, full error matrix (DeviceOfflineError / PlaybackAuthError /
PlaybackDispatchError), pre-dispatch 409 (session not in list), INFO log
content (no item IDs / tokens / titles), and repr/str token-leakage on the
playback client instance.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock

import httpx
from fastapi import APIRouter, FastAPI, Request
from fastapi.testclient import TestClient
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.auth.crypto import derive_keys
from app.auth.dependencies import get_current_session
from app.auth.models import SessionMeta
from app.jellyfin.errors import (
    DeviceOfflineError,
    JellyfinAuthError,
    JellyfinConnectionError,
    JellyfinError,
    PlaybackAuthError,
    PlaybackDispatchError,
)
from app.jellyfin.playback import JellyfinPlaybackClient
from app.jellyfin.transport import _JellyfinTransport
from app.middleware.csrf import CSRFMiddleware
from app.middleware.rate_limit import create_limiter
from app.play.router import (
    create_play_router,
    get_playback_client,
    get_sessions_client,
)
from tests.conftest import TEST_SECRET, make_test_settings

if TYPE_CHECKING:
    import pytest

_COOKIE_KEY, _ = derive_keys(TEST_SECRET)
_SESSION_ID = "test-session-id-play"
_USER_ID = "uid-play-1"
_JELLY_TOKEN = "jf-user-token-xyz"


def _make_session_meta() -> SessionMeta:
    return SessionMeta(
        session_id=_SESSION_ID,
        user_id=_USER_ID,
        username="player",
        server_name="TestJellyfin",
        expires_at=int(time.time()) + 3600,
    )


def _register_fake_devices_route(app: FastAPI, limiter: Any) -> None:
    """Mount a cheap GET /api/devices-fake to exercise rate-limit isolation.

    ``Request`` must be importable from the module globals so FastAPI can
    resolve the stringified annotation under ``from __future__ import annotations``.
    """
    other = APIRouter(prefix="/api", tags=["devices-fake"])

    if limiter is not None:

        @other.get("/devices-fake")
        @limiter.limit("10/minute")
        async def _fake_devices(request: Request) -> list[Any]:  # noqa: ARG001
            return []

    else:

        @other.get("/devices-fake")
        async def _fake_devices_no_limit() -> list[Any]:
            return []

    app.include_router(other)


def _device(session_id: str = "sess-1", name: str = "Living Room TV") -> Any:
    """Build a stand-in Device-shaped object.

    Avoid importing the T1-only ``Device`` model — the router only needs
    ``.session_id``, ``.name``, and ``.device_type`` attributes and duck-types
    whatever the sessions client returns.
    """
    dev = MagicMock()
    dev.session_id = session_id
    dev.name = name
    dev.device_type = "Tv"
    return dev


def _make_play_app(
    *,
    sessions_return: list[Any] | None = None,
    sessions_side_effect: Exception | None = None,
    dispatch_side_effect: Exception | None = None,
    limiter: Any = None,
    enable_csrf_middleware: bool = False,
    with_auth: bool = True,
    with_other_router: bool = False,
) -> tuple[FastAPI, TestClient, AsyncMock, AsyncMock]:
    settings = make_test_settings()

    sessions_client = AsyncMock()
    if sessions_side_effect is not None:
        sessions_client.list_controllable = AsyncMock(side_effect=sessions_side_effect)
    else:
        sessions_client.list_controllable = AsyncMock(
            return_value=sessions_return if sessions_return is not None else [_device()]
        )

    playback_client = AsyncMock()
    if dispatch_side_effect is not None:
        playback_client.dispatch_play = AsyncMock(side_effect=dispatch_side_effect)
    else:
        playback_client.dispatch_play = AsyncMock(return_value=None)

    app = FastAPI()
    app.state.cookie_key = _COOKIE_KEY
    app.state.settings = settings
    app.state.limiter = limiter

    session_store = AsyncMock()
    session_store.get_token = AsyncMock(return_value=_JELLY_TOKEN)
    app.state.session_store = session_store

    if limiter is not None:
        app.state.limiter = limiter
        app.add_exception_handler(
            RateLimitExceeded,
            _rate_limit_exceeded_handler,  # type: ignore[arg-type]
        )

    play_router = create_play_router(settings=settings, limiter=limiter)
    app.include_router(play_router)

    # Dependency-override the capability clients.
    app.dependency_overrides[get_sessions_client] = lambda: sessions_client
    app.dependency_overrides[get_playback_client] = lambda: playback_client

    if with_auth:

        async def _mock_session() -> SessionMeta:
            return _make_session_meta()

        app.dependency_overrides[get_current_session] = _mock_session

    # Optional: mount a cheap second router under /api/devices-fake to
    # exercise per-route rate-limit isolation (5.1 c').
    if with_other_router:
        _register_fake_devices_route(app, limiter)

    if enable_csrf_middleware:
        app.add_middleware(CSRFMiddleware)

    return app, TestClient(app), sessions_client, playback_client


# ---------------------------------------------------------------------------
# Auth + CSRF
# ---------------------------------------------------------------------------


class TestPlayAuth:
    def test_unauthenticated_returns_401(self) -> None:
        _, client, _, _ = _make_play_app(with_auth=False)
        resp = client.post(
            "/api/play",
            json={"item_id": "item-1", "session_id": "sess-1"},
        )
        assert resp.status_code == 401


class TestPlayCSRF:
    def test_missing_csrf_returns_403(self) -> None:
        _, client, _, _ = _make_play_app(enable_csrf_middleware=True)
        client.cookies.set("session_id", "fake-session-cookie-value")
        resp = client.post(
            "/api/play",
            json={"item_id": "item-1", "session_id": "sess-1"},
        )
        assert resp.status_code == 403

    def test_csrf_mismatch_returns_403(self) -> None:
        """Present-but-wrong CSRF header vs. cookie → 403 (Angua-C3, Double-Submit)."""
        _, client, _, _ = _make_play_app(enable_csrf_middleware=True)
        client.cookies.set("session_id", "fake-session-cookie-value")
        client.cookies.set("csrf_token", "correct-value")
        resp = client.post(
            "/api/play",
            json={"item_id": "item-1", "session_id": "sess-1"},
            headers={"X-CSRF-Token": "wrong-value"},
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


class TestPlayRateLimit:
    def test_fourth_request_returns_429(self) -> None:
        """Spec pins 3/min on POST /api/play; 4th within 60s → 429."""
        limiter = create_limiter()
        _, client, _, _ = _make_play_app(limiter=limiter)

        body = {"item_id": "item-1", "session_id": "sess-1"}
        for _ in range(3):
            resp = client.post("/api/play", json=body)
            assert resp.status_code == 200
        resp = client.post("/api/play", json=body)
        assert resp.status_code == 429

    def test_per_route_rate_limit_isolation(self) -> None:
        """Rate-limit buckets are per-route (Angua-C4).

        Saturating the 10/min cap on a sibling GET route must not starve
        the 3/min bucket on POST /api/play.
        """
        limiter = create_limiter()
        _, client, _, _ = _make_play_app(limiter=limiter, with_other_router=True)

        # Saturate the sibling 10/min bucket.
        for _ in range(10):
            r = client.get("/api/devices-fake")
            assert r.status_code == 200

        # Issue a single POST /api/play — must NOT be 429 because buckets
        # are keyed per-route.
        resp = client.post(
            "/api/play",
            json={"item_id": "item-1", "session_id": "sess-1"},
        )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Happy path + error matrix
# ---------------------------------------------------------------------------


class TestPlayHappyPath:
    def test_happy_path_returns_200_with_device_name(self) -> None:
        _, client, sessions_client, playback_client = _make_play_app(
            sessions_return=[_device("sess-1", "Living Room TV")]
        )
        resp = client.post(
            "/api/play",
            json={"item_id": "item-abc", "session_id": "sess-1"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok", "device_name": "Living Room TV"}
        sessions_client.list_controllable.assert_awaited_once_with(_JELLY_TOKEN)
        playback_client.dispatch_play.assert_awaited_once_with(
            "sess-1", "item-abc", _JELLY_TOKEN
        )


class TestPlayErrorMatrix:
    def test_device_offline_returns_409(self) -> None:
        """DeviceOfflineError from dispatch_play → 409 (post-dispatch)."""
        _, client, _, _ = _make_play_app(
            sessions_return=[_device("sess-1", "TV")],
            dispatch_side_effect=DeviceOfflineError("gone"),
        )
        resp = client.post(
            "/api/play",
            json={"item_id": "item-1", "session_id": "sess-1"},
        )
        assert resp.status_code == 409
        assert resp.json() == {"error": "device_offline"}

    def test_playback_auth_error_returns_401(self) -> None:
        _, client, _, _ = _make_play_app(
            sessions_return=[_device("sess-1", "TV")],
            dispatch_side_effect=PlaybackAuthError("bad token"),
        )
        resp = client.post(
            "/api/play",
            json={"item_id": "item-1", "session_id": "sess-1"},
        )
        assert resp.status_code == 401
        assert resp.json() == {"error": "jellyfin_auth_failed"}

    def test_playback_dispatch_error_returns_500(self) -> None:
        _, client, _, _ = _make_play_app(
            sessions_return=[_device("sess-1", "TV")],
            dispatch_side_effect=PlaybackDispatchError("broken"),
        )
        resp = client.post(
            "/api/play",
            json={"item_id": "item-1", "session_id": "sess-1"},
        )
        assert resp.status_code == 500
        assert resp.json() == {"error": "playback_failed"}


# ---------------------------------------------------------------------------
# Step-1 error matrix — list_controllable raises (Copilot review fix)
# ---------------------------------------------------------------------------


class TestPlayListControllableErrorMatrix:
    """list_controllable (step 1) must produce documented error shapes.

    Without these mappings, a revoked token or upstream failure during
    device resolution returns an unstructured 500. The router is the
    orchestration layer (Granny-B4); it owns the HTTP translation from
    the typed JellyfinError subclasses raised by the capability client.
    """

    def test_list_controllable_auth_error_returns_401(self) -> None:
        _, client, sessions_client, playback_client = _make_play_app(
            sessions_side_effect=JellyfinAuthError("token revoked"),
        )
        resp = client.post(
            "/api/play",
            json={"item_id": "item-1", "session_id": "sess-1"},
        )
        assert resp.status_code == 401
        assert resp.json() == {"error": "jellyfin_auth_failed"}
        sessions_client.list_controllable.assert_awaited_once_with(_JELLY_TOKEN)
        playback_client.dispatch_play.assert_not_called()

    def test_list_controllable_connection_error_returns_503(self) -> None:
        _, client, sessions_client, playback_client = _make_play_app(
            sessions_side_effect=JellyfinConnectionError("unreachable"),
        )
        resp = client.post(
            "/api/play",
            json={"item_id": "item-1", "session_id": "sess-1"},
        )
        assert resp.status_code == 503
        assert resp.json() == {"error": "jellyfin_unreachable"}
        sessions_client.list_controllable.assert_awaited_once_with(_JELLY_TOKEN)
        playback_client.dispatch_play.assert_not_called()

    def test_list_controllable_generic_jellyfin_error_returns_502(self) -> None:
        _, client, sessions_client, playback_client = _make_play_app(
            sessions_side_effect=JellyfinError("unexpected upstream"),
        )
        resp = client.post(
            "/api/play",
            json={"item_id": "item-1", "session_id": "sess-1"},
        )
        assert resp.status_code == 502
        assert resp.json() == {"error": "jellyfin_error"}
        sessions_client.list_controllable.assert_awaited_once_with(_JELLY_TOKEN)
        playback_client.dispatch_play.assert_not_called()


# ---------------------------------------------------------------------------
# Pre-dispatch 409 — session_id not in the list (Carrot A1)
# ---------------------------------------------------------------------------


class TestPlayPreDispatch409:
    def test_session_not_in_list_returns_409_without_calling_dispatch(self) -> None:
        """If list_controllable does not return the requested session_id,
        the router must return 409 without invoking dispatch_play."""
        _, client, sessions_client, playback_client = _make_play_app(
            sessions_return=[_device("other-session", "Other TV")]
        )
        resp = client.post(
            "/api/play",
            json={"item_id": "item-1", "session_id": "missing-session"},
        )
        assert resp.status_code == 409
        assert resp.json() == {"error": "device_offline"}
        sessions_client.list_controllable.assert_awaited_once_with(_JELLY_TOKEN)
        playback_client.dispatch_play.assert_not_called()


# ---------------------------------------------------------------------------
# Log-content assertion (5.2) — no PII in INFO records on happy dispatch
# ---------------------------------------------------------------------------


class TestPlayLogContent:
    def test_play_log_content_has_no_pii(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        _, client, _, _ = _make_play_app(
            sessions_return=[_device("sess-xyz", "Living Room TV")]
        )
        caplog.set_level(logging.INFO, logger="app.play.router")
        resp = client.post(
            "/api/play",
            json={"item_id": "item-abc-123", "session_id": "sess-xyz"},
        )
        assert resp.status_code == 200

        full_log = caplog.text
        assert "item-abc-123" not in full_log
        assert _JELLY_TOKEN not in full_log
        # The dispatch INFO line is present, carrying only device_name +
        # device_type (the spec forbids all other fields).
        dispatch_records = [
            r
            for r in caplog.records
            if r.levelno == logging.INFO and "play dispatched" in r.getMessage()
        ]
        assert len(dispatch_records) == 1
        record = dispatch_records[0]
        # extra={} flatten onto the record — confirm the two required keys
        # are present and that forbidden ones are not.
        assert getattr(record, "device_name", None) == "Living Room TV"
        assert getattr(record, "device_type", None) == "Tv"
        for banned in ("item_id", "item_ids", "session_id", "token", "user_token"):
            assert not hasattr(record, banned), (
                f"LogRecord unexpectedly carries {banned}: {record.__dict__}"
            )


# ---------------------------------------------------------------------------
# Playback-client repr/str token-leakage guard (Angua-C1 mirror)
# ---------------------------------------------------------------------------


class TestPlaybackClientTokenGuardRouter:
    async def test_playback_client_repr_and_str_have_no_token(self) -> None:
        transport = _JellyfinTransport(
            base_url="https://jellyfin.example",
            http_client=MagicMock(spec=httpx.AsyncClient),
        )
        client = JellyfinPlaybackClient(transport=transport)
        assert _JELLY_TOKEN not in repr(client)
        assert _JELLY_TOKEN not in str(client)
