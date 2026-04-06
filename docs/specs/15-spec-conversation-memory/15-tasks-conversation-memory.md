# 15 Tasks — Conversation Memory

## Relevant Files

- `backend/app/chat/conversation_store.py` - **NEW** — `ConversationStore`, `ConversationTurn`, `ConversationEntry` classes. Core in-memory store with turn management, TTL/LRU eviction, per-conversation locking.
- `backend/tests/test_conversation_store.py` - **NEW** — Unit tests for `ConversationStore`.
- `backend/app/chat/prompts.py` - Modify `build_chat_messages()` to accept `history` param. Add `estimate_tokens()`. Implement budget enforcement.
- `backend/tests/test_chat_prompts.py` - Add tests for history integration, budget enforcement, truncation priority.
- `backend/app/chat/service.py` - Modify `ChatService.__init__()` and `stream()` to wire conversation store, add `session_id` param, implement two-window locking.
- `backend/tests/test_chat_service.py` - Update `_make_chat_service()` factory and all `_collect_events()` calls for new `session_id` param. Add conversation memory tests.
- `backend/app/chat/router.py` - Pass `session_id` to `ChatService.stream()`. Add `DELETE /api/chat/history` endpoint.
- `backend/tests/test_chat_router.py` - Add DELETE endpoint tests. No changes to existing POST tests (they mock the service layer).
- `backend/app/chat/models.py` - No structural changes; `turn_count` is added to event dicts in `service.py`, not as a model field.
- `backend/app/config.py` - Add `CONVERSATION_MAX_TURNS`, `CONVERSATION_TTL_MINUTES`, `CONVERSATION_MAX_SESSIONS`, `CONVERSATION_CONTEXT_BUDGET` settings.
- `backend/app/main.py` - Create `ConversationStore` in lifespan. Pass to `ChatService`. Start periodic cleanup task. Store on `app.state`.
- `backend/app/auth/router.py` - Add `conversation_store.purge_session()` call after `session_store.delete()` in logout handler.
- `backend/app/auth/service.py` - Add `conversation_store.purge_session()` calls after `store.delete()` in `cleanup_expired_sessions()` and `_enforce_session_limit()`.

### Notes

- Unit tests live in `backend/tests/` alongside the existing test files.
- Run tests with: `cd backend && uv run pytest tests/<test_file>.py -v`
- Run full suite: `cd backend && uv run pytest tests/ -v --tb=short`
- Lint with: `cd backend && uv run ruff check app/`
- Follow existing test patterns: `make_test_settings()` factory from `conftest.py`, `AsyncMock` for service mocks, `_collect_events()` helper for streaming tests.
- Conventional commit prefix: `feat(chat):`

## Tasks

### [x] 1.0 Settings and ConversationStore Data Model

Add the four new settings to `config.py` and implement the `ConversationStore` class with `ConversationTurn` dataclass, turn management (add/get/clear/purge), FIFO eviction at the turn limit, content truncation for assistant responses, and per-conversation `asyncio.Lock`. This task does NOT include TTL/LRU cleanup — that is task 2.0.

#### 1.0 Proof Artifact(s)

- Test: `test_conversation_store_add_and_get_turns` — add user and assistant turns, verify retrieval in order
- Test: `test_conversation_store_turn_limit_eviction` — add more than max turns, verify oldest turns are evicted
- Test: `test_conversation_store_purge_session` — purge a session, verify conversation is immediately removed
- Test: `test_conversation_store_clear_history` — clear history, verify turns are empty but session entry persists
- Test: `test_conversation_store_concurrent_access` — concurrent adds to same session with lock, verify no corruption
- Test: `test_conversation_store_assistant_turn_truncation` — add assistant turn exceeding 4000 chars, verify truncation to `MAX_TURN_CONTENT_CHARS`
- Test: `test_conversation_max_turns_validation` — verify Settings rejects values outside 1-100 range
- CLI: `cd backend && uv run pytest tests/test_conversation_store.py -v` — all tests pass

#### 1.0 Tasks

