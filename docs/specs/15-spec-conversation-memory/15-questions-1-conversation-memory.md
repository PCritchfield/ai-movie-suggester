# 15 Questions Round 1 - Conversation Memory

Answered via Watch Council review (Granny, Angua, Carrot) on 2026-04-05.

## 1. Conversation Identity and Lifecycle

The current `POST /api/chat` has no conversation concept — each request is independent. Issue #113 proposes adding a `session_id` field. However, the auth session (`session_id` from the cookie) already exists. Should conversations be tied 1:1 to the auth session, or should there be a separate `conversation_id` allowing multiple conversations per auth session?

- [x] (A) One conversation per auth session — with compromise: session_id is the internal key but is **never exposed** in SSE events or responses. If the frontend needs a conversation identifier, derive an opaque token server-side.
- [ ] (B) Separate `conversation_id`
- [ ] (C) Other

**Council notes:** Granny and Carrot favored A for simplicity. Angua favored B because session IDs are security-sensitive (decrypt Jellyfin tokens). Compromise adopted: A's simplicity with Angua's constraint that the session_id never leaks into the protocol.

## 2. Storage Backend

Conversation history needs to live somewhere between requests. Issue #113 says "session-scoped memory (not DB — conversations are ephemeral)." This means in-process Python memory, which is lost on server restart.

- [x] (A) In-process memory only (dict keyed by session ID) — simplest, ephemeral, conversations lost on restart. Fine for a single-backend deployment.
- [ ] (B) In-process with optional SQLite persistence
- [ ] (C) SQLite only
- [ ] (D) Other

**Council notes:** Granny and Angua aligned on A. Angua's strong position: persisting chat messages to disk is functionally logging PII, violating the project's explicit constraint. Carrot preferred B for UX continuity but deferred to Angua's security reasoning.

## 3. Turn Limit and Eviction

Issue #113 proposes 10 turns (5 user + 5 assistant). When the limit is exceeded, oldest turns are evicted. Should this be configurable?

- [ ] (A) Hardcoded default (10 turns), not configurable
- [x] (B) Configurable via `CONVERSATION_MAX_TURNS` env var with default of 10, validated range min 1 / max 100 — follows the existing Settings pattern. Operator can tune for their model's context window.
- [ ] (C) Other

**Council notes:** Unanimous on B. Angua added the hard ceiling requirement (clamped 1-100) to prevent resource exhaustion.

## 4. Context Window Budget Management

The current `build_chat_messages()` has a `context_token_budget=4000` parameter that's accepted but not enforced. Issue #113 proposes actual token counting with a priority system: system prompt > movie context > recent history > older history.

- [x] (A) Character-based estimation (chars / 4 as rough token count) — fast, no dependencies, good enough for v1. **Budget is enforced.** Truncation order: system prompt is never truncated (contains anti-injection framing), then movie context preserved, then recent history preserved over older history.
- [ ] (B) Actual token counting with `tiktoken` or similar
- [ ] (C) No enforcement in v1 — **Angua vetoed this option.**
- [ ] (D) Other

**Council notes:** Unanimous on A. Angua vetoed C — unenforced budget allows context overflow. Hard requirement: STRUCTURAL_FRAMING is never truncated.

## 5. Follow-up Resolution Strategy

Issue #113 mentions resolving "more like that" and "not that one" references. The issue says "best-effort via prompt engineering, not deterministic logic."

- [x] (A) Pure prompt engineering — include the conversation history in the message list. The LLM naturally handles follow-ups from context. No special parsing or exclusion logic.
- [ ] (B) Lightweight programmatic support
- [ ] (C) Other

**Council notes:** Unanimous on A. Angua noted that programmatic parsing creates a new attack surface. The LLM handles coreference resolution from conversation history naturally.

## 6. Conversation Clear / Reset

Issue #113 proposes `DELETE /api/chat/{session_id}` to clear history. Is a dedicated endpoint needed, or is there a simpler approach?

- [x] (A) `DELETE /api/chat/history` — clears the current user's conversation (identified from auth cookie). Always returns 204 (no-op if no conversation exists) to avoid leaking existence.
- [ ] (B) `DELETE /api/chat/{conversation_id}`
- [ ] (C) No dedicated endpoint
- [ ] (D) Other

**Council notes:** Unanimous on A. Angua added: return 204 unconditionally to avoid existence leakage; CSRF middleware already covers DELETE.

## 7. SSE Protocol Changes

The current metadata event has `version: 1`. Adding conversation context will change what the backend sends.

- [ ] (A) Bump to `version: 2`
- [x] (B) Keep `version: 1` and add optional fields — backwards compatible, additive change. Any conversation identifier in SSE events must be opaque (e.g. `secrets.token_urlsafe`), never derived from session_id.
- [ ] (C) Other

**Council notes:** Unanimous on B. Angua: any exposed identifier must be opaque, not sequential or session-derived.

## 8. Concurrency and Race Conditions

Issue #113 says "concurrent requests on same session -> last-write-wins (no locking)."

- [ ] (A) Last-write-wins
- [x] (B) Simple asyncio.Lock per conversation — serialize conversation reads/writes. Prevents interleaving and history corruption.
- [ ] (C) Other

**Council notes:** Carrot and Angua favored B for correctness. Granny dissented: lock solves a nonexistent problem in a single-user-per-session deployment. Phil chose B.

## 9. Memory Cleanup

In-process conversation memory will grow unbounded if not cleaned up.

- [ ] (A) TTL-based
- [ ] (B) LRU eviction
- [x] (C) Both TTL and LRU — TTL of 1-2 hours (shorter than session expiry). LRU cap configurable (default 100). Session destruction (logout/expiry) cascades to immediate conversation purge.
- [ ] (D) Other

**Council notes:** Angua's strong position adopted. TTL handles idle conversations, LRU handles active abuse. Session destroy must cascade immediately — don't wait for TTL/LRU.

## 10. What Gets Stored Per Turn

Each turn in the conversation history needs to include enough context for the LLM.

- [x] (A) Messages only — store the user message and assistant response text. On follow-up, re-run search with the new query and build fresh movie context. History provides conversational continuity only.
- [ ] (B) Messages + recommendation IDs
- [ ] (C) Messages + full search results
- [ ] (D) Other

**Council notes:** Angua's strong position adopted. Data minimization: don't cache permission-sensitive data (Jellyfin item IDs) across turns. The assistant's response text already names the recommended movies, giving the LLM sufficient referents for follow-up resolution. Permission filtering at query time must hold for conversation memory too. Granny withdrew objection to A after recognizing the assistant response contains the movie titles.
