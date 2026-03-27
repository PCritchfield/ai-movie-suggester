# backend/tests/test_ollama_client.py
"""Unit tests for the Ollama embedding client (mock httpx)."""

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
from app.ollama.models import EmbeddingResult, EmbeddingSource
from tests.conftest import make_test_settings

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
# Error hierarchy
# ---------------------------------------------------------------------------


class TestErrorHierarchy:
    def test_connection_error_is_ollama_error(self) -> None:
        assert issubclass(OllamaConnectionError, OllamaError)

    def test_timeout_error_is_ollama_error(self) -> None:
        assert issubclass(OllamaTimeoutError, OllamaError)

    def test_model_error_is_ollama_error(self) -> None:
        assert issubclass(OllamaModelError, OllamaError)

    def test_ollama_error_is_exception(self) -> None:
        assert issubclass(OllamaError, Exception)

    def test_connection_error_message(self) -> None:
        err = OllamaConnectionError("Connection refused")
        assert str(err) == "Connection refused"

    def test_timeout_error_message(self) -> None:
        err = OllamaTimeoutError("Request timed out")
        assert str(err) == "Request timed out"

    def test_model_error_message(self) -> None:
        err = OllamaModelError("Model not found")
        assert str(err) == "Model not found"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class TestEmbeddingResult:
    def test_construction(self) -> None:
        result = EmbeddingResult(
            vector=[0.1, 0.2, 0.3],
            dimensions=3,
            model="nomic-embed-text",
        )
        assert result.vector == [0.1, 0.2, 0.3]
        assert result.dimensions == 3
        assert result.model == "nomic-embed-text"

    def test_dimensions_field(self) -> None:
        result = EmbeddingResult(vector=[1.0] * 768, dimensions=768, model="test")
        assert result.dimensions == 768

    def test_model_field(self) -> None:
        result = EmbeddingResult(vector=[0.0], dimensions=1, model="custom-model")
        assert result.model == "custom-model"


class TestEmbeddingSource:
    def test_jellyfin_only_value(self) -> None:
        assert EmbeddingSource.JELLYFIN_ONLY == "jellyfin_only"
        assert EmbeddingSource.JELLYFIN_ONLY.value == "jellyfin_only"

    def test_tmdb_enriched_value(self) -> None:
        assert EmbeddingSource.TMDB_ENRICHED == "tmdb_enriched"
        assert EmbeddingSource.TMDB_ENRICHED.value == "tmdb_enriched"


# ---------------------------------------------------------------------------
# embed()
# ---------------------------------------------------------------------------


