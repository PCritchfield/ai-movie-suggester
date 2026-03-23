"""Docs toggle tests — verify /docs and /redoc conditional access."""

from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import make_test_settings


def _make_client(**settings_overrides: str | int | float | bool | None) -> TestClient:
    return TestClient(create_app(make_test_settings(**settings_overrides)))


def test_docs_enabled_in_debug_mode() -> None:
    """LOG_LEVEL=debug enables /docs by default."""
    client = _make_client(log_level="debug")
    response = client.get("/docs")
    assert response.status_code == 200


def test_docs_disabled_in_info_mode() -> None:
    """LOG_LEVEL=info disables /docs by default."""
    client = _make_client(log_level="info")
    response = client.get("/docs")
    assert response.status_code == 404


def test_docs_override_enable() -> None:
    """ENABLE_DOCS=true overrides LOG_LEVEL=info."""
    client = _make_client(log_level="info", enable_docs=True)
    response = client.get("/docs")
    assert response.status_code == 200


def test_docs_override_disable() -> None:
    """ENABLE_DOCS=false overrides LOG_LEVEL=debug."""
    client = _make_client(log_level="debug", enable_docs=False)
    response = client.get("/docs")
    assert response.status_code == 404


def test_redoc_disabled_in_info_mode() -> None:
    """LOG_LEVEL=info disables /redoc by default."""
    client = _make_client(log_level="info")
    response = client.get("/redoc")
    assert response.status_code == 404
