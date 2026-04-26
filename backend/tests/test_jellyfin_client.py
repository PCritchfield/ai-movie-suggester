# backend/tests/test_jellyfin_client.py
"""Unit tests for the Jellyfin API client (mock httpx)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest
from pydantic import ValidationError

from app.jellyfin.client import _ITEM_FIELDS, JellyfinClient
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

    def test_parse_all_extended_fields(self) -> None:
        """LibraryItem parses all new fields from representative Jellyfin JSON."""
        data = {
            "Id": "item-3",
            "Name": "Toy Story",
            "Type": "Movie",
            "Overview": "A story about toys.",
            "Genres": ["Animation", "Comedy"],
            "ProductionYear": 1995,
            "Tags": ["family", "classic"],
            "Studios": [{"Name": "Pixar", "Id": "studio-1"}],
            "CommunityRating": 8.3,
            "People": [
                {"Name": "Tom Hanks", "Role": "Woody", "Type": "Actor"},
                {"Name": "John Lasseter", "Role": "", "Type": "Director"},
            ],
        }
        item = LibraryItem.model_validate(data)
        assert item.tags == ["family", "classic"]
        assert item.studios == ["Pixar"]
        assert item.community_rating == 8.3
        assert len(item.people) == 2
        assert item.people[0]["Name"] == "Tom Hanks"
        assert item.people[0]["Type"] == "Actor"
        assert item.people[1]["Type"] == "Director"

    def test_extended_fields_default_when_absent(self) -> None:
        """New fields default correctly when absent from JSON."""
        data = {"Id": "item-4", "Name": "Minimal Movie", "Type": "Movie"}
        item = LibraryItem.model_validate(data)
        assert item.tags == []
        assert item.studios == []
        assert item.community_rating is None
        assert item.people == []

    def test_studios_validator_extracts_names_from_objects(self) -> None:
        """Studios validator extracts Name from studio objects."""
        data = {
            "Id": "item-5",
            "Name": "Finding Nemo",
            "Type": "Movie",
            "Studios": [
                {"Name": "Pixar", "Id": "abc"},
                {"Name": "Disney", "Id": "def"},
            ],
        }
        item = LibraryItem.model_validate(data)
        assert item.studios == ["Pixar", "Disney"]

    def test_studios_validator_handles_plain_string_list(self) -> None:
        """Studios validator passes through plain string list."""
        data = {
            "Id": "item-6",
            "Name": "Some Movie",
            "Type": "Movie",
            "Studios": ["Pixar", "Disney"],
        }
        item = LibraryItem.model_validate(data)
        assert item.studios == ["Pixar", "Disney"]

    def test_people_field_parses_raw_jellyfin_array(self) -> None:
        """People field parses raw Jellyfin People array with Name, Role, Type."""
        data = {
            "Id": "item-7",
            "Name": "Cast Movie",
            "Type": "Movie",
            "People": [
                {"Name": "Actor One", "Role": "Lead", "Type": "Actor"},
                {"Name": "Director One", "Role": "", "Type": "Director"},
                {"Name": "Writer One", "Role": "", "Type": "Writer"},
            ],
        }
        item = LibraryItem.model_validate(data)
        assert len(item.people) == 3
        assert item.people[0] == {
            "Name": "Actor One",
            "Role": "Lead",
            "Type": "Actor",
        }
        assert item.people[2]["Type"] == "Writer"


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


class TestLogout:
    async def test_logout_success(
        self, jf_client: JellyfinClient, mock_http: AsyncMock
    ) -> None:
        """Logout returns normally on 204."""
        mock_http.request.return_value = httpx.Response(204, request=_FAKE_REQUEST)
        await jf_client.logout("tok-123")  # Should not raise
        call_args = mock_http.request.call_args
        assert call_args.args[0] == "POST"
        assert "/Sessions/Logout" in call_args.args[1]
        assert "Token=tok-123" in call_args.kwargs["headers"]["Authorization"]

    async def test_logout_401_does_not_raise(
        self, jf_client: JellyfinClient, mock_http: AsyncMock
    ) -> None:
        """Logout on already-revoked token (401) returns normally."""
        mock_http.request.return_value = httpx.Response(401, request=_FAKE_REQUEST)
        await jf_client.logout("expired-tok")  # Should not raise

    async def test_logout_transport_error_raises(
        self, jf_client: JellyfinClient, mock_http: AsyncMock
    ) -> None:
        """Transport error during logout raises JellyfinConnectionError."""
        mock_http.request.side_effect = httpx.ConnectError("Connection refused")
        with pytest.raises(JellyfinConnectionError):
            await jf_client.logout("tok-123")


class TestGetServerName:
    async def test_returns_server_name(
        self, jf_client: JellyfinClient, mock_http: AsyncMock
    ) -> None:
        """get_server_name returns ServerName from /System/Info/Public."""
        mock_http.request.return_value = httpx.Response(
            200,
            json={
                "ServerName": "MyJellyfin",
                "Version": "10.9.0",
                "Id": "srv-1",
            },
            request=_FAKE_REQUEST,
        )
        name = await jf_client.get_server_name()
        assert name == "MyJellyfin"
        # Verify no auth token is passed
        call_args = mock_http.request.call_args
        assert "Token=" not in call_args.kwargs["headers"]["Authorization"]

    async def test_caches_result(
        self, jf_client: JellyfinClient, mock_http: AsyncMock
    ) -> None:
        """Second call uses cached value, no HTTP request."""
        mock_http.request.return_value = httpx.Response(
            200,
            json={"ServerName": "MyJellyfin", "Version": "10.9.0", "Id": "srv-1"},
            request=_FAKE_REQUEST,
        )
        first = await jf_client.get_server_name()
        second = await jf_client.get_server_name()
        assert first == second == "MyJellyfin"
        assert mock_http.request.call_count == 1

    async def test_transport_error_raises(
        self, jf_client: JellyfinClient, mock_http: AsyncMock
    ) -> None:
        """Transport error raises JellyfinConnectionError."""
        mock_http.request.side_effect = httpx.ConnectError("Connection refused")
        with pytest.raises(JellyfinConnectionError):
            await jf_client.get_server_name()


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

    async def test_get_items_explicit_empty_fields_skips_extended_metadata(
        self, jf_client: JellyfinClient, mock_http: AsyncMock
    ) -> None:
        """Callers that only need IDs can pass fields="" to skip rich metadata."""
        mock_http.request.return_value = httpx.Response(
            200,
            json={"Items": [], "TotalRecordCount": 0, "StartIndex": 0},
            request=_FAKE_REQUEST,
        )
        await jf_client.get_items("tok-123", "uid-1", fields="")
        params = mock_http.request.call_args.kwargs["params"]
        assert params["Fields"] == ""

    async def test_get_items_custom_fields_value_forwarded(
        self, jf_client: JellyfinClient, mock_http: AsyncMock
    ) -> None:
        """An arbitrary fields override is passed through verbatim."""
        mock_http.request.return_value = httpx.Response(
            200,
            json={"Items": [], "TotalRecordCount": 0, "StartIndex": 0},
            request=_FAKE_REQUEST,
        )
        await jf_client.get_items("tok-123", "uid-1", fields="Genres,Tags")
        params = mock_http.request.call_args.kwargs["params"]
        assert params["Fields"] == "Genres,Tags"

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


class TestGetAllItems:
    """Tests for get_all_items() auto-paginating async iterator."""

    async def test_two_pages_yields_both(self, jf_client: JellyfinClient) -> None:
        """Mock get_items() returning two pages, verify iterator yields both."""
        page1_items = [
            LibraryItem(Id=f"item-{i}", Name=f"Movie {i}", Type="Movie")
            for i in range(200)
        ]
        page2_items = [
            LibraryItem(Id=f"item-{i}", Name=f"Movie {i}", Type="Movie")
            for i in range(200, 250)
        ]
        page1 = PaginatedItems(Items=page1_items, TotalRecordCount=250, StartIndex=0)
        page2 = PaginatedItems(Items=page2_items, TotalRecordCount=250, StartIndex=200)

        call_count = 0

        async def mock_get_items(
            token: str,
            user_id: str,
            *,
            item_types: list[str] | None = None,
            start_index: int = 0,
            limit: int = 50,
            recursive: bool = True,
            fields: str | None = None,
        ) -> PaginatedItems:
            nonlocal call_count
            call_count += 1
            if start_index == 0:
                return page1
            return page2

        with patch.object(jf_client, "get_items", side_effect=mock_get_items):
            pages: list[PaginatedItems] = []
            async for page in jf_client.get_all_items(
                "tok-123", "uid-1", page_size=200
            ):
                pages.append(page)

        assert len(pages) == 2
        assert len(pages[0].items) == 200
        assert len(pages[1].items) == 50
        assert call_count == 2

    async def test_empty_library(self, jf_client: JellyfinClient) -> None:
        """Empty library yields one page with zero items and stops."""
        empty_page = PaginatedItems(Items=[], TotalRecordCount=0, StartIndex=0)

        with patch.object(jf_client, "get_items", return_value=empty_page):
            pages: list[PaginatedItems] = []
            async for page in jf_client.get_all_items("tok-123", "uid-1"):
                pages.append(page)

        assert len(pages) == 1
        assert pages[0].items == []
        assert pages[0].total_count == 0

    async def test_auth_error_propagates(self, jf_client: JellyfinClient) -> None:
        """JellyfinAuthError on first page propagates immediately."""
        with (
            patch.object(
                jf_client, "get_items", side_effect=JellyfinAuthError("expired")
            ),
            pytest.raises(JellyfinAuthError),
        ):
            async for _page in jf_client.get_all_items("bad-tok", "uid-1"):
                pass  # pragma: no cover

    async def test_mid_pagination_error(self, jf_client: JellyfinClient) -> None:
        """JellyfinConnectionError on second page propagates after first yielded."""
        page1_items = [
            LibraryItem(Id=f"item-{i}", Name=f"Movie {i}", Type="Movie")
            for i in range(200)
        ]
        page1 = PaginatedItems(Items=page1_items, TotalRecordCount=400, StartIndex=0)

        call_count = 0

        async def mock_get_items(
            token: str,
            user_id: str,
            *,
            item_types: list[str] | None = None,
            start_index: int = 0,
            limit: int = 50,
            recursive: bool = True,
            fields: str | None = None,
        ) -> PaginatedItems:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return page1
            raise JellyfinConnectionError("Connection lost")

        pages_received: list[PaginatedItems] = []
        with (
            patch.object(jf_client, "get_items", side_effect=mock_get_items),
            pytest.raises(JellyfinConnectionError),
        ):
            async for page in jf_client.get_all_items(
                "tok-123", "uid-1", page_size=200
            ):
                pages_received.append(page)

        assert len(pages_received) == 1

    def test_item_fields_includes_extended_fields(self) -> None:
        """_ITEM_FIELDS constant includes Tags, Studios, CommunityRating, People."""
        assert "Tags" in _ITEM_FIELDS
        assert "Studios" in _ITEM_FIELDS
        assert "CommunityRating" in _ITEM_FIELDS
        assert "People" in _ITEM_FIELDS

    async def test_get_all_items_forwards_fields_to_get_items(
        self, jf_client: JellyfinClient
    ) -> None:
        """fields kwarg on get_all_items must propagate to *every* get_items call."""
        # Two non-empty pages so the loop iterates more than once — proves the
        # forwarding contract holds for subsequent pages, not just the first.
        page1 = PaginatedItems(
            Items=[LibraryItem(Id="a", Name="A", Type="Movie")],
            TotalRecordCount=2,
            StartIndex=0,
        )
        page2 = PaginatedItems(
            Items=[LibraryItem(Id="b", Name="B", Type="Movie")],
            TotalRecordCount=2,
            StartIndex=1,
        )
        captured_fields: list[str | None] = []

        async def mock_get_items(
            token: str,
            user_id: str,
            *,
            item_types: list[str] | None = None,
            start_index: int = 0,
            limit: int = 50,
            recursive: bool = True,
            fields: str | None = None,
        ) -> PaginatedItems:
            captured_fields.append(fields)
            return page1 if start_index == 0 else page2

        with patch.object(jf_client, "get_items", side_effect=mock_get_items):
            async for _ in jf_client.get_all_items(
                "tok-123", "uid-1", page_size=1, fields=""
            ):
                pass

        assert captured_fields == ["", ""]
