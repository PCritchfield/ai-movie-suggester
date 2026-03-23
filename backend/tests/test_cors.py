"""CORS middleware tests — verify single-origin enforcement."""

from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import make_test_settings


def _make_client(**settings_overrides: str | int | float | bool | None) -> TestClient:
    return TestClient(create_app(make_test_settings(**settings_overrides)))


def test_cors_rejects_unknown_origin() -> None:
    """OPTIONS from unknown origin gets no Access-Control-Allow-Origin."""
    client = _make_client()
    response = client.options(
        "/health",
        headers={
            "Origin": "https://evil.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert "access-control-allow-origin" not in response.headers


def test_cors_allows_configured_origin_preflight() -> None:
    """OPTIONS from configured origin gets correct ACAO header."""
    client = _make_client()
    response = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_cors_allows_configured_origin_simple_request() -> None:
    """GET from configured origin gets correct ACAO header."""
    client = _make_client()
    response = client.get(
        "/health",
        headers={"Origin": "http://localhost:3000"},
    )
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_cors_allows_credentials() -> None:
    """CORS preflight includes Allow-Credentials for cookie auth."""
    client = _make_client()
    response = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.headers.get("access-control-allow-credentials") == "true"
