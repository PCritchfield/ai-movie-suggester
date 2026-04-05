# 15-spec-conversation-memory

## Introduction/Overview

The conversation memory feature adds multi-turn chat capability to the existing single-turn streaming chat endpoint (Spec 12). Users can ask follow-up questions like "more like that last one" or "something scarier" and the system maintains conversational context across turns within a session. Conversations are ephemeral — stored in-process memory only, never persisted to disk — and scoped 1:1 to the user's auth session.

This spec extends `ChatService`, `build_chat_messages()`, and the SSE protocol to support conversation history, context window budget enforcement, and memory lifecycle management.

## Goals

- Add session-scoped conversation memory that maintains configurable turn history (default 10 turns) so users can have natural multi-turn conversations.
- Enforce context window budget using character-based token estimation (chars/4) with a strict truncation priority: system prompt (never truncated) > movie context > recent history > older history.
- Provide a `DELETE /api/chat/history` endpoint so users can reset their conversation without re-authenticating.
- Implement memory lifecycle management with TTL-based expiry, LRU eviction cap, and session-destruction cascade to prevent unbounded memory growth.
- Maintain the project's security constraints: no chat messages persisted to disk, no PII logging, permission filtering at query time (not cached across turns).

## User Stories

- **As a Jellyfin user**, I want to ask follow-up questions like "something scarier" or "more like that second one" so that I can refine my movie recommendations conversationally without repeating context.
- **As a Jellyfin user**, I want to start a fresh conversation by clearing my chat history so that I can change topics without logging out and back in.
- **As an operator**, I want to configure the maximum conversation length so that I can tune memory usage for my model's context window and server resources.
- **As an operator of a publicly accessible server**, I want conversation memory to be automatically cleaned up so that the server doesn't run out of memory from abandoned conversations.

## Demoable Units of Work

### Unit 1: Conversation Store and Turn Management

**Purpose:** Create the in-memory conversation store that holds turn history per session, with configurable limits, TTL/LRU eviction, and session-destruction cascade.

**Functional Requirements:**

- The system shall provide a `ConversationStore` class in `backend/app/chat/conversation_store.py` that stores conversation turns keyed by the auth session's `session_id`.
- The `ConversationStore` shall store turns as a list of `ConversationTurn` dataclasses, each containing `role: str` ("user" or "assistant") and `content: str`.
- The `ConversationStore` shall enforce a configurable maximum turn count (`CONVERSATION_MAX_TURNS` setting, default 10, validated range 1-100). When the limit is exceeded, the oldest turns shall be evicted first (FIFO).
- A "turn" is a single message (one user message = 1 turn, one assistant response = 1 turn). A full exchange is 2 turns.
- The `ConversationStore` shall provide an `asyncio.Lock` per conversation to serialize concurrent reads and writes to the same conversation's history.
- The `ConversationStore` shall track a `last_active` timestamp per conversation and expire conversations after a configurable TTL (`CONVERSATION_TTL_MINUTES` setting, default 120 minutes).
- The `ConversationStore` shall enforce an LRU eviction cap (`CONVERSATION_MAX_SESSIONS` setting, default 100). When the cap is reached, the least-recently-used conversation is evicted.
- The `ConversationStore` shall provide a `purge_session(session_id: str)` method for immediate cleanup on session destruction (logout/expiry).
- The `ConversationStore` shall provide a `clear_history(session_id: str)` method that removes all turns for a session without destroying the lock or metadata.
- The `ConversationStore` shall provide a `cleanup()` method that removes expired conversations (TTL check). This shall be called periodically.
- The `ConversationStore` shall provide `add_turn(session_id, role, content)` and `get_turns(session_id) -> list[ConversationTurn]` methods.
- The `add_turn()` method shall truncate stored content to a maximum of `MAX_TURN_CONTENT_CHARS = 4000` characters. User messages are already capped at 1000 chars by `ChatRequest` validation, but assistant responses from the LLM are unbounded. This cap prevents memory exhaustion from pathologically long model responses. This is a constant in `ConversationStore`, not a configurable setting.
- The session_id shall never be exposed outside the backend. It is an internal key only.

**Proof Artifacts:**

