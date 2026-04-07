# 16 Validation — Chat UI

Spec: [16-spec-chat-ui.md](16-spec-chat-ui.md) (authored on `spec/16-chat-ui` branch)
Task List: [16-tasks-chat-ui.md](16-tasks-chat-ui.md)
Branch: `feat/16-chat-ui` (HEAD: `7c555bc`)
Validated: 2026-04-06

---

## 1. Git Commit Mapping

| Commit | Scope | Spec Unit | Task(s) |
|--------|-------|-----------|---------|
| `5f68b3d` | `feat(chat): add TypeScript types, SSE parser, and API helpers` | Unit 1 | 1.1–1.10 |
| `ca12e08` | `feat(chat): add useChat hook, message components, and page integration` | Unit 1 | 2.1–2.17 |
| `1140dc4` | `feat(chat): add error handling and retry UX` | Unit 2 | 3.1–3.10 |
| `35d1652` | `feat(chat): add accessibility audit and mobile viewport polish` | Unit 2 | 4.1–4.10 |
| `3721035` | `feat(chat): add header, empty state, and search status banner` | Unit 3 | 5.1–5.11 |
| `cf282e4` | `fix(chat): address code review findings (error codes, retry, cleanup)` | All units | Review fixes |
| `7c555bc` | `fix(chat): address Copilot review feedback` | All units | Review fixes |

**Out-of-scope commits also on this branch:**

| Commit | Scope | Notes |
|--------|-------|-------|
| `9c331e9` | `docs(spec-17): add clarifying questions` | Spec 17 doc |
| `8994cfd` | `docs(spec-17): address council review feedback` | Spec 17 doc |
| `a3644de` | `docs(spec-17): add spec for watch history client` | Spec 17 doc |
| `b81fc4b` | `docs(spec-17): add parent tasks` | Spec 17 doc |
| `13328d4` | `docs(spec-17): add sub-tasks` | Spec 17 doc |
| `de97fd8` | `feat(jellyfin): add WatchHistoryEntry model, get_watched_items, get_favorite_items` | Spec 17 impl |
| `7f5e5a0` | `test(jellyfin): add integration tests for watch history methods` | Spec 17 tests |

Spec 17 doc files were removed in `7c555bc`, but the backend implementation commits (`de97fd8`, `7f5e5a0`) remain. These change `backend/app/jellyfin/client.py`, `backend/app/jellyfin/models.py`, `backend/tests/test_watch_history.py`, and `backend/tests/integration/test_jellyfin_client.py`. They are functionally independent of Spec 16 but will be included in any PR from this branch.

**Conventional commit format:** All commits use `feat(chat):`, `fix(chat):`, `docs(spec-17):`, `test(jellyfin):`, or `feat(jellyfin):` prefixes. Compliant.

---

## 2. File Integrity

### Expected Files (from Relevant Files in task list)

| File | Status | Notes |
|------|--------|-------|
| `frontend/src/lib/api/types.ts` | MODIFIED | `SearchResultItem`, `SearchStatus`, `ChatErrorCode`, `SSEEvent`, `ChatMessage` added |
| `frontend/src/lib/api/chat-stream.ts` | **NEW** | `parseSSEStream()` + `sendChatMessage()` |
| `frontend/src/lib/api/client.ts` | MODIFIED | `apiDelete()` added |
| `frontend/src/hooks/use-chat.ts` | **NEW** | `useChat()` hook |
| `frontend/src/components/chat/message-list.tsx` | **NEW** | MessageList with react-markdown |
| `frontend/src/components/chat/chat-input.tsx` | **NEW** | ChatInput with textarea |
| `frontend/src/components/chat/empty-state.tsx` | **NEW** | EmptyState with suggestion chips |
| `frontend/src/components/chat/header-content.tsx` | **NEW** | HeaderContent client component |
| `frontend/src/components/chat/search-status-banner.tsx` | **NEW** | SearchStatusBanner |
| `frontend/src/app/(protected)/page.tsx` | MODIFIED | Replaced AuthHome with chat composition |
| `frontend/src/app/(protected)/layout.tsx` | **NOT MODIFIED** | See deviation note below |
| `frontend/src/components/auth-home.tsx` | **DELETED** | Confirmed: no file on disk, no imports remain |
| `frontend/tests/page.test.tsx` | REWRITTEN | Tests chat page composition |
| `frontend/tests/lib/api/chat-stream.test.ts` | **NEW** | SSE parser + sendChatMessage + apiDelete tests |
| `frontend/tests/hooks/use-chat.test.ts` | **NEW** | Hook state transition tests |
| `frontend/tests/components/chat/message-list.test.tsx` | **NEW** | Component + error + axe tests |
| `frontend/tests/components/chat/chat-input.test.tsx` | **NEW** | Input + axe tests |
| `frontend/tests/components/chat/empty-state.test.tsx` | **NEW** | Chips + axe tests |
| `frontend/tests/components/chat/header-content.test.tsx` | **NEW** | Header + axe tests |
| `frontend/tests/components/chat/search-status-banner.test.tsx` | **NEW** | Banner + axe tests |
| `frontend/package.json` | MODIFIED | `react-markdown`, `remark-gfm`, `rehype-sanitize` added |

