"""Unit tests for JellyfinSessionsClient and the `_classify_device` table.

Covers:

* ``_classify_device`` fixture-table classification
* Happy path: three sessions, two controllable -> two Device items
* ``SupportsRemoteControl`` filter keeps only controllable sessions
* 401 -> JellyfinAuthError
* Empty list round-trip
* ``user_token`` is request-scoped (never cached on the client)
* ``repr()`` / ``str()`` do not leak any token fragment
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest

from app.jellyfin.device_models import Device
from app.jellyfin.errors import JellyfinAuthError
from app.jellyfin.sessions import JellyfinSessionsClient, _classify_device
from app.jellyfin.transport import _JellyfinTransport

_FAKE_REQUEST = httpx.Request("GET", "http://fake")


@pytest.fixture
def mock_http() -> AsyncMock:
    return AsyncMock(spec=httpx.AsyncClient)


@pytest.fixture
def sessions_client(mock_http: AsyncMock) -> JellyfinSessionsClient:
    transport = _JellyfinTransport(
        base_url="http://jellyfin:8096",
        client=mock_http,
    )
    return JellyfinSessionsClient(transport=transport)


class TestClassifyDevice:
    @pytest.mark.parametrize(
        ("client", "expected"),
        [
            # TV clients — substring "TV" wins
            ("Jellyfin Android TV", "Tv"),
            ("Jellyfin Kodi TV", "Tv"),
            ("Samsung Smart TV", "Tv"),
            # Bare Kodi — NOT a TV, not remote-controllable via /Sessions/Playing
            # per Jellyfin's own behavior. Explicit fallback row makes
            # this deliberate, not accidental.
            ("Kodi", "Other"),
            # Mobile clients — iOS/Android without "TV" suffix
            ("Jellyfin iOS", "Mobile"),
            ("Jellyfin Android", "Mobile"),
            # Tablet clients
            ("Jellyfin iPad", "Tablet"),
            ("SomeTablet", "Tablet"),
            # Unknown fall-through
            ("Unknown Client", "Other"),
        ],
    )
    def test_classify_device_fixture_table(self, client: str, expected: str) -> None:
        assert _classify_device(client) == expected


class TestSessionsClientHappyPath:
    async def test_happy_path_returns_only_controllable(
        self,
        sessions_client: JellyfinSessionsClient,
        mock_http: AsyncMock,
    ) -> None:
        mock_http.request.return_value = httpx.Response(
            200,
            json=[
                {
                    "Id": "sess-1",
                    "UserId": "u-1",
                    "DeviceId": "dev-1",
                    "DeviceName": "Living Room TV",
                    "Client": "Jellyfin Android TV",
                    "SupportsRemoteControl": True,
                },
                {
                    "Id": "sess-2",
                    "UserId": "u-1",
                    "DeviceId": "dev-2",
                    "DeviceName": "Phone",
                    "Client": "Jellyfin iOS",
                    "SupportsRemoteControl": True,
                },
                {
                    "Id": "sess-3",
                    "UserId": "u-1",
                    "DeviceId": "dev-3",
                    "DeviceName": "Laptop Web",
                    "Client": "Jellyfin Web",
                    "SupportsRemoteControl": False,
                },
            ],
            request=_FAKE_REQUEST,
        )

        devices = await sessions_client.list_controllable("tok-abc")

        assert len(devices) == 2
        assert all(isinstance(d, Device) for d in devices)
        tv = next(d for d in devices if d.session_id == "sess-1")
        assert tv.name == "Living Room TV"
        assert tv.client == "Jellyfin Android TV"
        assert tv.device_type == "Tv"
        phone = next(d for d in devices if d.session_id == "sess-2")
        assert phone.device_type == "Mobile"

    async def test_filter_drops_all_non_controllable(
        self,
        sessions_client: JellyfinSessionsClient,
        mock_http: AsyncMock,
    ) -> None:
        mock_http.request.return_value = httpx.Response(
            200,
            json=[
                {
                    "Id": "s1",
                    "UserId": "u",
                    "DeviceId": "d1",
                    "DeviceName": "web-1",
                    "Client": "Jellyfin Web",
                    "SupportsRemoteControl": False,
                },
                {
                    "Id": "s2",
                    "UserId": "u",
                    "DeviceId": "d2",
                    "DeviceName": "web-2",
                    "Client": "Jellyfin Web",
                    "SupportsRemoteControl": False,
                },
            ],
            request=_FAKE_REQUEST,
        )
        assert await sessions_client.list_controllable("tok") == []

    async def test_empty_list_from_jellyfin(
        self,
        sessions_client: JellyfinSessionsClient,
        mock_http: AsyncMock,
    ) -> None:
        mock_http.request.return_value = httpx.Response(
            200, json=[], request=_FAKE_REQUEST
        )
        assert await sessions_client.list_controllable("tok") == []

    async def test_non_list_body_returns_empty(
        self,
        sessions_client: JellyfinSessionsClient,
        mock_http: AsyncMock,
    ) -> None:
        """If Jellyfin somehow returns a non-list, return [] (no crash)."""
        mock_http.request.return_value = httpx.Response(
            200, json={"unexpected": "dict"}, request=_FAKE_REQUEST
        )
        assert await sessions_client.list_controllable("tok") == []

    async def test_missing_supports_remote_control_treated_as_false(
        self,
        sessions_client: JellyfinSessionsClient,
        mock_http: AsyncMock,
    ) -> None:
        """If Jellyfin omits SupportsRemoteControl, treat as False."""
        mock_http.request.return_value = httpx.Response(
            200,
            json=[
                {
                    "Id": "s1",
                    "UserId": "u",
                    "DeviceId": "d1",
                    "DeviceName": "TV",
                    "Client": "Jellyfin Android TV",
                    # no SupportsRemoteControl key
                },
            ],
            request=_FAKE_REQUEST,
        )
        assert await sessions_client.list_controllable("tok") == []


class TestSessionsClientAuthFailure:
    async def test_401_raises_jellyfin_auth_error(
        self,
        sessions_client: JellyfinSessionsClient,
        mock_http: AsyncMock,
    ) -> None:
        mock_http.request.return_value = httpx.Response(401, request=_FAKE_REQUEST)
        with pytest.raises(JellyfinAuthError):
            await sessions_client.list_controllable("bad-tok")


class TestSessionsClientTokenHandling:
    async def test_token_passed_in_auth_header(
        self,
        sessions_client: JellyfinSessionsClient,
        mock_http: AsyncMock,
    ) -> None:
        mock_http.request.return_value = httpx.Response(
            200, json=[], request=_FAKE_REQUEST
        )
        await sessions_client.list_controllable("tok-xyz-42")
        call = mock_http.request.call_args
        assert "Token=tok-xyz-42" in call.kwargs["headers"]["Authorization"]

    async def test_user_token_not_cached_on_instance(
        self,
        sessions_client: JellyfinSessionsClient,
        mock_http: AsyncMock,
    ) -> None:
        """After a call, no attribute on the client contains the token."""
        mock_http.request.return_value = httpx.Response(
            200, json=[], request=_FAKE_REQUEST
        )
        token = "super-secret-tok-do-not-persist"
        await sessions_client.list_controllable(token)

        # Probe every attribute reachable on the client instance
        for attr_name in dir(sessions_client):
            if attr_name.startswith("__"):
                continue
            value = getattr(sessions_client, attr_name, None)
            try:
                text = repr(value)
            except Exception:
                continue
            assert token not in text, (
                f"token leaked via attribute {attr_name!r}: {text!r}"
            )

    def test_repr_contains_no_token_fragment(
        self,
        sessions_client: JellyfinSessionsClient,
    ) -> None:
        """repr(client) / str(client) expose no auth/token state."""
        text = repr(sessions_client) + str(sessions_client)
        assert "Token=" not in text
        # Stronger: no attribute surface should ever contain a token value,
        # because the client holds no token. These asserts guard future regressions.
        assert "MediaBrowser" not in text
