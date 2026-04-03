"""Unit tests for ChatService orchestration (Spec 12, Task 3.0)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from app.chat.service import ChatService
from app.ollama.errors import OllamaConnectionError
from app.search.models import SearchResponse, SearchResultItem, SearchStatus
from tests.conftest import make_test_settings

# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _make_result(
    title: str = "Galaxy Quest",
    jid: str = "jf-001",
) -> SearchResultItem:
    return SearchResultItem(
        jellyfin_id=jid,
        title=title,
        overview="A comedy about sci-fi actors.",
        genres=["Comedy", "Sci-Fi"],
        year=1999,
        score=0.8,
        poster_url=f"/Items/{jid}/Images/Primary",
    )


def _make_search_response(
    results: list[SearchResultItem] | None = None,
    status: SearchStatus = SearchStatus.OK,
) -> SearchResponse:
    if results is None:
        results = [_make_result()]
    return SearchResponse(
        status=status,
        results=results,
        total_candidates=len(results),
        filtered_count=0,
        query_time_ms=5,
    )


def _make_chat_service(
    search_service: AsyncMock | None = None,
    chat_client: AsyncMock | None = None,
    pause_event: asyncio.Event | None = None,
) -> ChatService:
    settings = make_test_settings()
    _search = search_service or AsyncMock()
    _chat = chat_client or AsyncMock()
    _pause = pause_event or asyncio.Event()
    _pause.set()  # default: embedding not paused
    return ChatService(
        search_service=_search,
        chat_client=_chat,
        pause_event=_pause,
        settings=settings,
    )


async def _collect_events(service: ChatService, **kwargs) -> list[dict]:
    """Helper to collect all events from a chat stream."""
    events = []
    async for event in service.stream(**kwargs):
        events.append(event)
    return events


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestChatServiceHappyPath:
    async def test_chat_service_yields_metadata_first(self) -> None:
        """Metadata event is first, followed by text and done."""
        search = AsyncMock()
        search.search.return_value = _make_search_response()

        async def _fake_stream(messages):
            yield "Hello"
            yield " world"

        chat_client = AsyncMock()
        chat_client.chat_stream = _fake_stream

        service = _make_chat_service(
            search_service=search,
            chat_client=chat_client,
        )

        events = await _collect_events(
            service,
            query="funny space movies",
            user_id="uid-1",
            token="jf-token",
        )

        # First event is metadata
        assert events[0]["type"] == "metadata"
        assert events[0]["version"] == 1
        assert len(events[0]["recommendations"]) == 1
        assert events[0]["search_status"] == "ok"

        # Text events
        assert events[1] == {"type": "text", "content": "Hello"}
        assert events[2] == {"type": "text", "content": " world"}

        # Done event
        assert events[3] == {"type": "done"}

    async def test_chat_service_empty_results(self) -> None:
        """Empty search results still produce metadata and LLM response."""
        search = AsyncMock()
        search.search.return_value = _make_search_response(
            results=[], status=SearchStatus.NO_EMBEDDINGS
        )

        async def _fake_stream(messages):
            yield "No matches"

        chat_client = AsyncMock()
        chat_client.chat_stream = _fake_stream

        service = _make_chat_service(
            search_service=search,
            chat_client=chat_client,
        )

        events = await _collect_events(
            service,
            query="anything?",
            user_id="uid-1",
            token="jf-token",
        )

        assert events[0]["type"] == "metadata"
        assert events[0]["recommendations"] == []
        assert events[0]["search_status"] == "no_embeddings"
        assert events[-1] == {"type": "done"}


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestChatServiceErrors:
    async def test_chat_service_connection_error(self) -> None:
        """OllamaConnectionError yields error event."""
        search = AsyncMock()
        search.search.return_value = _make_search_response()

        async def _fail_stream(messages):
            raise OllamaConnectionError("Cannot reach Ollama")
            yield  # pragma: no cover  # noqa: RUF028

        chat_client = AsyncMock()
        chat_client.chat_stream = _fail_stream

        service = _make_chat_service(
            search_service=search,
            chat_client=chat_client,
        )

        events = await _collect_events(
            service,
            query="test",
            user_id="uid-1",
            token="jf-token",
        )

        assert events[0]["type"] == "metadata"
        assert events[1]["type"] == "error"
        assert events[1]["code"] == "ollama_unavailable"

    async def test_chat_service_unexpected_error(self) -> None:
        """Unexpected exception yields stream_interrupted error event."""
        search = AsyncMock()
        search.search.return_value = _make_search_response()

        async def _crash_stream(messages):
            raise RuntimeError("something unexpected")
            yield  # pragma: no cover  # noqa: RUF028

        chat_client = AsyncMock()
        chat_client.chat_stream = _crash_stream

        service = _make_chat_service(
            search_service=search,
            chat_client=chat_client,
        )

        events = await _collect_events(
            service,
            query="test",
            user_id="uid-1",
            token="jf-token",
        )

        assert events[0]["type"] == "metadata"
        assert events[1]["type"] == "error"
        assert events[1]["code"] == "stream_interrupted"


# ---------------------------------------------------------------------------
# Pause event signaling
# ---------------------------------------------------------------------------


class TestChatServicePauseSignaling:
    async def test_chat_service_signals_pause(self) -> None:
        """Pause event is cleared before chat and set after (happy path)."""
        search = AsyncMock()
        search.search.return_value = _make_search_response()

        async def _fake_stream(messages):
            yield "Hello"

        chat_client = AsyncMock()
        chat_client.chat_stream = _fake_stream

        pause_event = asyncio.Event()
        pause_event.set()  # Start unpaused

        service = _make_chat_service(
            search_service=search,
            chat_client=chat_client,
            pause_event=pause_event,
        )

        events = await _collect_events(
            service,
            query="test",
            user_id="uid-1",
            token="jf-token",
        )

        # After stream completes, pause event should be set (unpaused)
        assert pause_event.is_set()
        assert events[-1] == {"type": "done"}

    async def test_chat_service_signals_pause_on_error(self) -> None:
        """Pause event is restored even when chat stream errors."""
        search = AsyncMock()
        search.search.return_value = _make_search_response()

        async def _fail_stream(messages):
            raise OllamaConnectionError("Cannot reach Ollama")
            yield  # pragma: no cover  # noqa: RUF028

        chat_client = AsyncMock()
        chat_client.chat_stream = _fail_stream

        pause_event = asyncio.Event()
        pause_event.set()

        service = _make_chat_service(
            search_service=search,
            chat_client=chat_client,
            pause_event=pause_event,
        )

        events = await _collect_events(
            service,
            query="test",
            user_id="uid-1",
            token="jf-token",
        )

        # Even after error, pause event should be restored
        assert pause_event.is_set()
        assert events[1]["type"] == "error"
