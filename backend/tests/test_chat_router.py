"""Tests for the chat API endpoint (Spec 12, Task 3.0)."""

from __future__ import annotations

import json
import time
from typing import Any
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.auth.crypto import derive_keys
from app.auth.dependencies import get_current_session
from app.auth.models import SessionMeta
from app.chat.conversation_store import ConversationStore
from app.chat.router import create_chat_router
from app.middleware.rate_limit import create_limiter
from tests.conftest import TEST_SECRET, make_test_settings

_COOKIE_KEY, _ = derive_keys(TEST_SECRET)
_SESSION_ID = "test-session-id-chat"
_USER_ID = "uid-chat-1"


def _make_session_meta() -> SessionMeta:
    return SessionMeta(
        session_id=_SESSION_ID,
        user_id=_USER_ID,
        username="chatter",
        server_name="TestJellyfin",
        expires_at=int(time.time()) + 3600,
    )


def _make_chat_app(
    *,
    session_store: Any = None,
    chat_service: Any = None,
    settings: Any = None,
    with_auth: bool = True,
) -> tuple[FastAPI, TestClient]:
    settings = settings or make_test_settings()

    app = FastAPI()
    app.state.cookie_key = _COOKIE_KEY
    app.state.session_store = session_store or AsyncMock()
    app.state.settings = settings
    app.state.limiter = None

    # Chat service mock
    app.state.chat_service = chat_service or AsyncMock()

    # Conversation store (real, in-memory)
    app.state.conversation_store = ConversationStore(
        max_turns=10, ttl_seconds=7200, max_sessions=100
    )

    chat_router = create_chat_router(settings=settings, limiter=None)
    app.include_router(chat_router)

    if with_auth:

        async def _mock_session() -> SessionMeta:
            return _make_session_meta()

        app.dependency_overrides[get_current_session] = _mock_session

    return app, TestClient(app)


def _parse_sse_events(body: str) -> list[dict]:
    """Parse SSE response body into list of event dicts."""
    events = []
    for line in body.strip().split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    return events


# ---------------------------------------------------------------------------
# Helper to make an async generator from a list of events
# ---------------------------------------------------------------------------


def _make_stream_mock(events: list[dict]) -> AsyncMock:
    """Create a mock chat_service.stream that yields events."""
    service = AsyncMock()

    async def _stream(*args, **kwargs):
        for event in events:
            yield event

    service.stream = _stream
    return service


# ---------------------------------------------------------------------------
# Auth tests
# ---------------------------------------------------------------------------


class TestChatRequiresAuth:
    def test_unauthenticated_returns_401(self) -> None:
        _, client = _make_chat_app(with_auth=False)
        resp = client.post("/api/chat", json={"message": "test"})
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


class TestChatRateLimit:
    def test_exceeding_rate_limit_returns_429(self) -> None:
        """Requests beyond chat_rate_limit/minute return 429."""
        settings = make_test_settings(chat_rate_limit="2/minute")
        limiter = create_limiter()

        session_store = AsyncMock()
        session_store.get_token = AsyncMock(return_value="jf-token")

        events = [
            {
                "type": "metadata",
                "version": 1,
                "recommendations": [],
                "search_status": "ok",
            },
            {"type": "text", "content": "Hi"},
            {"type": "done"},
        ]
        service = _make_stream_mock(events)

        app = FastAPI()
        app.state.cookie_key = _COOKIE_KEY
        app.state.session_store = session_store
        app.state.settings = settings
        app.state.limiter = limiter
        app.state.chat_service = service

        chat_router = create_chat_router(settings=settings, limiter=limiter)
        app.include_router(chat_router)

        app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]

        async def _mock_session() -> SessionMeta:
            return _make_session_meta()

        app.dependency_overrides[get_current_session] = _mock_session

        client = TestClient(app)

        # First two requests should succeed (limit=2/minute)
        resp1 = client.post("/api/chat", json={"message": "one"})
        assert resp1.status_code == 200
        resp2 = client.post("/api/chat", json={"message": "two"})
        assert resp2.status_code == 200

        # Third should be rate limited
        resp3 = client.post("/api/chat", json={"message": "three"})
        assert resp3.status_code == 429


# ---------------------------------------------------------------------------
# Validation tests
# ---------------------------------------------------------------------------


class TestChatValidation:
    def test_empty_message_returns_422(self) -> None:
        _, client = _make_chat_app()
        resp = client.post("/api/chat", json={"message": ""})
        assert resp.status_code == 422

    def test_too_long_message_returns_422(self) -> None:
        _, client = _make_chat_app()
        resp = client.post("/api/chat", json={"message": "x" * 1001})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# SSE streaming tests
# ---------------------------------------------------------------------------


