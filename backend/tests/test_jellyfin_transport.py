"""Unit tests for the shared Jellyfin transport helper.

The transport helper is extracted from JellyfinClient and consumed by
future capability clients (JellyfinSessionsClient, JellyfinPlaybackClient)
via composition. This module asserts:

* MediaBrowser Authorization header format (with and without token)
* 401 → JellyfinAuthError mapping
* Transport failure → JellyfinConnectionError mapping
* Non-2xx non-401 → JellyfinError wrapping
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest

from app.jellyfin.errors import (
    JellyfinAuthError,
    JellyfinConnectionError,
    JellyfinError,
)
from app.jellyfin.transport import _JellyfinTransport

_FAKE_REQUEST = httpx.Request("GET", "http://fake")


@pytest.fixture
def mock_http() -> AsyncMock:
    """Mock httpx.AsyncClient for unit tests."""
    return AsyncMock(spec=httpx.AsyncClient)


@pytest.fixture
def transport(mock_http: AsyncMock) -> _JellyfinTransport:
    return _JellyfinTransport(
        base_url="http://jellyfin:8096",
        client=mock_http,
    )


class TestHeadersBuilder:
    """MediaBrowser Authorization header construction."""

    def test_headers_without_token(self, transport: _JellyfinTransport) -> None:
        headers = transport.headers()
        auth = headers["Authorization"]
        assert auth.startswith("MediaBrowser ")
        assert 'Client="ai-movie-suggester"' in auth
        assert 'Device="Server"' in auth
        assert "DeviceId=" in auth
        assert 'Version="0.1.0"' in auth
        assert "Token=" not in auth

    def test_headers_with_token(self, transport: _JellyfinTransport) -> None:
        headers = transport.headers(token="my-token")
        auth = headers["Authorization"]
        assert auth.endswith(", Token=my-token")
        assert 'Client="ai-movie-suggester"' in auth

    def test_custom_device_id(self, mock_http: AsyncMock) -> None:
        t = _JellyfinTransport(
            base_url="http://jellyfin:8096",
            client=mock_http,
            device_id="custom-id",
        )
        headers = t.headers()
        assert 'DeviceId="custom-id"' in headers["Authorization"]

    def test_base_url_trailing_slash_stripped(self, mock_http: AsyncMock) -> None:
        t = _JellyfinTransport(
            base_url="http://jellyfin:8096/",
            client=mock_http,
        )
        assert t.base_url == "http://jellyfin:8096"

    def test_token_whitespace_stripped(self, transport: _JellyfinTransport) -> None:
        headers = transport.headers(token="  tok-123  ")
        auth = headers["Authorization"]
        assert auth.endswith(", Token=tok-123")
        # No extra quotes sneaked in
        assert 'Token="' not in auth


class TestRequest:
    """_JellyfinTransport.request() error mapping."""

    async def test_401_raises_jellyfin_auth_error(
        self, transport: _JellyfinTransport, mock_http: AsyncMock
    ) -> None:
        mock_http.request.return_value = httpx.Response(401, request=_FAKE_REQUEST)
        with pytest.raises(JellyfinAuthError):
            await transport.request("GET", "/Sessions", token="tok-123")

    async def test_401_default_message(
        self, transport: _JellyfinTransport, mock_http: AsyncMock
    ) -> None:
        mock_http.request.return_value = httpx.Response(401, request=_FAKE_REQUEST)
        with pytest.raises(JellyfinAuthError) as info:
            await transport.request("GET", "/Sessions", token="tok-123")
        assert "Token is invalid or expired" in str(info.value)

    async def test_401_custom_auth_error_message(
        self, transport: _JellyfinTransport, mock_http: AsyncMock
    ) -> None:
        mock_http.request.return_value = httpx.Response(401, request=_FAKE_REQUEST)
        with pytest.raises(JellyfinAuthError) as info:
            await transport.request(
                "POST",
                "/Users/AuthenticateByName",
                auth_error_message="Invalid username or password",
            )
        assert "Invalid username or password" in str(info.value)

    async def test_transport_error_raises_connection_error(
        self, transport: _JellyfinTransport, mock_http: AsyncMock
    ) -> None:
        mock_http.request.side_effect = httpx.ConnectError("refused")
        with pytest.raises(JellyfinConnectionError) as info:
            await transport.request("GET", "/Sessions")
        assert "http://jellyfin:8096" in str(info.value)

    async def test_unexpected_status_raises_jellyfin_error(
        self, transport: _JellyfinTransport, mock_http: AsyncMock
    ) -> None:
        mock_http.request.return_value = httpx.Response(500, request=_FAKE_REQUEST)
        with pytest.raises(JellyfinError) as info:
            await transport.request("GET", "/Sessions")
        # The wrapped error is *not* JellyfinAuthError or JellyfinConnectionError
        assert not isinstance(info.value, JellyfinAuthError)
        assert not isinstance(info.value, JellyfinConnectionError)
        assert "500" in str(info.value)

    async def test_success_returns_response(
        self, transport: _JellyfinTransport, mock_http: AsyncMock
    ) -> None:
        mock_http.request.return_value = httpx.Response(
            200, json={"ok": True}, request=_FAKE_REQUEST
        )
        resp = await transport.request("GET", "/Sessions")
        assert resp.status_code == 200

    async def test_request_sends_auth_header_with_token(
        self, transport: _JellyfinTransport, mock_http: AsyncMock
    ) -> None:
        mock_http.request.return_value = httpx.Response(
            200, json=[], request=_FAKE_REQUEST
        )
        await transport.request("GET", "/Sessions", token="tok-xyz")
        call = mock_http.request.call_args
        assert "Token=tok-xyz" in call.kwargs["headers"]["Authorization"]

    async def test_request_passes_through_kwargs(
        self, transport: _JellyfinTransport, mock_http: AsyncMock
    ) -> None:
        mock_http.request.return_value = httpx.Response(
            200, json={}, request=_FAKE_REQUEST
        )
        await transport.request(
            "POST",
            "/Sessions/abc/Playing",
            params={"itemIds": "item-1"},
            json={"foo": "bar"},
        )
        call = mock_http.request.call_args
        assert call.kwargs["params"] == {"itemIds": "item-1"}
        assert call.kwargs["json"] == {"foo": "bar"}

    async def test_request_uses_base_url(
        self, transport: _JellyfinTransport, mock_http: AsyncMock
    ) -> None:
        mock_http.request.return_value = httpx.Response(
            200, json={}, request=_FAKE_REQUEST
        )
        await transport.request("GET", "/Sessions")
        call = mock_http.request.call_args
        assert call.args[0] == "GET"
        assert call.args[1] == "http://jellyfin:8096/Sessions"
