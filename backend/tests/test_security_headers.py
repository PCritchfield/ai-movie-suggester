"""Security headers middleware tests."""

from tests.conftest import make_test_client

# --- Static headers (docs disabled = default test settings) ---


def test_x_content_type_options() -> None:
    """Every response has X-Content-Type-Options: nosniff."""
    client = make_test_client()
    response = client.get("/health")
    assert response.headers.get("x-content-type-options") == "nosniff"


def test_x_frame_options() -> None:
    """Every response has X-Frame-Options: DENY."""
    client = make_test_client()
    response = client.get("/health")
    assert response.headers.get("x-frame-options") == "DENY"


def test_csp_header_present() -> None:
    """Every response has a Content-Security-Policy header."""
    client = make_test_client()
    response = client.get("/health")
    assert "content-security-policy" in response.headers


def test_cache_control_on_2xx() -> None:
    """2xx responses have Cache-Control: no-store."""
    client = make_test_client()
    response = client.get("/health")
    assert response.status_code == 200
    assert response.headers.get("cache-control") == "no-store"


def test_no_hsts() -> None:
    """Responses must NOT include Strict-Transport-Security."""
    client = make_test_client()
    response = client.get("/health")
    assert "strict-transport-security" not in response.headers


# --- CSP dual-mode ---


def test_csp_production_mode() -> None:
    """Docs disabled: CSP is strict production policy."""
    client = make_test_client(log_level="info")
    response = client.get("/health")
    csp = response.headers.get("content-security-policy", "")
    assert csp == "default-src 'none'; frame-ancestors 'none'"


def test_csp_debug_mode() -> None:
    """LOG_LEVEL=debug + ENABLE_DOCS unset: CSP allows Swagger UI resources."""
    client = make_test_client(log_level="debug")
    response = client.get("/health")
    csp = response.headers.get("content-security-policy", "")
    assert "script-src 'unsafe-inline' https://cdn.jsdelivr.net" in csp
    assert "style-src 'unsafe-inline' https://cdn.jsdelivr.net" in csp
    assert "frame-ancestors 'none'" in csp


def test_csp_enable_docs_override() -> None:
    """LOG_LEVEL=info + ENABLE_DOCS=true: CSP allows Swagger UI resources."""
    client = make_test_client(log_level="info", enable_docs=True)
    response = client.get("/health")
    csp = response.headers.get("content-security-policy", "")
    assert "script-src 'unsafe-inline' https://cdn.jsdelivr.net" in csp


def test_csp_disable_docs_override_in_debug() -> None:
    """ENABLE_DOCS=false overrides LOG_LEVEL=debug: CSP is strict production."""
    client = make_test_client(log_level="debug", enable_docs=False)
    response = client.get("/health")
    csp = response.headers.get("content-security-policy", "")
    assert csp == "default-src 'none'; frame-ancestors 'none'"


def test_no_cache_control_on_404() -> None:
    """Non-2xx responses do NOT get Cache-Control: no-store."""
    client = make_test_client()
    response = client.get("/nonexistent-route")
    assert response.status_code == 404
    assert "cache-control" not in response.headers


def test_debug_csp_includes_connect_src() -> None:
    """Debug CSP includes connect-src 'self' so Swagger can fetch /openapi.json."""
    client = make_test_client(log_level="debug")
    response = client.get("/health")
    csp = response.headers.get("content-security-policy", "")
    assert "connect-src 'self'" in csp
