from unittest.mock import AsyncMock, patch

import httpx


def test_health_endpoint_returns_200(client) -> None:
    response = client.get("/health")
    assert response.status_code == 200


def test_health_response_shape(client) -> None:
    """Health response must include jellyfin, ollama, and embeddings."""
    response = client.get("/health")
    data = response.json()
    assert "jellyfin" in data
    assert "ollama" in data
    assert "embeddings" in data
    assert "total" in data["embeddings"]
    assert "pending" in data["embeddings"]


def test_health_jellyfin_reports_status(client) -> None:
    """Health reports ok or error for each service (not crash)."""
    response = client.get("/health")
    data = response.json()
    assert data["jellyfin"] in ("ok", "error")
    assert data["ollama"] in ("ok", "error")


def test_health_reports_ok_when_services_reachable(client) -> None:
    """When external services respond 200, health reports 'ok'."""
    mock_response = httpx.Response(200)
    with patch("app.main.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client
        response = client.get("/health")
    data = response.json()
    assert data["jellyfin"] == "ok"
    assert data["ollama"] == "ok"


def test_health_embeddings_zero_until_epic2(client) -> None:
    """Embeddings should be 0/0 until Epic 2."""
    response = client.get("/health")
    data = response.json()
    assert data["embeddings"]["total"] == 0
    assert data["embeddings"]["pending"] == 0
