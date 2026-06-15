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
from typing import TYPE_CHECKING, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

from app.ollama.errors import (
    OllamaConnectionError,
    OllamaError,
    OllamaModelError,
    OllamaStreamError,
    OllamaStructuredOutputError,
    OllamaTimeoutError,
)

logger = logging.getLogger(__name__)

_StructuredT = TypeVar("_StructuredT", bound=BaseModel)


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

    async def chat_stream(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        """Stream chat tokens from Ollama.

        POSTs to ``{base_url}/api/chat`` with ``stream: true``.
        Yields individual content tokens as strings.
        Does NOT yield empty content on the final ``done: true`` line.

        Raises:
            OllamaTimeoutError: Ollama did not respond in time.
            OllamaConnectionError: Ollama is unreachable.
            OllamaModelError: The requested model is not available (404).
            OllamaError: Any other non-2xx response.
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
                if response.status_code == 404:
                    raise OllamaModelError(
                        f"Model '{self._chat_model}' not found on Ollama"
                    )
                if response.status_code >= 400:
                    raise OllamaError(
                        f"Unexpected response from Ollama: {response.status_code}"
                    )
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

    async def chat_structured(
        self,
        messages: list[dict[str, str]],
        response_model: type[_StructuredT],
    ) -> _StructuredT:
        """Request a grammar-constrained structured response from Ollama.

        POSTs to ``{base_url}/api/chat`` with ``stream: false``, the JSON
        schema derived from ``response_model`` as ``format`` (constraining the
        decoder to that shape), and ``temperature: 0`` for deterministic output.
        Parses the model's ``message.content`` into ``response_model``.

        Generic over the response model so this transport layer stays free of
        any chat-domain coupling — the caller owns the schema.

        Returns:
            An instance of ``response_model`` validated from the response.

        Raises:
            OllamaTimeoutError: Ollama did not respond in time.
            OllamaConnectionError: Ollama is unreachable.
            OllamaModelError: The requested model is not available (404).
            OllamaError: Any other non-2xx response.
            OllamaStructuredOutputError: Content was not valid JSON, did not
                match the schema, or the response shape was unexpected. The raw
                content is never included in the error message.
        """
        try:
            response = await self._client.post(
                f"{self._base_url}/api/chat",
                json={
                    "model": self._chat_model,
                    "messages": messages,
                    "stream": False,
                    "format": response_model.model_json_schema(),
                    "options": {"temperature": 0},
                },
            )
        except httpx.TimeoutException as exc:
            raise OllamaTimeoutError(
                f"Ollama chat request timed out at {self._base_url}"
            ) from exc
        except httpx.TransportError as exc:
            raise OllamaConnectionError(
                f"Cannot reach Ollama at {self._base_url}"
            ) from exc

        if response.status_code == 404:
            raise OllamaModelError(f"Model '{self._chat_model}' not found on Ollama")
        if response.status_code >= 400:
            raise OllamaError(
                f"Unexpected response from Ollama: {response.status_code}"
            )

        try:
            content = response.json()["message"]["content"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise OllamaStructuredOutputError(
                "Unexpected response shape from Ollama chat API"
            ) from exc

        # message.content is expected to be a JSON string. Guard against a
        # non-string (e.g. an already-parsed object) so it maps to a typed
        # structured-output error rather than an uncaught TypeError.
        if not isinstance(content, str):
            raise OllamaStructuredOutputError(
                "Ollama chat response content was not a JSON string"
            )

        try:
            return response_model.model_validate_json(content)
        except (ValidationError, TypeError) as exc:
            raise OllamaStructuredOutputError(
                "Ollama returned content that did not match the requested schema"
            ) from exc