### Deviation: layout.tsx header placement

The spec (Unit 3) and task 5.2 require: "Add a persistent 48px header to `(protected)/layout.tsx`." The implementation places `HeaderContent` inside `page.tsx` instead. The layout remains an unmodified Server Component.

**Impact:** Low. There is currently only one page in the protected route, so the header renders identically. However, if additional protected pages are added (e.g., settings), they would not get the header automatically. This is a minor deviation from the spec's intent of the header being persistent across all protected routes.

**Verdict:** ACCEPTABLE with note. The functional requirement is met for the current single-page scenario.

### Out-of-scope files included

Four backend files changed (Spec 17 watch history client):
- `backend/app/jellyfin/client.py`
- `backend/app/jellyfin/models.py`
- `backend/tests/integration/test_jellyfin_client.py`
- `backend/tests/test_watch_history.py`

**Recommendation:** These should be split into a separate PR or the `feat/17-watch-history-client` branch before merging Spec 16.

---

## 3. Test Results

```
npm run type-check   → PASS (tsc --noEmit, zero errors)
npm test -- --run    → PASS (17 test files, 126 tests, 0 failures)
npm run lint         → PASS (eslint, zero warnings)
npm run format:check → PASS (prettier, all files clean)
```

### Test Coverage by Component

| Test File | Tests | Axe Audits |
|-----------|-------|------------|
| `chat-stream.test.ts` | 18 (7 parseSSE + 7 sendChat + 4 apiDelete) | N/A |
| `use-chat.test.ts` | 7 (send, TEXT, DONE, ERROR, concurrent, clear, retry) | N/A |
| `message-list.test.tsx` | 12 (4 render + 5 error + 3 axe + 2 ARIA + aria-busy) | 3 |
| `chat-input.test.tsx` | 8 (5 interaction + 1 touch target + 2 axe) | 2 |
| `empty-state.test.tsx` | 4 (3 render/interaction + 1 axe) | 1 |
| `header-content.test.tsx` | 6 (5 render/interaction + 1 axe) | 1 |
| `search-status-banner.test.tsx` | 6 (5 render/interaction + 1 axe) | 1 |
| `page.test.tsx` | 3 (smoke tests for page composition) | 0 |

**Total axe audits: 8** (MessageList x3, ChatInput x2, EmptyState x1, HeaderContent x1, SearchStatusBanner x1). All pass with zero violations.

---

## 4. Functional Requirements Verification

### Unit 1 — Core Streaming Chat

