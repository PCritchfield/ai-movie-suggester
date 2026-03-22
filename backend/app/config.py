"""Application settings — loaded from environment / .env file.

All configuration is centralized here. No ad-hoc os.environ calls elsewhere.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # Optional: TMDb
    tmdb_enabled: bool = False
    tmdb_api_key: str | None = None

    @model_validator(mode="after")
    def _validate_tmdb(self) -> Settings:
        if self.tmdb_enabled and not self.tmdb_api_key:
            msg = "TMDB_API_KEY is required when TMDB_ENABLED=true"
            raise ValueError(msg)
        return self

    # Tuning
    log_level: Literal["debug", "info", "warning", "error", "critical"] = "info"
    session_expiry_hours: int = 24
    chat_rate_limit: int = 10
