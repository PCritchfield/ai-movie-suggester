# backend/tests/test_ollama_embed_batch.py
"""Unit tests for OllamaEmbeddingClient.embed_batch() (mock httpx)."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock

import httpx
import pytest

from app.ollama.client import OllamaEmbeddingClient
from app.ollama.errors import (
    OllamaConnectionError,
    OllamaError,
    OllamaModelError,
    OllamaTimeoutError,
)
from app.ollama.models import EmbeddingResult

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_FAKE_REQUEST = httpx.Request("POST", "http://fake")


@pytest.fixture
def mock_http() -> AsyncMock:
    """Mock httpx.AsyncClient for unit tests."""
    return AsyncMock(spec=httpx.AsyncClient)


@pytest.fixture
def ollama_client(mock_http: AsyncMock) -> OllamaEmbeddingClient:
    return OllamaEmbeddingClient(
        base_url="http://ollama:11434",
        http_client=mock_http,
        embed_model="nomic-embed-text",
        health_timeout=5.0,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_vector(seed: float, dims: int = 768) -> list[float]:
    """Create a deterministic vector from a seed value."""
    return [seed + i * 0.001 for i in range(dims)]


# ---------------------------------------------------------------------------
# embed_batch() — success cases
# ---------------------------------------------------------------------------


class TestEmbedBatchSuccess:
    async def test_batch_returns_correct_count(
        self, ollama_client: OllamaEmbeddingClient, mock_http: AsyncMock
    ) -> None:
        """embed_batch with 3 texts returns 3 EmbeddingResult objects."""
        vectors = [_make_vector(1.0), _make_vector(2.0), _make_vector(3.0)]
        mock_http.post.return_value = httpx.Response(
            200,
            json={"embeddings": vectors, "model": "nomic-embed-text"},
            request=_FAKE_REQUEST,
        )
        results = await ollama_client.embed_batch(["text-a", "text-b", "text-c"])
        assert len(results) == 3
        assert all(isinstance(r, EmbeddingResult) for r in results)

    async def test_batch_dimensions_correct(
        self, ollama_client: OllamaEmbeddingClient, mock_http: AsyncMock
    ) -> None:
        """Each EmbeddingResult has correct dimensions."""
        vectors = [_make_vector(1.0), _make_vector(2.0), _make_vector(3.0)]
        mock_http.post.return_value = httpx.Response(
            200,
            json={"embeddings": vectors, "model": "nomic-embed-text"},
            request=_FAKE_REQUEST,
        )
        results = await ollama_client.embed_batch(["a", "b", "c"])
        for result in results:
            assert result.dimensions == 768
            assert len(result.vector) == 768
            assert result.model == "nomic-embed-text"

    async def test_batch_positional_mapping(
        self, ollama_client: OllamaEmbeddingClient, mock_http: AsyncMock
    ) -> None:
        """First text maps to first vector, second to second, etc."""
        vec_a = _make_vector(1.0)
        vec_b = _make_vector(2.0)
        vec_c = _make_vector(3.0)
        mock_http.post.return_value = httpx.Response(
            200,
            json={"embeddings": [vec_a, vec_b, vec_c], "model": "nomic-embed-text"},
            request=_FAKE_REQUEST,
        )
        results = await ollama_client.embed_batch(["text-a", "text-b", "text-c"])
        assert results[0].vector == vec_a
        assert results[1].vector == vec_b
        assert results[2].vector == vec_c

    async def test_batch_sends_correct_json_body(
        self, ollama_client: OllamaEmbeddingClient, mock_http: AsyncMock
    ) -> None:
        """embed_batch sends input as a list (not a string)."""
        vectors = [_make_vector(1.0), _make_vector(2.0)]
        mock_http.post.return_value = httpx.Response(
            200,
            json={"embeddings": vectors, "model": "nomic-embed-text"},
            request=_FAKE_REQUEST,
        )
        await ollama_client.embed_batch(["hello", "world"])
        call_args = mock_http.post.call_args
        assert call_args.kwargs["json"] == {
            "model": "nomic-embed-text",
            "input": ["hello", "world"],
        }

    async def test_batch_posts_correct_url(
        self, ollama_client: OllamaEmbeddingClient, mock_http: AsyncMock
    ) -> None:
        """embed_batch POSTs to /api/embed."""
        vectors = [_make_vector(1.0)]
        mock_http.post.return_value = httpx.Response(
            200,
            json={"embeddings": vectors, "model": "nomic-embed-text"},
            request=_FAKE_REQUEST,
        )
        await ollama_client.embed_batch(["text"])
        call_args = mock_http.post.call_args
        assert call_args.args[0] == "http://ollama:11434/api/embed"


# ---------------------------------------------------------------------------
# embed_batch() — edge cases
# ---------------------------------------------------------------------------


class TestEmbedBatchEdgeCases:
    async def test_empty_input_returns_empty_list(
        self, ollama_client: OllamaEmbeddingClient, mock_http: AsyncMock
    ) -> None:
        """Empty texts list returns [] without making an HTTP call."""
        results = await ollama_client.embed_batch([])
        assert results == []
        mock_http.post.assert_not_called()

    async def test_fewer_vectors_than_texts_raises(
        self, ollama_client: OllamaEmbeddingClient, mock_http: AsyncMock
    ) -> None:
        """Ollama returning fewer vectors than input texts raises OllamaError."""
        mock_http.post.return_value = httpx.Response(
            200,
            json={
                "embeddings": [_make_vector(1.0)],  # Only 1 vector for 3 inputs
                "model": "nomic-embed-text",
            },
            request=_FAKE_REQUEST,
        )
        with pytest.raises(OllamaError, match="returned 1 embeddings for 3 inputs"):
            await ollama_client.embed_batch(["a", "b", "c"])

    async def test_mixed_dimensions_in_batch_preserved(
        self, ollama_client: OllamaEmbeddingClient, mock_http: AsyncMock
    ) -> None:
        """embed_batch preserves per-vector dimensions without enforcing uniformity.

        Each EmbeddingResult records its own len(vector) as dimensions.
        The caller (worker) is responsible for checking expected dimensions.
        """
        # One 768-dim vector and one 3-dim vector — both valid individually
        mock_http.post.return_value = httpx.Response(
            200,
            json={
                "embeddings": [
                    _make_vector(1.0, 768),
                    [0.1, 0.2, 0.3],  # Wrong dimensions — still valid at construction
                ],
                "model": "nomic-embed-text",
            },
            request=_FAKE_REQUEST,
        )
        # This should succeed because EmbeddingResult sets dimensions=len(vector)
        # dynamically — the validator checks consistency, and here they are consistent.
        # The dimension mismatch would be caught by the caller that knows the
        # expected dimensions. This test verifies the two vectors are correctly
        # created with their respective dimension counts.
        results = await ollama_client.embed_batch(["a", "b"])
        assert results[0].dimensions == 768
        assert results[1].dimensions == 3


# ---------------------------------------------------------------------------
# embed_batch() — error wrapping
# ---------------------------------------------------------------------------


class TestEmbedBatchErrors:
    async def test_timeout_raises_ollama_timeout_error(
        self, ollama_client: OllamaEmbeddingClient, mock_http: AsyncMock
    ) -> None:
        """httpx.TimeoutException → OllamaTimeoutError."""
        mock_http.post.side_effect = httpx.ReadTimeout("Read timed out")
        with pytest.raises(OllamaTimeoutError):
            await ollama_client.embed_batch(["text"])

    async def test_connection_error_raises_ollama_connection_error(
        self, ollama_client: OllamaEmbeddingClient, mock_http: AsyncMock
    ) -> None:
        """httpx.TransportError → OllamaConnectionError."""
        mock_http.post.side_effect = httpx.ConnectError("Connection refused")
        with pytest.raises(OllamaConnectionError):
            await ollama_client.embed_batch(["text"])

    async def test_404_raises_ollama_model_error(
        self, ollama_client: OllamaEmbeddingClient, mock_http: AsyncMock
    ) -> None:
        """404 → OllamaModelError."""
        mock_http.post.return_value = httpx.Response(
            404,
            json={"error": "model 'nomic-embed-text' not found"},
            request=_FAKE_REQUEST,
        )
        with pytest.raises(OllamaModelError):
            await ollama_client.embed_batch(["text"])

    async def test_500_raises_ollama_error(
        self, ollama_client: OllamaEmbeddingClient, mock_http: AsyncMock
    ) -> None:
        """Non-2xx (500) → OllamaError."""
        mock_http.post.return_value = httpx.Response(
            500,
            text="Internal Server Error",
            request=_FAKE_REQUEST,
        )
        with pytest.raises(OllamaError):
            await ollama_client.embed_batch(["text"])

    async def test_invalid_response_shape_raises_ollama_error(
        self, ollama_client: OllamaEmbeddingClient, mock_http: AsyncMock
    ) -> None:
        """Malformed response body raises OllamaError."""
        mock_http.post.return_value = httpx.Response(
            200,
            json={"unexpected": "shape"},
            request=_FAKE_REQUEST,
        )
        with pytest.raises(OllamaError, match="Invalid response shape"):
            await ollama_client.embed_batch(["text"])


# ---------------------------------------------------------------------------
# embed_batch() — error sanitization
# ---------------------------------------------------------------------------


class TestEmbedBatchSanitization:
    """Ensure raw Ollama response text never leaks into exception messages."""

    _OLLAMA_BODY = "OLLAMA_RAW_RESPONSE_BODY_SHOULD_NOT_APPEAR"

    async def test_connection_error_sanitized(
        self, ollama_client: OllamaEmbeddingClient, mock_http: AsyncMock
    ) -> None:
        mock_http.post.side_effect = httpx.ConnectError(self._OLLAMA_BODY)
        with pytest.raises(OllamaConnectionError) as exc_info:
            await ollama_client.embed_batch(["test"])
        assert self._OLLAMA_BODY not in str(exc_info.value)

    async def test_timeout_error_sanitized(
        self, ollama_client: OllamaEmbeddingClient, mock_http: AsyncMock
    ) -> None:
        mock_http.post.side_effect = httpx.ReadTimeout(self._OLLAMA_BODY)
        with pytest.raises(OllamaTimeoutError) as exc_info:
            await ollama_client.embed_batch(["test"])
        assert self._OLLAMA_BODY not in str(exc_info.value)

    async def test_model_error_sanitized(
        self, ollama_client: OllamaEmbeddingClient, mock_http: AsyncMock
    ) -> None:
        mock_http.post.return_value = httpx.Response(
            404,
            text=self._OLLAMA_BODY,
            request=_FAKE_REQUEST,
        )
        with pytest.raises(OllamaModelError) as exc_info:
            await ollama_client.embed_batch(["test"])
        assert self._OLLAMA_BODY not in str(exc_info.value)

    async def test_generic_error_sanitized(
        self, ollama_client: OllamaEmbeddingClient, mock_http: AsyncMock
    ) -> None:
        mock_http.post.return_value = httpx.Response(
            500,
            text=self._OLLAMA_BODY,
            request=_FAKE_REQUEST,
        )
        with pytest.raises(OllamaError) as exc_info:
            await ollama_client.embed_batch(["test"])
        assert self._OLLAMA_BODY not in str(exc_info.value)


# ---------------------------------------------------------------------------
# embed_batch() — logging
# ---------------------------------------------------------------------------


class TestEmbedBatchLogging:
    async def test_info_log_contains_count_and_elapsed(
        self,
        ollama_client: OllamaEmbeddingClient,
        mock_http: AsyncMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        vectors = [_make_vector(1.0), _make_vector(2.0)]
        mock_http.post.return_value = httpx.Response(
            200,
            json={"embeddings": vectors, "model": "nomic-embed-text"},
            request=_FAKE_REQUEST,
        )
        with caplog.at_level(logging.INFO, logger="app.ollama.client"):
            await ollama_client.embed_batch(["text-a", "text-b"])

        info_records = [r for r in caplog.records if r.levelno == logging.INFO]
        assert len(info_records) >= 1
        info_msg = info_records[0].message
        assert "count=" in info_msg
        assert "elapsed_ms=" in info_msg