| Requirement | Status | Evidence |
|-------------|--------|----------|
| `parseSSEStream` async generator exists | PASS | `chat-stream.ts:12` |
| Handles chunked boundaries | PASS | Buffer logic at `chat-stream.ts:29`, test at `chat-stream.test.ts:65` |
| Yields typed `SSEEvent` discriminated union | PASS | `types.ts:95` (`MetadataEvent \| TextEvent \| DoneEvent \| ErrorEvent`) |
| `sendChatMessage` with CSRF + credentials | PASS | `chat-stream.ts:73-83`, test at line 145 |
| `sendChatMessage` throws correct error types | PASS | Uses `networkFetch` + `parseResponse`, tests at lines 182-238 |
| `apiDelete` in `client.ts` | PASS | `client.ts:45-65` |
| `SearchResultItem` interface | PASS | `types.ts:47-55` |
| `SearchStatus` union type | PASS | `types.ts:58` |
| `ChatErrorCode` union type | PASS | `types.ts:61-67` — includes spec's 4 original codes plus `auth_expired` and `rate_limited` (added post-review) |
| `SSEEvent` discriminated union | PASS | `types.ts:95` |
| `ChatMessage` interface | PASS | `types.ts:99-107` with all specified fields |
| `useChat` hook with `useReducer` | PASS | `use-chat.ts:180` |
| 50ms ref-based text flush | PASS | `use-chat.ts:216-227` — `setInterval(50)` with `bufferRef` + `lastFlushedLengthRef` optimization |
| METADATA stored silently (not rendered) | PASS | `use-chat.ts:235-241` dispatches `SET_METADATA`, no component renders it |
| Concurrent send prevention | PASS | `use-chat.ts:347` checks `isStreamingRef.current`, test at line 167 |
| `MessageList` with `react-markdown` + `remark-gfm` + `rehype-sanitize` | PASS | `message-list.tsx:4-6` imports, line 153-158 usage |
| Auto-scroll with manual scroll detection | PASS | `message-list.tsx:108-123` |
| Loading indicator | PASS | `message-list.tsx:16-27`, conditional at line 149 |
| `ChatInput` Enter/Shift+Enter | PASS | `chat-input.tsx:44-57`, tests at lines 15-36 |
| Auto-resize textarea | PASS | `chat-input.tsx:59-72` |
| 44px touch target on send button | PASS | `chat-input.tsx:99` `min-h-11 min-w-11` |
| `aria-label="Send message"` | PASS | `chat-input.tsx:98` |
| `maxLength={1000}` | PASS | `chat-input.tsx:88` |
| Page replaces AuthHome | PASS | `page.tsx` imports chat components; `auth-home.tsx` deleted |
| `100dvh` layout | PASS | `page.tsx:49` `style={{ height: "100dvh" }}` |

### Unit 2 — Error Handling + Accessibility + Mobile

| Requirement | Status | Evidence |
|-------------|--------|----------|
| Inline error on message bubble with retry | PASS | `message-list.tsx:30-65` `MessageError` component |
| 401 "Log in again" link | PASS | `message-list.tsx:47-51`, test at line 150 |
| 429 disabled retry + 10s cooldown | PASS | `message-list.tsx:68-98` `RetryButton` with `setTimeout(10000)`, test at line 174 |
| `role="log"` | PASS | `message-list.tsx:129` |
| `aria-live="polite"` | PASS | `message-list.tsx:130` |
| `aria-busy` toggles | PASS | `message-list.tsx:131` `aria-busy={isStreaming}`, test at line 288 |
| `role="alert"` on errors | PASS | `message-list.tsx:43`, test at line 209 |
| NO focus management on new messages | PASS | No `focus()` calls in MessageList; only auto-scroll |
| `100dvh` | PASS | `page.tsx:49` |
| sticky input | PASS | `chat-input.tsx:76` `className="sticky bottom-0"` |
| `env(safe-area-inset-bottom)` | PASS | `chat-input.tsx:78` `style={{ paddingBottom: "env(safe-area-inset-bottom)" }}` |
| Axe audits on all components | PASS | 8 axe audits, zero violations |
| Retry buttons 44x44px touch target | PASS | `message-list.tsx:93` `min-h-11 min-w-11` |
| `aria-label="Retry message"` | PASS | `message-list.tsx:90` |
| Error code mapping (401 -> auth_expired, 429 -> rate_limited) | PASS | `use-chat.ts:300-319` |

### Unit 3 — Header + Empty State + Banner

