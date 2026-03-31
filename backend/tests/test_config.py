import os
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from app.config import Settings

_VALID_SECRET = "kG7xP2mN9qR4wL8jT3vF6yA5dH0sE1cB"
_REQUIRED_ENV = {
    "JELLYFIN_URL": "http://jellyfin:8096",
    "SESSION_SECRET": _VALID_SECRET,
}


def test_settings_loads_defaults() -> None:
    """Settings should load with defaults for optional fields."""
    env = {
        "JELLYFIN_URL": "http://jellyfin:8096",
        "SESSION_SECRET": _VALID_SECRET,
    }
    with patch.dict(os.environ, env, clear=False):
        s = Settings()  # type: ignore[call-arg]
    assert s.jellyfin_url == "http://jellyfin:8096"
    assert s.ollama_host == "http://ollama:11434"
    assert s.ollama_chat_model == "llama3.1:8b"
    assert s.ollama_embed_model == "nomic-embed-text"
    assert s.tmdb_enabled is False
    assert s.tmdb_api_key is None
    assert s.log_level == "info"
    assert s.session_expiry_hours == 24
    assert s.chat_rate_limit == 10


def test_settings_requires_jellyfin_url() -> None:
    """Settings should fail without JELLYFIN_URL."""
    env = {"SESSION_SECRET": _VALID_SECRET}
    with patch.dict(os.environ, env, clear=True), pytest.raises(ValidationError):
        Settings()  # type: ignore[call-arg]


def test_settings_requires_session_secret() -> None:
    """Settings should fail without SESSION_SECRET."""
    env = {"JELLYFIN_URL": "http://localhost:8096"}
    with patch.dict(os.environ, env, clear=True), pytest.raises(ValidationError):
        Settings()  # type: ignore[call-arg]


def test_settings_rejects_short_session_secret() -> None:
    """Session secret must be at least 32 characters."""
    env = {
        "JELLYFIN_URL": "http://localhost:8096",
        "SESSION_SECRET": "too-short",
    }
    with patch.dict(os.environ, env, clear=True), pytest.raises(ValidationError):
        Settings()  # type: ignore[call-arg]


def test_settings_jellyfin_timeout_default() -> None:
    """Jellyfin timeout should default to 10 seconds."""
    env = {
        "JELLYFIN_URL": "http://jellyfin:8096",
        "SESSION_SECRET": _VALID_SECRET,
    }
    with patch.dict(os.environ, env, clear=False):
        s = Settings()  # type: ignore[call-arg]
    assert s.jellyfin_timeout == 10.0


def test_settings_rejects_tmdb_enabled_without_key() -> None:
    """TMDB_ENABLED=true requires TMDB_API_KEY."""
    env = {
        "JELLYFIN_URL": "http://localhost:8096",
        "SESSION_SECRET": _VALID_SECRET,
        "TMDB_ENABLED": "true",
    }
    with patch.dict(os.environ, env, clear=True), pytest.raises(ValidationError):
        Settings()  # type: ignore[call-arg]


# --- cors_origin ---


def test_cors_origin_default() -> None:
    """cors_origin defaults to http://localhost:3000."""
    env = _REQUIRED_ENV.copy()
    with patch.dict(os.environ, env, clear=True):
        s = Settings()  # type: ignore[call-arg]
    assert s.cors_origin_str == "http://localhost:3000"


def test_cors_origin_custom_value() -> None:
    """cors_origin accepts a valid URL."""
    env = {**_REQUIRED_ENV, "CORS_ORIGIN": "https://movies.example.com"}
    with patch.dict(os.environ, env, clear=True):
        s = Settings()  # type: ignore[call-arg]
    assert s.cors_origin_str == "https://movies.example.com"


def test_cors_origin_rejects_invalid_url() -> None:
    """cors_origin rejects non-URL strings."""
    env = {**_REQUIRED_ENV, "CORS_ORIGIN": "not-a-url"}
    with patch.dict(os.environ, env, clear=True), pytest.raises(ValidationError):
        Settings()  # type: ignore[call-arg]