class TestChatStreamsSSE:
    def test_chat_endpoint_streams_sse(self) -> None:
        """Full happy path: metadata, text, done."""
        events_to_yield = [
            {
                "type": "metadata",
                "version": 1,
                "recommendations": [
                    {
                        "jellyfin_id": "jf-001",
                        "title": "Galaxy Quest",
                        "overview": "A comedy.",
                        "genres": ["Comedy"],
                        "year": 1999,
                        "score": 0.8,
                        "poster_url": "/Items/jf-001/Images/Primary",
                    }
                ],
                "search_status": "ok",
            },
            {"type": "text", "content": "Try "},
            {"type": "text", "content": "Galaxy Quest!"},
            {"type": "done"},
        ]

        session_store = AsyncMock()
        session_store.get_token = AsyncMock(return_value="jf-token")

        service = _make_stream_mock(events_to_yield)

        _, client = _make_chat_app(
            session_store=session_store,
            chat_service=service,
        )

        resp = client.post("/api/chat", json={"message": "funny space"})
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]

        parsed = _parse_sse_events(resp.text)
        assert len(parsed) == 4
        assert parsed[0]["type"] == "metadata"
        assert parsed[1]["type"] == "text"
        assert parsed[2]["type"] == "text"
        assert parsed[3]["type"] == "done"

    def test_chat_endpoint_metadata_first(self) -> None:
        """First SSE event is metadata with recommendations."""
        events_to_yield = [
            {
                "type": "metadata",
                "version": 1,
                "recommendations": [],
                "search_status": "no_embeddings",
            },
            {"type": "text", "content": "Hi"},
            {"type": "done"},
        ]

        session_store = AsyncMock()
        session_store.get_token = AsyncMock(return_value="jf-token")
        service = _make_stream_mock(events_to_yield)

        _, client = _make_chat_app(
            session_store=session_store,
            chat_service=service,
        )

        resp = client.post("/api/chat", json={"message": "test"})
        parsed = _parse_sse_events(resp.text)
        assert parsed[0]["type"] == "metadata"
        assert "recommendations" in parsed[0]
        assert "search_status" in parsed[0]

    def test_chat_endpoint_no_results(self) -> None:
        """Empty recommendations still work, LLM responds."""
        events_to_yield = [
            {
                "type": "metadata",
                "version": 1,
                "recommendations": [],
                "search_status": "no_embeddings",
            },
            {"type": "text", "content": "No movies found"},
            {"type": "done"},
        ]

        session_store = AsyncMock()
        session_store.get_token = AsyncMock(return_value="jf-token")
        service = _make_stream_mock(events_to_yield)

        _, client = _make_chat_app(
            session_store=session_store,
            chat_service=service,
        )

        resp = client.post("/api/chat", json={"message": "anything?"})
        parsed = _parse_sse_events(resp.text)
        assert parsed[0]["type"] == "metadata"
        assert parsed[0]["recommendations"] == []
        assert parsed[-1]["type"] == "done"

    def test_chat_endpoint_mid_stream_error(self) -> None:
        """SSE error event when Ollama disconnects mid-generation."""
        events_to_yield = [
            {
                "type": "metadata",
                "version": 1,
                "recommendations": [],
                "search_status": "ok",
            },
            {"type": "text", "content": "Starting..."},
            {
                "type": "error",
                "code": "ollama_unavailable",
                "message": (
                    "The AI service became unavailable. "
                    "Your recommendations are shown above."
                ),
            },
        ]

        session_store = AsyncMock()
        session_store.get_token = AsyncMock(return_value="jf-token")
        service = _make_stream_mock(events_to_yield)

        _, client = _make_chat_app(
            session_store=session_store,
            chat_service=service,
        )

        resp = client.post("/api/chat", json={"message": "test"})
        parsed = _parse_sse_events(resp.text)
        error_events = [e for e in parsed if e["type"] == "error"]
        assert len(error_events) == 1
        assert error_events[0]["code"] == "ollama_unavailable"

    def test_chat_endpoint_generation_timeout(self) -> None:
        """SSE error event with generation_timeout code."""
        events_to_yield = [
            {
                "type": "metadata",
                "version": 1,
                "recommendations": [],
                "search_status": "ok",
            },
            {"type": "text", "content": "Starting..."},
            {
                "type": "error",
                "code": "generation_timeout",
                "message": (
                    "The response took too long to generate. "
                    "Your recommendations are shown above."
                ),
            },
        ]

        session_store = AsyncMock()
        session_store.get_token = AsyncMock(return_value="jf-token")
        service = _make_stream_mock(events_to_yield)

        _, client = _make_chat_app(
            session_store=session_store,
            chat_service=service,
        )

        resp = client.post("/api/chat", json={"message": "test"})
        parsed = _parse_sse_events(resp.text)
        error_events = [e for e in parsed if e["type"] == "error"]
        assert len(error_events) == 1
        assert error_events[0]["code"] == "generation_timeout"

    def test_chat_endpoint_partial_embeddings(self) -> None:
        """Metadata event has search_status partial_embeddings."""
        events_to_yield = [
            {
                "type": "metadata",
                "version": 1,
                "recommendations": [
                    {
                        "jellyfin_id": "jf-001",
                        "title": "Galaxy Quest",
                        "overview": "A comedy.",
                        "genres": ["Comedy"],
                        "year": 1999,
                        "score": 0.8,
                        "poster_url": "/Items/jf-001/Images/Primary",
                    }
                ],
                "search_status": "partial_embeddings",
            },
            {"type": "text", "content": "Try Galaxy Quest!"},
            {"type": "done"},
        ]

        session_store = AsyncMock()
        session_store.get_token = AsyncMock(return_value="jf-token")
        service = _make_stream_mock(events_to_yield)

        _, client = _make_chat_app(
            session_store=session_store,
            chat_service=service,
        )

        resp = client.post("/api/chat", json={"message": "funny"})
        parsed = _parse_sse_events(resp.text)
        assert parsed[0]["search_status"] == "partial_embeddings"
        text_events = [e for e in parsed if e["type"] == "text"]
        assert len(text_events) >= 1

    def test_chat_endpoint_stream_event_format(self) -> None:
        """All SSE events are valid JSON with expected type field."""
        events_to_yield = [
            {
                "type": "metadata",
                "version": 1,
                "recommendations": [],
                "search_status": "ok",
            },
            {"type": "text", "content": "Hello"},
            {"type": "done"},
        ]

        session_store = AsyncMock()
        session_store.get_token = AsyncMock(return_value="jf-token")
        service = _make_stream_mock(events_to_yield)

        _, client = _make_chat_app(
            session_store=session_store,
            chat_service=service,
        )

        resp = client.post("/api/chat", json={"message": "test"})
        parsed = _parse_sse_events(resp.text)

        # Every event has a "type" key
        for event in parsed:
            assert "type" in event

        # Metadata event has version: 1
        assert parsed[0]["version"] == 1

        # Text events have content key
        text_events = [e for e in parsed if e["type"] == "text"]
        for te in text_events:
            assert "content" in te

        # Done event has only "type" key
        done_events = [e for e in parsed if e["type"] == "done"]
        assert len(done_events) == 1
        assert set(done_events[0].keys()) == {"type"}


