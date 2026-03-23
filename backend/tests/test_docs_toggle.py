"""Docs toggle tests — verify /docs and /redoc conditional access."""

from tests.conftest import make_test_client


def test_docs_enabled_in_debug_mode() -> None:
    """LOG_LEVEL=debug enables /docs by default."""
    client = make_test_client(log_level="debug")
    response = client.get("/docs")
    assert response.status_code == 200


def test_docs_disabled_in_info_mode() -> None:
    """LOG_LEVEL=info disables /docs by default."""
    client = make_test_client(log_level="info")
    response = client.get("/docs")
    assert response.status_code == 404


def test_docs_override_enable() -> None:
    """ENABLE_DOCS=true overrides LOG_LEVEL=info."""
    client = make_test_client(log_level="info", enable_docs=True)
    response = client.get("/docs")
    assert response.status_code == 200


def test_docs_override_disable() -> None:
    """ENABLE_DOCS=false overrides LOG_LEVEL=debug."""
    client = make_test_client(log_level="debug", enable_docs=False)
    response = client.get("/docs")
    assert response.status_code == 404


def test_redoc_disabled_in_info_mode() -> None:
    """LOG_LEVEL=info disables /redoc by default."""
    client = make_test_client(log_level="info")
    response = client.get("/redoc")
    assert response.status_code == 404
