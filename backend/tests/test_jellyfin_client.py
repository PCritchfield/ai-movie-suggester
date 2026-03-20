# backend/tests/test_jellyfin_client.py
"""Unit tests for the Jellyfin API client (mock httpx)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from app.jellyfin.client import JellyfinClient
from app.jellyfin.errors import (
    JellyfinAuthError,
    JellyfinConnectionError,
    JellyfinError,
)
from app.jellyfin.models import AuthResult, LibraryItem, PaginatedItems, UserInfo


@pytest.fixture
def mock_http() -> AsyncMock:
    """Mock httpx.AsyncClient for unit tests."""
    return AsyncMock(spec=httpx.AsyncClient)


@pytest.fixture
def jf_client(mock_http: AsyncMock) -> JellyfinClient:
    return JellyfinClient(
        base_url="http://jellyfin:8096",
        http_client=mock_http,
    )


class TestErrorHierarchy:
    def test_auth_error_is_jellyfin_error(self) -> None:
        assert issubclass(JellyfinAuthError, JellyfinError)

    def test_connection_error_is_jellyfin_error(self) -> None:
        assert issubclass(JellyfinConnectionError, JellyfinError)

    def test_jellyfin_error_is_exception(self) -> None:
        assert issubclass(JellyfinError, Exception)

    def test_auth_error_message(self) -> None:
        err = JellyfinAuthError("Invalid credentials")
        assert str(err) == "Invalid credentials"

    def test_connection_error_message(self) -> None:
        err = JellyfinConnectionError("Connection refused")
        assert str(err) == "Connection refused"


class TestAuthResult:
    def test_parse_jellyfin_response(self) -> None:
        """AuthResult parses from Jellyfin's AuthenticateByName response."""
        data = {
            "AccessToken": "abc123",
            "User": {"Id": "user-1", "Name": "alice"},
        }
        result = AuthResult.from_jellyfin(data)
        assert result.access_token == "abc123"
        assert result.user_id == "user-1"
        assert result.user_name == "alice"


class TestUserInfo:
    def test_parse_from_jellyfin(self) -> None:
        data = {
            "Id": "user-1",
            "Name": "alice",
            "ServerId": "server-1",
            "HasPassword": True,
        }
        user = UserInfo.model_validate(data)
        assert user.id == "user-1"
        assert user.name == "alice"
        assert user.server_id == "server-1"
        assert user.has_password is True

    def test_missing_required_field_raises(self) -> None:
        with pytest.raises(ValidationError):
            UserInfo.model_validate({"Name": "alice"})


class TestLibraryItem:
    def test_parse_minimal_item(self) -> None:
        data = {"Id": "item-1", "Name": "Alien", "Type": "Movie"}
        item = LibraryItem.model_validate(data)
        assert item.id == "item-1"
        assert item.name == "Alien"
        assert item.type == "Movie"
        assert item.overview is None
        assert item.genres == []
        assert item.production_year is None

    def test_parse_full_item(self) -> None:
        data = {
            "Id": "item-2",
            "Name": "Galaxy Quest",
            "Type": "Movie",
            "Overview": "A great comedy.",
            "Genres": ["Comedy", "Sci-Fi"],
            "ProductionYear": 1999,
        }
        item = LibraryItem.model_validate(data)
        assert item.overview == "A great comedy."
        assert item.genres == ["Comedy", "Sci-Fi"]
        assert item.production_year == 1999


class TestPaginatedItems:
    def test_parse_from_jellyfin(self) -> None:
        data = {
            "Items": [
                {"Id": "1", "Name": "Alien", "Type": "Movie"},
                {"Id": "2", "Name": "Aliens", "Type": "Movie"},
            ],
            "TotalRecordCount": 50,
            "StartIndex": 0,
        }
        page = PaginatedItems.model_validate(data)
        assert len(page.items) == 2
        assert page.total_count == 50
        assert page.start_index == 0
        assert page.items[0].name == "Alien"

    def test_empty_library(self) -> None:
        data = {"Items": [], "TotalRecordCount": 0, "StartIndex": 0}
        page = PaginatedItems.model_validate(data)
        assert page.items == []
        assert page.total_count == 0


