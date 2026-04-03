"""Chat service — orchestrates search, prompt assembly, and LLM streaming."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from app.chat.models import ChatErrorCode, SSEEventType
from app.chat.prompts import build_chat_messages, get_system_prompt
from app.ollama.errors import (
    OllamaConnectionError,
    OllamaStreamError,
    OllamaTimeoutError,
)
from app.search.models import SearchUnavailableError

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from app.config import Settings
    from app.ollama.chat_client import OllamaChatClient
    from app.search.service import SearchService

logger = logging.getLogger(__name__)


class ChatService:
    """Orchestrates the chat pipeline: search -> prompt -> stream.

    Yields SSE event dicts:
    - metadata event (first, always)
    - text events (LLM tokens)
    - done event (stream complete)
    - error event (on failure)
    """

    def __init__(
        self,
        search_service: SearchService,
        chat_client: OllamaChatClient,
        pause_event: asyncio.Event,
        settings: Settings,
    ) -> None:
        self._search_service = search_service
        self._chat_client = chat_client
        self._pause_event = pause_event
        self._settings = settings

    async def stream(
        self,
        query: str,
        user_id: str,
        token: str,
    ) -> AsyncIterator[dict]:
        """Execute the full chat pipeline as an async generator.

        Yields SSE event dicts in order:
        1. metadata — recommendations and search status
        2. text — individual LLM tokens
        3. done — stream complete
        On error: yields an error event instead of done.

        Args:
            query: User's natural-language message.
            user_id: Jellyfin user ID.
            token: Decrypted Jellyfin access token.

        Yields:
            Event dicts with ``type`` key.
        """
        try:
            response = await self._search_service.search(
                query=query,
                limit=10,
                user_id=user_id,
                token=token,
            )
        except SearchUnavailableError:
            logger.warning("chat_search_unavailable query_len=%d", len(query))
            yield {
                "type": SSEEventType.ERROR,
                "code": ChatErrorCode.OLLAMA_UNAVAILABLE,
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
        }

        system_prompt = get_system_prompt(self._settings.chat_system_prompt)
        messages = build_chat_messages(
            query=query,
            results=response.results,
            system_prompt=system_prompt,
        )

        # Clear pause event so embedding worker yields to chat
        self._pause_event.clear()
        try:
            async with asyncio.timeout(120.0):
                async for content in self._chat_client.chat_stream(messages):
                    yield {"type": SSEEventType.TEXT, "content": content}

            yield {"type": SSEEventType.DONE}
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
