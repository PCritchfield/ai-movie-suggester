# 16 Tasks — Chat UI

Spec: [16-spec-chat-ui.md](16-spec-chat-ui.md)

## Relevant Files

- `frontend/src/lib/api/types.ts` — Add `SearchResultItem`, `SearchStatus`, `ChatErrorCode`, `SSEEvent` (discriminated union), `ChatMessage` types
- `frontend/src/lib/api/chat-stream.ts` — **NEW** — `parseSSEStream()` async generator + `sendChatMessage()` client
- `frontend/src/lib/api/client.ts` — Add `apiDelete()` function following `apiPost()` pattern
- `frontend/src/hooks/use-chat.ts` — **NEW** — `useChat()` hook with `useReducer`, ref-based text buffering, streaming lifecycle
- `frontend/src/components/chat/message-list.tsx` — **NEW** — Message rendering with `react-markdown`, auto-scroll, loading indicator
- `frontend/src/components/chat/chat-input.tsx` — **NEW** — Textarea with Enter/Shift+Enter, auto-resize, send button
- `frontend/src/components/chat/empty-state.tsx` — **NEW** — Welcome view with suggestion chips and tagline
- `frontend/src/app/(protected)/page.tsx` — Replace `AuthHome` import with chat UI composition
- `frontend/src/app/(protected)/layout.tsx` — Add persistent 48px header with username, new conversation, and logout
- `frontend/src/components/auth-home.tsx` — **DELETE** — Replaced by chat UI
- `frontend/tests/page.test.tsx` — **DELETE or REWRITE** — Tests `AuthHome` which no longer exists
- `frontend/tests/lib/api/chat-stream.test.ts` — **NEW** — SSE parser unit tests (mock ReadableStream)
- `frontend/tests/hooks/use-chat.test.ts` — **NEW** — Hook state transition tests (renderHook)
- `frontend/tests/components/chat/message-list.test.tsx` — **NEW** — Component rendering + axe audit
- `frontend/tests/components/chat/chat-input.test.tsx` — **NEW** — Input interactions + axe audit
- `frontend/tests/components/chat/empty-state.test.tsx` — **NEW** — Suggestion chip interactions + axe audit
- `frontend/package.json` — Add `react-markdown`, `remark-gfm`, `rehype-sanitize`

### Notes

- Unit tests follow the existing `__tests__/` subdirectory pattern (see `frontend/src/components/__tests__/login-form.test.tsx`) OR the `frontend/tests/` top-level pattern (see `frontend/tests/page.test.tsx`). The spec defines paths in `frontend/tests/` — follow those.
- Axe accessibility audits follow the pattern in `login-form.test.tsx`: import `{ axe, toHaveNoViolations } from "jest-axe"`, extend expect, render component, assert `toHaveNoViolations()`.
- CSRF token handling reuses `getCsrfToken()` from `frontend/src/lib/api/shared.ts`.
- Backend SSE types to mirror are in `backend/app/chat/models.py` (ChatErrorCode, SSEEventType) and `backend/app/search/models.py` (SearchResultItem, SearchStatus).
- Conventional commits: `feat(chat):` prefix for all commits in this spec.
- Run tests: `cd frontend && npm test`
- Run lint: `cd frontend && npm run lint && npm run format:check && npm run type-check`

## Tasks

### [x] 1.0 TypeScript Types, SSE Parser, and API Helpers

Add all TypeScript types mirroring the backend SSE contract, implement the `parseSSEStream()` async generator and `sendChatMessage()` client function, and add `apiDelete()` to the existing API client. This is the data/network foundation — no React components, no UI. Demoable via unit test output confirming the parser handles all SSE framing edge cases.

#### 1.0 Proof Artifact(s)