class TestEmbed:
    async def test_embed_success(
        self, ollama_client: OllamaEmbeddingClient, mock_http: AsyncMock
    ) -> None:
        mock_http.post.return_value = httpx.Response(
            200,
            json={
                "embeddings": [[0.1, 0.2, 0.3] * 256],
                "model": "nomic-embed-text",
            },
            request=_FAKE_REQUEST,
        )
        result = await ollama_client.embed("Test text")
        assert isinstance(result, EmbeddingResult)
        assert result.dimensions == 768
        assert len(result.vector) == 768
        assert result.model == "nomic-embed-text"

    async def test_embed_connection_error(
        self, ollama_client: OllamaEmbeddingClient, mock_http: AsyncMock
    ) -> None:
        mock_http.post.side_effect = httpx.ConnectError("Connection refused")
        with pytest.raises(OllamaConnectionError):
            await ollama_client.embed("Test text")

    async def test_embed_timeout_error(
        self, ollama_client: OllamaEmbeddingClient, mock_http: AsyncMock
    ) -> None:
        mock_http.post.side_effect = httpx.ReadTimeout("Read timed out")
        with pytest.raises(OllamaTimeoutError):
            await ollama_client.embed("Test text")

    async def test_embed_model_not_found(
        self, ollama_client: OllamaEmbeddingClient, mock_http: AsyncMock
    ) -> None:
        mock_http.post.return_value = httpx.Response(
            404,
            json={"error": "model 'nomic-embed-text' not found"},
            request=_FAKE_REQUEST,
        )
        with pytest.raises(OllamaModelError):
            await ollama_client.embed("Test text")

    async def test_embed_server_error(
        self, ollama_client: OllamaEmbeddingClient, mock_http: AsyncMock
    ) -> None:
        mock_http.post.return_value = httpx.Response(
            500,
            text="Internal Server Error",
            request=_FAKE_REQUEST,
        )
        with pytest.raises(OllamaError):
            await ollama_client.embed("Test text")

    async def test_embed_posts_correct_url(
        self, ollama_client: OllamaEmbeddingClient, mock_http: AsyncMock
    ) -> None:
        mock_http.post.return_value = httpx.Response(
            200,
            json={"embeddings": [[0.1, 0.2]], "model": "nomic-embed-text"},
            request=_FAKE_REQUEST,
        )
        await ollama_client.embed("Test text")
        call_args = mock_http.post.call_args
        assert call_args.args[0] == "http://ollama:11434/api/embed"

    async def test_embed_sends_correct_json_body(
        self, ollama_client: OllamaEmbeddingClient, mock_http: AsyncMock
    ) -> None:
        mock_http.post.return_value = httpx.Response(
            200,
            json={"embeddings": [[0.1, 0.2]], "model": "nomic-embed-text"},
            request=_FAKE_REQUEST,
        )
        await ollama_client.embed("Hello world")
        call_args = mock_http.post.call_args
        assert call_args.kwargs["json"] == {
            "model": "nomic-embed-text",
            "input": "Hello world",
        }

    async def test_embed_base_url_trailing_slash_stripped(
        self, mock_http: AsyncMock
    ) -> None:
        client = OllamaEmbeddingClient(
            base_url="http://ollama:11434/",
            http_client=mock_http,
        )
        assert client._base_url == "http://ollama:11434"

    async def test_embed_invalid_response_shape(
        self, ollama_client: OllamaEmbeddingClient, mock_http: AsyncMock
    ) -> None:
        """Malformed response body raises OllamaError, not a crash."""
        mock_http.post.return_value = httpx.Response(
            200,
            json={"unexpected": "shape"},
            request=_FAKE_REQUEST,
        )
        with pytest.raises(OllamaError, match="Invalid response shape"):
            await ollama_client.embed("Test text")


# ---------------------------------------------------------------------------
# health()
# ---------------------------------------------------------------------------


class TestHealth:
    async def test_health_returns_true_on_200(
        self, ollama_client: OllamaEmbeddingClient, mock_http: AsyncMock
    ) -> None:
        mock_http.get.return_value = httpx.Response(
            200,
            text="Ollama is running",
            request=httpx.Request("GET", "http://fake"),
        )
        result = await ollama_client.health()
        assert result is True

    async def test_health_returns_false_on_connect_error(
        self, ollama_client: OllamaEmbeddingClient, mock_http: AsyncMock
    ) -> None:
        mock_http.get.side_effect = httpx.ConnectError("Connection refused")
        result = await ollama_client.health()
        assert result is False

    async def test_health_returns_false_on_timeout(
        self, ollama_client: OllamaEmbeddingClient, mock_http: AsyncMock
    ) -> None:
        mock_http.get.side_effect = httpx.ReadTimeout("Read timed out")
        result = await ollama_client.health()
        assert result is False

    async def test_health_returns_false_on_500(
        self, ollama_client: OllamaEmbeddingClient, mock_http: AsyncMock
    ) -> None:
        mock_http.get.return_value = httpx.Response(
            500,
            text="Internal Server Error",
            request=httpx.Request("GET", "http://fake"),
        )
        result = await ollama_client.health()
        assert result is False

    async def test_health_passes_timeout_kwarg(
        self, ollama_client: OllamaEmbeddingClient, mock_http: AsyncMock
    ) -> None:
        mock_http.get.return_value = httpx.Response(
            200,
            text="Ollama is running",
            request=httpx.Request("GET", "http://fake"),
        )
        await ollama_client.health()
        call_args = mock_http.get.call_args
        assert call_args.kwargs["timeout"] == 5.0

    async def test_health_uses_correct_url(
        self, ollama_client: OllamaEmbeddingClient, mock_http: AsyncMock
    ) -> None:
        mock_http.get.return_value = httpx.Response(
            200,
            text="Ollama is running",
            request=httpx.Request("GET", "http://fake"),
        )
        await ollama_client.health()
        call_args = mock_http.get.call_args
        assert call_args.args[0] == "http://ollama:11434/"


