"""Unit tests for ConversationStore (Spec 15, Tasks 1.0 & 2.0)."""

from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from app.chat.conversation_store import (
    MAX_TURN_CONTENT_CHARS,
    ConversationStore,
)
from tests.conftest import make_test_settings


class TestConversationStoreBasics:
    def test_add_and_get_turns(self) -> None:
        """Add user and assistant turns, verify retrieval in order."""
        store = ConversationStore(max_turns=10)
        store.add_turn("s1", "user", "hello")
        store.add_turn("s1", "assistant", "hi there")
        turns = store.get_turns("s1")
        assert len(turns) == 2
        assert turns[0].role == "user"
        assert turns[0].content == "hello"
        assert turns[1].role == "assistant"
        assert turns[1].content == "hi there"

    def test_get_turns_returns_copy(self) -> None:
        """Returned list is a copy, not a reference."""
        store = ConversationStore(max_turns=10)
        store.add_turn("s1", "user", "hello")
        turns1 = store.get_turns("s1")
        turns2 = store.get_turns("s1")
        assert turns1 is not turns2

    def test_get_turns_empty_session(self) -> None:
        """Unknown session returns empty list."""
        store = ConversationStore(max_turns=10)
        assert store.get_turns("nonexistent") == []

    def test_turn_count(self) -> None:
        """turn_count returns correct count."""
        store = ConversationStore(max_turns=10)
        assert store.turn_count("s1") == 0
        store.add_turn("s1", "user", "hello")
        assert store.turn_count("s1") == 1
        store.add_turn("s1", "assistant", "hi")
        assert store.turn_count("s1") == 2


class TestTurnLimitEviction:
    def test_turn_limit_eviction(self) -> None:
        """Oldest turns evicted when limit exceeded."""
        store = ConversationStore(max_turns=4)
        for i in range(6):
            store.add_turn("s1", "user", f"msg-{i}")
        turns = store.get_turns("s1")
        assert len(turns) == 4
        # Oldest (msg-0, msg-1) should be gone
        assert turns[0].content == "msg-2"
        assert turns[3].content == "msg-5"


class TestPurgeAndClear:
    def test_purge_session(self) -> None:
        """Purge removes the entire conversation."""
        store = ConversationStore(max_turns=10)
        store.add_turn("s1", "user", "hello")
        store.purge_session("s1")
        assert store.get_turns("s1") == []
        assert store.turn_count("s1") == 0

    def test_purge_nonexistent(self) -> None:
        """Purging a nonexistent session is a no-op."""
        store = ConversationStore(max_turns=10)
        store.purge_session("nonexistent")  # should not raise

    def test_clear_history(self) -> None:
        """Clear removes turns but the session entry persists."""
        store = ConversationStore(max_turns=10)
        store.add_turn("s1", "user", "hello")
        store.clear_history("s1")
        assert store.get_turns("s1") == []
        # Session entry still exists (lock is preserved)
        assert "s1" in store._conversations

    def test_clear_nonexistent(self) -> None:
        """Clearing a nonexistent session is a no-op."""
        store = ConversationStore(max_turns=10)
        store.clear_history("nonexistent")  # should not raise


class TestContentTruncation:
    def test_assistant_turn_truncation(self) -> None:
        """Assistant turn content exceeding 4000 chars is truncated."""
        store = ConversationStore(max_turns=10)
        long_content = "x" * 5000
        store.add_turn("s1", "assistant", long_content)
        turns = store.get_turns("s1")
        assert len(turns[0].content) == MAX_TURN_CONTENT_CHARS

    def test_short_content_not_truncated(self) -> None:
        """Content within limit is not modified."""
        store = ConversationStore(max_turns=10)
        store.add_turn("s1", "user", "short message")
        turns = store.get_turns("s1")
        assert turns[0].content == "short message"


class TestConcurrentAccess:
    async def test_concurrent_access(self) -> None:
        """Concurrent adds through the lock don't corrupt the conversation."""
        store = ConversationStore(max_turns=100)
        lock = store.get_lock("s1")

        async def _add_turns(start: int) -> None:
            for i in range(10):
                async with lock:
                    store.add_turn("s1", "user", f"msg-{start + i}")

        await asyncio.gather(
            _add_turns(0),
            _add_turns(100),
            _add_turns(200),
        )

        turns = store.get_turns("s1")
        assert len(turns) == 30
        # All messages should be present (no corruption)
        contents = {t.content for t in turns}
        for i in range(10):
            assert f"msg-{i}" in contents
            assert f"msg-{100 + i}" in contents
            assert f"msg-{200 + i}" in contents


class TestSettingsValidation:
    def test_conversation_max_turns_too_low(self) -> None:
        """Settings rejects conversation_max_turns below 1."""
        with pytest.raises(ValidationError):
            make_test_settings(conversation_max_turns=0)

    def test_conversation_max_turns_too_high(self) -> None:
        """Settings rejects conversation_max_turns above 100."""
        with pytest.raises(ValidationError):
            make_test_settings(conversation_max_turns=101)

    def test_conversation_max_turns_valid(self) -> None:
        """Valid conversation_max_turns is accepted."""
        settings = make_test_settings(conversation_max_turns=50)
        assert settings.conversation_max_turns == 50