- Test: `test_conversation_store_add_and_get_turns` — add user and assistant turns, verify retrieval in order.
- Test: `test_conversation_store_turn_limit_eviction` — add more than max turns, verify oldest turns are evicted.
- Test: `test_conversation_store_ttl_expiry` — set short TTL, verify conversation is removed after expiry.
- Test: `test_conversation_store_lru_eviction` — fill to capacity, add a new conversation, verify LRU conversation is evicted.
- Test: `test_conversation_store_purge_session` — purge a session, verify conversation is immediately removed.
- Test: `test_conversation_store_clear_history` — clear history, verify turns are empty but session entry persists.
- Test: `test_conversation_store_concurrent_access` — concurrent adds to same session with lock, verify no corruption.
- Test: `test_conversation_store_assistant_turn_truncation` — add an assistant turn exceeding 4000 chars, verify stored content is truncated to `MAX_TURN_CONTENT_CHARS`.
- Test: `test_conversation_max_turns_validation` — verify Settings rejects values outside 1-100 range. Use `Field(ge=1, le=100)` pattern consistent with existing `search_overfetch_multiplier`.

### Unit 2: Context Window Budget Enforcement

**Purpose:** Enforce the existing `context_token_budget` parameter in `build_chat_messages()` using character-based token estimation, with a strict truncation priority that never removes the system prompt.

**Functional Requirements:**

- The system shall modify `build_chat_messages()` in `backend/app/chat/prompts.py` to accept an additional `history: list[ConversationTurn] = []` parameter (default empty list for backward compatibility).
- The system shall provide an `estimate_tokens(text: str) -> int` function in `backend/app/chat/prompts.py` that returns `len(text) // 4` as a conservative token estimate.
- The `build_chat_messages()` function shall enforce `context_token_budget` using `estimate_tokens()` with the following truncation priority (highest priority = never truncated):
  1. **System prompt** (always included in full — contains `STRUCTURAL_FRAMING` and anti-injection instructions)
  2. **Current user query** (always included in full)
  3. **Movie context from current search** (included in full if budget allows, otherwise truncated by reducing `max_results`)
  4. **Recent conversation history** (newest turns preserved, oldest turns dropped first)
- When history is provided, `build_chat_messages()` shall return a message list in Ollama's expected format: `[system, ...history_turns, movie_context, user_query]` where history turns alternate `{"role": "user", "content": ...}` and `{"role": "assistant", "content": ...}`.
- The system shall add `CONVERSATION_CONTEXT_BUDGET: int = 6000` to `Settings` (estimated tokens). This replaces the hardcoded `context_token_budget=4000` default, giving room for both movie context and conversation history.
- The `build_chat_messages()` function shall allocate the budget as: total budget minus system prompt tokens minus current query tokens = remaining budget. Conversation history and movie context share the remaining budget, with movie context taking priority.

**Proof Artifacts:**

- Test: `test_estimate_tokens` — verify `estimate_tokens("hello world")` returns `len("hello world") // 4`.
- Test: `test_build_chat_messages_with_history` — provide history turns, verify they appear in the message list between system prompt and current context.
- Test: `test_build_chat_messages_history_truncation` — provide history that exceeds budget, verify oldest turns are dropped while newest are preserved.
- Test: `test_build_chat_messages_system_prompt_never_truncated` — even with massive history, verify system prompt is always present and complete.
- Test: `test_build_chat_messages_backward_compatible` — call without history parameter, verify output matches current single-turn behavior.
- Test: `test_build_chat_messages_budget_allocation` — verify movie context is preserved when history is truncated.
- Test: `test_build_chat_messages_budget_exhausted_by_system_and_query` — when system prompt + user query alone exceed the budget, return `[system, user_query]` with no history and no movie context. Graceful degradation, not a crash.

### Unit 3: ChatService Integration and Endpoint Changes

**Purpose:** Wire the conversation store into `ChatService`, update the chat endpoint to read/write history on each request, and add the `DELETE /api/chat/history` endpoint.

**Functional Requirements:**

- The `ChatService.__init__()` shall accept a `conversation_store: ConversationStore` parameter.
- The `ChatService.stream()` method shall use a narrow lock scope with two mutation windows:
  1. **Mutation window 1 (pre-stream):** Acquire the conversation lock. Retrieve existing conversation history via `conversation_store.get_turns(session_id)`. Add the user's message as a turn (`role="user"`). Copy the history snapshot for prompt building. Release the lock.
  2. **Unlocked phase:** Pass history snapshot to `build_chat_messages()`. Stream LLM response, accumulating the full assistant response text. A concurrent request arriving during this phase will see the user turn but not the partial assistant response — this is correct behavior.
  3. **Mutation window 2 (post-stream):** Re-acquire the conversation lock. Add the assistant response as a turn (`role="assistant"`). Release the lock.
  4. On error mid-stream, the user turn is already stored (from window 1). Do not add a partial assistant turn. The lock is not held during streaming, so errors do not leave locks dangling.
