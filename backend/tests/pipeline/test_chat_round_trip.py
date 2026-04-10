"""Chat round-trip verification against real Ollama inference.

Proves the full RAG pipeline — query → embed → search → context → LLM →
response — produces a coherent response that references fixture media.
"""

from __future__ import annotations

import asyncio
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import httpx
import pytest

from app.chat.conversation_store import ConversationStore
from app.chat.service import ChatPauseCounter, ChatService
from app.ollama.chat_client import OllamaChatClient
from app.ollama.client import OllamaEmbeddingClient
from app.search.service import SearchService
from tests.pipeline.conftest import CHAT_MODEL, EMBED_MODEL, OLLAMA_HOST

if TYPE_CHECKING:
    from app.config import Settings
    from app.library.store import LibraryStore
    from app.vectors.repository import SqliteVecRepository

# ---------------------------------------------------------------------------
# Build fixture title set from NFO files (stays in sync automatically)
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[3]
_MEDIA_ROOT = _REPO_ROOT / "tests" / "fixtures" / "media"


def _extract_titles_from_nfos() -> set[str]:
    """Parse all movie.nfo and tvshow.nfo files to extract titles."""
    titles: set[str] = set()
    for nfo_path in _MEDIA_ROOT.glob("movies/*/movie.nfo"):
        tree = ET.parse(nfo_path)  # noqa: S314
        title = tree.getroot().findtext("title")
        if title:
            titles.add(title.strip())
    for nfo_path in _MEDIA_ROOT.glob("shows/*/tvshow.nfo"):
        tree = ET.parse(nfo_path)  # noqa: S314
        title = tree.getroot().findtext("title")
        if title:
            titles.add(title.strip())
    return titles


FIXTURE_TITLES = _extract_titles_from_nfos()


def _make_permit_all_permission_service() -> AsyncMock:
    """Stub PermissionService that permits all item IDs."""
    mock = AsyncMock()
    mock.filter_permitted = AsyncMock(
        side_effect=lambda user_id, token, candidate_ids: candidate_ids
    )
    return mock


def _make_pipeline_settings(jellyfin_url: str) -> Settings:
    """Minimal Settings for ChatService (no real Jellyfin calls needed)."""
    from pydantic import SecretStr

    from app.config import Settings

    return Settings(
        jellyfin_url=jellyfin_url,
        session_secret="a" * 32 + "-test-not-real-secret-12345678",
        session_secure_cookie=False,
        jellyfin_api_key=SecretStr("not-used-in-chat"),
        jellyfin_admin_user_id="not-used-in-chat",
        ollama_host=OLLAMA_HOST,
        ollama_chat_model=CHAT_MODEL,
        log_level="debug",
    )  # type: ignore[call-arg]


@pytest.mark.pipeline
async def test_chat_round_trip_references_fixtures(
    embedded_library: SqliteVecRepository,
    pipeline_library_store: LibraryStore,
) -> None:
    """Full RAG pipeline: query → embed → search → LLM → fixture title in response."""
    assert FIXTURE_TITLES, (
        "No fixture titles found — is tests/fixtures/media/ populated?"
    )

    settings = _make_pipeline_settings("http://localhost:8096")

    async with httpx.AsyncClient(timeout=300.0) as http:
        embed_client = OllamaEmbeddingClient(
            base_url=OLLAMA_HOST,
            http_client=http,
            embed_model=EMBED_MODEL,
        )
        chat_client = OllamaChatClient(
            base_url=OLLAMA_HOST,
            http_client=http,
            chat_model=CHAT_MODEL,
        )

        search_service = SearchService(
            ollama_client=embed_client,
            vec_repo=embedded_library,
            permission_service=_make_permit_all_permission_service(),
            library_store=pipeline_library_store,
        )

        chat_service = ChatService(
            search_service=search_service,
            chat_client=chat_client,
            pause_counter=ChatPauseCounter(),
            settings=settings,
            conversation_store=ConversationStore(),
        )

        # Collect all SSE events with a generous timeout for CPU inference
        text_chunks: list[str] = []
        error_events: list[dict] = []

        try:
            async with asyncio.timeout(60):
                async for event in chat_service.stream(
                    query="recommend me a sci-fi movie",
                    user_id="pipeline-test-user",
                    token="not-used-permit-all",
                    session_id="pipeline-test-session",
                ):
                    if event.get("type") == "text":
                        text_chunks.append(event.get("content", ""))
                    elif event.get("type") == "error":
                        error_events.append(event)
        except TimeoutError:
            pytest.fail(
                "Chat stream timed out after 60s. "
                "Is Ollama responsive? CPU inference can be slow."
            )

    full_response = "".join(text_chunks)

    # Assert: non-empty response
    assert full_response.strip(), "Chat response was empty — no text events received"

    # Assert: no errors
    assert not error_events, f"Chat stream produced error events: {error_events}"

    # Assert: response references at least one fixture title
    response_lower = full_response.lower()
    matched = [t for t in FIXTURE_TITLES if t.lower() in response_lower]
    assert matched, (
        f"Response did not reference any fixture title. "
        f"Response excerpt: {full_response[:500]!r}"
    )