def test_cors_origin_rejects_url_with_path() -> None:
    """cors_origin rejects URLs with paths — Origin headers never include paths."""
    env = {**_REQUIRED_ENV, "CORS_ORIGIN": "https://example.com/app"}
    with patch.dict(os.environ, env, clear=True), pytest.raises(ValidationError):
        Settings()  # type: ignore[call-arg]


def test_cors_origin_strips_trailing_slash() -> None:
    """cors_origin_str strips trailing slash for CORS matching."""
    env = {**_REQUIRED_ENV, "CORS_ORIGIN": "http://localhost:3000/"}
    with patch.dict(os.environ, env, clear=True):
        s = Settings()  # type: ignore[call-arg]
    assert s.cors_origin_str == "http://localhost:3000"


# --- enable_docs ---


def test_enable_docs_default_none() -> None:
    """enable_docs defaults to None when not set."""
    env = _REQUIRED_ENV.copy()
    with patch.dict(os.environ, env, clear=True):
        s = Settings()  # type: ignore[call-arg]
    assert s.enable_docs is None


def test_enable_docs_true() -> None:
    """enable_docs=true produces True."""
    env = {**_REQUIRED_ENV, "ENABLE_DOCS": "true"}
    with patch.dict(os.environ, env, clear=True):
        s = Settings()  # type: ignore[call-arg]
    assert s.enable_docs is True


def test_enable_docs_false() -> None:
    """enable_docs=false produces False."""
    env = {**_REQUIRED_ENV, "ENABLE_DOCS": "false"}
    with patch.dict(os.environ, env, clear=True):
        s = Settings()  # type: ignore[call-arg]
    assert s.enable_docs is False


# --- session config fields ---


def test_session_secure_cookie_default_true() -> None:
    """session_secure_cookie defaults to True."""
    env = _REQUIRED_ENV.copy()
    with patch.dict(os.environ, env, clear=True):
        s = Settings()  # type: ignore[call-arg]
    assert s.session_secure_cookie is True


def test_max_sessions_per_user_default_five() -> None:
    """max_sessions_per_user defaults to 5."""
    env = _REQUIRED_ENV.copy()
    with patch.dict(os.environ, env, clear=True):
        s = Settings()  # type: ignore[call-arg]
    assert s.max_sessions_per_user == 5


def test_session_db_path_default() -> None:
    """session_db_path defaults to 'data/sessions.db'."""
    env = _REQUIRED_ENV.copy()
    with patch.dict(os.environ, env, clear=True):
        s = Settings()  # type: ignore[call-arg]
    assert s.session_db_path == "data/sessions.db"


# --- SESSION_SECRET blocklist ---


def test_blocklist_rejects_changeme_in_production() -> None:
    """SESSION_SECRET containing 'changeme' is rejected when not in debug."""
    env = {
        "JELLYFIN_URL": "http://jellyfin:8096",
        "SESSION_SECRET": "changeme" * 5,  # meets min_length
        "LOG_LEVEL": "info",
    }
    with patch.dict(os.environ, env, clear=True), pytest.raises(ValidationError):
        Settings()  # type: ignore[call-arg]


def test_blocklist_rejects_repeated_chars_in_production() -> None:
    """SESSION_SECRET of repeated characters is rejected when not in debug."""
    env = {
        "JELLYFIN_URL": "http://jellyfin:8096",
        "SESSION_SECRET": "a" * 32,
        "LOG_LEVEL": "info",
    }
    with patch.dict(os.environ, env, clear=True), pytest.raises(ValidationError):
        Settings()  # type: ignore[call-arg]


