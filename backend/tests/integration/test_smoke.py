import httpx
import pytest


@pytest.mark.integration
async def test_jellyfin_health(jellyfin_url: str) -> None:
    """Verify Jellyfin is reachable and returns a healthy status."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{jellyfin_url}/health")
    assert resp.status_code == 200
    assert resp.text == "Healthy"


@pytest.mark.integration
async def test_jellyfin_wizard_complete(jellyfin_url: str) -> None:
    """Verify the first-run wizard has been completed."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{jellyfin_url}/System/Info/Public")
    assert resp.status_code == 200
    data = resp.json()
    assert "Version" in data
    assert "StartupWizardCompleted" in data
    assert data["StartupWizardCompleted"] is True


@pytest.mark.integration
async def test_admin_authentication(admin_auth_token: str) -> None:
    """Verify the admin user can authenticate and receives a token."""
    assert isinstance(admin_auth_token, str)
    assert len(admin_auth_token) > 0


@pytest.mark.integration
async def test_test_users_provisioned(test_users: dict[str, str]) -> None:
    """Verify test users exist with expected names and valid IDs."""
    from tests.integration.conftest import TEST_USER_ALICE, TEST_USER_BOB

    assert TEST_USER_ALICE in test_users
    assert TEST_USER_BOB in test_users
    for user_id in test_users.values():
        assert isinstance(user_id, str)
        assert len(user_id) > 0