class TestHeaderConstruction:
    def test_headers_without_token(self, jf_client: JellyfinClient) -> None:
        headers = jf_client._headers()
        auth = headers["Authorization"]
        assert auth.startswith("MediaBrowser ")
        assert 'Client="ai-movie-suggester"' in auth
        assert 'Device="Server"' in auth
        assert "DeviceId=" in auth
        assert 'Version="0.1.0"' in auth
        assert "Token=" not in auth

    def test_headers_with_token(self, jf_client: JellyfinClient) -> None:
        headers = jf_client._headers(token="my-token")
        auth = headers["Authorization"]
        assert auth.endswith(", Token=my-token")
        assert 'Client="ai-movie-suggester"' in auth

    def test_custom_device_id(self, mock_http: AsyncMock) -> None:
        client = JellyfinClient(
            base_url="http://jellyfin:8096",
            http_client=mock_http,
            device_id="custom-id",
        )
        headers = client._headers()
        assert 'DeviceId="custom-id"' in headers["Authorization"]

    def test_base_url_trailing_slash_stripped(self, mock_http: AsyncMock) -> None:
        client = JellyfinClient(
            base_url="http://jellyfin:8096/",
            http_client=mock_http,
        )
        assert client._base_url == "http://jellyfin:8096"

    def test_token_whitespace_stripped(self, jf_client: JellyfinClient) -> None:
        headers = jf_client._headers(token="  tok-123  ")
        auth = headers["Authorization"]
        assert auth.endswith(", Token=tok-123")


_FAKE_REQUEST = httpx.Request("GET", "http://fake")


class TestAuthenticate:
    async def test_authenticate_success(
        self, jf_client: JellyfinClient, mock_http: AsyncMock
    ) -> None:
        mock_http.request.return_value = httpx.Response(
            200,
            json={
                "AccessToken": "tok-123",
                "User": {"Id": "uid-1", "Name": "alice"},
            },
            request=_FAKE_REQUEST,
        )
        result = await jf_client.authenticate("alice", "password123")
        assert isinstance(result, AuthResult)
        assert result.access_token == "tok-123"
        assert result.user_id == "uid-1"
        assert result.user_name == "alice"
        # Verify correct method, URL, and payload
        mock_http.request.assert_called_once()
        call_args = mock_http.request.call_args
        assert call_args.args[0] == "POST"
        assert "/Users/AuthenticateByName" in call_args.args[1]
        assert call_args.kwargs["json"] == {"Username": "alice", "Pw": "password123"}

    async def test_authenticate_invalid_credentials(
        self, jf_client: JellyfinClient, mock_http: AsyncMock
    ) -> None:
        mock_http.request.return_value = httpx.Response(401, request=_FAKE_REQUEST)
        with pytest.raises(JellyfinAuthError):
            await jf_client.authenticate("alice", "wrong")

    async def test_authenticate_server_unreachable(
        self, jf_client: JellyfinClient, mock_http: AsyncMock
    ) -> None:
        mock_http.request.side_effect = httpx.ConnectError("Connection refused")
        with pytest.raises(JellyfinConnectionError):
            await jf_client.authenticate("alice", "password")

    async def test_authenticate_unexpected_status(
        self, jf_client: JellyfinClient, mock_http: AsyncMock
    ) -> None:
        mock_http.request.return_value = httpx.Response(500, request=_FAKE_REQUEST)
        with pytest.raises(JellyfinError):
            await jf_client.authenticate("alice", "password")


class TestGetUser:
    async def test_get_user_success(
        self, jf_client: JellyfinClient, mock_http: AsyncMock
    ) -> None:
        mock_http.request.return_value = httpx.Response(
            200,
            json={
                "Id": "uid-1",
                "Name": "alice",
                "ServerId": "srv-1",
                "HasPassword": True,
            },
            request=_FAKE_REQUEST,
        )
        user = await jf_client.get_user("tok-123")
        assert isinstance(user, UserInfo)
        assert user.id == "uid-1"
        assert user.name == "alice"
        assert user.server_id == "srv-1"
        # Verify token is passed in headers
        call_args = mock_http.request.call_args
        assert "Token=tok-123" in call_args.kwargs["headers"]["Authorization"]

    async def test_get_user_invalid_token(
        self, jf_client: JellyfinClient, mock_http: AsyncMock
    ) -> None:
        mock_http.request.return_value = httpx.Response(401, request=_FAKE_REQUEST)
        with pytest.raises(JellyfinAuthError):
            await jf_client.get_user("expired-token")

    async def test_get_user_server_unreachable(
        self, jf_client: JellyfinClient, mock_http: AsyncMock
    ) -> None:
        mock_http.request.side_effect = httpx.ConnectError("Connection refused")
        with pytest.raises(JellyfinConnectionError):
            await jf_client.get_user("tok-123")

    async def test_get_user_unexpected_status(
        self, jf_client: JellyfinClient, mock_http: AsyncMock
    ) -> None:
        mock_http.request.return_value = httpx.Response(500, request=_FAKE_REQUEST)
        with pytest.raises(JellyfinError):
            await jf_client.get_user("tok-123")


