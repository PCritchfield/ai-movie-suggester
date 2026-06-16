"""Chat service — orchestrates search, prompt assembly, and LLM streaming."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from app.chat.conversation_store import RecommendationPick
from app.chat.models import (
    ChatErrorCode,
    SSEEventType,
    StructuredChatResponse,
    StructuredRecommendation,
)
from app.chat.prompts import (
    build_chat_messages,
    format_watch_history_context,
    get_system_prompt,
    synthesize_recommendation_prose,
)
from app.chat.sanitize import check_injection_patterns, sanitize_user_input
from app.jellyfin.errors import JellyfinError
from app.ollama.errors import OllamaError, OllamaStructuredOutputError
from app.search.models import SearchStatus, SearchUnavailableError

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, AsyncIterator

    from app.chat.conversation_store import ConversationStore
    from app.config import Settings
    from app.jellyfin.models import WatchHistoryEntry
    from app.library.store import LibraryStore
    from app.ollama.chat_client import OllamaChatClient
    from app.search.models import SearchResultItem
    from app.search.service import SearchService
    from app.watch_history.service import WatchData, WatchHistoryService

logger = logging.getLogger(__name__)

# Spec 27 — safe fallback messages. The structured-output path NEVER falls back
# to free-prose LLM generation (Angua veto: that would be an attacker-triggerable
# downgrade to the soft-prompt-only surface). Instead it emits a canned message
# and leaves the already-shown search-result cards in place.
FALLBACK_NO_PICKS_MESSAGE = (
    "I found some options in your library, but I couldn't put together a "
    "confident recommendation this time. Take a look at the matches above."
)
FALLBACK_UNAVAILABLE_MESSAGE = (
    "I wasn't able to finish that recommendation just now — the AI service "
    "may be busy. The closest matches from your library are shown above."
)


class ChatPauseCounter:
    """Reference-counted GPU pause signal for concurrent chat requests.

    Replaces the binary ``asyncio.Event`` to handle concurrent chat
    correctly.  When ``active_count > 0`` the embedding worker should
    yield the GPU.
    """

    def __init__(self) -> None:
        self._count: int = 0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Signal that a chat request is active."""
        async with self._lock:
            self._count += 1

    async def release(self) -> None:
        """Signal that a chat request has finished."""
        async with self._lock:
            self._count = max(0, self._count - 1)

    @property
    def is_paused(self) -> bool:
        """True when any chat request is active."""
        return self._count > 0


