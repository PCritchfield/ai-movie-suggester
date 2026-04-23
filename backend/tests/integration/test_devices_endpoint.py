"""Integration tests for GET /api/devices against a real Jellyfin instance.

Two tests:

1. Authenticate as a test user, call the endpoint via FastAPI's in-process
   TestClient, and assert 200 with an empty JSON array. Disposable Jellyfin
   has no active controllable sessions by default.

2. Verify the Jellyfin ``/Sessions`` JSON shape we depend on —
   ``Id``, ``UserId``, ``DeviceId``, ``DeviceName``, ``Client``,
   ``SupportsRemoteControl`` — so we get a loud CI failure if Jellyfin
   ever renames these fields.
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.auth.crypto import derive_keys
from app.auth.dependencies import get_current_session
from app.auth.models import SessionMeta
from app.devices.router import create_devices_router
from app.jellyfin.sessions import JellyfinSessionsClient
from app.jellyfin.transport import _JellyfinTransport
from tests.integration.conftest import TEST_USER_ALICE, TEST_USER_ALICE_PASS

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from app.jellyfin.client import JellyfinClient
    from tests.integration.conftest import JellyfinInstance

_TEST_SECRET = "kG7xP2mN9qR4wL8jT3vF6yA5dH0sE1cB"  # fixed, matches unit test suite
_COOKIE_KEY, _ = derive_keys(_TEST_SECRET)


@pytest.mark.integration
async def test_devices_endpoint_returns_empty_list_against_real_jellyfin(
    jellyfin: JellyfinInstance,
    jf_client: JellyfinClient,
    test_users: dict[str, str],
) -> None:
    """GET /api/devices returns 200 [] when no controllable sessions exist."""
    auth = await jf_client.authenticate(TEST_USER_ALICE, TEST_USER_ALICE_PASS)
    # `test_users` is forced here so user provisioning has run before auth.
    assert auth.user_id == test_users[TEST_USER_ALICE]

    # Use the FastAPI app's lifespan to own the httpx.AsyncClient so it is
    # closed on the TestClient's portal event loop. Mixing a manually-managed
    # `async with httpx.AsyncClient()` outside TestClient's portal triggers
    # "Event loop is closed" on __aexit__ when the portal tears down first.
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with httpx.AsyncClient(timeout=15.0) as http:
            transport = _JellyfinTransport(base_url=jellyfin.url, client=http)
            app.state.jellyfin_sessions_client = JellyfinSessionsClient(
                transport=transport,
            )
            yield

    app = FastAPI(lifespan=lifespan)
    app.state.cookie_key = _COOKIE_KEY
    app.state.limiter = None
    app.add_exception_handler(
        RateLimitExceeded,
        _rate_limit_exceeded_handler,  # type: ignore[arg-type]
    )

    # Mock session_store.get_token to return the real Jellyfin token
    class _TokenStore:
        async def get_token(self, _session_id: str) -> str:
            return auth.access_token

    app.state.session_store = _TokenStore()

    meta = SessionMeta(
        session_id="integration-sess",
        user_id=auth.user_id,
        username=auth.user_name,
        server_name="TestJellyfin",
        expires_at=int(time.time()) + 3600,
    )

    async def _session() -> SessionMeta:
        return meta

    app.dependency_overrides[get_current_session] = _session
    app.include_router(create_devices_router(limiter=None))

    with TestClient(app) as client:
        resp = client.get("/api/devices")

    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    # Disposable Jellyfin has no cast targets. An empty list is the
    # correct answer; future tests can relax this if we stand up a
    # simulated controllable session.
    assert body == []


@pytest.mark.integration
async def test_devices_endpoint_field_mapping_matches_jellyfin_shape(
    jellyfin: JellyfinInstance,
    admin_auth_token: str,
) -> None:
    """Guard the Jellyfin /Sessions field-name contract.

    We hit ``/Sessions`` directly with the admin token so at least one
    session (the admin's) is present, then assert the response shape
    exposes the six fields we depend on. If Jellyfin ever renames any
    of them, this test turns red loudly instead of the production client
    returning an empty list by silent fall-through.
    """
    async with httpx.AsyncClient(timeout=15.0) as http:
        resp = await http.get(
            f"{jellyfin.url}/Sessions",
            headers={
                "Authorization": (
                    'MediaBrowser Client="ai-movie-suggester-tests", '
                    f'DeviceId="integration-test", Device="pytest", '
                    f'Version="0.0.0", Token={admin_auth_token}'
                )
            },
        )
    assert resp.status_code == 200
    sessions = resp.json()
    assert isinstance(sessions, list)
    assert len(sessions) >= 1, (
        "expected at least one Jellyfin session (admin) for shape check"
    )

    required_fields = {
        "Id",
        "UserId",
        "DeviceId",
        "DeviceName",
        "Client",
        "SupportsRemoteControl",
    }
    for session in sessions:
        missing = required_fields - session.keys()
        assert not missing, (
            f"Jellyfin /Sessions session missing field(s) {missing}: "
            f"{list(session.keys())!r}"
        )
