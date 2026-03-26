"""Async HTTP client for the Ollama embedding API.

Uses an injected httpx.AsyncClient for connection pooling and testability.
The Ollama client uses a SEPARATE httpx instance from JellyfinClient with
its own timeout configuration (120s for embeddings vs 10s for Jellyfin).

Network Trust Assumption:
    Ollama is assumed to be a trusted, network-local service. This client:
    - Does NOT verify TLS certificates (Ollama typically runs on HTTP).
    - Does NOT authenticate (Ollama has no auth by default).
    - DOES sanitize error messages (never forwards raw response bodies).
    - Does NOT log response bodies at INFO level.
    If Ollama is exposed over an untrusted network, the operator is
    responsible for TLS termination and access control at the network level.
"""

from __future__ import annotations

import logging
import time

import httpx

from app.ollama.errors import (
    OllamaConnectionError,
    OllamaError,
    OllamaModelError,
    OllamaTimeoutError,
)
from app.ollama.models import EmbeddingResult

logger = logging.getLogger(__name__)


class OllamaEmbeddingClient:
    """Async client for the Ollama embedding API.

    Stateless and fire-and-forget — no retry logic. The caller
    (background sync worker) owns retry and queue orchestration.

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
        embed_model: str = "nomic-embed-text",
        health_timeout: float = 5.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = http_client
        self._embed_model = embed_model
        self._health_timeout = health_timeout

    async def embed(self, text: str) -> EmbeddingResult:
        """Generate an embedding vector for the given text.

        POSTs to ``{base_url}/api/embed`` with the configured model.
        Returns an :class:`EmbeddingResult` containing the vector,
        its dimensionality, and the model name.

        Raises:
            OllamaTimeoutError: Ollama did not respond in time.
            OllamaConnectionError: Ollama is unreachable.
            OllamaModelError: The requested model is not available (404).
            OllamaError: Any other non-2xx response.
        """
        logger.debug("ollama_embed input_preview=%.100s", text)

        t0 = time.perf_counter()
        try:
            resp = await self._client.post(
                f"{self._base_url}/api/embed",
                json={"model": self._embed_model, "input": text},
            )
        except httpx.TimeoutException as exc:
            raise OllamaTimeoutError(
                f"Ollama embedding request timed out at {self._base_url}"
            ) from exc
        except httpx.TransportError as exc:
            raise OllamaConnectionError(
                f"Cannot reach Ollama at {self._base_url}"
            ) from exc

        if resp.status_code == 404:
            raise OllamaModelError(f"Model '{self._embed_model}' not found on Ollama")

        if resp.status_code >= 400:
            raise OllamaError(f"Unexpected response from Ollama: {resp.status_code}")

        try:
            data = resp.json()
            vector = data["embeddings"][0]
        except Exception as exc:
            raise OllamaError(
                "Invalid response shape from Ollama embedding API"
            ) from exc

        elapsed_ms = (time.perf_counter() - t0) * 1000
        dims = len(vector)
        logger.info("ollama_embed dims=%d elapsed_ms=%.0f", dims, elapsed_ms)

        return EmbeddingResult(
            vector=vector,
            dimensions=dims,
            model=self._embed_model,
        )

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
