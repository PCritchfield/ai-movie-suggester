"""Chat service — orchestrates search, prompt assembly, and LLM streaming."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from app.chat.models import ChatErrorCode, SSEEventType
from app.chat.prompts import build_chat_messages, get_system_prompt
from app.chat.sanitize import check_injection_patterns, sanitize_user_input
from app.ollama.errors import (
    OllamaConnectionError,
    OllamaStreamError,
    OllamaTimeoutError,
)
from app.search.models import SearchUnavailableError

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from app.chat.conversation_store import ConversationStore
    from app.config import Settings
    from app.ollama.chat_client import OllamaChatClient
    from app.search.service import SearchService
    from app.watch_history.service import WatchHistoryService

logger = logging.getLogger(__name__)


class ChatService:
    """Orchestrates the chat pipeline: search -> prompt -> stream.

    Yields SSE event dicts:
    - metadata event (first on success)
    - text events (LLM tokens)
    - done event (stream complete)
    - error event (on failure — may be first if search is unavailable)

    Concurrency note: ``pause_event`` is a binary ``asyncio.Event`` shared
    with ``EmbeddingWorker``.  Under concurrent chat requests the
    clear/set calls can race (request B's ``clear()`` vs request A's
    ``finally: set()``).  The per-IP rate limiter (default 10 req/min)
    makes true concurrency unlikely on consumer hardware.  If concurrent
    chat becomes common, replace the event with a reference counter or
    ``asyncio.Semaphore``.
    """

    def __init__(
        self,
        search_service: SearchService,
        chat_client: OllamaChatClient,
        pause_event: asyncio.Event,
        settings: Settings,
        conversation_store: ConversationStore,
        watch_history_service: WatchHistoryService | None = None,
    ) -> None:
        self._search_service = search_service
        self._chat_client = chat_client
        self._pause_event = pause_event
        self._settings = settings
        self._conversation_store = conversation_store
        self._watch_history_service = watch_history_service

    async def stream(
        self,
        query: str,
        user_id: str,
        token: str,
        session_id: str,
    ) -> AsyncIterator[dict]:
        """Execute the full chat pipeline as an async generator.

        Yields SSE event dicts in order:
        1. metadata — recommendations, search status, and turn_count
        2. text — individual LLM tokens
        3. done — stream complete
        On pre-search error: yields an error event as the first (and only) event.
        On mid-stream error: yields an error event after metadata/text.

        Conversation history is managed via two mutation windows to avoid
        holding the conversation lock across I/O:
        - Window 1 (before search): read history + store user turn
        - Window 2 (after streaming): store assistant turn on success only

        Args:
            query: User's natural-language message.
            user_id: Jellyfin user ID.
            token: Decrypted Jellyfin access token.
            session_id: Auth session ID for conversation tracking.

        Yields:
            Event dicts with ``type`` key.
        """
        query = sanitize_user_input(query)

        patterns = check_injection_patterns(query)
        if patterns:
            logger.warning(
                "chat_injection_detected patterns=%s query_len=%d",
                ",".join(patterns),
                len(query),
            )

        # Mutation window 1: read history + store user turn
        lock = self._conversation_store.get_lock(session_id)
        async with lock:
            history = self._conversation_store.get_turns(session_id)
            self._conversation_store.add_turn(session_id, "user", query)
            turn_count = self._conversation_store.turn_count(session_id)

        # Fetch watch history for exclusion (graceful degradation)
        watched_ids: set[str] | None = None
        if self._watch_history_service is not None:
            try:
                watch_data = await self._watch_history_service.get(token, user_id)
                watched_ids = {e.jellyfin_id for e in watch_data.watched}
            except Exception:
                logger.warning("watch_history_unavailable user_id=%s", user_id)

        try:
            response = await self._search_service.search(
                query=query,
                limit=10,
                user_id=user_id,
                token=token,
                exclude_ids=watched_ids,
            )
        except SearchUnavailableError:
            logger.warning("chat_search_unavailable query_len=%d", len(query))
            yield {
                "type": SSEEventType.ERROR,
                "code": ChatErrorCode.SEARCH_UNAVAILABLE,
                "message": (
                    "The search service is currently unavailable. "
                    "Please try again shortly."
                ),
            }
            return

        yield {
            "type": SSEEventType.METADATA,
            "version": 1,
            "recommendations": [r.model_dump() for r in response.results],
            "search_status": response.status.value,
            "turn_count": turn_count,
        }

        system_prompt = get_system_prompt(self._settings.chat_system_prompt)
        messages = build_chat_messages(
            query=query,
            results=response.results,
            system_prompt=system_prompt,
            history=history,
            context_token_budget=self._settings.conversation_context_budget,
        )

        # Clear pause event so embedding worker yields to chat
        self._pause_event.clear()
        try:
            assistant_chunks: list[str] = []
            async with asyncio.timeout(120.0):
                async for content in self._chat_client.chat_stream(messages):
                    assistant_chunks.append(content)
                    yield {"type": SSEEventType.TEXT, "content": content}

            assistant_text = "".join(assistant_chunks)
            yield {"type": SSEEventType.DONE}

            # Mutation window 2: store assistant response (success only).
            # Re-acquire lock via get_lock() in case the original entry
            # was purged/evicted during the unlocked streaming phase.
            window2_lock = self._conversation_store.get_lock(session_id)
            async with window2_lock:
                self._conversation_store.add_turn(
                    session_id, "assistant", assistant_text
                )
        except (TimeoutError, OllamaTimeoutError):
            yield {
                "type": SSEEventType.ERROR,
                "code": ChatErrorCode.GENERATION_TIMEOUT,
                "message": (
                    "The response took too long to generate. "
                    "Your recommendations are shown above."
                ),
            }
        except (OllamaConnectionError, OllamaStreamError):
            yield {
                "type": SSEEventType.ERROR,
                "code": ChatErrorCode.OLLAMA_UNAVAILABLE,
                "message": (
                    "The AI service became unavailable. "
                    "Your recommendations are shown above."
                ),
            }
        except Exception:
            # exc_info logged here — ensure no exception embeds user query content
            logger.exception("chat_stream_interrupted")
            yield {
                "type": SSEEventType.ERROR,
                "code": ChatErrorCode.STREAM_INTERRUPTED,
                "message": (
                    "The response was interrupted. "
                    "Your recommendations are shown above."
                ),
            }
        finally:
            self._pause_event.set()
