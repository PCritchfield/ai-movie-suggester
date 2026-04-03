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
from app.search.models import SearchResultItem  # noqa: E402

TEST_COOKIE_KEY, TEST_COLUMN_KEY = derive_keys(TEST_SECRET)


def make_search_result_item(
    title: str = "Galaxy Quest",
    jellyfin_id: str | None = None,
    year: int | None = 1999,
    genres: list[str] | None = None,
    overview: str | None = "A comedy about sci-fi actors.",
    score: float = 0.8,
    poster_url: str | None = None,
) -> SearchResultItem:
    """Create a SearchResultItem with sensible defaults for tests."""
    jid = jellyfin_id or f"jf-{title.lower().replace(' ', '-')}"
    return SearchResultItem(
        jellyfin_id=jid,
        title=title,
        overview=overview,
        genres=genres or ["Comedy", "Sci-Fi"],
        year=year,
        score=score,
        poster_url=poster_url or f"/Items/{jid}/Images/Primary",
    )


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
    """Create a TestClient with custom settings for tests needing overrides.

    Returns a TestClient with lifespan started (via context manager entry).

    WARNING: Callers MUST call ``client.close()`` (or wrap in try/finally)
    to trigger lifespan shutdown. Failing to close leaks the httpx clients
    and session store opened during startup. The ``client`` fixture handles
    this automatically via yield, but direct callers of this function do not
    get automatic cleanup.
    """
    tc = TestClient(create_app(make_test_settings(**settings_overrides)))
    tc.__enter__()
    return tc


@pytest.fixture
def client() -> TestClient:  # type: ignore[misc]
    tc = make_test_client()
    yield tc  # type: ignore[misc]
    tc.__exit__(None, None, None)