# ---------------------------------------------------------------------------
# Error sanitization
# ---------------------------------------------------------------------------


class TestErrorSanitization:
    """Ensure raw Ollama response text never leaks into exception messages."""

    _OLLAMA_BODY = "OLLAMA_RAW_RESPONSE_BODY_SHOULD_NOT_APPEAR"

    async def test_connection_error_sanitized(
        self, ollama_client: OllamaEmbeddingClient, mock_http: AsyncMock
    ) -> None:
        mock_http.post.side_effect = httpx.ConnectError(self._OLLAMA_BODY)
        with pytest.raises(OllamaConnectionError) as exc_info:
            await ollama_client.embed("test")
        assert self._OLLAMA_BODY not in str(exc_info.value)

    async def test_timeout_error_sanitized(
        self, ollama_client: OllamaEmbeddingClient, mock_http: AsyncMock
    ) -> None:
        mock_http.post.side_effect = httpx.ReadTimeout(self._OLLAMA_BODY)
        with pytest.raises(OllamaTimeoutError) as exc_info:
            await ollama_client.embed("test")
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
            await ollama_client.embed("test")
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
            await ollama_client.embed("test")
        assert self._OLLAMA_BODY not in str(exc_info.value)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


class TestEmbedLogging:
    async def test_info_log_contains_dims_and_elapsed(
        self,
        ollama_client: OllamaEmbeddingClient,
        mock_http: AsyncMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        mock_http.post.return_value = httpx.Response(
            200,
            json={"embeddings": [[0.1, 0.2, 0.3]], "model": "nomic-embed-text"},
            request=_FAKE_REQUEST,
        )
        with caplog.at_level(logging.INFO, logger="app.ollama.client"):
            await ollama_client.embed("Test text for embedding")

        info_records = [r for r in caplog.records if r.levelno == logging.INFO]
        assert len(info_records) >= 1
        info_msg = info_records[0].message
        assert "dims=" in info_msg
        assert "elapsed_ms=" in info_msg
        # Input text must NOT appear at INFO
        assert "Test text for embedding" not in info_msg

    async def test_debug_log_contains_input_preview(
        self,
        ollama_client: OllamaEmbeddingClient,
        mock_http: AsyncMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        mock_http.post.return_value = httpx.Response(
            200,
            json={"embeddings": [[0.1, 0.2, 0.3]], "model": "nomic-embed-text"},
            request=_FAKE_REQUEST,
        )
        with caplog.at_level(logging.DEBUG, logger="app.ollama.client"):
            await ollama_client.embed("Test text for embedding")

        debug_records = [r for r in caplog.records if r.levelno == logging.DEBUG]
        assert len(debug_records) >= 1
        assert "Test text for embedding" in debug_records[0].message


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class TestConfigOllamaFields:
    def test_ollama_embed_timeout_default(self) -> None:
        settings = make_test_settings()
        assert settings.ollama_embed_timeout == 120

    def test_ollama_health_timeout_default(self) -> None:
        settings = make_test_settings()
        assert settings.ollama_health_timeout == 5


# ---------------------------------------------------------------------------
# Integration tests (skipped by default, require real Ollama)
# ---------------------------------------------------------------------------


@pytest.mark.ollama_integration
class TestOllamaIntegration:
    """Integration tests requiring a running Ollama instance."""

    async def test_embed_returns_768_dim_vector(self) -> None:
        async with httpx.AsyncClient(timeout=120) as http:
            client = OllamaEmbeddingClient(
                base_url="http://localhost:11434",
                http_client=http,
            )
            result = await client.embed("A test movie about space exploration")
        assert isinstance(result, EmbeddingResult)
        assert result.dimensions == 768
        assert len(result.vector) == 768

    async def test_health_returns_true(self) -> None:
        async with httpx.AsyncClient(timeout=120) as http:
            client = OllamaEmbeddingClient(
                base_url="http://localhost:11434",
                http_client=http,
            )
            assert await client.health() is True