- Test: `parseSSEStream` — single event parsing yields correct typed object
- Test: `parseSSEStream` — multiple events in one stream yield in order
- Test: `parseSSEStream` — chunks split across SSE frame boundaries are buffered and parsed correctly
- Test: `parseSSEStream` — malformed JSON data is handled gracefully (skipped or errored, not thrown)
- Test: `parseSSEStream` — empty stream yields nothing
- Test: `parseSSEStream` — error event yields `ErrorEvent` with correct code and message
- Test: `sendChatMessage` — includes CSRF token and credentials in request
- Test: `sendChatMessage` — throws `ApiAuthError` on 401/403, `ApiError` on 429/422, `NetworkError` on fetch TypeError
- Test: `apiDelete` — sends DELETE with CSRF token, returns void on 204, throws on error responses
- CLI: `cd frontend && npx vitest run tests/lib/api/chat-stream.test.ts` — all tests pass
- CLI: `cd frontend && npm run type-check` — no TypeScript errors

#### 1.0 Tasks

- [x] 1.1 Add `SearchResultItem` interface to types module, mirroring backend `SearchResultItem` fields: `jellyfin_id: string`, `title: string`, `overview: string | null`, `genres: string[]`, `year: number | null`, `score: number`, `poster_url: string` (file: `frontend/src/lib/api/types.ts`)
- [x] 1.2 Add `SearchStatus` union type (`"ok" | "no_embeddings" | "partial_embeddings"`) and `ChatErrorCode` union type (`"generation_timeout" | "ollama_unavailable" | "search_unavailable" | "stream_interrupted"`) to types module (file: `frontend/src/lib/api/types.ts`)
- [x] 1.3 Add `SSEEvent` discriminated union type (`MetadataEvent | TextEvent | DoneEvent | ErrorEvent`) with each variant typed on the `type` field. Add `ChatMessage` interface with `id`, `role`, `content`, `recommendations?`, `searchStatus?`, `error?`, `isStreaming?` fields (file: `frontend/src/lib/api/types.ts`)
- [x] 1.4 Create `parseSSEStream()` async generator function: accepts `ReadableStream<Uint8Array>`, pipes through `TextDecoderStream`, buffers partial lines, splits on `\n\n` boundaries, strips `data: ` prefix, parses JSON, and yields typed `SSEEvent` objects. Handle malformed JSON gracefully (skip, do not throw) (file: `frontend/src/lib/api/chat-stream.ts`)
- [x] 1.5 Create `sendChatMessage(message: string)` function: issues `POST /api/chat` with JSON body `{ message }`, includes `credentials: "include"`, `Content-Type: application/json`, and `X-CSRF-Token` header via `getCsrfToken()`. On `response.ok`, return `response.body` (the `ReadableStream`). On 401/403 throw `ApiAuthError`, on 429 throw `ApiError` with `status: 429`, on 422 throw `ApiError` with `status: 422`, on `TypeError` from fetch throw `NetworkError` (file: `frontend/src/lib/api/chat-stream.ts`)
- [x] 1.6 Add `apiDelete(path: string)` function to the existing API client: sends DELETE with `credentials: "include"` and `X-CSRF-Token` header, returns `void` for 204 responses, throws `ApiAuthError` or `ApiError` for error responses following the `apiPost` pattern (file: `frontend/src/lib/api/client.ts`)
- [x] 1.7 Write `parseSSEStream` unit tests using mock `ReadableStream` instances: (1) single event yields correct typed object, (2) multiple events yield in order, (3) chunks split across frame boundaries are buffered correctly, (4) malformed JSON is handled gracefully, (5) empty stream yields nothing, (6) error event yields `ErrorEvent` with correct code and message (file: `frontend/tests/lib/api/chat-stream.test.ts`)
- [x] 1.8 Write `sendChatMessage` unit tests mocking global `fetch`: (1) includes CSRF token and credentials in request, (2) returns `response.body` stream on success, (3) throws `ApiAuthError` on 401, (4) throws `ApiAuthError` on 403, (5) throws `ApiError` on 429, (6) throws `ApiError` on 422, (7) throws `NetworkError` on fetch `TypeError` (file: `frontend/tests/lib/api/chat-stream.test.ts`)
- [x] 1.9 Write `apiDelete` unit tests mocking global `fetch`: (1) sends DELETE method with CSRF token, (2) returns void on 204, (3) throws `ApiAuthError` on 401, (4) throws `ApiError` on 500 (file: `frontend/tests/lib/api/chat-stream.test.ts` or a new `frontend/tests/lib/api/client.test.ts`)
- [x] 1.10 Run `npm run type-check` to confirm zero TypeScript errors, run `npx vitest run tests/lib/api/chat-stream.test.ts` to confirm all tests pass

