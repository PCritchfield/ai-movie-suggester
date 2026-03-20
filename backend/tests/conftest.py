import os

# Set test environment BEFORE any app imports happen.
os.environ.setdefault("JELLYFIN_URL", "http://jellyfin-test:8096")
os.environ.setdefault("SESSION_SECRET", "test-secret-not-real-at-least-32-characters")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)
