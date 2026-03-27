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
from app.ollama.text_builder import (
    TEMPLATE_VERSION,
    CompositeTextResult,
    build_composite_text,
)

__all__ = [
    "CompositeTextResult",
    "EmbeddingResult",
    "EmbeddingSource",
    "OllamaConnectionError",
    "OllamaEmbeddingClient",
    "OllamaError",
    "OllamaModelError",
    "OllamaTimeoutError",
    "TEMPLATE_VERSION",
    "build_composite_text",
]
