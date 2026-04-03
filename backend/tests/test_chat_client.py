"""Unit tests for the Ollama chat client (mock httpx)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.ollama.chat_client import OllamaChatClient
from app.ollama.errors import (
    OllamaConnectionError,
    OllamaError,
    OllamaStreamError,
    OllamaTimeoutError,
)
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
def chat_client(mock_http: AsyncMock) -> OllamaChatClient:
    return OllamaChatClient(
        base_url="http://ollama:11434",
        http_client=mock_http,
        chat_model="llama3.1:8b",
        health_timeout=5.0,
    )


# ---------------------------------------------------------------------------
# Helpers for streaming mock
# ---------------------------------------------------------------------------


def _make_stream_response(lines: list[str]) -> MagicMock:
    """Create a mock async context manager that yields lines."""

    class _FakeStream:
        async def aiter_lines(self):
            for line in lines:
                yield line

    stream = _FakeStream()

    @asynccontextmanager
    async def _stream_ctx(*args, **kwargs):
        yield stream

    return _stream_ctx


# ---------------------------------------------------------------------------
# Error hierarchy
# ---------------------------------------------------------------------------


class TestStreamErrorHierarchy:
    def test_stream_error_is_ollama_error(self) -> None:
        assert issubclass(OllamaStreamError, OllamaError)

    def test_stream_error_message(self) -> None:
        err = OllamaStreamError("Stream broke")
        assert str(err) == "Stream broke"


# ---------------------------------------------------------------------------
# health()
# ---------------------------------------------------------------------------


class TestChatHealth:
    async def test_chat_client_health_true(
        self, chat_client: OllamaChatClient, mock_http: AsyncMock
    ) -> None:
        mock_http.get.return_value = httpx.Response(
            200,
            text="Ollama is running",
            request=httpx.Request("GET", "http://fake"),
        )
        result = await chat_client.health()
        assert result is True

    async def test_chat_client_health_false(
        self, chat_client: OllamaChatClient, mock_http: AsyncMock
    ) -> None:
        mock_http.get.side_effect = httpx.ConnectError("Connection refused")
        result = await chat_client.health()
        assert result is False

    async def test_chat_client_health_false_on_500(
        self, chat_client: OllamaChatClient, mock_http: AsyncMock
    ) -> None:
        mock_http.get.return_value = httpx.Response(
            500,
            text="Internal Server Error",
            request=httpx.Request("GET", "http://fake"),
        )
        result = await chat_client.health()
        assert result is False

    async def test_health_passes_timeout_kwarg(
        self, chat_client: OllamaChatClient, mock_http: AsyncMock
    ) -> None:
        mock_http.get.return_value = httpx.Response(
            200,
            text="Ollama is running",
            request=httpx.Request("GET", "http://fake"),
        )
        await chat_client.health()
        call_args = mock_http.get.call_args
        assert call_args.kwargs["timeout"] == 5.0

    async def test_health_uses_correct_url(
        self, chat_client: OllamaChatClient, mock_http: AsyncMock
    ) -> None:
        mock_http.get.return_value = httpx.Response(
            200,
            text="Ollama is running",
            request=httpx.Request("GET", "http://fake"),
        )
        await chat_client.health()
        call_args = mock_http.get.call_args
        assert call_args.args[0] == "http://ollama:11434/"


# ---------------------------------------------------------------------------
# chat_stream()
# ---------------------------------------------------------------------------


class TestChatStream:
    async def test_chat_client_streams_tokens(
        self, chat_client: OllamaChatClient, mock_http: AsyncMock
    ) -> None:
        """Mock streaming response, assert tokens yielded, empty on done skipped."""
        lines = [
            '{"message": {"role": "assistant", "content": "Hello"}, "done": false}',
            '{"message": {"role": "assistant", "content": " world"}, "done": false}',
            '{"message": {"role": "assistant", "content": ""}, "done": true}',
        ]
        mock_http.stream = _make_stream_response(lines)

        tokens = []
        async for token in chat_client.chat_stream([{"role": "user", "content": "Hi"}]):
            tokens.append(token)

        assert tokens == ["Hello", " world"]

    async def test_chat_client_does_not_yield_empty_on_done(
        self, chat_client: OllamaChatClient, mock_http: AsyncMock
    ) -> None:
        """Ensure empty content on done:true is not yielded."""
        lines = [
            '{"message": {"role": "assistant", "content": "A"}, "done": false}',
            '{"message": {"role": "assistant", "content": ""}, "done": true}',
        ]
        mock_http.stream = _make_stream_response(lines)

        tokens = []
        async for token in chat_client.chat_stream(
            [{"role": "user", "content": "test"}]
        ):
            tokens.append(token)

        assert tokens == ["A"]
        assert "" not in tokens

    async def test_chat_client_connection_error(
        self, chat_client: OllamaChatClient, mock_http: AsyncMock
    ) -> None:
        """Assert OllamaConnectionError raised when Ollama unreachable."""

        @asynccontextmanager
        async def _raise_connect(*args, **kwargs):
            raise httpx.ConnectError("Connection refused")
            yield  # pragma: no cover  # noqa: E711, RUF028

        mock_http.stream = _raise_connect

        with pytest.raises(OllamaConnectionError):
            async for _ in chat_client.chat_stream([{"role": "user", "content": "Hi"}]):
                pass  # pragma: no cover

    async def test_chat_client_timeout(
        self, chat_client: OllamaChatClient, mock_http: AsyncMock
    ) -> None:
        """Assert OllamaTimeoutError raised on read timeout."""

        @asynccontextmanager
        async def _raise_timeout(*args, **kwargs):
            raise httpx.ReadTimeout("Read timed out")
            yield  # pragma: no cover  # noqa: E711, RUF028

        mock_http.stream = _raise_timeout

        with pytest.raises(OllamaTimeoutError):
            async for _ in chat_client.chat_stream([{"role": "user", "content": "Hi"}]):
                pass  # pragma: no cover

    async def test_chat_client_malformed_json(
        self, chat_client: OllamaChatClient, mock_http: AsyncMock
    ) -> None:
        """Malformed JSON in stream raises OllamaStreamError."""
        lines = ["not valid json at all"]
        mock_http.stream = _make_stream_response(lines)

        with pytest.raises(OllamaStreamError, match="Malformed JSON"):
            async for _ in chat_client.chat_stream([{"role": "user", "content": "Hi"}]):
                pass  # pragma: no cover

    async def test_chat_client_unexpected_shape(
        self, chat_client: OllamaChatClient, mock_http: AsyncMock
    ) -> None:
        """Unexpected response shape raises OllamaStreamError."""
        lines = ['{"unexpected": "shape"}']
        mock_http.stream = _make_stream_response(lines)

        with pytest.raises(OllamaStreamError, match="Unexpected response shape"):
            async for _ in chat_client.chat_stream([{"role": "user", "content": "Hi"}]):
                pass  # pragma: no cover

    async def test_base_url_trailing_slash_stripped(self, mock_http: AsyncMock) -> None:
        client = OllamaChatClient(
            base_url="http://ollama:11434/",
            http_client=mock_http,
            chat_model="llama3.1:8b",
        )
        assert client._base_url == "http://ollama:11434"


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class TestConfigChatFields:
    def test_default_batch_size(self) -> None:
        settings = make_test_settings()
        assert settings.embedding_batch_size == 5

    def test_chat_system_prompt_default_none(self) -> None:
        settings = make_test_settings()
        assert settings.chat_system_prompt is None