- [ ] 1.1 Add `CONVERSATION_MAX_TURNS: int = Field(default=10, ge=1, le=100)`, `CONVERSATION_TTL_MINUTES: int = 120`, `CONVERSATION_MAX_SESSIONS: int = 100`, and `CONVERSATION_CONTEXT_BUDGET: int = 6000` to the `Settings` class in `backend/app/config.py`. Place them in a new `# Conversation memory` comment section after the existing `# Search` section.
- [ ] 1.2 Create `backend/app/chat/conversation_store.py` with the `ConversationTurn` dataclass (`role: str`, `content: str`) and `ConversationEntry` dataclass (`turns: list[ConversationTurn]`, `lock: asyncio.Lock`, `last_active: float` using `time.monotonic()`, `created_at: float` using `time.time()`).
- [ ] 1.3 Implement the `ConversationStore` class with constructor accepting `max_turns: int`, `ttl_seconds: float`, `max_sessions: int`. Store these as instance attributes. Initialize `_conversations: dict[str, ConversationEntry]` as an empty dict.
- [ ] 1.4 Implement `add_turn(session_id: str, role: str, content: str) -> None`. If no conversation exists for the session, create a new `ConversationEntry`. Truncate `content` to `MAX_TURN_CONTENT_CHARS = 4000` characters. Append the turn. If len(turns) exceeds `_max_turns`, pop from the front (index 0) until within limit. Update `last_active` to `time.monotonic()`. This method does NOT acquire the lock — the caller (`ChatService`) manages locking.
- [ ] 1.5 Implement `get_turns(session_id: str) -> list[ConversationTurn]`. Return a copy of the turns list (not a reference) for the given session, or an empty list if no conversation exists. Update `last_active`.
- [ ] 1.6 Implement `get_lock(session_id: str) -> asyncio.Lock`. Return the lock for the given session, creating the `ConversationEntry` if it doesn't exist.
- [ ] 1.7 Implement `clear_history(session_id: str) -> None`. If the session exists, clear the turns list but keep the `ConversationEntry` (preserving the lock and metadata). If the session doesn't exist, do nothing (no-op).
- [ ] 1.8 Implement `purge_session(session_id: str) -> None`. Remove the entire `ConversationEntry` for the session from `_conversations`. Log at INFO: `conversation_purged session_id_hash=<first 8 chars of sha256>`. If the session doesn't exist, do nothing.
- [ ] 1.9 Add `turn_count(session_id: str) -> int` property/method. Return the number of turns for the session, or 0 if no conversation exists.
- [ ] 1.10 Create `backend/tests/test_conversation_store.py` with all 7 proof artifact tests. Use `make_test_settings()` from `conftest.py` for the settings validation test. For the concurrent access test, use `asyncio.gather()` with multiple `add_turn` calls through the lock.

### [x] 2.0 TTL/LRU Memory Lifecycle

Add TTL-based expiry and LRU eviction cap to `ConversationStore`. Implement the `cleanup()` method for periodic TTL sweeps and LRU eviction on `add_turn()` when the session cap is reached. This task builds on the store from 1.0 — it adds the memory safety layer.

#### 2.0 Proof Artifact(s)

- Test: `test_conversation_store_ttl_expiry` — set short TTL, verify conversation is removed after `cleanup()`
- Test: `test_conversation_store_lru_eviction` — fill to capacity, add a new conversation, verify LRU conversation is evicted
- CLI: `cd backend && uv run pytest tests/test_conversation_store.py -v` — all tests pass (including 1.0 tests)

#### 2.0 Tasks

