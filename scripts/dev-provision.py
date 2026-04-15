# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx"]
# ///
"""Provision the local dev stack: Jellyfin wizard, test users, library, backend sync.

Dev-only — all credentials are for the disposable local stack.
Do not use these values against a real Jellyfin server.

Runs as a one-shot container in docker-compose.localdev.yml.
Idempotent — safe to re-run against an already-provisioned instance.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [provision] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("provision")

# ---------------------------------------------------------------------------
# Config — matches docker-compose.localdev.yml and integration conftest
# ---------------------------------------------------------------------------
JELLYFIN_URL = os.environ.get("JELLYFIN_URL", "http://jellyfin:8096")
BACKEND_URL = os.environ.get("BACKEND_URL", "http://backend:8000")

ADMIN_USER = "root"
ADMIN_PASS = "test-admin-password"

TEST_USERS = [
    ("test-alice", "test-alice-password"),
    ("test-bob", "test-bob-password"),
]

EXPECTED_TOTAL = 35  # 25 movies + 10 shows

# Jellyfin auth header format (same as integration conftest)
_AUTH_HEADER = (
    'MediaBrowser Client="ai-movie-suggester-dev", '
    'DeviceId="dev-provision", Device="provision-script", Version="0.0.0"'
)

POLL_INTERVAL = 2
POLL_TIMEOUT = 120


def _auth_headers(token: str | None = None) -> dict[str, str]:
    value = _AUTH_HEADER if token is None else f"{_AUTH_HEADER}, Token={token}"
    return {"Authorization": value}


# ---------------------------------------------------------------------------
# Phase 1: Jellyfin wizard
# ---------------------------------------------------------------------------
async def complete_wizard(client: httpx.AsyncClient) -> str:
    """Complete Jellyfin first-run wizard. Returns admin username."""
    admin_user = ADMIN_USER

    resp = await client.get(f"{JELLYFIN_URL}/Startup/Configuration")
    if resp.status_code != 200:
        log.info("Wizard already completed")
        return admin_user

    # Discover admin username
    resp = await client.get(f"{JELLYFIN_URL}/Startup/User")
    if resp.is_success:
        admin_user = resp.json().get("Name", ADMIN_USER)

    log.info("Completing wizard for user '%s'...", admin_user)

    await client.post(
        f"{JELLYFIN_URL}/Startup/Configuration",
        json={
            "UICulture": "en-US",
            "MetadataCountryCode": "US",
            "PreferredMetadataLanguage": "en",
        },
    )

    await client.post(
        f"{JELLYFIN_URL}/Startup/User",
        json={"Name": admin_user, "Password": ADMIN_PASS},
    )

    await client.post(
        f"{JELLYFIN_URL}/Startup/RemoteAccess",
        json={"EnableRemoteAccess": True, "EnableAutomaticPortMapping": False},
    )

    resp = await client.post(f"{JELLYFIN_URL}/Startup/Complete")
    resp.raise_for_status()
    log.info("Wizard complete")
    return admin_user


# ---------------------------------------------------------------------------
# Phase 2: Authenticate as admin
# ---------------------------------------------------------------------------
async def authenticate_admin(client: httpx.AsyncClient, admin_user: str) -> str:
    """Authenticate as admin, setting password if needed. Returns token."""
    credentials = [
        (admin_user, ADMIN_PASS),
        (admin_user, ""),  # fresh instance may have empty password
    ]

    for attempt in range(10):
        for username, password in credentials:
            resp = await client.post(
                f"{JELLYFIN_URL}/Users/AuthenticateByName",
                json={"Username": username, "Pw": password},
                headers=_auth_headers(),
            )
            if resp.is_success:
                data = resp.json()
                token: str = data["AccessToken"]
                user_id: str = data["User"]["Id"]

                # Set password if it was empty
                if password != ADMIN_PASS:
                    await client.post(
                        f"{JELLYFIN_URL}/Users/{user_id}/Password",
                        json={"CurrentPw": password, "NewPw": ADMIN_PASS},
                        headers=_auth_headers(token),
                    )
                    log.info("Admin password set")

                log.info("Authenticated as '%s'", username)
                return token

        if attempt < 9:
            await asyncio.sleep(3)

    log.error("Failed to authenticate as admin after 10 attempts")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Phase 3: Create test users
# ---------------------------------------------------------------------------
async def create_test_users(client: httpx.AsyncClient, token: str) -> None:
    """Create test users if they don't exist."""
    headers = _auth_headers(token)
    resp = await client.get(f"{JELLYFIN_URL}/Users", headers=headers)
    resp.raise_for_status()
    existing = {u["Name"] for u in resp.json()}

    for username, password in TEST_USERS:
        if username in existing:
            log.info("User '%s' already exists", username)
            continue
        resp = await client.post(
            f"{JELLYFIN_URL}/Users/New",
            json={"Name": username, "Password": password},
            headers=headers,
        )
        resp.raise_for_status()
        log.info("Created user '%s'", username)


