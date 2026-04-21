"""Integration test fixtures — Jellyfin provisioning and readiness.

Wizard completion and auth follow the pattern from Jellyfin's own
integration tests (tests/Jellyfin.Server.Integration.Tests/AuthHelper.cs).
"""

from __future__ import annotations

import asyncio
import logging
import os
import warnings
from typing import TYPE_CHECKING, NamedTuple

import httpx
import pytest
import pytest_asyncio

from app.jellyfin.client import JellyfinClient
from app.library.store import LibraryStore

if TYPE_CHECKING:
    import pathlib
    from collections.abc import AsyncGenerator

    from app.jellyfin.models import AuthResult

_logger = logging.getLogger(__name__)


class JellyfinInstance(NamedTuple):
    """Jellyfin connection info discovered during wizard setup."""

    url: str
    admin_user: str


# ---------------------------------------------------------------------------
# Constants — test-only, never imported outside backend/tests/integration/
# ---------------------------------------------------------------------------
JELLYFIN_TEST_URL = os.environ.get(
    "JELLYFIN_TEST_URL", "http://host.docker.internal:8096"
)
# Must match the image version in docker-compose.test.yml
EXPECTED_JELLYFIN_VERSION = "10.11.8"
TEST_ADMIN_PASS = "test-admin-password"

TEST_USER_ALICE = "test-alice"
TEST_USER_ALICE_PASS = "test-alice-password"

TEST_USER_BOB = "test-bob"
TEST_USER_BOB_PASS = "test-bob-password"

# Auth header format matching Jellyfin's own integration tests.
# Uses "Authorization" (not "X-Emby-Authorization") and no quotes on Token.
_AUTH_HEADER = (
    'MediaBrowser Client="ai-movie-suggester-tests", '
    'DeviceId="integration-test", Device="pytest", Version="0.0.0"'
)

POLL_INTERVAL_SECONDS = 2
POLL_TIMEOUT_SECONDS = 60


def _auth_headers(token: str | None = None) -> dict[str, str]:
    """Build Jellyfin Authorization header, optionally with token."""
    value = _AUTH_HEADER if token is None else f"{_AUTH_HEADER}, Token={token}"
    return {"Authorization": value}


# ---------------------------------------------------------------------------
# Session-scoped fixture — polls, version-checks, completes wizard
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture(scope="session")
async def jellyfin() -> JellyfinInstance:
    """Wait for Jellyfin readiness, verify version, complete wizard if needed.

    Returns a JellyfinInstance with the URL and discovered admin username.
    """
    base = JELLYFIN_TEST_URL
    admin_user = "root"

    async with httpx.AsyncClient() as client:
        # Phase 1: Poll for readiness
        elapsed = 0.0
        while elapsed < POLL_TIMEOUT_SECONDS:
            try:
                resp = await client.get(f"{base}/health")
                if resp.status_code == 200:
                    break
            except httpx.TransportError:
                pass
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
            elapsed += POLL_INTERVAL_SECONDS
        else:
            msg = (
                f"Jellyfin not reachable at {base}/health after {POLL_TIMEOUT_SECONDS}s"
            )
            raise TimeoutError(msg)

        # Phase 2: Version check
        resp = await client.get(f"{base}/System/Info/Public")
        resp.raise_for_status()
        info = resp.json()
        actual = info.get("Version", "unknown")
        if actual != EXPECTED_JELLYFIN_VERSION:
            msg = (
                f"Unexpected Jellyfin version {actual}, "
                f"expected {EXPECTED_JELLYFIN_VERSION}. "
                f"Review wizard API compatibility."
            )
            raise AssertionError(msg)

        # Phase 3: Complete first-run wizard (idempotent)
        # Docker service containers need the full wizard sequence for auth
        # to work. Jellyfin's own tests use just /Startup/Complete but they
        # run in-process, not in Docker.
        resp = await client.get(f"{base}/Startup/Configuration")
        if resp.status_code == 200:
            # Discover admin username before wizard changes state
            resp = await client.get(f"{base}/Startup/User")
            if resp.is_success:
                admin_user = resp.json().get("Name", "root")

            resp = await client.post(
                f"{base}/Startup/Configuration",
                json={
                    "UICulture": "en-US",
                    "MetadataCountryCode": "US",
                    "PreferredMetadataLanguage": "en",
                },
            )
            resp.raise_for_status()

            # Set admin user — may return 500 in CI, wizard still completes
            resp = await client.post(
                f"{base}/Startup/User",
                json={"Name": admin_user, "Password": TEST_ADMIN_PASS},
            )

            resp = await client.post(
                f"{base}/Startup/RemoteAccess",
                json={
                    "EnableRemoteAccess": True,
                    "EnableAutomaticPortMapping": False,
                },
            )
            resp.raise_for_status()

            resp = await client.post(f"{base}/Startup/Complete")
            resp.raise_for_status()

    return JellyfinInstance(url=base, admin_user=admin_user)