- The `ChatService.stream()` signature shall gain a `session_id: str` parameter: `stream(self, query: str, user_id: str, token: str, session_id: str)`.
- The SSE metadata event shall include an optional `turn_count: int` field indicating the current number of turns in the conversation (including the current exchange). This is additive to the existing v1 protocol.
- The system shall expose `DELETE /api/chat/history` in the chat router. This endpoint:
  - Requires session authentication via `get_current_session`.
  - Calls `conversation_store.clear_history(session.session_id)`.
  - Returns `204 No Content` unconditionally (clearing a nonexistent conversation is a no-op, not an error). This avoids timing oracles that leak conversation existence.
- The chat router shall pass `session.session_id` to `ChatService.stream()`.
- The `ConversationStore` shall be created in the lifespan in `main.py`, stored on `app.state.conversation_store`, and passed to `ChatService`.
- The lifespan shall start a periodic cleanup task that calls `conversation_store.cleanup()` every 5 minutes (configurable is not required — hardcoded interval is fine).
- Session destruction shall cascade to `ConversationStore.purge_session()` at every code path where sessions are destroyed. There are exactly three call sites: (a) explicit logout in `auth/router.py`, (b) periodic `cleanup_expired_sessions` in `auth/service.py`, (c) LRU eviction in `AuthService._enforce_session_limit`. Each call site shall invoke `conversation_store.purge_session(session_id)` immediately after `session_store.delete(session_id)`. No callback/observer pattern — direct calls at each site. The conversation TTL is a safety net, not the primary cleanup mechanism.

**Proof Artifacts:**

- Test: `test_chat_endpoint_maintains_history` — send two messages in sequence, verify the second response has awareness of the first exchange (turn_count increases).
- Test: `test_chat_endpoint_turn_count_in_metadata` — verify the metadata SSE event includes `turn_count` field.
- Test: `test_chat_endpoint_history_truncation_graceful` — send many messages exceeding turn limit, verify no error and oldest turns are evicted.
- Test: `test_delete_chat_history` — call `DELETE /api/chat/history`, verify next message starts fresh (turn_count resets).
- Test: `test_delete_chat_history_requires_auth` — unauthenticated DELETE returns 401.
- Test: `test_delete_chat_history_idempotent` — DELETE when no conversation exists returns 204 (not 404). Calling DELETE twice returns 204 both times.
- Test: `test_chat_mid_stream_error_preserves_user_turn` — simulate Ollama failure, verify user turn is stored but no assistant turn.
- Test: `test_session_destroy_purges_conversation` — destroy session, verify conversation is removed.
- Test: `test_conversation_cleanup_periodic` — verify expired conversations are cleaned up by the periodic task.

## Non-Goals (Out of Scope)

