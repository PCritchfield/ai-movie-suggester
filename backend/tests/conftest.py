import os

# Set test environment BEFORE any app imports happen.
# Unconditional override — unit tests must never hit real services
os.environ["JELLYFIN_URL"] = "http://jellyfin-test:8096"
os.environ["SESSION_SECRET"] = "test-secret-not-real-at-least-32-characters"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402


def make_test_settings(**overrides: str | int | float | bool | None) -> Settings:
    """Create a Settings instance for tests with sensible defaults."""
    defaults: dict[str, str | int | float | bool | None] = {
        "jellyfin_url": "http://jellyfin-test:8096",
        "session_secret": "test-secret-not-real-at-least-32-characters",
    }
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


def make_test_client(
    **settings_overrides: str | int | float | bool | None,
) -> TestClient:
    """Create a TestClient with custom settings for tests needing overrides."""
    return TestClient(create_app(make_test_settings(**settings_overrides)))


@pytest.fixture
def client() -> TestClient:
    return make_test_client()
