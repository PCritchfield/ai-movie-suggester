"""Async HTTP client for the Ollama chat (streaming) API.

Uses an injected httpx.AsyncClient for connection pooling and testability.
The chat client uses a SEPARATE httpx instance from the embedding client
with its own timeout configuration (300s read for LLM generation).

Network Trust Assumption:
    Same as OllamaEmbeddingClient — see client.py docstring.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

from app.ollama.errors import (
    OllamaConnectionError,
    OllamaStreamError,
    OllamaTimeoutError,
)

logger = logging.getLogger(__name__)


class OllamaChatClient:
    """Async streaming client for the Ollama chat API.

    Stateless and fire-and-forget — no retry logic. The caller
    (ChatService) owns orchestration and error handling.

    Network Trust Assumption:
        Ollama is assumed to be a trusted, network-local service.
        No TLS verification or authentication is performed. Error
        messages are sanitized — raw response bodies are never
        forwarded in exceptions.
    """

    def __init__(
        self,
        base_url: str,
        http_client: httpx.AsyncClient,
        chat_model: str,
        health_timeout: float = 5.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = http_client
        self._chat_model = chat_model
        self._health_timeout = health_timeout

    async def health(self) -> bool:
        """Check if Ollama is reachable.

        GETs ``{base_url}/`` with a short timeout override.
        Returns ``True`` on HTTP 200, ``False`` on any error.
        Never raises.
        """
        try:
            resp = await self._client.get(
                f"{self._base_url}/",
                timeout=self._health_timeout,
            )
            return resp.status_code == 200
        except Exception:
            return False

    async def chat_stream(
        self, messages: list[dict[str, str]]
    ) -> AsyncIterator[str]:
        """Stream chat tokens from Ollama.

        POSTs to ``{base_url}/api/chat`` with ``stream: true``.
        Yields individual content tokens as strings.
        Does NOT yield empty content on the final ``done: true`` line.

        Raises:
            OllamaTimeoutError: Ollama did not respond in time.
            OllamaConnectionError: Ollama is unreachable.
            OllamaStreamError: Malformed JSON or unexpected response shape.
        """
        try:
            async with self._client.stream(
                "POST",
                f"{self._base_url}/api/chat",
                json={
                    "model": self._chat_model,
                    "messages": messages,
                    "stream": True,
                },
            ) as response:
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise OllamaStreamError(
                            "Malformed JSON in Ollama streaming response"
                        ) from exc

                    try:
                        done = data["done"]
                        content = data["message"]["content"]
                    except (KeyError, TypeError) as exc:
                        raise OllamaStreamError(
                            "Unexpected response shape from Ollama chat API"
                        ) from exc

                    if done:
                        return
                    if content:
                        yield content
        except httpx.TimeoutException as exc:
            raise OllamaTimeoutError(
                f"Ollama chat request timed out at {self._base_url}"
            ) from exc
        except httpx.TransportError as exc:
            raise OllamaConnectionError(
                f"Cannot reach Ollama at {self._base_url}"
            ) from exc