# ---------------------------------------------------------------------------
# Session-scoped fixture — authenticates as admin, returns access token
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture(scope="session")
async def admin_auth_token(jellyfin: JellyfinInstance) -> str:
    """Authenticate as admin and return the access token.

    On a fresh instance after /Startup/Complete, the default user has an
    empty password. We authenticate, then set the expected password.
    Retries handle the case where auth isn't ready immediately after wizard.
    """
    credentials = [
        (jellyfin.admin_user, TEST_ADMIN_PASS),
        (jellyfin.admin_user, ""),
    ]
    max_attempts = 10
    last_status = 0

    async with httpx.AsyncClient() as client:
        for attempt in range(max_attempts):
            for username, password in credentials:
                resp = await client.post(
                    f"{jellyfin.url}/Users/AuthenticateByName",
                    json={"Username": username, "Pw": password},
                    headers=_auth_headers(),
                )
                last_status = resp.status_code
                if resp.is_success:
                    data = resp.json()
                    token: str = data["AccessToken"]
                    user_id: str = data["User"]["Id"]

                    if password != TEST_ADMIN_PASS:
                        resp = await client.post(
                            f"{jellyfin.url}/Users/{user_id}/Password",
                            json={
                                "CurrentPw": password,
                                "NewPw": TEST_ADMIN_PASS,
                            },
                            headers=_auth_headers(token),
                        )
                        if not resp.is_success:
                            warnings.warn(
                                f"Could not set admin password "
                                f"(status {resp.status_code})",
                                stacklevel=2,
                            )

                    return token

            if attempt < max_attempts - 1:
                await asyncio.sleep(3)

    msg = (
        f"Cannot authenticate as {jellyfin.admin_user} after "
        f"{max_attempts} attempts (last status: {last_status})"
    )
    raise RuntimeError(msg)


# ---------------------------------------------------------------------------
# Session-scoped fixture — provisions test users (idempotent)
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture(scope="session")
async def test_users(
    jellyfin: JellyfinInstance, admin_auth_token: str
) -> dict[str, str]:
    """Create test users if they don't exist. Returns {username: user_id}.

    Idempotent — safe to run against an already-provisioned instance.
    """
    headers = _auth_headers(admin_auth_token)
    users_to_create = [
        (TEST_USER_ALICE, TEST_USER_ALICE_PASS),
        (TEST_USER_BOB, TEST_USER_BOB_PASS),
    ]

    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{jellyfin.url}/Users", headers=headers)
        resp.raise_for_status()
        existing = {u["Name"]: u["Id"] for u in resp.json()}

        created: dict[str, str] = {}
        for username, password in users_to_create:
            if username in existing:
                created[username] = existing[username]
                continue
            resp = await client.post(
                f"{jellyfin.url}/Users/New",
                json={"Name": username, "Password": password},
                headers=headers,
            )
            resp.raise_for_status()
            created[username] = resp.json()["Id"]

    return created


# Expected fixture counts — update if fixtures are added/removed
EXPECTED_MOVIES = 25
EXPECTED_SHOWS = 10
EXPECTED_TOTAL = EXPECTED_MOVIES + EXPECTED_SHOWS

# Scan polling config
_SCAN_POLL_INTERVAL = 2
_SCAN_POLL_TIMEOUT = 120