### [x] 2.0 Chat Hook, Message Components, and Page Integration

Install `react-markdown`, `remark-gfm`, and `rehype-sanitize`. Implement the `useChat()` hook with `useReducer` state management and 50ms ref-based text flush. Build `MessageList` (markdown rendering, auto-scroll, loading indicator) and `ChatInput` (textarea with Enter/Shift+Enter, auto-resize, send button). Replace `AuthHome` in `(protected)/page.tsx` with the chat composition. Delete `auth-home.tsx` and its test. Demoable via screenshot of a streaming chat exchange with markdown-formatted assistant response.

#### 2.0 Proof Artifact(s)

- Test: `useChat` — `sendMessage` appends user message + placeholder assistant message to state
- Test: `useChat` — TEXT events accumulate content in assistant message
- Test: `useChat` — DONE event clears `isStreaming` and flushes remaining text
- Test: `useChat` — ERROR event sets error field on assistant message
- Test: `useChat` — concurrent send prevention (second `sendMessage` is no-op while streaming)
- Test: `useChat` — `clearHistory` calls `apiDelete` and resets messages to empty
- Test: `MessageList` — renders user messages right-aligned and assistant messages left-aligned
- Test: `MessageList` — renders markdown content via `react-markdown` (bold, lists render as HTML)
- Test: `MessageList` — shows loading indicator when `isStreaming` and content is empty
- Test: `ChatInput` — Enter submits message, Shift+Enter inserts newline
- Test: `ChatInput` — disabled during streaming (button disabled, Enter no-op)
- Test: `ChatInput` — clears textarea and refocuses after send
- Proof: Screenshot of streaming chat exchange with markdown-formatted assistant response
- CLI: `cd frontend && npm test` — all tests pass
- CLI: `cd frontend && npm run type-check` — no TypeScript errors
- CLI: `cd frontend && npm run lint` — no lint errors

#### 2.0 Tasks