1. **Persistent conversation history across server restarts**: Conversations are in-process memory only. Persistence would require encryption-at-rest and a retention policy (per Angua's security review).
2. **Multiple conversations per user session**: One conversation per auth session. Multi-conversation support is a separate spec if needed.
3. **Conversation search or export**: No API to retrieve full conversation history. The store is internal to the chat service.
4. **Actual token counting**: Character-based estimation (chars/4) is sufficient for v1. A tokenizer dependency adds complexity with low payoff.
5. **Programmatic follow-up resolution**: No parsing of user messages to detect "more like that" patterns. The LLM handles coreference from conversation history naturally.
6. **Caching recommendation IDs across turns**: Each turn re-queries the search service. Permission filtering at query time is maintained — no stale permission data cached in conversation memory.

## Design Considerations

### Message List Structure

The Ollama chat API expects a `messages` list with `role` and `content` fields. With conversation history, the message list becomes:

```
[
  {"role": "system", "content": "<STRUCTURAL_FRAMING + conversational tone>"},
  {"role": "user", "content": "<turn 1 user message>"},
  {"role": "assistant", "content": "<turn 1 assistant response>"},
  {"role": "user", "content": "<turn 2 user message>"},
  {"role": "assistant", "content": "<turn 2 assistant response>"},
  ...oldest turns may be truncated...
  {"role": "user", "content": "Movies similar to: <title1>, <title2>...\n\n<current movie context>"},
  {"role": "user", "content": "<current user query>"}
]
```

History turns are inserted between the system prompt and the current movie context. The current search results are always fresh (re-queried per request) and placed immediately before the user's query.

**Note on consecutive user messages:** The message list ends with two consecutive `user` role messages (movie context + user query). This matches the existing single-turn behavior from Spec 12 and works with llama3.1:8b. However, some models enforce strict role alternation and may mishandle this. If a future model swap causes issues, the fix is to fold the movie context into the final user message as a single combined message. This is not required for v1.

### SSE Protocol (v1, additive change)

The metadata event gains an optional `turn_count` field:

```json
{"type": "metadata", "version": 1, "recommendations": [...], "search_status": "ok", "turn_count": 4}
```

Existing frontends that don't understand `turn_count` ignore it. No version bump required.

### Memory Layout

```
ConversationStore
├── _conversations: dict[str, ConversationEntry]
│   └── ConversationEntry
│       ├── turns: list[ConversationTurn]  (role + content)
│       ├── lock: asyncio.Lock
│       ├── last_active: float  (time.monotonic — for TTL/LRU, not affected by clock adjustments)
│       └── created_at: float  (time.time — wall clock, meaningful for logging)
├── _max_turns: int  (from Settings)
├── _ttl_seconds: float  (from Settings)
└── _max_sessions: int  (from Settings)
```

## Repository Standards

- **Settings via Pydantic BaseSettings**: New settings `CONVERSATION_MAX_TURNS` (int, default 10, ge=1, le=100), `CONVERSATION_TTL_MINUTES` (int, default 120), `CONVERSATION_MAX_SESSIONS` (int, default 100), `CONVERSATION_CONTEXT_BUDGET` (int, default 6000) in `backend/app/config.py`.
- **Router factory pattern**: The DELETE endpoint is added to the existing `create_chat_router()` factory.
- **Service layer**: `ChatService` owns orchestration. The router is a thin HTTP adapter.
- **Lifespan wiring**: `ConversationStore` created in the lifespan, stored on `app.state`, passed to `ChatService`.
- **Logging**: Structured key=value format. Log conversation lifecycle events (create, evict, clear, purge) at INFO. Never log message content.
- **Conventional commits**: `feat(chat):` prefix for this spec.
- **Async/await**: All I/O and lock operations use async.
- **Type hints**: All function signatures have type annotations.

## Technical Considerations

### New Files

| File | Purpose |
|------|---------|
| `backend/app/chat/conversation_store.py` | `ConversationStore` — in-memory conversation history with TTL/LRU |

### Modified Files

| File | Change |
|------|--------|
| `backend/app/chat/prompts.py` | Add `history` parameter to `build_chat_messages()`. Add `estimate_tokens()`. Implement budget enforcement with truncation priority. |
| `backend/app/chat/service.py` | Add `conversation_store` to `ChatService.__init__()`. Read/write history in `stream()`. Add `session_id` parameter to `stream()`. Accumulate assistant response for storage. **Breaking change:** existing `test_chat_service.py` tests call `stream()` without `session_id` and `_make_chat_service()` without `conversation_store` — all existing tests must be updated. |
| `backend/app/chat/router.py` | Pass `session_id` to `ChatService.stream()`. Add `DELETE /api/chat/history` endpoint. |
| `backend/app/chat/models.py` | Add `turn_count` to metadata event construction if applicable. (`ConversationTurn` dataclass lives in `conversation_store.py`, not here.) |
| `backend/app/config.py` | Add `CONVERSATION_MAX_TURNS`, `CONVERSATION_TTL_MINUTES`, `CONVERSATION_MAX_SESSIONS`, `CONVERSATION_CONTEXT_BUDGET` to Settings. |
| `backend/app/main.py` | Create `ConversationStore` in lifespan. Pass to `ChatService`. Start periodic cleanup task (wrapped in `try/except Exception` + log warning, matching existing periodic task pattern). Store on `app.state`. |
| `backend/app/auth/router.py` | Add `conversation_store.purge_session(session_id)` after `session_store.delete()` in logout handler. |
| `backend/app/auth/service.py` | Add `conversation_store.purge_session(session_id)` after `store.delete()` in `cleanup_expired_sessions()` and `_enforce_session_limit()`. |

### Dependencies

- `ChatService` (Spec 12) — extended with conversation store.
- `SessionStore` (Spec 03) — session destruction cascades to conversation purge.
- `build_chat_messages()` (Spec 12) — extended with history parameter and budget enforcement.
- No new external dependencies. All implementation uses stdlib (`asyncio`, `time`, `dataclasses`, `collections`).

## Security Considerations

- **No disk persistence**: Conversation content is never written to disk. In-process memory only. This maintains the project constraint: "Never log PII, chat messages, or tokens." (Angua — strong position, near-veto.)
- **Session ID isolation**: The auth session_id is the internal key for conversations but is never exposed in SSE events, API responses, or logs. If a conversation identifier is needed in the protocol, it must be an opaque derived token (`secrets.token_urlsafe`).
- **Permission filtering at query time**: Each turn re-queries the search service with fresh permission checks. No recommendation data (Jellyfin item IDs, search results) is cached across turns. A user whose Jellyfin permissions change mid-session gets correct filtering on the next turn.
- **Data minimization**: Only message text (role + content) is stored per turn. No item IDs, no search results, no metadata.
- **Memory exhaustion protection**: TTL (default 2h) + LRU cap (default 100 sessions) + turn limit (default 10, max 100) bound memory usage. Session destruction cascades to immediate purge.
- **Context window safety**: Budget enforcement ensures conversation history cannot overflow the model's context window. The system prompt (containing `STRUCTURAL_FRAMING` and anti-injection instructions) is never truncated regardless of history size.
- **CSRF protection**: The `DELETE /api/chat/history` endpoint is covered by the existing `CSRFMiddleware` (exempts only GET/HEAD/OPTIONS).
- **No existence leakage**: `DELETE /api/chat/history` returns 204 unconditionally. Clearing a nonexistent conversation is a no-op — no timing oracle to probe conversation existence.
- **Assistant response size cap**: Stored assistant turns are truncated to 4000 characters to prevent memory exhaustion from pathologically long model responses. Combined with turn limits, LRU cap, and TTL, this bounds per-session and total memory usage.

## Success Metrics

1. **Multi-turn coherence**: A user can ask "something like Alien but funny," receive recommendations, then ask "more like that second one" and get a relevant response referencing the prior recommendation.
2. **Turn limit enforcement**: Conversations gracefully truncate at the configured limit without errors. Oldest turns are evicted, newest preserved.
3. **Budget enforcement**: Conversations with many turns do not cause Ollama context overflow. The system prompt is always present and complete.
4. **Memory stability**: On a server running for 24+ hours with active users, memory usage from conversation storage remains bounded by TTL + LRU limits.
5. **Clear endpoint**: `DELETE /api/chat/history` resets the conversation. The next message starts fresh with `turn_count: 2` (the new user/assistant pair).
6. **Backward compatibility**: The SSE protocol change is additive. Existing frontends work without modification (they ignore `turn_count`).
7. **Test coverage**: All functional requirements covered by unit tests. Integration tests validate multi-turn conversation flow with mocked Ollama.

## Open Questions

1. Should `CONVERSATION_CONTEXT_BUDGET` default to 6000 tokens (estimated), or should it be derived from the model's actual context window? For llama3.1:8b with an 8192-token context, 6000 leaves ~2000 tokens for the response. If the operator swaps to a model with a larger context window, they would need to increase this setting.
2. Should the periodic cleanup interval (5 minutes) be configurable, or is a hardcoded constant sufficient? Recommendation: hardcode for v1.

## Council Review Notes (incorporated)

The following items were raised during the council's final review and have been incorporated into the spec above:

1. **Lock scope narrowed** (Granny) — Lock held only during mutation windows, not across LLM streaming.
2. **Session-destroy cascade made explicit** (Granny + Angua + Carrot) — Three specific call sites identified, direct calls, no callback pattern.
3. **DELETE returns 204 unconditionally** (Granny + Angua) — Avoids timing oracle, simplifies frontend.
4. **Assistant response truncation** (Angua) — 4000 char cap on stored assistant turns.
5. **Double-user-message risk documented** (Granny) — Known limitation with alternation-strict models.
6. **Clock types pinned** (Granny) — `time.monotonic` for `last_active`, `time.time` for `created_at`.
7. **Existing test breakage noted** (Carrot) — `test_chat_service.py` must be updated for new `stream()` signature.
8. **Budget exhaustion edge case test added** (Granny) — Graceful degradation when system prompt + query exceeds budget.
