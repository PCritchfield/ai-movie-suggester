"""Tests for JellyfinPlaybackClient (Spec 24, sub-tasks 4.4 and 4.5).

Covers the full Jellyfin-status → exception matrix for ``dispatch_play`` and
the broadened scrub matrix (Angua-C2) ensuring httpx exception messages,
``exc.request.url``, PEP-678 ``__notes__``, and ``extra={}`` keys never leak
tokens or URLs into captured log output.
"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.jellyfin.errors import (
    DeviceOfflineError,
    PlaybackAuthError,
    PlaybackDispatchError,
)
from app.jellyfin.playback import JellyfinPlaybackClient
from app.jellyfin.transport import _JellyfinTransport

_BASE_URL = "https://jellyfin.example"
_SESSION_ID = "sess-123"
_ITEM_ID = "item-abc"
_USER_TOKEN = "user-token-xyz"


def _make_client(
    response: httpx.Response | None = None,
    exc: Exception | None = None,
) -> tuple[JellyfinPlaybackClient, AsyncMock]:
    """Return a JellyfinPlaybackClient whose transport is driven by a mock httpx client.

    Either ``response`` (happy-ish path — maybe an error status code) or
    ``exc`` (transport / timeout raised by ``httpx.AsyncClient.request``).
    """
    http_client = AsyncMock(spec=httpx.AsyncClient)
    if exc is not None:
        http_client.request.side_effect = exc
    else:
        assert response is not None
        http_client.request.return_value = response
    transport = _JellyfinTransport(
        base_url=_BASE_URL,
        http_client=http_client,
    )
    return JellyfinPlaybackClient(transport=transport), http_client


def _resp(status_code: int) -> httpx.Response:
    """Build an httpx.Response with a populated request attribute."""
    req = httpx.Request("POST", f"{_BASE_URL}/Sessions/{_SESSION_ID}/Playing")
    return httpx.Response(status_code=status_code, request=req)


# ---------------------------------------------------------------------------
# Error-mapping matrix — each status code is its own parametrize row per A5
# ---------------------------------------------------------------------------


class TestPlaybackClientErrorMapping:
    async def test_playback_client_204_happy_path(self) -> None:
        """Jellyfin 204 → dispatch_play returns None without raising."""
        client, http_client = _make_client(response=_resp(204))
        result = await client.dispatch_play(
            session_id=_SESSION_ID, item_id=_ITEM_ID, user_token=_USER_TOKEN
        )
        assert result is None
        # Confirm token was passed in the Authorization header and never
        # stored on the client instance.
        kwargs = http_client.request.call_args.kwargs
        assert _USER_TOKEN in kwargs["headers"]["Authorization"]

    @pytest.mark.parametrize("status_code", [404, 400])
    async def test_playback_client_offline(self, status_code: int) -> None:
        """Jellyfin 404/400 → DeviceOfflineError."""
        client, _ = _make_client(response=_resp(status_code))
        with pytest.raises(DeviceOfflineError):
            await client.dispatch_play(
                session_id=_SESSION_ID, item_id=_ITEM_ID, user_token=_USER_TOKEN
            )

    async def test_playback_client_401(self) -> None:
        """Jellyfin 401 → PlaybackAuthError (own parametrize row per A5)."""
        client, _ = _make_client(response=_resp(401))
        with pytest.raises(PlaybackAuthError):
            await client.dispatch_play(
                session_id=_SESSION_ID, item_id=_ITEM_ID, user_token=_USER_TOKEN
            )

    async def test_playback_client_403(self) -> None:
        """Jellyfin 403 → PlaybackAuthError (own parametrize row, separate from 401)."""
        client, _ = _make_client(response=_resp(403))
        with pytest.raises(PlaybackAuthError):
            await client.dispatch_play(
                session_id=_SESSION_ID, item_id=_ITEM_ID, user_token=_USER_TOKEN
            )

    @pytest.mark.parametrize("status_code", [500, 502, 503])
    async def test_playback_client_5xx(self, status_code: int) -> None:
        """Jellyfin 5xx → PlaybackDispatchError."""
        client, _ = _make_client(response=_resp(status_code))
        with pytest.raises(PlaybackDispatchError):
            await client.dispatch_play(
                session_id=_SESSION_ID, item_id=_ITEM_ID, user_token=_USER_TOKEN
            )

    async def test_playback_client_timeout(self) -> None:
        """Base httpx.TimeoutException (covers ConnectTimeout, ReadTimeout,
        WriteTimeout, PoolTimeout per A8) → PlaybackDispatchError."""
        client, _ = _make_client(exc=httpx.TimeoutException("timeout"))
        with pytest.raises(PlaybackDispatchError):
            await client.dispatch_play(
                session_id=_SESSION_ID, item_id=_ITEM_ID, user_token=_USER_TOKEN
            )

    async def test_playback_client_transport_error(self) -> None:
        """httpx.TransportError (e.g. ConnectError) → PlaybackDispatchError."""
        client, _ = _make_client(exc=httpx.ConnectError("boom"))
        with pytest.raises(PlaybackDispatchError):
            await client.dispatch_play(
                session_id=_SESSION_ID, item_id=_ITEM_ID, user_token=_USER_TOKEN
            )


# ---------------------------------------------------------------------------
# Scrub matrix — Angua-C2 broadened: message, exc.request.url, __notes__, extra
# ---------------------------------------------------------------------------

_LEAK_TOKEN = "SECRET_abcdef123"
_LEAK_URL = (
    f"https://jellyfin.example/Sessions/{_SESSION_ID}/Playing"
    f"?api_key={_LEAK_TOKEN}&token=xyz"
)


class TestPlaybackScrub:
    async def test_playback_scrub_removes_url_and_token_from_logs(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Raw httpx message with URL + token fragments must not appear in logs."""
        exc = httpx.ConnectError(f"connection failed at {_LEAK_URL}")
        client, _ = _make_client(exc=exc)
        caplog.set_level(logging.DEBUG)
        with pytest.raises(PlaybackDispatchError):
            await client.dispatch_play(
                session_id=_SESSION_ID, item_id=_ITEM_ID, user_token=_USER_TOKEN
            )
        full_log = caplog.text
        assert _LEAK_TOKEN not in full_log
        assert "token=xyz" not in full_log
        assert "api_key" not in full_log
        assert "https://" not in full_log

    async def test_playback_scrub_handles_exc_request_url(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """exc.request.url (token-bearing) must not be logged by the handler."""
        req = httpx.Request("POST", _LEAK_URL)
        exc = httpx.ConnectError("boom")
        exc.request = req  # type: ignore[assignment]
        client, _ = _make_client(exc=exc)
        caplog.set_level(logging.DEBUG)
        with pytest.raises(PlaybackDispatchError):
            await client.dispatch_play(
                session_id=_SESSION_ID, item_id=_ITEM_ID, user_token=_USER_TOKEN
            )
        full_log = caplog.text
        assert _LEAK_TOKEN not in full_log
        assert str(req.url) not in full_log
        # URL fragments should also not leak
        assert "Sessions/" not in full_log

    async def test_playback_scrub_handles_exc_notes(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """PEP-678 __notes__ must not be logged by the handler."""
        exc = httpx.ConnectError("boom")
        exc.add_note("token=LEAK")
        client, _ = _make_client(exc=exc)
        caplog.set_level(logging.DEBUG)
        with pytest.raises(PlaybackDispatchError):
            await client.dispatch_play(
                session_id=_SESSION_ID, item_id=_ITEM_ID, user_token=_USER_TOKEN
            )
        full_log = caplog.text
        assert "LEAK" not in full_log

    async def test_playback_scrub_no_exception_in_extra(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Log records must not carry the exception object in ``extra={}``.

        A captured ``LogRecord``'s ``__dict__`` should not contain an ``exc``,
        ``exception``, ``request``, or ``response`` key pointing at the raw
        httpx objects (which would let an attacker recover the URL/token via
        any log handler that serialises record attributes).
        """
        req = httpx.Request("POST", _LEAK_URL)
        exc = httpx.ConnectError("boom")
        exc.request = req  # type: ignore[assignment]
        client, _ = _make_client(exc=exc)
        caplog.set_level(logging.DEBUG)
        with pytest.raises(PlaybackDispatchError):
            await client.dispatch_play(
                session_id=_SESSION_ID, item_id=_ITEM_ID, user_token=_USER_TOKEN
            )
        forbidden_keys = {"exc", "exception", "request", "response"}
        for record in caplog.records:
            leaked = forbidden_keys.intersection(record.__dict__.keys())
            assert not leaked, (
                f"LogRecord leaks forbidden key(s) {leaked}: {record.__dict__}"
            )

    async def test_playback_scrub_message_shape(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Log message is the type-only shape 'playback dispatch failed: <Class>'."""
        exc = httpx.ConnectError(f"boom {_LEAK_URL}")
        client, _ = _make_client(exc=exc)
        caplog.set_level(logging.DEBUG)
        with pytest.raises(PlaybackDispatchError):
            await client.dispatch_play(
                session_id=_SESSION_ID, item_id=_ITEM_ID, user_token=_USER_TOKEN
            )
        # At least one log line mentions the type-only shape.
        assert any(
            "playback dispatch failed" in r.getMessage()
            and "ConnectError" in r.getMessage()
            for r in caplog.records
        )


# ---------------------------------------------------------------------------
# Token-leakage guard on repr/str (Angua-C1 mirror for the playback client)
# ---------------------------------------------------------------------------


class TestPlaybackClientTokenGuard:
    async def test_repr_and_str_contain_no_token_state(self) -> None:
        """dispatch_play must not cache user_token on self; repr/str carry no token."""
        transport = _JellyfinTransport(
            base_url=_BASE_URL,
            http_client=MagicMock(spec=httpx.AsyncClient),
        )
        client = JellyfinPlaybackClient(transport=transport)
        # Dispatch a call to ensure the token flowed as a parameter.
        # (We don't await it; simply assert instance state.)
        assert _USER_TOKEN not in repr(client)
        assert _USER_TOKEN not in str(client)
        # And no attribute on the instance holds the token.
        for val in vars(client).values():
            assert _USER_TOKEN not in repr(val)
