import os
from unittest.mock import AsyncMock

# Canonical test constants — single source of truth
TEST_SECRET = "kG7xP2mN9qR4wL8jT3vF6yA5dH0sE1cB"
TEST_JELLYFIN_URL = "http://jellyfin-test:8096"

# Set test environment BEFORE any app imports happen.
# Unconditional override — unit tests must never hit real services
os.environ["JELLYFIN_URL"] = TEST_JELLYFIN_URL
os.environ["SESSION_SECRET"] = TEST_SECRET

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.auth.crypto import derive_keys  # noqa: E402
from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402

TEST_COOKIE_KEY, TEST_COLUMN_KEY = derive_keys(TEST_SECRET)


@pytest.fixture
def mock_jf() -> AsyncMock:
    """Mock JellyfinClient shared across test modules."""
    jf = AsyncMock()
    jf.authenticate.return_value = AsyncMock(
        access_token="jf-tok-123",
        user_id="uid-1",
        user_name="alice",
    )
    jf.get_server_name.return_value = "MyJellyfin"
    jf.logout.return_value = None
    return jf


def make_test_settings(**overrides: str | int | float | bool | None) -> Settings:
    """Create a Settings instance for tests with sensible defaults."""
    defaults: dict[str, str | int | float | bool | None] = {
        "jellyfin_url": "http://jellyfin-test:8096",
        "session_secret": TEST_SECRET,
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