- [x] 2.1 Install `react-markdown`, `remark-gfm`, and `rehype-sanitize` as production dependencies (file: `frontend/package.json`)
- [x] 2.2 Create the `useChat()` hook with `useReducer` for state management. Define action types: `ADD_USER_MESSAGE`, `ADD_ASSISTANT_PLACEHOLDER`, `UPDATE_ASSISTANT_CONTENT`, `SET_METADATA`, `SET_STREAMING_DONE`, `SET_ERROR`, `CLEAR_MESSAGES`. State shape: `{ messages: ChatMessage[], isStreaming: boolean, error: string | null }`. Generate client-side UUIDs for message `id` fields via `crypto.randomUUID()` (file: `frontend/src/hooks/use-chat.ts`)
- [x] 2.3 Implement the `sendMessage` flow in `useChat`: dispatch `ADD_USER_MESSAGE`, dispatch `ADD_ASSISTANT_PLACEHOLDER` with `isStreaming: true`, call `sendChatMessage()`, iterate `parseSSEStream()`, dispatch `SET_METADATA` on metadata events, accumulate TEXT chunks in a `useRef` buffer, set up a 50ms `setInterval` to flush buffer into state via `UPDATE_ASSISTANT_CONTENT`, dispatch `SET_STREAMING_DONE` on DONE events (clearing interval and flushing remaining buffer). Guard against concurrent sends by checking `isStreaming` (file: `frontend/src/hooks/use-chat.ts`)
- [x] 2.4 Implement error handling in `sendMessage`: on `ERROR` SSE events dispatch `SET_ERROR` on the assistant message with code and message. On HTTP-level errors (caught before streaming), dispatch `SET_ERROR` on the user message. Clear `isStreaming` in both cases. Store the original message text so retry is possible (file: `frontend/src/hooks/use-chat.ts`)
- [x] 2.5 Implement `clearHistory` in `useChat`: call `apiDelete("/api/chat/history")` then dispatch `CLEAR_MESSAGES` to reset state. Handle `apiDelete` errors gracefully (still clear local state) (file: `frontend/src/hooks/use-chat.ts`)
- [x] 2.6 Create `MessageList` component: accepts `messages: ChatMessage[]` and `isStreaming: boolean` props. Render user messages right-aligned with distinct background, assistant messages left-aligned with distinct background. Use Tailwind utility classes consistent with existing shadcn theme (file: `frontend/src/components/chat/message-list.tsx`)
- [x] 2.7 Add markdown rendering to `MessageList`: render assistant message `content` through `<ReactMarkdown>` with `remarkGfm` and `rehypeSanitize` plugins. Ensure code blocks, bold, lists, headers, and GFM tables render correctly (file: `frontend/src/components/chat/message-list.tsx`)
- [x] 2.8 Add auto-scroll behavior to `MessageList`: use a `useRef` on the scroll container and `useEffect` that scrolls to bottom when messages change or streaming content updates. Track whether user has manually scrolled up (via `onScroll` handler comparing `scrollTop + clientHeight` against `scrollHeight`) and suppress auto-scroll if so (file: `frontend/src/components/chat/message-list.tsx`)
- [x] 2.9 Add loading indicator to `MessageList`: when the latest assistant message has `isStreaming: true` and `content` is empty, render an animated dots/spinner indicator between the user message and the assistant response area (file: `frontend/src/components/chat/message-list.tsx`)
- [x] 2.10 Create `ChatInput` component: render a `<form>` containing a `<textarea>` and a send `<button>`. `Enter` submits (calls `onSend` prop), `Shift+Enter` inserts newline. Auto-resize textarea vertically up to ~6 lines then scroll internally. Disable send button and Enter key while `isStreaming` prop is true or textarea is empty. Clear textarea and refocus after submit. Send button has `aria-label="Send message"` and minimum 44x44px touch target (file: `frontend/src/components/chat/chat-input.tsx`)
- [x] 2.11 Enforce `maxLength={1000}` on the `ChatInput` textarea to match the backend's `ChatRequest` validation (file: `frontend/src/components/chat/chat-input.tsx`)
- [x] 2.12 Replace `(protected)/page.tsx`: remove `AuthHome` import, make it a `"use client"` component that composes `useChat`, `MessageList`, and `ChatInput`. Layout: `height: 100dvh` with message list as `flex: 1; overflow-y: auto` and input pinned to bottom (file: `frontend/src/app/(protected)/page.tsx`)
- [x] 2.13 Delete `auth-home.tsx` and rewrite `tests/page.test.tsx`: remove `frontend/src/components/auth-home.tsx`. Rewrite `frontend/tests/page.test.tsx` to test the new chat page composition (renders message list and input, or replace with a minimal smoke test) (files: `frontend/src/components/auth-home.tsx` [DELETE], `frontend/tests/page.test.tsx`)
- [x] 2.14 Write `useChat` hook tests with `renderHook` and mocked `sendChatMessage`: (1) `sendMessage` appends user + placeholder assistant message, (2) TEXT events accumulate content in assistant message, (3) DONE event clears `isStreaming` and flushes remaining text, (4) ERROR event sets error field on assistant message, (5) concurrent send prevention — second call is no-op while streaming, (6) `clearHistory` calls `apiDelete` and resets messages to empty (file: `frontend/tests/hooks/use-chat.test.ts`)
- [x] 2.15 Write `MessageList` component tests: (1) renders user messages right-aligned and assistant messages left-aligned, (2) renders markdown content (bold text renders as `<strong>`), (3) shows loading indicator when `isStreaming` is true and content is empty, (4) does not show loading indicator when content has arrived (file: `frontend/tests/components/chat/message-list.test.tsx`)
- [x] 2.16 Write `ChatInput` component tests: (1) Enter submits message via `onSend` prop, (2) Shift+Enter inserts newline without submitting, (3) send button is disabled when `isStreaming` is true, (4) send button is disabled when textarea is empty, (5) clears textarea and refocuses after send (file: `frontend/tests/components/chat/chat-input.test.tsx`)
- [x] 2.17 Run full test suite (`npm test`), type-check (`npm run type-check`), and lint (`npm run lint`) to confirm zero errors

### [x] 3.0 Error Handling and Retry UX

