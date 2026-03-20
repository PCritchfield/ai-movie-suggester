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
