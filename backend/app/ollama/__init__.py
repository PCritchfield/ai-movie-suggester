"""Ollama API client package."""

from __future__ import annotations

from app.ollama.client import OllamaEmbeddingClient
from app.ollama.errors import (
    OllamaConnectionError,
    OllamaError,
    OllamaModelError,
    OllamaTimeoutError,
)
from app.ollama.models import EmbeddingResult, EmbeddingSource

__all__ = [
    "EmbeddingResult",
    "EmbeddingSource",
    "OllamaConnectionError",
    "OllamaEmbeddingClient",
    "OllamaError",
    "OllamaModelError",
    "OllamaTimeoutError",
]