Add inline error display on message bubbles for both SSE-level errors (ChatErrorCode) and HTTP-level errors (401, 422, 429). Implement retry buttons that re-send the original message. Add 401 "Log in again" link and 429 cooldown-disabled retry. All retry buttons meet 44x44px touch target. Error messages use `role="alert"` for screen reader announcement. Demoable via screenshot of error state with visible retry button.

#### 3.0 Proof Artifact(s)

- Test: SSE error event displays inline error message and retry button on assistant message
- Test: HTTP 401 error displays "Log in again" link pointing to `/login?reason=session_expired`
- Test: HTTP 429 error disables retry button with cooldown, re-enables after timeout
- Test: Retry button re-sends the original user message via `sendMessage`
- Test: Error messages have `role="alert"` attribute
- Proof: Screenshot of error state with retry button visible
- CLI: `cd frontend && npm test` — all tests pass

#### 3.0 Tasks

- [x] 3.1 Add a `retry` callback to the `useChat` hook return value. `retry(messageId: string)` looks up the user message that triggered the failed exchange, re-sends its text via `sendMessage`, and removes the failed assistant message from state before the new attempt (file: `frontend/src/hooks/use-chat.ts`)
- [x] 3.2 Add inline error display to `MessageList` for SSE-level errors: when an assistant message has an `error` field set, render the error `message` text and a "Retry" button below the assistant bubble. The retry button calls `retry(messageId)` from the hook (file: `frontend/src/components/chat/message-list.tsx`)
- [x] 3.3 Add inline error display to `MessageList` for HTTP-level errors: when a user message has an `error` field set (meaning the request failed before streaming), render a failure indicator and "Retry" button on the user message bubble (file: `frontend/src/components/chat/message-list.tsx`)
- [x] 3.4 Handle HTTP 401 specifically: when error status is 401, render a "Log in again" link (`<a href="/login?reason=session_expired">`) instead of / in addition to a retry button (file: `frontend/src/components/chat/message-list.tsx`)
- [x] 3.5 Handle HTTP 429 specifically: render the retry button in a disabled state with a "Try again in a moment" label. Use a `setTimeout(10000)` to re-enable the button after 10 seconds. Use local component state to track the cooldown (file: `frontend/src/components/chat/message-list.tsx`)
- [x] 3.6 Ensure all retry buttons have a minimum touch target of 44x44px (`min-h-11 min-w-11` or equivalent Tailwind) and `aria-label="Retry message"` (file: `frontend/src/components/chat/message-list.tsx`)
- [x] 3.7 Add `role="alert"` to all error message containers so screen readers announce them immediately (file: `frontend/src/components/chat/message-list.tsx`)
- [x] 3.8 Write error handling tests: (1) SSE error event displays inline error message and retry button on assistant message, (2) clicking retry re-sends the original user message, (3) HTTP 401 error displays "Log in again" link pointing to `/login?reason=session_expired`, (4) HTTP 429 error disables retry button with cooldown text and re-enables after timeout (use `vi.useFakeTimers`), (5) error messages have `role="alert"` attribute (file: `frontend/tests/components/chat/message-list.test.tsx`)
- [x] 3.9 Write `retry` hook test: calling `retry(messageId)` removes the failed assistant message and re-sends the original user message text (file: `frontend/tests/hooks/use-chat.test.ts`)
- [x] 3.10 Run full test suite (`npm test`) to confirm all error handling tests pass

### [ ] 4.0 Accessibility Audit and Mobile Viewport Polish

Add `role="log"` and `aria-live="polite"` to message list container. Toggle `aria-busy` with streaming state. Ensure all interactive elements use semantic HTML (`<form>`, `<button>`, `<textarea>`). Add `aria-label` attributes to send, retry, and new conversation buttons. Apply `height: 100dvh` layout, `position: sticky` input, `env(safe-area-inset-bottom)` padding. Run axe audits on all chat components. Demoable via axe audit passing with zero violations plus mobile viewport screenshot at 375px.

#### 4.0 Proof Artifact(s)