def test_blocklist_allows_weak_secret_in_debug(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """In debug mode, blocklisted secrets log CRITICAL but don't raise."""
    import logging

    env = {
        "JELLYFIN_URL": "http://jellyfin:8096",
        "SESSION_SECRET": "changeme" * 5,
        "LOG_LEVEL": "debug",
    }
    with patch.dict(os.environ, env, clear=True), caplog.at_level(logging.CRITICAL):
        s = Settings()  # type: ignore[call-arg]
    assert s.session_secret == "changeme" * 5
    assert any("SESSION_SECRET" in r.message for r in caplog.records)


def test_blocklist_accepts_strong_secret() -> None:
    """A strong random secret passes validation."""
    env = {
        "JELLYFIN_URL": "http://jellyfin:8096",
        "SESSION_SECRET": "kG7xP2mN9qR4wL8jT3vF6yA5dH0sE1cB",
        "LOG_LEVEL": "info",
    }
    with patch.dict(os.environ, env, clear=True):
        s = Settings()  # type: ignore[call-arg]
    assert len(s.session_secret) >= 32


# --- permission cache config ---


def test_permission_cache_ttl_default() -> None:
    """permission_cache_ttl_seconds defaults to 300."""
    env = _REQUIRED_ENV.copy()
    with patch.dict(os.environ, env, clear=True):
        s = Settings()  # type: ignore[call-arg]
    assert s.permission_cache_ttl_seconds == 300


def test_permission_cache_ttl_env_override() -> None:
    """PERMISSION_CACHE_TTL_SECONDS env var overrides default."""
    env = {**_REQUIRED_ENV, "PERMISSION_CACHE_TTL_SECONDS": "60"}
    with patch.dict(os.environ, env, clear=True):
        s = Settings()  # type: ignore[call-arg]
    assert s.permission_cache_ttl_seconds == 60


# --- library sync config ---


def test_library_sync_page_size_default() -> None:
    """library_sync_page_size defaults to 200."""
    env = _REQUIRED_ENV.copy()
    with patch.dict(os.environ, env, clear=True):
        s = Settings()  # type: ignore[call-arg]
    assert s.library_sync_page_size == 200


def test_library_db_path_default() -> None:
    """library_db_path defaults to 'data/library.db'."""
    env = _REQUIRED_ENV.copy()
    with patch.dict(os.environ, env, clear=True):
        s = Settings()  # type: ignore[call-arg]
    assert s.library_db_path == "data/library.db"


# --- jellyfin_api_key ---


def test_jellyfin_api_key_default_none() -> None:
    """jellyfin_api_key defaults to None when env var not set."""
    env = _REQUIRED_ENV.copy()
    with patch.dict(os.environ, env, clear=True):
        s = Settings()  # type: ignore[call-arg]
    assert s.jellyfin_api_key is None


def test_jellyfin_api_key_valid_value() -> None:
    """Valid JELLYFIN_API_KEY is stored as SecretStr in settings."""
    env = {**_REQUIRED_ENV, "JELLYFIN_API_KEY": "my-api-key-123"}
    with patch.dict(os.environ, env, clear=True):
        s = Settings()  # type: ignore[call-arg]
    assert s.jellyfin_api_key is not None
    assert s.jellyfin_api_key.get_secret_value() == "my-api-key-123"


def test_jellyfin_api_key_empty_treated_as_none() -> None:
    """Empty string JELLYFIN_API_KEY is treated as None."""
    env = {**_REQUIRED_ENV, "JELLYFIN_API_KEY": ""}
    with patch.dict(os.environ, env, clear=True):
        s = Settings()  # type: ignore[call-arg]
    assert s.jellyfin_api_key is None


def test_jellyfin_api_key_whitespace_treated_as_none() -> None:
    """Whitespace-only JELLYFIN_API_KEY is treated as None."""
    env = {**_REQUIRED_ENV, "JELLYFIN_API_KEY": "   "}
    with patch.dict(os.environ, env, clear=True):
        s = Settings()  # type: ignore[call-arg]
    assert s.jellyfin_api_key is None


def test_jellyfin_api_key_whitespace_stripped() -> None:
    """JELLYFIN_API_KEY with leading/trailing whitespace is stripped."""
    env = {**_REQUIRED_ENV, "JELLYFIN_API_KEY": "  key123  "}
    with patch.dict(os.environ, env, clear=True):
        s = Settings()  # type: ignore[call-arg]
    assert s.jellyfin_api_key is not None
    assert s.jellyfin_api_key.get_secret_value() == "key123"


# --- sync engine config ---


def test_jellyfin_admin_user_id_default_none() -> None:
    """jellyfin_admin_user_id defaults to None when not set."""
    env = _REQUIRED_ENV.copy()
    with patch.dict(os.environ, env, clear=True):
        s = Settings()  # type: ignore[call-arg]
    assert s.jellyfin_admin_user_id is None


def test_sync_interval_hours_default() -> None:
    """sync_interval_hours defaults to 6.0."""
    env = _REQUIRED_ENV.copy()
    with patch.dict(os.environ, env, clear=True):
        s = Settings()  # type: ignore[call-arg]
    assert s.sync_interval_hours == 6.0


def test_tombstone_ttl_days_default() -> None:
    """tombstone_ttl_days defaults to 7."""
    env = _REQUIRED_ENV.copy()
    with patch.dict(os.environ, env, clear=True):
        s = Settings()  # type: ignore[call-arg]
    assert s.tombstone_ttl_days == 7


def test_wal_checkpoint_threshold_mb_default() -> None:
    """wal_checkpoint_threshold_mb defaults to 50.0."""
    env = _REQUIRED_ENV.copy()
    with patch.dict(os.environ, env, clear=True):
        s = Settings()  # type: ignore[call-arg]
    assert s.wal_checkpoint_threshold_mb == 50.0


# --- embedding worker config ---


def test_embedding_batch_size_default() -> None:
    """embedding_batch_size defaults to 10."""
    env = _REQUIRED_ENV.copy()
    with patch.dict(os.environ, env, clear=True):
        s = Settings()  # type: ignore[call-arg]
    assert s.embedding_batch_size == 10


def test_embedding_worker_interval_seconds_default() -> None:
    """embedding_worker_interval_seconds defaults to 300."""
    env = _REQUIRED_ENV.copy()
    with patch.dict(os.environ, env, clear=True):
        s = Settings()  # type: ignore[call-arg]
    assert s.embedding_worker_interval_seconds == 300


def test_embedding_max_retries_default() -> None:
    """embedding_max_retries defaults to 3."""
    env = _REQUIRED_ENV.copy()
    with patch.dict(os.environ, env, clear=True):
        s = Settings()  # type: ignore[call-arg]
    assert s.embedding_max_retries == 3


def test_embedding_cooldown_seconds_default() -> None:
    """embedding_cooldown_seconds defaults to 300."""
    env = _REQUIRED_ENV.copy()
    with patch.dict(os.environ, env, clear=True):
        s = Settings()  # type: ignore[call-arg]
    assert s.embedding_cooldown_seconds == 300


def test_embedding_batch_size_env_override() -> None:
    """EMBEDDING_BATCH_SIZE env var overrides default."""
    env = {**_REQUIRED_ENV, "EMBEDDING_BATCH_SIZE": "25"}
    with patch.dict(os.environ, env, clear=True):
        s = Settings()  # type: ignore[call-arg]
    assert s.embedding_batch_size == 25


def test_embedding_batch_size_rejects_zero() -> None:
    """embedding_batch_size must be >= 1."""
    env = {**_REQUIRED_ENV, "EMBEDDING_BATCH_SIZE": "0"}
    with patch.dict(os.environ, env, clear=True), pytest.raises(ValidationError):
        Settings()  # type: ignore[call-arg]


def test_embedding_batch_size_rejects_over_50() -> None:
    """embedding_batch_size must be <= 50."""
    env = {**_REQUIRED_ENV, "EMBEDDING_BATCH_SIZE": "51"}
    with patch.dict(os.environ, env, clear=True), pytest.raises(ValidationError):
        Settings()  # type: ignore[call-arg]


def test_sync_engine_config_from_env() -> None:
    """All sync engine config fields loaded from environment variables."""
    env = {
        **_REQUIRED_ENV,
        "JELLYFIN_ADMIN_USER_ID": "abc-123-admin",
        "SYNC_INTERVAL_HOURS": "12.0",
        "TOMBSTONE_TTL_DAYS": "14",
        "WAL_CHECKPOINT_THRESHOLD_MB": "100.0",
    }
    with patch.dict(os.environ, env, clear=True):
        s = Settings()  # type: ignore[call-arg]
    assert s.jellyfin_admin_user_id == "abc-123-admin"
    assert s.sync_interval_hours == 12.0
    assert s.tombstone_ttl_days == 14
    assert s.wal_checkpoint_threshold_mb == 100.0