class ChatService:
    """Orchestrates the chat pipeline: search -> prompt -> stream.

    Yields SSE event dicts:
    - metadata event (first on success)
    - text events (LLM tokens)
    - done event (stream complete)
    - error event (on failure — may be first if search is unavailable)

    Concurrency note: ``pause_counter`` is a reference-counted
    ``ChatPauseCounter`` shared with ``EmbeddingWorker``.  Each chat
    request increments the counter on entry and decrements it on exit
    (including error paths).  The embedding worker checks
    ``is_paused`` and yields the GPU when any chat is active.  This is
    safe under concurrent chat requests — unlike the previous binary
    ``asyncio.Event``, request B's release cannot cancel request A's
    pause.
    """

    def __init__(
        self,
        search_service: SearchService,
        chat_client: OllamaChatClient,
        pause_counter: ChatPauseCounter,
        settings: Settings,
        conversation_store: ConversationStore,
        watch_history_service: WatchHistoryService | None = None,
        library_store: LibraryStore | None = None,
    ) -> None:
        self._search_service = search_service
        self._chat_client = chat_client
        self._pause_counter = pause_counter
        self._settings = settings
        self._conversation_store = conversation_store
        self._watch_history_service = watch_history_service
        self._library_store = library_store

    async def clear_history(self, session_id: str) -> None:
        """Clear conversation history for a session (service-mediated)."""
        lock = self._conversation_store.get_lock(session_id)
        async with lock:
            self._conversation_store.clear_history(session_id)

    def purge_session(self, session_id: str) -> None:
        """Remove all conversation data for a session (logout/eviction)."""
        self._conversation_store.purge_session(session_id)

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

        # Fetch watch history for exclusion + prompt context (graceful degradation)
        watched_ids: set[str] | None = None
        watch_data: WatchData | None = None
        if self._watch_history_service is not None:
            try:
                watch_data = await self._watch_history_service.get(token, user_id)
                watched_ids = {e.jellyfin_id for e in watch_data.watched}
            except JellyfinError:
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
            "version": 2,
            "recommendations": [r.model_dump() for r in response.results],
            "search_status": response.status.value,
            "turn_count": turn_count,
        }

        # Spec 25 Task 5.0 — empty candidate set short-circuits the LLM.
        # Without an early return, the model was being asked to recommend
        # from an empty list and predictably hallucinated. Emit a stable
        # graceful text event + done, and store the assistant turn so the
        # session transcript stays coherent.
        #
        # Copilot review (PR #248) — message branches on response.status
        # so an unindexed library tells the operator to wait, not to
        # rephrase a query the system simply hasn't ingested yet.
        if not response.results:
            graceful_text = self._empty_results_message(response.status)
            async for event in self._emit_fallback(session_id, graceful_text):
                yield event
            return

        # Resolve watch history titles for prompt context
        watch_history_context: str | None = None
        if watch_data is not None and self._library_store is not None:
            watch_history_context = await self._resolve_watch_history_context(
                watch_data
            )

        system_prompt = get_system_prompt(self._settings.chat_system_prompt)
        messages = build_chat_messages(
            query=query,
            results=response.results,
            system_prompt=system_prompt,
            history=history,
            context_token_budget=self._settings.conversation_context_budget,
            watch_history_context=watch_history_context,
        )

        # Increment pause counter so embedding worker yields to chat
        await self._pause_counter.acquire()
        try:
            # Generation now blocks until the whole structured payload is ready
            # (no token streaming under grammar-constrained decoding), so signal
            # a staged wait state the frontend can surface while we wait.
            yield {"type": SSEEventType.STATUS, "phase": "generating"}

            async with asyncio.timeout(120.0):
                structured = await self._chat_client.chat_structured(
                    messages, StructuredChatResponse
                )

            # Validate every returned id against the permission-filtered
            # candidate set. A jellyfin_id from the model is a CLAIM, not a
            # trusted reference — drop any that aren't real candidates, and
            # drop repeats (the model can name the same candidate twice) so a
            # duplicate doesn't waste a pick slot or show a card/prose line twice.
            candidate_by_id = {r.jellyfin_id: r for r in response.results}
            valid: list[tuple[StructuredRecommendation, SearchResultItem]] = []
            seen: set[str] = set()
            for rec in structured.recommendations:
                item = candidate_by_id.get(rec.jellyfin_id)
                if item is None or rec.jellyfin_id in seen:
                    continue
                seen.add(rec.jellyfin_id)
                valid.append((rec, item))
            dropped = len(structured.recommendations) - len(valid)
            if dropped:
                logger.warning(
                    "chat_picks_dropped dropped=%d kept=%d", dropped, len(valid)
                )

            if not valid:
                # Zero valid picks → safe canned fallback (cards already shown).
                async for event in self._emit_fallback(
                    session_id, FALLBACK_NO_PICKS_MESSAGE
                ):
                    yield event
                return

            yield {
                "type": SSEEventType.PICKS,
                "version": 2,
                "picks": [
                    {
                        "jellyfin_id": rec.jellyfin_id,
                        "reasoning": rec.reasoning,
                        "pick_order": order,
                    }
                    for order, (rec, _item) in enumerate(valid, start=1)
                ],
            }

            prose = synthesize_recommendation_prose(
                structured.introductory_message,
                [(item.title, rec.reasoning) for rec, item in valid],
            )
            yield {"type": SSEEventType.TEXT, "content": prose}
            yield {"type": SSEEventType.DONE}

            # Structured sidecar (Spec 27): the validated picks behind the prose,
            # so ordinal follow-ups ("more like the second one") resolve reliably.
            # IDs + titles + order only — reasoning is intentionally excluded.
            sidecar = tuple(
                RecommendationPick(
                    pick_order=order, jellyfin_id=rec.jellyfin_id, title=item.title
                )
                for order, (rec, item) in enumerate(valid, start=1)
            )

            # Mutation window 2: store assistant response (success only).
            # Re-acquire lock via get_lock() in case the original entry was
            # purged/evicted during the unlocked generation phase.
            window2_lock = self._conversation_store.get_lock(session_id)
            async with window2_lock:
                self._conversation_store.add_turn(
                    session_id, "assistant", prose, picks=sidecar
                )
        except OllamaStructuredOutputError:
            # Got a response, but it didn't parse/validate. Do NOT downgrade to
            # free-prose (Angua veto) — emit the canned fallback instead.
            async for event in self._emit_fallback(
                session_id, FALLBACK_NO_PICKS_MESSAGE
            ):
                yield event
        except (TimeoutError, OllamaError):
            # Timeout / transport / model error — AI unavailable. Canned message,
            # cards retained, no free-prose path.
            async for event in self._emit_fallback(
                session_id, FALLBACK_UNAVAILABLE_MESSAGE
            ):
                yield event
        except Exception:
            # exc_info logged here — ensure no exception embeds user query content
            logger.exception("chat_generation_interrupted")
            async for event in self._emit_fallback(
                session_id, FALLBACK_UNAVAILABLE_MESSAGE
            ):
                yield event
        finally:
            await self._pause_counter.release()

    async def _emit_fallback(
        self, session_id: str, message: str
    ) -> AsyncGenerator[dict, None]:
        """Emit the safe fallback: canned text + done, and store the turn.

        No ``picks`` event (the frontend keeps the raw search-result cards) and
        no free-prose LLM call. The canned message is stored as the assistant
        turn so the conversation transcript stays coherent (sidecar is None —
        added in Spec 27 Task 3).
        """
        yield {"type": SSEEventType.TEXT, "content": message}
        yield {"type": SSEEventType.DONE}
        window2_lock = self._conversation_store.get_lock(session_id)
        async with window2_lock:
            self._conversation_store.add_turn(session_id, "assistant", message)

    @staticmethod
    def _empty_results_message(status: SearchStatus) -> str:
        """Pick the operator-facing message when the candidate set is empty.

        ``NO_EMBEDDINGS`` and ``PARTIAL_EMBEDDINGS`` describe a library
        that hasn't finished indexing — telling the user to "rephrase"
        is misleading because the issue is the system, not the query.
        ``OK`` with empty results is the genuine zero-match case.
        """
        if status in (SearchStatus.NO_EMBEDDINGS, SearchStatus.PARTIAL_EMBEDDINGS):
            return (
                "Your library is still being indexed in the background. "
                "Recommendations will improve as more items become indexed — "
                "try again in a few minutes."
            )
        return (
            "I couldn't find anything in your library that matches that "
            "request. Try rephrasing, or ask for something a bit broader."
        )

    async def _resolve_watch_history_context(self, watch_data: WatchData) -> str | None:
        """Resolve watch history IDs to titles and format for prompt context.

        Returns the formatted watch history block, or None if empty.
        Caller must ensure ``self._library_store`` is not None before calling.
        """
        if self._library_store is None:
            return None

        # Sort by last_played_date descending, take top 10 recent + 5 favorites.
        # Use epoch 0 as fallback to avoid naive/aware datetime comparison errors.
        def _sort_key(e: WatchHistoryEntry) -> float:
            if e.last_played_date is None:
                return 0.0
            return e.last_played_date.timestamp()

        recent_sorted = sorted(watch_data.watched, key=_sort_key, reverse=True)[:10]
        fav_sorted = sorted(watch_data.favorites, key=_sort_key, reverse=True)[:5]

        # Deduplicate IDs for a single batch lookup
        recent_ids = [e.jellyfin_id for e in recent_sorted]
        fav_ids = [e.jellyfin_id for e in fav_sorted]
        all_ids = list(dict.fromkeys(recent_ids + fav_ids))

        if not all_ids:
            return None

        items = await self._library_store.get_many(all_ids)
        title_map = {
            item.jellyfin_id: (
                f"{item.title} ({item.production_year})"
                if item.production_year
                else item.title
            )
            for item in items
        }

        recent_titles = [title_map[jid] for jid in recent_ids if jid in title_map]
        fav_titles = [title_map[jid] for jid in fav_ids if jid in title_map]

        result = format_watch_history_context(
            recent_titles, fav_titles, len(watch_data.watched)
        )
        return result or None