- Test: Axe accessibility audit passes on `MessageList` (default and streaming states)
- Test: Axe accessibility audit passes on `ChatInput`
- Test: Axe accessibility audit passes on error state with retry button
- Test: Message list container has `role="log"` and `aria-live="polite"`
- Test: `aria-busy` toggles between `"true"` (streaming) and `"false"` (idle)
- Test: Error elements have `role="alert"`
- Proof: Screenshot at 375px viewport width showing input pinned to bottom with safe-area padding
- CLI: `cd frontend && npm test` — all tests pass (including axe audits)

#### 4.0 Tasks

- [ ] 4.1 Add `role="log"` and `aria-live="polite"` attributes to the `MessageList` scroll container element (file: `frontend/src/components/chat/message-list.tsx`)
- [ ] 4.2 Add `aria-busy` attribute to the `MessageList` container that toggles to `"true"` when `isStreaming` prop is true and `"false"` when idle (file: `frontend/src/components/chat/message-list.tsx`)
- [ ] 4.3 Verify all interactive elements use semantic HTML: `ChatInput` uses `<form>` wrapping `<textarea>` + `<button>`, retry/clear actions use `<button>` elements (not `<div>` or `<span>` with click handlers). Audit and fix any non-semantic elements (files: `frontend/src/components/chat/chat-input.tsx`, `frontend/src/components/chat/message-list.tsx`)
- [ ] 4.4 Ensure `aria-label` attributes are present: send button (`"Send message"`), retry buttons (`"Retry message"`), new conversation button (`"Start new conversation"`). Verify no duplicate or missing labels (files: `frontend/src/components/chat/chat-input.tsx`, `frontend/src/components/chat/message-list.tsx`)
- [ ] 4.5 Apply `height: 100dvh` to the chat page root container, `flex: 1; overflow-y: auto` to the message list, and `position: sticky; bottom: 0` to the input area. Add `padding-bottom: env(safe-area-inset-bottom)` to the input container for iOS home indicator (file: `frontend/src/app/(protected)/page.tsx`)
- [ ] 4.6 Add axe accessibility audit to `MessageList` tests: (1) default state with mixed user/assistant messages passes axe, (2) streaming state (assistant message with `isStreaming: true`) passes axe (file: `frontend/tests/components/chat/message-list.test.tsx`)
- [ ] 4.7 Add axe accessibility audit to `ChatInput` tests: (1) default state passes axe, (2) disabled/streaming state passes axe (file: `frontend/tests/components/chat/chat-input.test.tsx`)
- [ ] 4.8 Add axe accessibility audit to error state: render a `MessageList` containing a message with an error and retry button, assert `toHaveNoViolations()` (file: `frontend/tests/components/chat/message-list.test.tsx`)
- [ ] 4.9 Write ARIA attribute tests: (1) message list container has `role="log"`, (2) message list container has `aria-live="polite"`, (3) `aria-busy` is `"true"` during streaming and `"false"` when idle, (4) error elements have `role="alert"` (file: `frontend/tests/components/chat/message-list.test.tsx`)
- [ ] 4.10 Run full test suite (`npm test`) including all axe audits to confirm zero violations. Verify mobile layout at 375px viewport width via responsive devtools or screenshot

### [ ] 5.0 Header, Empty State, and Search Status Banner

Add a persistent 48px header to `(protected)/layout.tsx` with app name, username (from `useAuth()`), "New conversation" button, and existing `LogoutButton`. The header content that needs client state is extracted into a client component while the layout shell remains a Server Component. Implement the empty state with tappable suggestion chips that send messages on tap. Add a dismissible `search_status` banner for `no_embeddings` and `partial_embeddings` states. Demoable via screenshot of empty state with suggestion chips, header, and search status banner.

#### 5.0 Proof Artifact(s)

- Test: Header renders app name, username, "New conversation" button, and logout button
- Test: "New conversation" button calls `clearHistory` (which calls `DELETE /api/chat/history` and resets messages)
- Test: Empty state renders suggestion chips; clicking a chip calls `sendMessage` with the chip text
- Test: Empty state disappears after the first message is sent
- Test: `search_status` banner appears for `no_embeddings` and `partial_embeddings`, does not appear for `ok`
- Test: `search_status` banner is manually dismissible (close button)
- Test: Axe accessibility audit passes on empty state component
- Proof: Screenshot of empty state with suggestion chips and header visible
- Proof: Screenshot of search status banner displayed above chat messages
- CLI: `cd frontend && npm test` — all tests pass
- CLI: `cd frontend && npm run lint && npm run format:check` — no lint warnings

