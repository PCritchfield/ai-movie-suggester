"""CORS middleware tests — verify single-origin enforcement."""

from tests.conftest import make_test_client


def test_cors_rejects_unknown_origin() -> None:
    """OPTIONS from unknown origin gets no Access-Control-Allow-Origin."""
    client = make_test_client()
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
    client = make_test_client()
    response = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert (
        response.headers.get("access-control-allow-origin") == "http://localhost:3000"
    )


def test_cors_allows_configured_origin_simple_request() -> None:
    """GET from configured origin gets correct ACAO header."""
    client = make_test_client()
    response = client.get(
        "/health",
        headers={"Origin": "http://localhost:3000"},
    )
    assert (
        response.headers.get("access-control-allow-origin") == "http://localhost:3000"
    )


def test_cors_allows_credentials() -> None:
    """CORS preflight includes Allow-Credentials for cookie auth."""
    client = make_test_client()
    response = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.headers.get("access-control-allow-credentials") == "true"