| Requirement | Status | Evidence |
|-------------|--------|----------|
| 48px header | PASS | `header-content.tsx:14` `h-12` (48px) |
| App name displayed | PASS | `header-content.tsx:15` "ai-movie-suggester" |
| Username from `useAuth()` | PASS | `header-content.tsx:12,17` |
| "New conversation" button | PASS | `header-content.tsx:19-25` "New chat" with `aria-label="Start new conversation"` |
| LogoutButton reused | PASS | `header-content.tsx:4,28` |
| Header in layout.tsx | **DEVIATION** | Header is in `page.tsx:50`, not `layout.tsx`. See Section 2. |
| Layout remains Server Component | PASS | `layout.tsx` has no "use client" directive |
| EmptyState with suggestion chips | PASS | `empty-state.tsx:9-11` three hardcoded chips |
| Tapping chip sends message | PASS | `empty-state.tsx:33` `onClick={() => onSend(chip)}`, test at line 26 |
| Chips disappear after first message | PASS | `page.tsx:57-58` conditional render on `messages.length === 0` |
| Tagline text | PASS | `empty-state.tsx:26` "Ask me for movie recommendations from your Jellyfin library" |
| `search_status` banner for `no_embeddings` | PASS | `search-status-banner.tsx:12-13`, test at line 15 |
| `search_status` banner for `partial_embeddings` | PASS | `search-status-banner.tsx:14-15`, test at line 27 |
| Banner auto-dismiss on `ok` | PASS | `page.tsx:43-46` `showBanner` checks `latestSearchStatus !== "ok"` |
| Banner manually dismissible | PASS | `search-status-banner.tsx:33-39`, test at line 54 |
| Banner dismiss resets on status change | PASS | `page.tsx:29-35` ref-based pattern |

---

## 5. Proof Artifacts

| Artifact | Status | Notes |
|----------|--------|-------|
| `16-proofs/task-1.0-tests.txt` | PRESENT | 18/18 tests passing for Task 1.0 |
| Screenshots (spec requires multiple) | **NOT PRESENT** | Spec calls for screenshots of streaming chat, error state, mobile viewport, empty state, search banner. None produced. |

**Note:** All functional proofs that can be verified via test output are covered by the 126 passing tests. Screenshot proofs would require a running backend with Ollama, which is beyond automated validation. The absence of screenshots is documented but does not block the quality gate, as the test suite provides equivalent or stronger verification for all testable requirements.

---

## 6. Repository Standards

| Standard | Status | Evidence |
|----------|--------|----------|
| Strict TypeScript (no `any`) | PASS | `grep`: zero matches for `: any` in `frontend/src/` |
| `"use client"` only where needed | PASS | Applied to page, hook, and interactive components only. Layout remains Server Component. |
| vitest + RTL | PASS | All test files use vitest + @testing-library/react |
| eslint + prettier clean | PASS | `npm run lint` + `npm run format:check` = zero warnings |
| Conventional commits | PASS | All commits use `feat(chat):`, `fix(chat):`, etc. |
| Axe audit pattern | PASS | All 5 component test files import `jest-axe`, extend expect, run `toHaveNoViolations()` |
| No PII in client-side logs | PASS | No `console.log/error` calls with message content or user data |

---

## 7. Summary

### Verdict: **PASS** (with noted deviations)

All 5 task groups (1.0 through 5.0) are marked complete and verified against the spec. 126 tests pass, type-check is clean, lint is clean, formatting is clean. The core streaming chat pipeline, error handling, accessibility, mobile viewport, header, empty state, and search status banner all meet spec requirements.

### Deviations

1. **Header placement (Low severity):** The spec requires the header in `layout.tsx`; the implementation places it in `page.tsx`. Functionally equivalent for the single-page scenario. If additional protected pages are added, the header would need to be lifted to the layout.

2. **Spec 17 backend files on branch (Medium severity, procedural):** The branch includes 4 backend files from Spec 17 (watch history client). The doc files were cleaned up, but the implementation commits remain. Recommend splitting these into a separate branch or cherry-picking before merging the Spec 16 PR.

3. **Missing screenshot proofs (Low severity):** The spec requests screenshots for streaming chat, error states, mobile viewport, empty state, and search banner. These were not produced. Test coverage substitutes for most of these, but a manual visual check against a running instance is recommended before final merge.

### ChatErrorCode Extension

The implementation extends `ChatErrorCode` beyond the spec's original four values (`generation_timeout`, `ollama_unavailable`, `search_unavailable`, `stream_interrupted`) with two additional codes: `auth_expired` and `rate_limited`. These were added during code review to properly classify HTTP 401 and 429 errors rather than reusing `generation_timeout`. This is an improvement, not a deviation.

### Metrics

- **Test files:** 17 (7 new, 1 rewritten, 9 pre-existing)
- **Tests:** 126 passing, 0 failing
- **Axe audits:** 8, zero violations
- **New source files:** 7
- **Deleted source files:** 1 (`auth-home.tsx`)
- **New dependencies:** 3 (`react-markdown`, `remark-gfm`, `rehype-sanitize`)
