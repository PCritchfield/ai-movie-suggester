"""Unit tests for the Ollama chat client (mock httpx)."""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest

from app.chat.models import StructuredChatResponse
from app.ollama.chat_client import OllamaChatClient
from app.ollama.errors import (
    OllamaConnectionError,
    OllamaError,
    OllamaModelError,
    OllamaStreamError,
    OllamaStructuredOutputError,
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


def _make_stream_response(lines: list[str], status_code: int = 200) -> Any:
    """Create a mock async context manager that yields lines."""

    class _FakeStream:
        def __init__(self) -> None:
            self.status_code = status_code

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

    async def test_chat_client_model_not_found(
        self, chat_client: OllamaChatClient, mock_http: AsyncMock
    ) -> None:
        """404 from Ollama raises OllamaModelError."""
        from app.ollama.errors import OllamaModelError

        mock_http.stream = _make_stream_response([], status_code=404)

        with pytest.raises(OllamaModelError, match="not found"):
            async for _ in chat_client.chat_stream([{"role": "user", "content": "Hi"}]):
                pass  # pragma: no cover

    async def test_chat_client_server_error(
        self, chat_client: OllamaChatClient, mock_http: AsyncMock
    ) -> None:
        """Non-2xx from Ollama raises OllamaError."""
        from app.ollama.errors import OllamaError

        mock_http.stream = _make_stream_response([], status_code=500)

        with pytest.raises(OllamaError, match="Unexpected response"):
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
# chat_structured() — Spec 27 grammar-constrained structured output
# ---------------------------------------------------------------------------


def _valid_payload_content() -> str:
    """A schema-valid structured response, as Ollama returns it (JSON string)."""
    return json.dumps(
        {
            "introductory_message": "Here are a couple of picks for you.",
            "recommendations": [
                {"jellyfin_id": "abc123", "reasoning": "Spooky and atmospheric."},
                {"jellyfin_id": "def456", "reasoning": "A funnier take on the theme."},
            ],
        }
    )


def _structured_response(content: str, status_code: int = 200) -> httpx.Response:
    """Build a non-streaming /api/chat response carrying `content`."""
    return httpx.Response(
        status_code,
        json={"message": {"role": "assistant", "content": content}, "done": True},
        request=_FAKE_REQUEST,
    )


class TestChatStructured:
    async def test_sends_format_schema_stream_false_and_temperature_zero(
        self, chat_client: OllamaChatClient, mock_http: AsyncMock
    ) -> None:
        """The request constrains decoding: format=schema, stream=False, temp=0."""
        mock_http.post.return_value = _structured_response(_valid_payload_content())

        await chat_client.chat_structured(
            [{"role": "user", "content": "something spooky"}],
            StructuredChatResponse,
        )

        sent = mock_http.post.call_args.kwargs["json"]
        assert sent["model"] == "llama3.1:8b"
        assert sent["messages"] == [{"role": "user", "content": "something spooky"}]
        assert sent["stream"] is False
        assert sent["format"] == StructuredChatResponse.model_json_schema()
        assert sent["options"]["temperature"] == 0

    async def test_posts_to_chat_endpoint(
        self, chat_client: OllamaChatClient, mock_http: AsyncMock
    ) -> None:
        mock_http.post.return_value = _structured_response(_valid_payload_content())
        await chat_client.chat_structured(
            [{"role": "user", "content": "hi"}], StructuredChatResponse
        )
        assert mock_http.post.call_args.args[0] == "http://ollama:11434/api/chat"

    async def test_parses_valid_payload_into_model(
        self, chat_client: OllamaChatClient, mock_http: AsyncMock
    ) -> None:
        mock_http.post.return_value = _structured_response(_valid_payload_content())

        result = await chat_client.chat_structured(
            [{"role": "user", "content": "hi"}], StructuredChatResponse
        )

        assert isinstance(result, StructuredChatResponse)
        assert [r.jellyfin_id for r in result.recommendations] == ["abc123", "def456"]
        assert result.introductory_message == "Here are a couple of picks for you."

    async def test_invalid_json_raises_structured_output_error(
        self, chat_client: OllamaChatClient, mock_http: AsyncMock
    ) -> None:
        mock_http.post.return_value = _structured_response("not valid json {")

        with pytest.raises(OllamaStructuredOutputError):
            await chat_client.chat_structured(
                [{"role": "user", "content": "hi"}], StructuredChatResponse
            )

    async def test_schema_violation_raises_structured_output_error(
        self, chat_client: OllamaChatClient, mock_http: AsyncMock
    ) -> None:
        """Valid JSON, wrong shape (missing required reasoning) → structured error."""
        bad = json.dumps({"recommendations": [{"jellyfin_id": "abc123"}]})
        mock_http.post.return_value = _structured_response(bad)

        with pytest.raises(OllamaStructuredOutputError):
            await chat_client.chat_structured(
                [{"role": "user", "content": "hi"}], StructuredChatResponse
            )

    async def test_unexpected_response_shape_raises_structured_output_error(
        self, chat_client: OllamaChatClient, mock_http: AsyncMock
    ) -> None:
        """Response missing message.content → structured error, not a crash."""
        mock_http.post.return_value = httpx.Response(
            200, json={"unexpected": "shape"}, request=_FAKE_REQUEST
        )

        with pytest.raises(OllamaStructuredOutputError):
            await chat_client.chat_structured(
                [{"role": "user", "content": "hi"}], StructuredChatResponse
            )

    async def test_non_string_content_raises_structured_output_error(
        self, chat_client: OllamaChatClient, mock_http: AsyncMock
    ) -> None:
        """A non-string message.content (already-parsed object) maps to a typed
        structured-output error, not an uncaught TypeError."""
        mock_http.post.return_value = httpx.Response(
            200,
            json={"message": {"role": "assistant", "content": {"already": "parsed"}}},
            request=_FAKE_REQUEST,
        )

        with pytest.raises(OllamaStructuredOutputError):
            await chat_client.chat_structured(
                [{"role": "user", "content": "hi"}], StructuredChatResponse
            )

    async def test_timeout_raises_ollama_timeout_error(
        self, chat_client: OllamaChatClient, mock_http: AsyncMock
    ) -> None:
        mock_http.post.side_effect = httpx.ReadTimeout("Read timed out")
        with pytest.raises(OllamaTimeoutError):
            await chat_client.chat_structured(
                [{"role": "user", "content": "hi"}], StructuredChatResponse
            )

    async def test_connection_error_raises_ollama_connection_error(
        self, chat_client: OllamaChatClient, mock_http: AsyncMock
    ) -> None:
        mock_http.post.side_effect = httpx.ConnectError("Connection refused")
        with pytest.raises(OllamaConnectionError):
            await chat_client.chat_structured(
                [{"role": "user", "content": "hi"}], StructuredChatResponse
            )

    async def test_404_raises_model_error(
        self, chat_client: OllamaChatClient, mock_http: AsyncMock
    ) -> None:
        mock_http.post.return_value = httpx.Response(
            404, text="not found", request=_FAKE_REQUEST
        )
        with pytest.raises(OllamaModelError, match="not found"):
            await chat_client.chat_structured(
                [{"role": "user", "content": "hi"}], StructuredChatResponse
            )

    async def test_server_error_raises_ollama_error(
        self, chat_client: OllamaChatClient, mock_http: AsyncMock
    ) -> None:
        mock_http.post.return_value = httpx.Response(
            500, text="boom", request=_FAKE_REQUEST
        )
        with pytest.raises(OllamaError, match="Unexpected response"):
            await chat_client.chat_structured(
                [{"role": "user", "content": "hi"}], StructuredChatResponse
            )

    async def test_does_not_log_response_payload(
        self,
        chat_client: OllamaChatClient,
        mock_http: AsyncMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """No log record at any level may contain the model's reasoning text."""
        secret_marker = "ATMOSPHERIC_SECRET_REASONING_TEXT"
        content = json.dumps(
            {
                "introductory_message": None,
                "recommendations": [
                    {"jellyfin_id": "abc123", "reasoning": secret_marker}
                ],
            }
        )
        mock_http.post.return_value = _structured_response(content)

        with caplog.at_level(logging.DEBUG):
            await chat_client.chat_structured(
                [{"role": "user", "content": "hi"}], StructuredChatResponse
            )

        assert all(secret_marker not in rec.getMessage() for rec in caplog.records)


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