class TestGetItems:
    async def test_get_items_success(
        self, jf_client: JellyfinClient, mock_http: AsyncMock
    ) -> None:
        mock_http.request.return_value = httpx.Response(
            200,
            json={
                "Items": [
                    {"Id": "1", "Name": "Alien", "Type": "Movie"},
                    {"Id": "2", "Name": "Aliens", "Type": "Movie"},
                ],
                "TotalRecordCount": 50,
                "StartIndex": 0,
            },
            request=_FAKE_REQUEST,
        )
        result = await jf_client.get_items("tok-123", "uid-1")
        assert isinstance(result, PaginatedItems)
        assert len(result.items) == 2
        assert result.total_count == 50
        assert result.items[0].name == "Alien"

    async def test_get_items_passes_pagination_params(
        self, jf_client: JellyfinClient, mock_http: AsyncMock
    ) -> None:
        mock_http.request.return_value = httpx.Response(
            200,
            json={"Items": [], "TotalRecordCount": 0, "StartIndex": 10},
            request=_FAKE_REQUEST,
        )
        await jf_client.get_items(
            "tok-123",
            "uid-1",
            start_index=10,
            limit=25,
        )
        call_args = mock_http.request.call_args
        params = call_args.kwargs["params"]
        assert params["StartIndex"] == 10
        assert params["Limit"] == 25

    async def test_get_items_with_item_types_filter(
        self, jf_client: JellyfinClient, mock_http: AsyncMock
    ) -> None:
        mock_http.request.return_value = httpx.Response(
            200,
            json={"Items": [], "TotalRecordCount": 0, "StartIndex": 0},
            request=_FAKE_REQUEST,
        )
        await jf_client.get_items(
            "tok-123",
            "uid-1",
            item_types=["Movie", "Series"],
        )
        call_args = mock_http.request.call_args
        params = call_args.kwargs["params"]
        assert params["IncludeItemTypes"] == "Movie,Series"

    async def test_get_items_requests_metadata_fields(
        self, jf_client: JellyfinClient, mock_http: AsyncMock
    ) -> None:
        """Verify we request the fields our models expect."""
        mock_http.request.return_value = httpx.Response(
            200,
            json={"Items": [], "TotalRecordCount": 0, "StartIndex": 0},
            request=_FAKE_REQUEST,
        )
        await jf_client.get_items("tok-123", "uid-1")
        call_args = mock_http.request.call_args
        params = call_args.kwargs["params"]
        assert "Fields" in params
        assert "Overview" in params["Fields"]
        assert "Genres" in params["Fields"]

    async def test_get_items_uses_per_user_endpoint(
        self, jf_client: JellyfinClient, mock_http: AsyncMock
    ) -> None:
        """Items endpoint must be /Users/{id}/Items for permission filtering."""
        mock_http.request.return_value = httpx.Response(
            200,
            json={"Items": [], "TotalRecordCount": 0, "StartIndex": 0},
            request=_FAKE_REQUEST,
        )
        await jf_client.get_items("tok-123", "uid-1")
        url = mock_http.request.call_args.args[1]
        assert "/Users/uid-1/Items" in url

    async def test_get_items_invalid_token(
        self, jf_client: JellyfinClient, mock_http: AsyncMock
    ) -> None:
        mock_http.request.return_value = httpx.Response(401, request=_FAKE_REQUEST)
        with pytest.raises(JellyfinAuthError):
            await jf_client.get_items("bad-tok", "uid-1")

    async def test_get_items_server_unreachable(
        self, jf_client: JellyfinClient, mock_http: AsyncMock
    ) -> None:
        mock_http.request.side_effect = httpx.ConnectError("Connection refused")
        with pytest.raises(JellyfinConnectionError):
            await jf_client.get_items("tok-123", "uid-1")

    async def test_get_items_unexpected_status(
        self, jf_client: JellyfinClient, mock_http: AsyncMock
    ) -> None:
        mock_http.request.return_value = httpx.Response(500, request=_FAKE_REQUEST)
        with pytest.raises(JellyfinError):
            await jf_client.get_items("tok-123", "uid-1")