- [ ] 2.1 Implement `cleanup() -> int` in `ConversationStore`. Iterate `_conversations`, remove any entry where `time.monotonic() - entry.last_active > _ttl_seconds`. Return the count of removed conversations. Log at INFO: `conversation_cleanup removed=<count>` (only if count > 0).
- [ ] 2.2 Add LRU eviction to `add_turn()`. Before creating a new `ConversationEntry` (when the session doesn't exist yet), check if `len(_conversations) >= _max_sessions`. If so, find the entry with the smallest `last_active` value and remove it. Log at INFO: `conversation_lru_eviction session_id_hash=<first 8 chars of sha256>`.
- [ ] 2.3 Add `test_conversation_store_ttl_expiry` to the test file. Create a store with `ttl_seconds=0.1`. Add a turn, sleep briefly (`await asyncio.sleep(0.15)`), call `cleanup()`, verify the conversation is gone. Also verify a fresh conversation added after the sleep is NOT removed.
- [ ] 2.4 Add `test_conversation_store_lru_eviction` to the test file. Create a store with `max_sessions=2`. Add turns to sessions A and B. Then add a turn to session C. Verify session A (least recently used) is evicted. Verify sessions B and C remain.

### [x] 3.0 Context Window Budget Enforcement

Add `estimate_tokens()` and the `history` parameter to `build_chat_messages()` in `prompts.py`. Implement budget enforcement with the truncation priority: system prompt (never truncated) > user query > movie context > conversation history (oldest dropped first). Add `CONVERSATION_CONTEXT_BUDGET` setting usage.

#### 3.0 Proof Artifact(s)

- Test: `test_estimate_tokens` — verify `estimate_tokens("hello world")` returns `len("hello world") // 4`
- Test: `test_build_chat_messages_with_history` — history turns appear between system prompt and current context
- Test: `test_build_chat_messages_history_truncation` — history exceeding budget: oldest turns dropped, newest preserved
- Test: `test_build_chat_messages_system_prompt_never_truncated` — massive history, system prompt always present and complete
- Test: `test_build_chat_messages_backward_compatible` — call without history parameter, output matches current single-turn behavior
- Test: `test_build_chat_messages_budget_allocation` — movie context preserved when history is truncated
- Test: `test_build_chat_messages_budget_exhausted_by_system_and_query` — returns `[system, user_query]` with no history/context
- CLI: `cd backend && uv run pytest tests/test_chat_prompts.py -v` — all tests pass (existing + new)

#### 3.0 Tasks

- [ ] 3.1 Add `estimate_tokens(text: str) -> int` function to `backend/app/chat/prompts.py`. Returns `len(text) // 4`. Add a brief docstring noting this is a conservative char-based estimate.
- [ ] 3.2 Add `from __future__ import annotations` import if not present, and add `ConversationTurn` to the TYPE_CHECKING imports in `prompts.py`.
- [ ] 3.3 Modify the `build_chat_messages()` signature to add `history: list[ConversationTurn] = []` parameter after `system_prompt`. Keep all existing parameters and their defaults. Update the docstring to document the new parameter and remove the "NOT enforced in v1" note.
- [ ] 3.4 Implement budget enforcement inside `build_chat_messages()`:
  - Calculate `system_tokens = estimate_tokens(system_prompt)` and `query_tokens = estimate_tokens(query)`.
  - Calculate `remaining_budget = context_token_budget - system_tokens - query_tokens`. If `remaining_budget <= 0`, return `[system_msg, query_msg]` only (graceful degradation).
  - Format movie context with `format_movie_context(results, max_results, max_overview_chars)`. Calculate `context_tokens = estimate_tokens(context)`.
  - If `context_tokens > remaining_budget`, reduce `max_results` iteratively until the context fits (minimum 0 results).
  - Calculate `history_budget = remaining_budget - estimate_tokens(context)` (after context is sized).
  - Build history messages from the `history` list, newest first. Accumulate token estimates. Stop adding when the next turn would exceed `history_budget`. Reverse the kept turns to restore chronological order.
  - Assemble final message list: `[system, ...history_turns, movie_context, user_query]`.
- [ ] 3.5 Add `test_estimate_tokens` to `test_chat_prompts.py`. Verify `estimate_tokens("hello world")` returns `len("hello world") // 4`. Also test empty string returns 0.
- [ ] 3.6 Add `test_build_chat_messages_with_history`. Create 2 `ConversationTurn` objects (user + assistant). Call `build_chat_messages()` with `history=[turn1, turn2]` and a generous budget. Verify the returned messages list has: system at [0], turn1 (user) at [1], turn2 (assistant) at [2], movie context at [3], user query at [4]. Verify `len(messages) == 5`.
- [ ] 3.7 Add `test_build_chat_messages_backward_compatible`. Call `build_chat_messages()` with no `history` argument. Verify `len(messages) == 3` and the structure matches the existing single-turn format exactly (system, movie context, user query).
- [ ] 3.8 Add `test_build_chat_messages_history_truncation`. Create 20 history turns with long content. Set `context_token_budget=500`. Verify the system prompt and user query are present, some recent history turns are present, and older turns are dropped.
- [ ] 3.9 Add `test_build_chat_messages_system_prompt_never_truncated`. Set a very small `context_token_budget` (e.g., 100). Provide massive history. Verify `messages[0]["content"]` equals the full system prompt.
- [ ] 3.10 Add `test_build_chat_messages_budget_allocation`. Provide history and search results with `context_token_budget` sized so movie context fits but not all history. Verify movie context message is present (movie titles appear) while some history is truncated.
- [ ] 3.11 Add `test_build_chat_messages_budget_exhausted_by_system_and_query`. Set `context_token_budget=10` (far too small). Verify only 2 messages returned: system and user query. No crash.

### [x] 4.0 ChatService Integration and Existing Test Updates

Wire `ConversationStore` into `ChatService`. Add `session_id` parameter to `stream()`. Implement the two-mutation-window lock pattern (pre-stream: read history + store user turn; post-stream: store assistant turn). Add `turn_count` to metadata SSE event. Update all existing `test_chat_service.py` and `test_chat_router.py` tests for the new signatures.

#### 4.0 Proof Artifact(s)

- Test: `test_chat_endpoint_maintains_history` — two sequential messages, second response has awareness of the first (turn_count increases)
- Test: `test_chat_endpoint_turn_count_in_metadata` — metadata SSE event includes `turn_count` field
- Test: `test_chat_endpoint_history_truncation_graceful` — many messages exceeding turn limit, no error, oldest evicted
- Test: `test_chat_mid_stream_error_preserves_user_turn` — simulate Ollama failure, user turn stored, no assistant turn
- CLI: `cd backend && uv run pytest tests/test_chat_service.py tests/test_chat_router.py -v` — all tests pass (existing updated + new)

#### 4.0 Tasks

- [ ] 4.1 Modify `ChatService.__init__()` in `service.py` to accept a `conversation_store: ConversationStore` parameter. Store as `self._conversation_store`. Add the import (under `TYPE_CHECKING`).
- [ ] 4.2 Add `session_id: str` to the `ChatService.stream()` signature. Update the docstring.
- [ ] 4.3 Implement mutation window 1 (pre-stream) at the top of `stream()`, before the search call:
  - `lock = self._conversation_store.get_lock(session_id)`
  - `async with lock:` — get existing turns, add user turn, copy history snapshot.
  - Release lock (exit the `async with` block) before calling search.
- [ ] 4.4 Pass the history snapshot to `build_chat_messages()` via the new `history` parameter. Pass `context_token_budget=self._settings.conversation_context_budget`.
- [ ] 4.5 Accumulate the full assistant response during streaming. Initialize `assistant_text = ""` before the streaming loop. In the `async for content in self._chat_client.chat_stream(messages):` loop, append each `content` chunk to `assistant_text`.
- [ ] 4.6 Implement mutation window 2 (post-stream). After the `yield {"type": SSEEventType.DONE}` line and inside the `try` block: `async with lock:` — call `self._conversation_store.add_turn(session_id, "assistant", assistant_text)`.
- [ ] 4.7 Add `turn_count` to the metadata event dict. After the existing metadata `yield`, the `turn_count` is the number of turns *after* adding the user turn (from window 1): `self._conversation_store.turn_count(session_id)`.  Modify the metadata dict to include `"turn_count": turn_count`.
- [ ] 4.8 Handle the error case: on mid-stream error, the user turn is already stored (from window 1). Do NOT add a partial assistant turn. The existing error handling blocks already handle this — just verify no `add_turn("assistant", ...)` call happens in the error paths.
- [ ] 4.9 Update `_make_chat_service()` in `test_chat_service.py`: add `conversation_store` parameter (default: create a real `ConversationStore` with test settings). Import `ConversationStore` at the top of the test file.
- [ ] 4.10 Update every `_collect_events()` call in `test_chat_service.py` to include `session_id="test-session"`. There are 6 existing calls across 4 test methods.
- [ ] 4.11 Add `test_chat_endpoint_maintains_history` to `test_chat_service.py`. Create a service with a real `ConversationStore`. Call `_collect_events()` twice with the same `session_id`. Verify the second call passes history to `build_chat_messages()` (check the `turn_count` in the metadata event increases from 2 to 4).
- [ ] 4.12 Add `test_chat_endpoint_turn_count_in_metadata` to `test_chat_service.py`. Send one message, verify the metadata event contains `"turn_count"` key with value `1` (the user turn added before streaming).
- [ ] 4.13 Add `test_chat_endpoint_history_truncation_graceful` to `test_chat_service.py`. Create a store with `max_turns=4`. Send 5 messages in sequence. Verify no error, and the store has exactly 4 turns (oldest evicted).
- [ ] 4.14 Add `test_chat_mid_stream_error_preserves_user_turn` to `test_chat_service.py`. Use a chat client that raises `OllamaConnectionError`. Verify the user turn is stored in the conversation store but no assistant turn exists.

### [x] 5.0 DELETE Endpoint, Session Cascade, and Lifespan Wiring

Add `DELETE /api/chat/history` endpoint (returns 204 unconditionally). Wire `ConversationStore` creation in `main.py` lifespan. Start periodic cleanup task. Add `conversation_store.purge_session()` calls at all three session destruction sites in auth code.

#### 5.0 Proof Artifact(s)

- Test: `test_delete_chat_history` — call DELETE, verify next message starts fresh (turn_count resets)
- Test: `test_delete_chat_history_requires_auth` — unauthenticated DELETE returns 401
- Test: `test_delete_chat_history_idempotent` — DELETE with no conversation returns 204; calling twice returns 204 both times
- Test: `test_session_destroy_purges_conversation` — destroy session, verify conversation is removed
- Test: `test_conversation_cleanup_periodic` — verify expired conversations are cleaned up by periodic task
- CLI: `cd backend && uv run pytest tests/ -v --tb=short` — full test suite passes
- CLI: `cd backend && uv run ruff check app/` — no lint errors

#### 5.0 Tasks

- [ ] 5.1 Add `DELETE /api/chat/history` to `create_chat_router()` in `router.py`. The endpoint requires `session: SessionMeta = Depends(get_current_session)`. It retrieves `conversation_store` from `request.app.state.conversation_store` and calls `conversation_store.clear_history(session.session_id)`. Returns `Response(status_code=204)` unconditionally. Import `Response` from `fastapi`.
- [ ] 5.2 Update the `POST /api/chat` handler in `router.py` to pass `session_id=session.session_id` to `service.stream()`.
- [ ] 5.3 Wire `ConversationStore` in the lifespan in `main.py`. After the `ChatService` creation block:
  - Import `ConversationStore`.
  - Create: `conversation_store = ConversationStore(max_turns=settings.conversation_max_turns, ttl_seconds=settings.conversation_ttl_minutes * 60, max_sessions=settings.conversation_max_sessions)`.
  - Store: `app.state.conversation_store = conversation_store`.
  - Pass to `ChatService` constructor: add `conversation_store=conversation_store`.
- [ ] 5.4 Start a periodic conversation cleanup task in the lifespan, after the existing `_periodic_cleanup` task. Follow the same pattern (wrapped in `try/except Exception` + `_logger.warning`):
  ```python
  async def _periodic_conversation_cleanup() -> None:
      while True:
          await asyncio.sleep(300)  # 5 minutes
          try:
              conversation_store.cleanup()
          except Exception:
              _logger.warning("conversation cleanup failed", exc_info=True)
  
  conversation_cleanup_task = asyncio.create_task(_periodic_conversation_cleanup())
  ```
  Cancel this task in the shutdown block (before `yield` returns).
- [ ] 5.5 Add `conversation_store.purge_session(session_id)` call in `backend/app/auth/router.py` after the existing `await session_store.delete(session_id)` in the logout handler (around line 176). Retrieve `conversation_store` from `request.app.state.conversation_store`.
- [ ] 5.6 Modify `cleanup_expired_sessions()` in `backend/app/auth/service.py` to accept an optional `conversation_store` parameter. After each `await store.delete(session.session_id)` call (around line 112), call `conversation_store.purge_session(session.session_id)` if `conversation_store` is not None.
- [ ] 5.7 Modify `AuthService._enforce_session_limit()` in `backend/app/auth/service.py` to accept an optional `conversation_store` parameter. After `await self._store.delete(oldest.session_id)` (around line 49), call `conversation_store.purge_session(oldest.session_id)` if not None.
- [ ] 5.8 Update the callers in `main.py` that pass `conversation_store` to `cleanup_expired_sessions()` and where `AuthService` is constructed/called, so the `conversation_store` parameter is threaded through.
- [ ] 5.9 Add `test_delete_chat_history` to `test_chat_router.py`. Create a chat app with a real `ConversationStore` on `app.state`. Add some turns to the store. Call `DELETE /api/chat/history`. Verify 204 response. Then verify the store has no turns for that session.
- [ ] 5.10 Add `test_delete_chat_history_requires_auth` to `test_chat_router.py`. Create a chat app with `with_auth=False`. Call `DELETE /api/chat/history`. Verify 401 response.
- [ ] 5.11 Add `test_delete_chat_history_idempotent` to `test_chat_router.py`. Call `DELETE /api/chat/history` when no conversation exists. Verify 204. Call it again. Verify 204 again.
- [ ] 5.12 Add `test_session_destroy_purges_conversation` to `test_chat_router.py` or a new `test_session_cascade.py`. Create a `ConversationStore`, add turns, then call `purge_session()`. Verify the conversation is removed.
- [ ] 5.13 Add `test_conversation_cleanup_periodic` to `test_conversation_store.py`. Create a store with `ttl_seconds=0.1`. Add turns. Sleep 0.15s. Call `cleanup()`. Verify conversations are removed and the return count is correct.
- [ ] 5.14 Run `cd backend && uv run pytest tests/ -v --tb=short` — full test suite passes. Run `cd backend && uv run ruff check app/` — no lint errors.
