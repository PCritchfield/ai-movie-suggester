# backend/tests/test_config.py
import os
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from app.config import Settings


def test_settings_loads_defaults() -> None:
    """Settings should load with defaults for optional fields."""
    env = {
        "JELLYFIN_URL": "http://jellyfin:8096",
        "SESSION_SECRET": "test-secret-value-at-least-32-chars-long",
    }
    with patch.dict(os.environ, env, clear=False):
        s = Settings()  # type: ignore[call-arg]
    assert s.jellyfin_url == "http://jellyfin:8096"
    assert s.ollama_host == "http://ollama:11434"
    assert s.ollama_chat_model == "llama3.1:8b"
    assert s.ollama_embed_model == "nomic-embed-text"
    assert s.tmdb_enabled is False
    assert s.log_level == "info"
    assert s.session_expiry_hours == 24
    assert s.chat_rate_limit == 10


def test_settings_requires_jellyfin_url() -> None:
    """Settings should fail without JELLYFIN_URL."""
    env = {"SESSION_SECRET": "test-secret"}
    with patch.dict(os.environ, env, clear=True), pytest.raises(ValidationError):
        Settings()  # type: ignore[call-arg]


def test_settings_requires_session_secret() -> None:
    """Settings should fail without SESSION_SECRET."""
    env = {"JELLYFIN_URL": "http://localhost:8096"}
    with patch.dict(os.environ, env, clear=True), pytest.raises(ValidationError):
        Settings()  # type: ignore[call-arg]
