"""Ollama API client exceptions.

Mirrors the jellyfin/errors.py hierarchy. Error messages are always
sanitized application-level strings — raw Ollama response bodies are
NEVER forwarded in exception messages.
"""

from __future__ import annotations


class OllamaError(Exception):
    """Base exception for Ollama API errors."""


class OllamaConnectionError(OllamaError):
    """Cannot reach the Ollama server (transport-level failure)."""


class OllamaTimeoutError(OllamaError):
    """Ollama did not respond within the configured timeout."""


class OllamaModelError(OllamaError):
    """The requested model is not available (not pulled or not found)."""


class OllamaStreamError(OllamaError):
    """An error occurred during streaming response from Ollama."""


class OllamaStructuredOutputError(OllamaError):
    """A structured (non-streaming) response could not be parsed or validated.

    Raised when Ollama returns content that is not valid JSON or does not
    match the requested schema. The raw content is NEVER included in the
    message — it may echo user/chat text.
    """
