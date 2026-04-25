"""Ollama API client package."""

from __future__ import annotations

from app.ollama.client import OllamaEmbeddingClient
from app.ollama.errors import (
    OllamaConnectionError,
    OllamaError,
    OllamaModelError,
    OllamaTimeoutError,
)
from app.ollama.models import EmbeddingResult
from app.ollama.text_builder import TEMPLATE_VERSION, build_sections

__all__ = [
    "EmbeddingResult",
    "OllamaConnectionError",
    "OllamaEmbeddingClient",
    "OllamaError",
    "OllamaModelError",
    "OllamaTimeoutError",
    "TEMPLATE_VERSION",
    "build_sections",
]