# ---------------------------------------------------------------------------
# Phase 4: Add libraries and scan
# ---------------------------------------------------------------------------
async def setup_libraries(client: httpx.AsyncClient, token: str) -> None:
    """Add Movies and Shows libraries, trigger scan, poll for completion."""
    headers = _auth_headers(token)

    resp = await client.get(f"{JELLYFIN_URL}/Library/VirtualFolders", headers=headers)
    resp.raise_for_status()
    existing = {lib["Name"] for lib in resp.json()}

    if "Movies" not in existing:
        resp = await client.post(
            f"{JELLYFIN_URL}/Library/VirtualFolders",
            params={
                "name": "Movies",
                "collectionType": "movies",
                "refreshLibrary": "false",
                "paths": "/media/movies",
            },
            headers=headers,
        )
        log.info("Added Movies library (status %d)", resp.status_code)

    if "Shows" not in existing:
        resp = await client.post(
            f"{JELLYFIN_URL}/Library/VirtualFolders",
            params={
                "name": "Shows",
                "collectionType": "tvshows",
                "refreshLibrary": "false",
                "paths": "/media/shows",
            },
            headers=headers,
        )
        log.info("Added Shows library (status %d)", resp.status_code)

    # Trigger library scan
    resp = await client.post(f"{JELLYFIN_URL}/Library/Refresh", headers=headers)
    resp.raise_for_status()
    log.info("Library scan triggered, polling for %d items...", EXPECTED_TOTAL)

    elapsed = 0.0
    total_count = 0
    while elapsed < POLL_TIMEOUT:
        await asyncio.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL

        resp = await client.get(
            f"{JELLYFIN_URL}/Items",
            params={"Recursive": "true", "IncludeItemTypes": "Movie,Series"},
            headers=headers,
        )
        if resp.is_success:
            total_count = resp.json().get("TotalRecordCount", 0)
            if total_count >= EXPECTED_TOTAL:
                log.info("Library scan complete: %d items", total_count)
                return

    log.error(
        "Library scan did not reach %d items within %ds (got %d)",
        EXPECTED_TOTAL,
        POLL_TIMEOUT,
        total_count,
    )
    sys.exit(1)


# ---------------------------------------------------------------------------
# Phase 5: Trigger backend sync via authenticated session
# ---------------------------------------------------------------------------
async def trigger_backend_sync(client: httpx.AsyncClient) -> None:
    """Log in to the backend as admin and trigger library sync."""
    # Log in to the backend (which authenticates against Jellyfin)
    log.info("Logging in to backend as '%s'...", ADMIN_USER)
    resp = await client.post(
        f"{BACKEND_URL}/api/auth/login",
        json={"username": ADMIN_USER, "password": ADMIN_PASS},
    )
    if not resp.is_success:
        log.error(
            "Backend login failed (status %d): %s",
            resp.status_code,
            resp.text[:200],
        )
        sys.exit(1)

    # Extract session cookie for subsequent requests
    cookies = resp.cookies
    log.info("Backend login successful, triggering sync...")

    resp = await client.post(
        f"{BACKEND_URL}/api/admin/sync",
        cookies=cookies,
    )
    if resp.status_code == 202:
        log.info("Sync triggered (202 Accepted)")
    elif resp.status_code == 409:
        log.info("Sync already running (409 Conflict) — OK")
    else:
        log.warning(
            "Sync trigger returned %d: %s",
            resp.status_code,
            resp.text[:200],
        )

    # Poll sync status until complete
    log.info("Waiting for sync to complete...")
    for _ in range(60):
        await asyncio.sleep(5)
        resp = await client.get(
            f"{BACKEND_URL}/api/admin/sync/status",
            cookies=cookies,
        )
        if resp.is_success:
            data = resp.json()
            status = data.get("status", "unknown")
            if status == "idle":
                item_count = data.get("items_synced", 0)
                log.info("Sync complete: %d items synced", item_count)
                return
            log.info("Sync status: %s", status)

    log.warning("Sync did not complete within timeout — continuing anyway")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
async def main() -> None:
    log.info("=== Dev provisioner starting ===")
    log.info("Jellyfin: %s", JELLYFIN_URL)
    log.info("Backend:  %s", BACKEND_URL)

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Phase 1-4: Jellyfin provisioning
        admin_user = await complete_wizard(client)
        token = await authenticate_admin(client, admin_user)
        await create_test_users(client, token)
        await setup_libraries(client, token)

    # Phase 5: Backend sync (separate client for cookie handling)
    async with httpx.AsyncClient(timeout=60.0) as client:
        await trigger_backend_sync(client)

    log.info("=== Dev provisioner complete ===")
    log.info("Open http://localhost:3000 and log in as:")
    log.info("  Username: test-alice")
    log.info("  Password: test-alice-password")


if __name__ == "__main__":
    asyncio.run(main())
