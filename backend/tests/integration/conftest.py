"""Integration test fixtures — Jellyfin provisioning and readiness.

Wizard completion and auth follow the pattern from Jellyfin's own
integration tests (tests/Jellyfin.Server.Integration.Tests/AuthHelper.cs).
"""

import asyncio
import os

import httpx
import pytest_asyncio

# ---------------------------------------------------------------------------
# Constants — test-only, never imported outside backend/tests/integration/
# ---------------------------------------------------------------------------
JELLYFIN_TEST_URL = os.environ.get(
    "JELLYFIN_TEST_URL", "http://host.docker.internal:8096"
)
EXPECTED_JELLYFIN_VERSION = "10.11.6"
TEST_ADMIN_PASS = "test-admin-password"

# Test users — known credentials for downstream permission-scoping tests
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
async def jellyfin_url() -> str:
    """Wait for Jellyfin readiness, verify version, complete wizard if needed.

    Follows Jellyfin's own test pattern: read default user from
    GET /Startup/User, then POST /Startup/Complete. Skips the unreliable
    /Startup/Configuration, /Startup/User POST, and /Startup/RemoteAccess.
    """
    base = JELLYFIN_TEST_URL

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
        # Pattern from Jellyfin's AuthHelper.cs: just POST /Startup/Complete.
        resp = await client.get(f"{base}/Startup/Configuration")
        if resp.status_code == 200:
            resp = await client.post(f"{base}/Startup/Complete")
            resp.raise_for_status()

    return base


# ---------------------------------------------------------------------------
# Session-scoped fixture — authenticates as admin, returns access token
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture(scope="session")
async def admin_auth_token(jellyfin_url: str) -> str:
    """Authenticate as admin and return the access token.

    On a fresh instance after /Startup/Complete, the default user ("root")
    has an empty password. We authenticate, then set the expected password
    for downstream use.
    """
    async with httpx.AsyncClient() as client:
        # Discover the default admin username (typically "root")
        # Try /Startup/User first (available before auth is needed)
        resp = await client.get(f"{jellyfin_url}/Startup/User")
        default_user = resp.json().get("Name", "root") if resp.is_success else "root"

        # Authenticate — try expected creds first, then default empty password
        for username, password in [
            (default_user, TEST_ADMIN_PASS),  # Previous run set password
            (default_user, ""),  # Fresh instance, empty password
        ]:
            resp = await client.post(
                f"{jellyfin_url}/Users/AuthenticateByName",
                json={"Username": username, "Pw": password},
                headers=_auth_headers(),
            )
            if resp.is_success:
                data = resp.json()
                token: str = data["AccessToken"]
                user_id: str = data["User"]["Id"]

                # Set expected password if authenticated with empty
                if password != TEST_ADMIN_PASS:
                    resp = await client.post(
                        f"{jellyfin_url}/Users/{user_id}/Password",
                        json={
                            "CurrentPw": password,
                            "NewPw": TEST_ADMIN_PASS,
                        },
                        headers=_auth_headers(token),
                    )
                    # Non-fatal — password change may fail but auth works
                    if not resp.is_success:
                        import warnings

                        warnings.warn(
                            f"Could not set admin password (status {resp.status_code})",
                            stacklevel=1,
                        )

                return token

        msg = f"Cannot authenticate as {default_user} with any known password"
        raise RuntimeError(msg)


# ---------------------------------------------------------------------------
# Session-scoped fixture — provisions test users (idempotent)
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture(scope="session")
async def test_users(jellyfin_url: str, admin_auth_token: str) -> dict[str, str]:
    """Create test users if they don't exist. Returns {username: user_id}.

    Idempotent — safe to run against an already-provisioned instance.
    """
    headers = _auth_headers(admin_auth_token)
    users_to_create = [
        (TEST_USER_ALICE, TEST_USER_ALICE_PASS),
        (TEST_USER_BOB, TEST_USER_BOB_PASS),
    ]

    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{jellyfin_url}/Users", headers=headers)
        resp.raise_for_status()
        existing = {u["Name"]: u["Id"] for u in resp.json()}

        created: dict[str, str] = {}
        for username, password in users_to_create:
            if username in existing:
                created[username] = existing[username]
                continue
            resp = await client.post(
                f"{jellyfin_url}/Users/New",
                json={"Name": username, "Password": password},
                headers=headers,
            )
            resp.raise_for_status()
            created[username] = resp.json()["Id"]

    return created
