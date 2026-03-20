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
