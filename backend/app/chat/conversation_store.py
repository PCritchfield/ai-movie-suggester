"""In-memory conversation store — ephemeral, session-scoped, never persisted to disk."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field

from app.utils import hash_for_log

logger = logging.getLogger(__name__)

MAX_TURN_CONTENT_CHARS = 4000


@dataclass(frozen=True, slots=True)
class ConversationTurn:
    """A single message in a conversation."""

    role: str  # "user" or "assistant"
    content: str


@dataclass
class ConversationEntry:
    """Per-session conversation state."""

    turns: deque[ConversationTurn] = field(default_factory=deque)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    last_active: float = field(default_factory=time.monotonic)
    created_at: float = field(default_factory=time.time)


def _make_entry(max_turns: int) -> ConversationEntry:
    """Create a ConversationEntry with a bounded deque."""
    return ConversationEntry(turns=deque(maxlen=max_turns))


class ConversationStore:
    """In-memory conversation history with turn limits and per-conversation locking.

    Conversations are keyed by auth session_id (never exposed outside the backend).
    TTL/LRU eviction is handled by cleanup() and add_turn() respectively.
    """

    def __init__(
        self,
        max_turns: int = 10,
        ttl_seconds: float = 7200.0,
        max_sessions: int = 100,
    ) -> None:
        self._conversations: dict[str, ConversationEntry] = {}
        self._max_turns = max_turns
        self._ttl_seconds = ttl_seconds
        self._max_sessions = max_sessions

    def _session_hash(self, session_id: str) -> str:
        """Return first 8 chars of SHA-256 hash for safe logging."""
        return hash_for_log(session_id)

    def _evict_lru_if_needed(self) -> None:
        """Evict the least-recently-used session if at capacity."""
        if len(self._conversations) >= self._max_sessions:
            lru_id = min(
                self._conversations,
                key=lambda k: self._conversations[k].last_active,
            )
            del self._conversations[lru_id]
            logger.info(
                "conversation_lru_eviction session_id_hash=%s",
                self._session_hash(lru_id),
            )

    def _get_or_create(self, session_id: str) -> ConversationEntry:
        """Return existing entry or create one (with LRU eviction check)."""
        entry = self._conversations.get(session_id)
        if entry is not None:
            return entry
        self._evict_lru_if_needed()
        entry = _make_entry(self._max_turns)
        self._conversations[session_id] = entry
        return entry

    def add_turn(self, session_id: str, role: str, content: str) -> None:
        """Add a turn to the conversation, creating entry if needed.

        Content is truncated to MAX_TURN_CONTENT_CHARS.
        deque(maxlen) handles FIFO eviction automatically.

        The caller is responsible for acquiring the conversation lock.
        """
        entry = self._get_or_create(session_id)

        if len(content) > MAX_TURN_CONTENT_CHARS:
            content = content[:MAX_TURN_CONTENT_CHARS]

        entry.turns.append(ConversationTurn(role=role, content=content))
        entry.last_active = time.monotonic()

    def get_turns(self, session_id: str) -> list[ConversationTurn]:
        """Return a copy of the turns for a session, or empty list if none."""
        entry = self._conversations.get(session_id)
        if entry is None:
            return []
        entry.last_active = time.monotonic()
        return list(entry.turns)

    def get_lock(self, session_id: str) -> asyncio.Lock:
        """Return the lock for a session, creating the entry if needed.

        Uses _get_or_create to ensure LRU capacity check is honoured.
        """
        return self._get_or_create(session_id).lock

    def clear_history(self, session_id: str) -> None:
        """Clear all turns for a session (no-op if session doesn't exist)."""
        entry = self._conversations.get(session_id)
        if entry is not None:
            entry.turns.clear()
            logger.info(
                "conversation_cleared session_id_hash=%s",
                self._session_hash(session_id),
            )

    def purge_session(self, session_id: str) -> None:
        """Remove the entire conversation entry for a session."""
        if self._conversations.pop(session_id, None) is not None:
            logger.info(
                "conversation_purged session_id_hash=%s",
                self._session_hash(session_id),
            )

    def turn_count(self, session_id: str) -> int:
        """Return the number of turns for a session, or 0."""
        entry = self._conversations.get(session_id)
        return len(entry.turns) if entry else 0

    def cleanup(self) -> int:
        """Remove expired conversations (TTL check). Returns count removed."""
        now = time.monotonic()
        expired = [
            sid
            for sid, entry in self._conversations.items()
            if now - entry.last_active > self._ttl_seconds
        ]
        for sid in expired:
            del self._conversations[sid]
        if expired:
            logger.info("conversation_cleanup removed=%d", len(expired))
        return len(expired)
