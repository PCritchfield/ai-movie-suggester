"""Integration tests for JellyfinClient against a real Jellyfin instance.

Requires: make jellyfin-up (disposable Jellyfin on localhost:8096).
Uses the existing fixture chain: jellyfin -> admin_auth_token -> test_users.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import pytest
import pytest_asyncio

from app.jellyfin.client import JellyfinClient
from app.jellyfin.errors import JellyfinAuthError
from app.jellyfin.models import AuthResult, PaginatedItems, UserInfo

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from tests.integration.conftest import JellyfinInstance

# Re-use credentials from conftest
from tests.integration.conftest import TEST_USER_ALICE, TEST_USER_ALICE_PASS


@pytest_asyncio.fixture
async def jf_client(
    jellyfin: JellyfinInstance,
) -> AsyncGenerator[JellyfinClient, None]:
    """JellyfinClient pointed at the test instance."""
    # TODO(#29): Read timeout from Settings.jellyfin_timeout when wired
    async with httpx.AsyncClient(timeout=10.0) as http:
        yield JellyfinClient(base_url=jellyfin.url, http_client=http)


@pytest.mark.integration
async def test_authenticate_valid_credentials(
    jf_client: JellyfinClient,
    test_users: dict[str, str],
) -> None:
    """Authenticate as test-alice with correct password."""
    result = await jf_client.authenticate(TEST_USER_ALICE, TEST_USER_ALICE_PASS)
    assert isinstance(result, AuthResult)
    assert result.user_name == TEST_USER_ALICE
    assert result.user_id == test_users[TEST_USER_ALICE]
    assert len(result.access_token) > 0


@pytest.mark.integration
async def test_authenticate_invalid_credentials(
    jf_client: JellyfinClient,
    test_users: dict[str, str],
) -> None:
    """Invalid password should raise JellyfinAuthError."""
    with pytest.raises(JellyfinAuthError):
        await jf_client.authenticate(TEST_USER_ALICE, "wrong-password")


@pytest.mark.integration
async def test_get_user_with_valid_token(
    jf_client: JellyfinClient,
    test_users: dict[str, str],
) -> None:
    """get_user() returns correct info for an authenticated user."""
    auth = await jf_client.authenticate(TEST_USER_ALICE, TEST_USER_ALICE_PASS)
    user = await jf_client.get_user(auth.access_token)
    assert isinstance(user, UserInfo)
    assert user.name == TEST_USER_ALICE
    assert user.id == test_users[TEST_USER_ALICE]


@pytest.mark.integration
async def test_get_user_with_invalid_token(
    jf_client: JellyfinClient,
    test_users: dict[str, str],
) -> None:
    """Invalid token should raise JellyfinAuthError."""
    with pytest.raises(JellyfinAuthError):
        await jf_client.get_user("not-a-real-token")


@pytest.mark.integration
async def test_get_items_returns_paginated_result(
    jf_client: JellyfinClient,
    test_users: dict[str, str],
) -> None:
    """get_items() returns a PaginatedItems even if library is empty."""
    auth = await jf_client.authenticate(TEST_USER_ALICE, TEST_USER_ALICE_PASS)
    result = await jf_client.get_items(
        auth.access_token,
        auth.user_id,
        item_types=["Movie"],
    )
    assert isinstance(result, PaginatedItems)
    assert result.start_index == 0
    # Library may be empty in test Jellyfin -- that's fine
    assert result.total_count >= 0


@pytest.mark.integration
async def test_get_items_pagination_params(
    jf_client: JellyfinClient,
    test_users: dict[str, str],
) -> None:
    """Pagination parameters are respected (no crash, correct start_index)."""
    auth = await jf_client.authenticate(TEST_USER_ALICE, TEST_USER_ALICE_PASS)
    result = await jf_client.get_items(
        auth.access_token,
        auth.user_id,
        start_index=0,
        limit=5,
    )
    assert isinstance(result, PaginatedItems)
    assert result.start_index == 0