# ---------------------------------------------------------------------------
# Session-scoped fixture — adds libraries and waits for scan completion
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture(scope="session")
async def populated_library(
    jellyfin: JellyfinInstance,
    admin_auth_token: str,
    test_users: dict[str, str],  # noqa: ARG001 — forces user provisioning before library setup
) -> int:
    """Add Movies and Shows libraries from fixture media, trigger scan, poll.

    Returns the total item count discovered after scan completion.
    Idempotent — skips library creation if libraries already exist.
    """
    base = jellyfin.url
    headers = _auth_headers(admin_auth_token)

    async with httpx.AsyncClient(timeout=_SCAN_POLL_TIMEOUT + 30) as client:
        # Check existing libraries
        resp = await client.get(f"{base}/Library/VirtualFolders", headers=headers)
        resp.raise_for_status()
        existing = {lib["Name"] for lib in resp.json()}

        # Add Movies library if missing
        # Note: paths must be a query parameter, not body — Jellyfin
        # ignores PathInfos in the JSON body for this endpoint.
        if "Movies" not in existing:
            resp = await client.post(
                f"{base}/Library/VirtualFolders",
                params={
                    "name": "Movies",
                    "collectionType": "movies",
                    "refreshLibrary": "false",
                    "paths": "/media/movies",
                },
                headers=headers,
            )
            if resp.status_code == 400:
                pytest.skip(
                    "Jellyfin cannot access /media/movies — "
                    "fixture media not mounted (CI service containers "
                    "don't support bind mounts). Run locally with "
                    "make test-integration-full."
                )
            if resp.status_code not in (200, 204):
                _logger.warning(
                    "Movies library creation returned %d: %s",
                    resp.status_code,
                    resp.text[:200],
                )

        # Add Shows library if missing
        if "Shows" not in existing:
            resp = await client.post(
                f"{base}/Library/VirtualFolders",
                params={
                    "name": "Shows",
                    "collectionType": "tvshows",
                    "refreshLibrary": "false",
                    "paths": "/media/shows",
                },
                headers=headers,
            )
            if resp.status_code not in (200, 204):
                _logger.warning(
                    "Shows library creation returned %d: %s",
                    resp.status_code,
                    resp.text[:200],
                )

        # Trigger library scan
        resp = await client.post(f"{base}/Library/Refresh", headers=headers)
        resp.raise_for_status()

        # Poll for scan completion
        elapsed = 0.0
        total_count = 0
        while elapsed < _SCAN_POLL_TIMEOUT:
            await asyncio.sleep(_SCAN_POLL_INTERVAL)
            elapsed += _SCAN_POLL_INTERVAL

            resp = await client.get(
                f"{base}/Items",
                params={
                    "Recursive": "true",
                    "IncludeItemTypes": "Movie,Series",
                },
                headers=headers,
            )
            if resp.is_success:
                total_count = resp.json().get("TotalRecordCount", 0)
                if total_count >= EXPECTED_TOTAL:
                    _logger.info("library scan complete: %d items found", total_count)
                    return total_count

        msg = (
            f"Library scan did not reach {EXPECTED_TOTAL} items "
            f"within {_SCAN_POLL_TIMEOUT}s (got {total_count})"
        )
        raise TimeoutError(msg)


# ---------------------------------------------------------------------------
# Shared fixtures — used across integration test modules
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def jf_client(
    jellyfin: JellyfinInstance,
) -> AsyncGenerator[JellyfinClient, None]:
    """JellyfinClient pointed at the test instance."""
    async with httpx.AsyncClient(timeout=30.0) as http:
        yield JellyfinClient(base_url=jellyfin.url, http_client=http)


@pytest_asyncio.fixture
async def library_store(
    tmp_path: pathlib.Path,
) -> AsyncGenerator[LibraryStore, None]:
    """Temporary LibraryStore for integration tests."""
    db_path = tmp_path / "test_library.db"
    store = LibraryStore(str(db_path))
    await store.init()
    yield store
    await store.close()


@pytest_asyncio.fixture
async def alice_auth(
    jf_client: JellyfinClient,
    test_users: dict[str, str],  # noqa: ARG001 — ensures users exist
) -> AuthResult:
    """Authenticate as test-alice. Returns AuthResult."""
    return await jf_client.authenticate(TEST_USER_ALICE, TEST_USER_ALICE_PASS)
