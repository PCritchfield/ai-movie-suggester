# Spec 15 — Conversation Memory — Proof Artifacts

## Test Results (all tasks)

```
59 passed in 0.13s
```

### Task 1.0 + 2.0: ConversationStore (15 tests)

```
tests/test_conversation_store.py::TestConversationStoreBasics::test_add_and_get_turns PASSED
tests/test_conversation_store.py::TestConversationStoreBasics::test_get_turns_returns_copy PASSED
tests/test_conversation_store.py::TestConversationStoreBasics::test_get_turns_empty_session PASSED
tests/test_conversation_store.py::TestConversationStoreBasics::test_turn_count PASSED
tests/test_conversation_store.py::TestTurnLimitEviction::test_turn_limit_eviction PASSED
tests/test_conversation_store.py::TestPurgeAndClear::test_purge_session PASSED
tests/test_conversation_store.py::TestPurgeAndClear::test_purge_nonexistent PASSED
tests/test_conversation_store.py::TestPurgeAndClear::test_clear_history PASSED
tests/test_conversation_store.py::TestPurgeAndClear::test_clear_nonexistent PASSED
tests/test_conversation_store.py::TestContentTruncation::test_assistant_turn_truncation PASSED
tests/test_conversation_store.py::TestContentTruncation::test_short_content_not_truncated PASSED
tests/test_conversation_store.py::TestConcurrentAccess::test_concurrent_access PASSED
tests/test_conversation_store.py::TestSettingsValidation::test_conversation_max_turns_too_low PASSED
tests/test_conversation_store.py::TestSettingsValidation::test_conversation_max_turns_too_high PASSED
tests/test_conversation_store.py::TestSettingsValidation::test_conversation_max_turns_valid PASSED
```

### Task 3.0: Budget Enforcement (7 new + 12 existing = 19 tests)

```
tests/test_chat_prompts.py::TestBuildChatMessagesWithHistory::test_estimate_tokens PASSED
tests/test_chat_prompts.py::TestBuildChatMessagesWithHistory::test_build_chat_messages_with_history PASSED
tests/test_chat_prompts.py::TestBuildChatMessagesWithHistory::test_build_chat_messages_backward_compatible PASSED
tests/test_chat_prompts.py::TestBuildChatMessagesWithHistory::test_build_chat_messages_history_truncation PASSED
tests/test_chat_prompts.py::TestBuildChatMessagesWithHistory::test_build_chat_messages_system_prompt_never_truncated PASSED
tests/test_chat_prompts.py::TestBuildChatMessagesWithHistory::test_build_chat_messages_budget_allocation PASSED
tests/test_chat_prompts.py::TestBuildChatMessagesWithHistory::test_build_chat_messages_budget_exhausted_by_system_and_query PASSED
```

All 12 existing prompt tests pass unchanged (backward compatibility confirmed).

### Task 4.0: ChatService Integration (4 new + 6 updated = 10 tests)

```
tests/test_chat_service.py::TestChatServiceConversationMemory::test_chat_endpoint_maintains_history PASSED
tests/test_chat_service.py::TestChatServiceConversationMemory::test_chat_endpoint_turn_count_in_metadata PASSED
tests/test_chat_service.py::TestChatServiceConversationMemory::test_chat_endpoint_history_truncation_graceful PASSED
tests/test_chat_service.py::TestChatServiceConversationMemory::test_chat_mid_stream_error_preserves_user_turn PASSED
```

All 6 existing ChatService tests updated for new `session_id` parameter and pass.

### Task 5.0: DELETE Endpoint + Cascade (4 new tests)

```
tests/test_chat_router.py::TestDeleteChatHistory::test_delete_chat_history PASSED
tests/test_chat_router.py::TestDeleteChatHistory::test_delete_chat_history_requires_auth PASSED
tests/test_chat_router.py::TestDeleteChatHistory::test_delete_chat_history_idempotent PASSED
tests/test_chat_router.py::TestSessionCascade::test_session_destroy_purges_conversation PASSED
```

All 11 existing router tests pass unchanged.

## Lint Results

```
$ uv run ruff check app/
All checks passed!
```

## Full Suite Results

```
591 passed, 5 failed (pre-existing Ollama connectivity), 13 errors (integration — requires Jellyfin)
```

## Files Changed

### New files
- `backend/app/chat/conversation_store.py` — ConversationStore, ConversationTurn, ConversationEntry
- `backend/tests/test_conversation_store.py` — 15 tests

### Modified files
- `backend/app/config.py` — 4 new conversation memory settings
- `backend/app/chat/prompts.py` — estimate_tokens(), history param, budget enforcement
- `backend/app/chat/service.py` — ConversationStore wiring, session_id, two-window locking, turn_count
- `backend/app/chat/router.py` — DELETE /api/chat/history, session_id pass-through
- `backend/app/main.py` — ConversationStore creation, lifespan wiring, periodic cleanup task
- `backend/app/auth/router.py` — Session destroy cascade (logout)
- `backend/app/auth/service.py` — Session destroy cascade (expiry + LRU)
- `backend/tests/test_chat_prompts.py` — 7 new budget enforcement tests
- `backend/tests/test_chat_service.py` — 4 new tests, 6 existing tests updated
- `backend/tests/test_chat_router.py` — 4 new tests, ConversationStore wired in fixture
- `backend/tests/test_auth_router.py` — ConversationStore wired in fixture
- `backend/tests/test_csrf.py` — ConversationStore wired in fixture
- `backend/tests/test_permission_wiring.py` — ConversationStore wired in fixture
- `backend/tests/test_rate_limit.py` — ConversationStore wired in fixture
