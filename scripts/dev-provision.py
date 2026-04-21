# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx"]
# ///
"""Provision the local dev stack in two phases.

Phase 1 (--phase init): Jellyfin wizard, test users, API key, library scan.
  Writes JELLYFIN_API_KEY and JELLYFIN_ADMIN_USER_ID to /shared/.localdev-env
  so the backend can source them at startup.

Phase 2 (--phase sync): Log in to backend, trigger library sync, wait.

Dev-only — all credentials are for the disposable local stack.
Do not use these values against a real Jellyfin server.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

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
SHARED_DIR = os.environ.get("SHARED_DIR", "/shared")

ADMIN_USER = "root"
ADMIN_PASS = "test-admin-password"

TEST_USERS = [
    ("test-alice", "test-alice-password"),
    ("test-bob", "test-bob-password"),
]

EXPECTED_TOTAL = 35  # 25 movies + 10 shows

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
# Phase 1: Init — Jellyfin provisioning
# ---------------------------------------------------------------------------
async def phase_init() -> None:
    """Provision Jellyfin and write runtime env for the backend."""
    log.info("=== Phase 1: Jellyfin init ===")

    async with httpx.AsyncClient(timeout=30.0) as client:
        admin_user = await _complete_wizard(client)
        token, user_id = await _authenticate_admin(client, admin_user)
        await _create_test_users(client, token)
        api_key = await _create_api_key(client, token)
        await _setup_libraries(client, token)

    # Write runtime env for the backend to source
    env_path = Path(SHARED_DIR) / ".localdev-env"
    env_path.write_text(
        f"JELLYFIN_API_KEY={api_key}\nJELLYFIN_ADMIN_USER_ID={user_id}\n"
    )
    log.info("Wrote runtime env to %s", env_path)
    log.info("=== Phase 1 complete ===")


async def _complete_wizard(client: httpx.AsyncClient) -> str:
    """Complete Jellyfin first-run wizard. Returns admin username."""
    admin_user = ADMIN_USER

    resp = await client.get(f"{JELLYFIN_URL}/Startup/Configuration")
    if resp.status_code != 200:
        log.info("Wizard already completed")
        return admin_user

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


async def _authenticate_admin(
    client: httpx.AsyncClient, admin_user: str
) -> tuple[str, str]:
    """Authenticate as admin. Returns (token, user_id)."""
    credentials = [
        (admin_user, ADMIN_PASS),
        (admin_user, ""),
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

                if password != ADMIN_PASS:
                    await client.post(
                        f"{JELLYFIN_URL}/Users/{user_id}/Password",
                        json={"CurrentPw": password, "NewPw": ADMIN_PASS},
                        headers=_auth_headers(token),
                    )
                    log.info("Admin password set")

                log.info("Authenticated as '%s' (id=%s)", username, user_id)
                return token, user_id

        if attempt < 9:
            await asyncio.sleep(3)

    log.error("Failed to authenticate as admin after 10 attempts")
    sys.exit(1)


async def _create_test_users(client: httpx.AsyncClient, token: str) -> None:
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


async def _create_api_key(client: httpx.AsyncClient, token: str) -> str:
    """Create a Jellyfin API key for the backend sync engine."""
    headers = _auth_headers(token)

    # Check if key already exists
    resp = await client.get(f"{JELLYFIN_URL}/Auth/Keys", headers=headers)
    resp.raise_for_status()
    for key in resp.json().get("Items", []):
        if key.get("AppName") == "localdev-sync":
            log.info("API key 'localdev-sync' already exists")
            return key["AccessToken"]

    # Create new key
    resp = await client.post(
        f"{JELLYFIN_URL}/Auth/Keys",
        params={"App": "localdev-sync"},
        headers=headers,
    )
    resp.raise_for_status()

    # Fetch back to get the generated key
    resp = await client.get(f"{JELLYFIN_URL}/Auth/Keys", headers=headers)
    resp.raise_for_status()
    for key in resp.json().get("Items", []):
        if key.get("AppName") == "localdev-sync":
            log.info("Created API key 'localdev-sync'")
            return key["AccessToken"]

    log.error("Failed to retrieve created API key")
    sys.exit(1)


async def _setup_libraries(client: httpx.AsyncClient, token: str) -> None:
    """Add libraries, trigger scan, poll for completion."""
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
# Phase 2: Sync — trigger backend library sync
# ---------------------------------------------------------------------------
async def phase_sync() -> None:
    """Log in to the backend and trigger library sync."""
    log.info("=== Phase 2: Backend sync ===")

    async with httpx.AsyncClient(timeout=60.0) as client:
        # Log in as admin
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

        cookies = resp.cookies
        csrf_token = cookies.get("csrf_token", "")
        csrf_headers = {"X-CSRF-Token": csrf_token} if csrf_token else {}
        log.info("Backend login successful, triggering sync...")

        # Trigger sync
        resp = await client.post(
            f"{BACKEND_URL}/api/admin/sync",
            cookies=cookies,
            headers=csrf_headers,
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
            # Non-fatal — sync may not be configured yet on first run
            # The backend will sync when it has the right env vars

        # Poll sync status
        log.info("Waiting for sync to complete...")
        for _ in range(60):
            await asyncio.sleep(5)
            resp = await client.get(
                f"{BACKEND_URL}/api/admin/sync/status",
                cookies=cookies,
                headers=csrf_headers,
            )
            if resp.is_success:
                data = resp.json()
                status = data.get("status", "unknown")
                if status == "idle":
                    item_count = data.get("items_synced", 0)
                    log.info("Sync complete: %d items synced", item_count)
                    break
                log.info("Sync status: %s", status)
        else:
            log.warning("Sync did not complete within timeout — continuing")

    log.info("=== Phase 2 complete ===")
    log.info("Open http://localhost:3000 and log in as:")
    log.info("  Username: test-alice")
    log.info("  Password: test-alice-password")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
async def main() -> None:
    phase = "all"
    if "--phase" in sys.argv:
        idx = sys.argv.index("--phase")
        if idx + 1 < len(sys.argv):
            phase = sys.argv[idx + 1]

    if phase in ("all", "init"):
        await phase_init()
    if phase in ("all", "sync"):
        await phase_sync()


if __name__ == "__main__":
    asyncio.run(main())