#### 5.0 Tasks

- [ ] 5.1 Extract a `HeaderContent` client component that uses `useAuth()` to get the username and renders: app name on the left, username display + "New conversation" button + `<LogoutButton />` on the right. The "New conversation" button accepts an `onNewConversation` prop (or uses context/prop drilling from the page). Add `aria-label="Start new conversation"` (file: `frontend/src/components/chat/header-content.tsx`)
- [ ] 5.2 Add a persistent 48px header to `(protected)/layout.tsx`: render a `<header>` element with `h-12` and a bottom border above the `{children}` slot. Import and render `HeaderContent` inside it. The outer layout remains a Server Component; `HeaderContent` is `"use client"` (file: `frontend/src/app/(protected)/layout.tsx`)
- [ ] 5.3 Wire the "New conversation" button: the chat page passes `clearHistory` from `useChat()` down to `HeaderContent` (or lifts it via a callback prop / layout slot pattern). Clicking the button calls `clearHistory()` which deletes server-side history and resets local messages to empty — returning the UI to the empty state. No confirmation dialog (file: `frontend/src/app/(protected)/page.tsx`, `frontend/src/components/chat/header-content.tsx`)
- [ ] 5.4 Create `EmptyState` component: render a welcome view with a tagline ("Ask me for movie recommendations from your Jellyfin library") and 2-3 tappable suggestion chips. Hardcoded chip texts: "Something like Alien but funny", "A good movie for date night", "What's the best thriller in my library?". Each chip is a `<button>` with `onClick` calling `onSend(chipText)` prop. Chips disappear when `messages.length > 0` (the parent conditionally renders `EmptyState` only when messages are empty) (file: `frontend/src/components/chat/empty-state.tsx`)
- [ ] 5.5 Integrate `EmptyState` into the chat page: when `messages` from `useChat()` is empty, render `<EmptyState onSend={sendMessage} />` instead of `<MessageList />`. After the first message is sent, `EmptyState` is replaced by `MessageList` (file: `frontend/src/app/(protected)/page.tsx`)
- [ ] 5.6 Create a `SearchStatusBanner` component: accepts `searchStatus: SearchStatus | undefined` and `onDismiss` callback. Renders a non-blocking informational banner above the message list for `"no_embeddings"` ("Your library is being indexed — recommendations aren't available yet.") and `"partial_embeddings"` ("Your library is still being indexed — some recommendations may be missing."). Does not render for `"ok"` or `undefined`. Includes a close button calling `onDismiss` (file: `frontend/src/components/chat/search-status-banner.tsx`)
- [ ] 5.7 Integrate `SearchStatusBanner` into the chat page: derive the `searchStatus` from the most recent assistant message's `searchStatus` field. Track a dismissed state in local `useState` — reset it when a new assistant message arrives. Auto-dismiss when a subsequent message has `searchStatus === "ok"` (file: `frontend/src/app/(protected)/page.tsx`)
- [ ] 5.8 Write header tests: (1) header renders app name, (2) header renders username from auth context, (3) header renders "New conversation" button with `aria-label`, (4) header renders logout button, (5) "New conversation" button calls the `onNewConversation` callback (file: `frontend/tests/components/chat/header-content.test.tsx`)
- [ ] 5.9 Write empty state tests: (1) renders suggestion chips with expected text, (2) clicking a chip calls `onSend` with the chip's text, (3) renders the tagline text, (4) axe accessibility audit passes with zero violations (file: `frontend/tests/components/chat/empty-state.test.tsx`)
- [ ] 5.10 Write search status banner tests: (1) renders banner with correct text for `"no_embeddings"`, (2) renders banner with correct text for `"partial_embeddings"`, (3) does not render for `"ok"`, (4) does not render for `undefined`, (5) close button calls `onDismiss`, (6) axe accessibility audit passes (file: `frontend/tests/components/chat/search-status-banner.test.tsx`)
- [ ] 5.11 Run full test suite (`npm test`), lint (`npm run lint && npm run format:check`), and type-check (`npm run type-check`) to confirm everything passes