# ---------------------------------------------------------------------------
# DELETE /api/chat/history tests
# ---------------------------------------------------------------------------


class TestDeleteChatHistory:
    def test_delete_chat_history(self) -> None:
        """DELETE clears conversation, next message starts fresh."""
        session_store = AsyncMock()
        session_store.get_token = AsyncMock(return_value="jf-token")

        events = [
            {
                "type": "metadata",
                "version": 1,
                "recommendations": [],
                "search_status": "ok",
                "turn_count": 1,
            },
            {"type": "text", "content": "Hi"},
            {"type": "done"},
        ]
        service = _make_stream_mock(events)

        app, client = _make_chat_app(
            session_store=session_store,
            chat_service=service,
        )

        # Add some turns to the store
        app.state.conversation_store.add_turn(_SESSION_ID, "user", "hello")
        app.state.conversation_store.add_turn(_SESSION_ID, "assistant", "hi")
        assert app.state.conversation_store.turn_count(_SESSION_ID) == 2

        # DELETE should clear
        resp = client.delete("/api/chat/history")
        assert resp.status_code == 204
        assert app.state.conversation_store.turn_count(_SESSION_ID) == 0

    def test_delete_chat_history_requires_auth(self) -> None:
        """Unauthenticated DELETE returns 401."""
        _, client = _make_chat_app(with_auth=False)
        resp = client.delete("/api/chat/history")
        assert resp.status_code == 401

    def test_delete_chat_history_idempotent(self) -> None:
        """DELETE with no conversation returns 204. Twice returns 204."""
        _, client = _make_chat_app()
        resp1 = client.delete("/api/chat/history")
        assert resp1.status_code == 204
        resp2 = client.delete("/api/chat/history")
        assert resp2.status_code == 204


# ---------------------------------------------------------------------------
# Session cascade tests
# ---------------------------------------------------------------------------


class TestSessionCascade:
    def test_session_destroy_purges_conversation(self) -> None:
        """purge_session removes conversation."""
        store = ConversationStore(max_turns=10, ttl_seconds=7200, max_sessions=100)
        store.add_turn("session-1", "user", "hello")
        store.add_turn("session-1", "assistant", "hi")
        assert store.turn_count("session-1") == 2

        store.purge_session("session-1")
        assert store.turn_count("session-1") == 0
        assert store.get_turns("session-1") == []
