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
