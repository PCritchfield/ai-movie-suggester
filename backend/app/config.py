"""Application settings — loaded from environment / .env file.

All configuration is centralized here. No ad-hoc os.environ calls elsewhere.
"""

from __future__ import annotations

import logging
from typing import Annotated, Literal

from pydantic import AnyHttpUrl, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Required
    jellyfin_url: str
    jellyfin_timeout: float = 10.0
    session_secret: Annotated[str, Field(min_length=32)]

    # Ollama
    ollama_host: str = "http://ollama:11434"
    ollama_chat_model: str = "llama3.1:8b"
    ollama_embed_model: str = "nomic-embed-text"
    ollama_embed_dimensions: int = 768
    ollama_embed_timeout: int = 120
    ollama_health_timeout: int = 5

    # Optional: TMDb
    tmdb_enabled: bool = False
    tmdb_api_key: str | None = None

    @model_validator(mode="after")
    def _validate_tmdb(self) -> Settings:
        if self.tmdb_enabled and not self.tmdb_api_key:
            msg = "TMDB_API_KEY is required when TMDB_ENABLED=true"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _validate_session_secret(self) -> Settings:
        """Reject known-weak SESSION_SECRET values."""
        secret = self.session_secret
        _blocklist_patterns = ("changeme", "password", "secret", "example")
        is_weak = len(set(secret)) <= 2 or any(
            pat in secret.lower() for pat in _blocklist_patterns
        )
        if is_weak:
            if self.log_level == "debug":
                _logger.critical(
                    "SESSION_SECRET matches a blocklist pattern — "
                    "acceptable ONLY in debug mode"
                )
            else:
                msg = (
                    "SESSION_SECRET is too weak (matches a known pattern). "
                    "Generate a strong secret with: openssl rand -hex 32"
                )
                raise ValueError(msg)
        return self

    # Library (shared by LibraryItemStore + SqliteVecRepository)
    library_db_path: str = "data/library.db"

    # Sessions
    session_secure_cookie: bool = True
    max_sessions_per_user: int = 5
    session_db_path: str = "data/sessions.db"
    trusted_proxy_ips: str = "127.0.0.1"
    login_rate_limit: str = "5/minute"

    # Security
    cors_origin: AnyHttpUrl = AnyHttpUrl("http://localhost:3000")
    enable_docs: bool | None = None

    # Library sync
    jellyfin_api_key: SecretStr | None = None
    library_db_path: str = "data/library.db"
    library_sync_page_size: int = 200

    # Sync engine
    jellyfin_admin_user_id: str | None = None
    sync_interval_hours: float = 6.0
    tombstone_ttl_days: int = 7
    wal_checkpoint_threshold_mb: float = 50.0

    @model_validator(mode="after")
    def _validate_jellyfin_api_key(self) -> Settings:
        """Strip whitespace from API key; treat empty/whitespace-only as None."""
        if self.jellyfin_api_key is not None:
            stripped = self.jellyfin_api_key.get_secret_value().strip()
            if not stripped:
                _logger.warning(
                    "JELLYFIN_API_KEY is empty/whitespace-only — treating as unset"
                )
                self.jellyfin_api_key = None
            elif stripped != self.jellyfin_api_key.get_secret_value():
                self.jellyfin_api_key = SecretStr(stripped)
        return self

    # Tuning
    log_level: Literal["debug", "info", "warning", "error", "critical"] = "info"
    session_expiry_hours: int = 24
    chat_rate_limit: int = 10

    @model_validator(mode="after")
    def _validate_cors_origin(self) -> Settings:
        """Reject CORS origins with paths, query strings, or fragments.

        Browser Origin headers never include a path — allowing one would
        silently break CORS matching.
        """
        from urllib.parse import urlparse

        parsed = urlparse(str(self.cors_origin))
        # AnyHttpUrl always adds a trailing slash, so "/" is the "no path" case
        if parsed.path not in ("", "/"):
            msg = (
                "CORS_ORIGIN must be an origin (scheme + host + optional port), "
                f"not a URL with a path: {self.cors_origin}"
            )
            raise ValueError(msg)
        if parsed.query or parsed.fragment:
            msg = (
                "CORS_ORIGIN must not include query string or fragment: "
                f"{self.cors_origin}"
            )
            raise ValueError(msg)
        return self

    @property
    def cors_origin_str(self) -> str:
        """Return cors_origin as a plain string with trailing slash stripped."""
        return str(self.cors_origin).rstrip("/")
