"""Integration test fixtures — Jellyfin provisioning and readiness."""

import asyncio
import os
import warnings

import httpx
import pytest_asyncio

# ---------------------------------------------------------------------------
# Constants — test-only, never imported outside backend/tests/integration/
# ---------------------------------------------------------------------------
JELLYFIN_TEST_URL = os.environ.get(
    "JELLYFIN_TEST_URL", "http://host.docker.internal:8096"
)
EXPECTED_JELLYFIN_VERSION = "10.11.6"
TEST_ADMIN_USER = "admin"
TEST_ADMIN_PASS = "test-admin-password"

# Test users — known credentials for downstream permission-scoping tests
TEST_USER_ALICE = "test-alice"
TEST_USER_ALICE_PASS = "test-alice-password"

TEST_USER_BOB = "test-bob"
TEST_USER_BOB_PASS = "test-bob-password"

# Jellyfin client header required for authenticated API calls
JELLYFIN_AUTH_HEADER = (
    'MediaBrowser Client="ai-movie-suggester-tests", '
    'Device="pytest", DeviceId="integration-test", Version="0.0.0"'
)

POLL_INTERVAL_SECONDS = 2
POLL_TIMEOUT_SECONDS = 60


# ---------------------------------------------------------------------------
# Session-scoped fixture — polls, version-checks, completes wizard
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture(scope="session")
async def jellyfin_url() -> str:
    """Wait for Jellyfin readiness, verify version, complete wizard if needed.

    Returns the base URL of the ready Jellyfin instance.
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
        resp = await client.get(f"{base}/Startup/Configuration")
        if resp.status_code == 200:
            # Wizard not yet completed — run through the 4-step sequence
            resp = await client.post(
                f"{base}/Startup/Configuration",
                json={
                    "UICulture": "en-US",
                    "MetadataCountryCode": "US",
                    "PreferredMetadataLanguage": "en",
                },
            )
            resp.raise_for_status()

            # POST /Startup/User returns 500 on Jellyfin 10.11.6 when the
            # internal user database isn't fully initialized. The wizard
            # still completes without it, so we log but don't fail.
            resp = await client.post(
                f"{base}/Startup/User",
                json={
                    "Name": TEST_ADMIN_USER,
                    "Password": TEST_ADMIN_PASS,
                },
            )
            if not resp.is_success:
                warnings.warn(
                    f"POST /Startup/User returned {resp.status_code} "
                    f"(known Jellyfin 10.11.6 quirk, wizard still completes)",
                    stacklevel=1,
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

    return base


# ---------------------------------------------------------------------------
# Session-scoped fixture — authenticates as admin, returns access token
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture(scope="session")
async def admin_auth_token(jellyfin_url: str) -> str:
    """Authenticate as the admin user and return the access token.

    Handles the Jellyfin 10.11.6 quirk where POST /Startup/User may fail,
    leaving the default "root" user with an empty password instead of
    creating "admin" with the expected password. Tries multiple username/
    password combinations and normalizes to expected credentials.
    """
    # Jellyfin may need a moment after wizard completion before auth works
    await asyncio.sleep(2)

    # Try both header styles — Jellyfin versions vary
    header_styles = [
        {"X-Emby-Authorization": JELLYFIN_AUTH_HEADER},
        {"Authorization": JELLYFIN_AUTH_HEADER},
    ]

    # Candidates: (username, password) in priority order
    candidates = [
        (TEST_ADMIN_USER, TEST_ADMIN_PASS),  # Happy path: wizard worked
        (TEST_ADMIN_USER, ""),  # Wizard renamed user but no password
        ("root", ""),  # Default Jellyfin user, wizard POST failed
        ("root", TEST_ADMIN_PASS),  # Previous run set password on root
    ]

    async with httpx.AsyncClient() as client:
        token: str | None = None
        user_id: str | None = None
        matched_user: str | None = None
        matched_pass: str | None = None
        debug_attempts: list[str] = []

        for headers in header_styles:
            for username, password in candidates:
                resp = await client.post(
                    f"{jellyfin_url}/Users/AuthenticateByName",
                    json={"Username": username, "Pw": password},
                    headers=headers,
                )
                hdr = "X-Emby" if "X-Emby-Authorization" in headers else "Auth"
                debug_attempts.append(
                    f"{username}/{password!r} {hdr} → {resp.status_code}"
                )
                if resp.is_success:
                    data = resp.json()
                    token = data["AccessToken"]
                    user_id = data["User"]["Id"]
                    matched_user = username
                    matched_pass = password
                    break
            if token is not None:
                break

        if token is None or user_id is None:
            msg = "Cannot authenticate as admin. Attempts: " + "; ".join(debug_attempts)
            raise RuntimeError(msg)

        token_header = {
            "X-Emby-Authorization": f'{JELLYFIN_AUTH_HEADER}, Token="{token}"',
        }

        # Rename user to expected name if needed
        if matched_user != TEST_ADMIN_USER:
            resp = await client.post(
                f"{jellyfin_url}/Users/{user_id}",
                json={"Name": TEST_ADMIN_USER},
                headers=token_header,
            )
            if not resp.is_success:
                warnings.warn(
                    f"Could not rename {matched_user} to {TEST_ADMIN_USER} "
                    f"(status {resp.status_code})",
                    stacklevel=1,
                )

        # Set expected password if needed
        if matched_pass != TEST_ADMIN_PASS:
            resp = await client.post(
                f"{jellyfin_url}/Users/{user_id}/Password",
                json={"CurrentPw": matched_pass, "NewPw": TEST_ADMIN_PASS},
                headers=token_header,
            )
            if not resp.is_success:
                warnings.warn(
                    f"Could not set admin password (status {resp.status_code})",
                    stacklevel=1,
                )

    return token


# ---------------------------------------------------------------------------
# Session-scoped fixture — provisions test users (idempotent)
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture(scope="session")
async def test_users(jellyfin_url: str, admin_auth_token: str) -> dict[str, str]:
    """Create test users if they don't exist. Returns {username: user_id}.

    Idempotent — safe to run against an already-provisioned instance.
    """
    auth_headers = {
        "X-Emby-Authorization": (f'{JELLYFIN_AUTH_HEADER}, Token="{admin_auth_token}"'),
    }
    users_to_create = [
        (TEST_USER_ALICE, TEST_USER_ALICE_PASS),
        (TEST_USER_BOB, TEST_USER_BOB_PASS),
    ]

    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{jellyfin_url}/Users", headers=auth_headers)
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
                headers=auth_headers,
            )
            resp.raise_for_status()
            created[username] = resp.json()["Id"]

    return created
