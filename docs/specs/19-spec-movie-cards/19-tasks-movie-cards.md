# 19-tasks-movie-cards

Task list for [19-spec-movie-cards](./19-spec-movie-cards.md).

## Relevant Files

### Backend — New Files
- `backend/app/images/__init__.py` — Package init for image proxy module
- `backend/app/images/router.py` — Image proxy endpoint (`GET /api/images/{jellyfin_id}`)
- `backend/tests/test_image_proxy.py` — Tests for image proxy endpoint

### Backend — Modified Files
- `backend/app/main.py` — Register images router (lines ~214–273, follow existing router pattern)
- `backend/app/search/models.py` — Add `community_rating`, `runtime_minutes`, `jellyfin_web_url` to `SearchResultItem`
- `backend/app/search/service.py` — Update `poster_url` to proxy path, populate new fields (line ~120)
- `backend/app/jellyfin/client.py` — Add `RunTimeTicks` to `_ITEM_FIELDS` (line 35)
- `backend/app/jellyfin/models.py` — Add `run_time_ticks` field to `LibraryItem` (lines ~71–100)
- `backend/app/library/models.py` — Add `runtime_minutes` to `LibraryItemRow` dataclass (lines ~12–31)
- `backend/app/library/store.py` — Add `runtime_minutes` column to schema, SELECT queries, upsert, and `_row_to_item()` (lines ~24–39, ~176, ~291–316)
- `backend/app/sync/engine.py` — Convert `run_time_ticks` to `runtime_minutes` in `_to_row()` (lines ~38–58)
- `backend/app/ollama/text_builder.py` — Add runtime to `build_sections()`, bump `TEMPLATE_VERSION` (lines ~72–99)
- `backend/app/config.py` — Add `JELLYFIN_WEB_URL` setting (optional, falls back to `JELLYFIN_URL`)
- `backend/tests/test_search_service.py` — Update for new SearchResultItem fields
- `backend/tests/test_sync_engine.py` — Update for RunTimeTicks conversion
- `backend/tests/test_library_store.py` — Update for runtime_minutes column

### Frontend — New Files
- `frontend/src/components/chat/movie-card.tsx` — Individual movie card component
- `frontend/src/components/chat/poster-placeholder.tsx` — Fallback for missing poster images
- `frontend/src/components/chat/card-carousel.tsx` — Responsive carousel/grid container
- `frontend/src/components/chat/card-detail.tsx` — Detail sheet/modal for card tap
- `frontend/src/components/ui/dialog.tsx` — shadcn/ui Dialog component (install or create)
- `frontend/src/components/chat/__tests__/movie-card.test.tsx` — MovieCard tests
- `frontend/src/components/chat/__tests__/card-carousel.test.tsx` — CardCarousel tests
- `frontend/src/components/chat/__tests__/card-detail.test.tsx` — CardDetail tests

### Frontend — Modified Files
- `frontend/src/lib/api/types.ts` — Add `community_rating`, `runtime_minutes`, `jellyfin_web_url` to `SearchResultItem`
- `frontend/src/components/chat/message-list.tsx` — Insert card rendering in assistant message block (after line ~159)

### Notes

- Unit tests should be placed alongside the code they test (frontend: `__tests__/` subdirectory pattern; backend: `backend/tests/` flat pattern)
- Backend tests: `pytest backend/tests/` — uses TestClient + AsyncMock pattern
- Frontend tests: `npx vitest run` — uses vitest + React Testing Library + jest-axe
- Follow conventional commits: `feat:`, `fix:`, `test:`, `chore:`
- Each parent task is scoped to one PR

## Tasks

### [x] 1.0 Backend Image Proxy

Expose `GET /api/images/{jellyfin_id}` — an authenticated endpoint that proxies Jellyfin poster images through the backend. Update `poster_url` in `SearchResultItem` to point at the proxy. This is the prerequisite for any frontend poster display.

#### 1.0 Proof Artifact(s)

- Test: `backend/tests/test_image_proxy.py` passes — covers valid ID (200 + image bytes), invalid ID format (422), missing poster (404), unauthenticated request (401), Jellyfin unreachable (502)
- CLI: `curl -v -b session_cookie http://localhost:8000/api/images/{valid_id}` returns image bytes with `Content-Type: image/jpeg` and `Cache-Control: private, max-age=86400`
- Test: Existing `test_search_service.py` still passes after `poster_url` format change

#### 1.0 Tasks

- [x] 1.1 Create `backend/app/images/__init__.py` (empty package init)
- [x] 1.2 Create `backend/app/images/router.py` with `create_images_router(settings)` factory function. Single endpoint `GET /api/images/{jellyfin_id}` with:
  - Path parameter `jellyfin_id` validated via `Path(pattern=r"^[a-f0-9]{32}$")` (Pydantic/FastAPI path validation)
  - `get_current_session` dependency for auth (returns `SessionMeta`)
  - Retrieve the user's Jellyfin token via `request.app.state.session_store.get_token(session.session_id)`
  - Fetch `{settings.jellyfin_url}/Items/{jellyfin_id}/Images/Primary` using `httpx.AsyncClient` with the user's token in the `Authorization` header
  - Return `StreamingResponse` with `content_type` from Jellyfin response, `Cache-Control: private, max-age=86400` header
  - Only forward `Content-Type` and `Content-Length` headers from Jellyfin
  - Error mapping: Jellyfin 404 → 404, Jellyfin 401 → 401, `httpx.ConnectError`/`httpx.TimeoutException` → 502
- [x] 1.3 Register the images router in `backend/app/main.py` — create via `create_images_router(settings=settings)` and call `app.include_router()`, following the existing pattern near line ~235
- [x] 1.4 Update `poster_url` in `backend/app/search/service.py` (line ~120) from `f"/Items/{jid}/Images/Primary"` to `f"/api/images/{jid}"`
- [x] 1.5 Write `backend/tests/test_image_proxy.py` following the TestClient + AsyncMock pattern from `test_search_router.py`:
  - Test valid ID returns 200 with image bytes and correct headers
  - Test invalid ID format (e.g., `"not-a-hex-id"`, `"ZZZZ"`) returns 422
  - Test uppercase hex ID (e.g., `"AABBCCDD..."`) — verify regex handles case (document whether case-insensitive or lowercase-only, and test the boundary)
  - Test path traversal attempt (e.g., `"../../etc/passwd"`, ID with slashes or dots) returns 422
  - Test unauthenticated request (no session) returns 401
  - Test Jellyfin returns 404 (no poster) → proxy returns 404
  - Test Jellyfin unreachable → proxy returns 502
  - Test that only `Content-Type` and `Content-Length` headers are forwarded
- [x] 1.6 Run existing `test_search_service.py` and `test_search_router.py` to confirm poster_url format change doesn't break them — update expected values if tests assert on the old `/Items/...` format

### [x] 2.0 Extend Search Results with Community Rating + Runtime

Add `community_rating` and `runtime_minutes` to `SearchResultItem`. Community rating is already in the DB — wire it through. Runtime requires a sync pipeline change: fetch `RunTimeTicks` from Jellyfin, convert to minutes, store in `library_items`, include in content hash.

#### 2.0 Proof Artifact(s)

- Test: `backend/tests/test_search_service.py` updated — confirms `community_rating` and `runtime_minutes` appear in search results
- Test: `backend/tests/test_sync_engine.py` updated — confirms `RunTimeTicks` is fetched, converted to minutes, and stored
- Test: `backend/tests/test_library_store.py` updated — confirms `runtime_minutes` column exists and round-trips correctly
- CLI: `curl -b session_cookie http://localhost:8000/api/search?q=action` response includes `community_rating` and `runtime_minutes` fields

#### 2.0 Tasks

- [x] 2.1 Add `run_time_ticks: int | None = Field(default=None, alias="RunTimeTicks")` to `LibraryItem` in `backend/app/jellyfin/models.py`
- [x] 2.2 Add `"RunTimeTicks"` to `_ITEM_FIELDS` in `backend/app/jellyfin/client.py` (line 35) — append to the comma-separated string
- [x] 2.3 Add `runtime_minutes: int | None` field to `LibraryItemRow` dataclass in `backend/app/library/models.py` (insert before `content_hash`)
- [x] 2.4 Update `backend/app/library/store.py`:
  - Add `runtime_minutes INTEGER` to the CREATE TABLE statement
  - Add a `PRAGMA table_info(library_items)` check in the `open()` method — if `runtime_minutes` column is absent, run `ALTER TABLE library_items ADD COLUMN runtime_minutes INTEGER`. This matches the existing migration pattern used for `deleted_at` in the same file. Do NOT use try/except OperationalError.
  - **IMPORTANT: Append `runtime_minutes` at the END of all SELECT column lists** (after `synced_at`, as positional index 11). Do NOT insert it mid-query — `_row_to_item()` maps by positional index and inserting mid-list would silently corrupt all subsequent field mappings.
  - Update `_row_to_item()` to map `row[11]` to `runtime_minutes`
  - Update upsert logic to include `runtime_minutes` in INSERT and UPDATE
- [x] 2.5 Update `_to_row()` in `backend/app/sync/engine.py` to convert `item.run_time_ticks` to `runtime_minutes`: `runtime_minutes = item.run_time_ticks // 600_000_000 if item.run_time_ticks is not None else None`
- [x] 2.6 Add `runtime_minutes: int | None = None` parameter to `build_sections()` in `backend/app/ollama/text_builder.py`. Add a `_build_runtime_section()` helper (e.g., `"Runtime: 120 minutes."`) and append to sections if present. Bump `TEMPLATE_VERSION` so existing embeddings are re-queued. **⚠️ WARNING: Bumping TEMPLATE_VERSION triggers a full library re-embedding.** The first sync after deploy will re-queue every item in the library for embedding. On consumer hardware, expect ~seconds per item (a 1000-movie library ≈ 30–60 minutes of Ollama inference). Note this in the PR description so operators are aware.
- [x] 2.7 Add `community_rating: float | None = None` and `runtime_minutes: int | None = None` to `SearchResultItem` in `backend/app/search/models.py`
- [x] 2.8 Populate the new fields in `backend/app/search/service.py` (line ~120 area): `community_rating=item.community_rating` and `runtime_minutes=item.runtime_minutes` (runtime_minutes will need to be added to `LibraryItemRow` first)
- [x] 2.9 Update `SearchResultItem` interface in `frontend/src/lib/api/types.ts` — add `community_rating: number | null` and `runtime_minutes: number | null`
- [x] 2.10 Write/update tests:
  - Update `test_sync_engine.py` — test that a Jellyfin item with `RunTimeTicks: 54000000000` produces `runtime_minutes: 90`, and `None` produces `None`
  - Update `test_library_store.py` — test that `runtime_minutes` round-trips through upsert and get_many
  - Update `test_search_service.py` — test that `community_rating` and `runtime_minutes` appear on `SearchResultItem` results
  - Update text builder tests — test that runtime appears in composite text when present, is omitted when None

### [x] 3.0 Movie Card Component + Responsive Layout

Render movie recommendation cards below the assistant's text response. Each card shows poster, title, year, truncated overview, and up to 3 genre pills. Horizontal scroll carousel on mobile (< 768px) with peek and scroll indicator. 2-column grid on tablet/desktop. Placeholder graphic for missing posters.

#### 3.0 Proof Artifact(s)

- Screenshot: Mobile view (375px) showing card carousel in a chat conversation with visible peek on next card and scroll indicator
- Screenshot: Desktop view (1024px) showing 2-column grid layout
- Screenshot: Card with missing poster showing placeholder with title overlaid
- Test: `frontend/src/components/chat/__tests__/movie-card.test.tsx` passes — card rendering with all fields, missing poster fallback, alt text, genre pill cap
- Test: `frontend/src/components/chat/__tests__/card-carousel.test.tsx` passes — carousel rendering, responsive layout switching
- Test: Integration test confirming cards render from SSE metadata event

#### 3.0 Tasks

- [x] 3.1 Create `frontend/src/components/chat/poster-placeholder.tsx` — a `"use client"` component that renders an SVG film-frame icon (from lucide-react, e.g., `Film` or `Clapperboard`) centered on a `bg-muted` background with the movie title overlaid below. Use existing semantic colors. Ensure text contrast passes WCAG AA against the muted background. Accept `title: string` and `className?: string` props.
- [x] 3.2 Create `frontend/src/components/chat/movie-card.tsx` — a `"use client"` component using the existing shadcn `Card` compound component as a base. Props: `item: SearchResultItem`, `onClick: () => void`. Renders:
  - Poster `<img>` with `src={item.poster_url}`, `alt="{title} ({year})"`, `loading="lazy"`, 2:3 aspect ratio container. On error (404), swap to `PosterPlaceholder`.
  - Title + year in `CardHeader`
  - Truncated overview (~3 lines, CSS `line-clamp-3`) in `CardContent`
  - Up to 3 genre pills (slice `item.genres` to 3) as small `muted` background badges
  - Entire card wrapped in a `<button>` or has `role="button"` + `tabIndex={0}` + `onClick`/`onKeyDown` for the full-card tap target (min 44x44px)
- [x] 3.3 Create `frontend/src/components/chat/card-carousel.tsx` — a `"use client"` component. Props: `items: SearchResultItem[]`, `onCardClick: (item: SearchResultItem) => void`. Renders:
  - Mobile (< 768px): horizontal scroll container with `overflow-x-auto`, `scroll-snap-type: x mandatory`, `scroll-snap-align: start` on children, and `scroll-padding` on the container to prevent mandatory snap from overshooting the peek (critical for iOS Safari). Cards at ~80% viewport width to show peek (~15-20px of next card). Scroll position indicator dots below.
  - Desktop (768px+): 2-column CSS grid (`grid-cols-2`, `gap-4`)
  - Use Tailwind responsive prefixes (`md:grid md:grid-cols-2`) for the breakpoint switch
  - Renders `MovieCard` for each item, passing the `onCardClick` callback
- [x] 3.4 Integrate into `frontend/src/components/chat/message-list.tsx` — after the ReactMarkdown block in the assistant message branch (after line ~159), render `<CardCarousel>` when `msg.recommendations` exists and has length > 0. Pass a no-op `onCardClick` for now (Task 4.0 will wire the detail sheet). Import CardCarousel as a lazy-loaded component or direct import.
- [x] 3.5 Write `frontend/src/components/chat/__tests__/movie-card.test.tsx`:
  - Test renders title, year, overview, genres
  - Test overview is truncated (line-clamp class present)
  - Test only first 3 genres are shown when item has > 3
  - Test poster img has correct alt text `"{title} ({year})"`
  - Test poster img has `loading="lazy"`
  - Test calls onClick when card is clicked
  - Test calls onClick on Enter keypress
  - Test shows PosterPlaceholder when image fires `onError`
  - Test axe accessibility audit passes
- [x] 3.6 Write `frontend/src/components/chat/__tests__/card-carousel.test.tsx`:
  - Test renders correct number of MovieCard children
  - Test renders scroll indicator dots matching item count
  - Test carousel container has scroll-snap CSS classes
  - Test integration: render CardCarousel with mock SearchResultItem[] data matching the shape from SSE metadata
  - Test renders nothing when `items` is an empty array (carousel should not appear)

### [ ] 4.0 Card Detail Sheet

Tapping a card opens a bottom sheet (mobile) or modal dialog (desktop) showing full movie details: full-size poster, title, year, all genres, complete overview, community rating, runtime, and a "View in Jellyfin" link. Dismissible via swipe-down, backdrop click, Escape, or close button. Fully accessible with focus trap.

#### 4.0 Proof Artifact(s)

- Screenshot: Mobile bottom sheet showing full movie details with "View in Jellyfin" link
- Screenshot: Desktop modal showing the same detail view
- Test: `frontend/src/components/chat/__tests__/card-detail.test.tsx` passes — open/close, keyboard dismiss (Escape), backdrop click dismiss, accessibility attributes (`role="dialog"`, `aria-modal`, `aria-labelledby`), Jellyfin link construction
- Test: Backend test confirms `jellyfin_web_url` field is populated correctly in search results

#### 4.0 Tasks

- [ ] 4.1 Add `JELLYFIN_WEB_URL: str | None = None` to the backend settings in `backend/app/config.py`. This is the public-facing Jellyfin URL for "View in Jellyfin" links (may differ from `JELLYFIN_URL` which could be a Docker-internal address like `http://jellyfin:8096`). Falls back to `JELLYFIN_URL` if not set. Document in `.env.example`.
- [ ] 4.2 Add `jellyfin_web_url: str | None = None` to `SearchResultItem` in `backend/app/search/models.py`. Populate in `backend/app/search/service.py` as `f"{jellyfin_web_url}/web/#!/details?id={jid}"` where `jellyfin_web_url` comes from the new setting. Update TypeScript interface in `frontend/src/lib/api/types.ts` to add `jellyfin_web_url: string | null`.
- [ ] 4.3 Write backend test confirming `jellyfin_web_url` is correctly constructed in search results — both when `JELLYFIN_WEB_URL` is set and when it falls back to `JELLYFIN_URL`.
- [ ] 4.4 Install shadcn/ui Dialog component (`npx shadcn@latest add dialog`) or manually create `frontend/src/components/ui/dialog.tsx` using Radix UI Dialog primitive. This provides the accessible modal foundation with focus trap, Escape dismiss, and backdrop click built in.
- [ ] 4.5 Create `frontend/src/components/chat/card-detail.tsx` — a `"use client"` component. Props: `item: SearchResultItem | null`, `open: boolean`, `onClose: () => void`. Renders:
  - On desktop (768px+): shadcn Dialog (centered modal) with max-width ~md
  - On mobile (< 768px): Dialog styled as bottom sheet (positioned at bottom, rounded top corners, max-height ~85vh, overflow-y-auto)
  - Content: full-size poster image (with PosterPlaceholder fallback), title + year, all genres as pills (no 3-cap here), full overview text, community rating displayed as "★ 7.2/10" if present, runtime formatted as "1h 30m" for ≥60min or "45m" for <60min (never show "0h")
  - "View in Jellyfin" link (`<a href={item.jellyfin_web_url} target="_blank" rel="noopener noreferrer">`) styled as a primary button. Hidden if `jellyfin_web_url` is null.
  - Close button (X icon) in top-right corner
  - Accessibility: `aria-labelledby` referencing the title element ID, focus returns to triggering card on close
- [ ] 4.6 Wire the detail sheet into `message-list.tsx` — add state `const [selectedMovie, setSelectedMovie] = useState<SearchResultItem | null>(null)`. Pass `onCardClick={setSelectedMovie}` to `CardCarousel`. Render `<CardDetail item={selectedMovie} open={selectedMovie !== null} onClose={() => setSelectedMovie(null)} />` once at the end of the message list (not per-message).
- [ ] 4.7 Write `frontend/src/components/chat/__tests__/card-detail.test.tsx`:
  - Test renders all fields when item has full data (title, year, genres, overview, rating, runtime, jellyfin_web_url)
  - Test hides "View in Jellyfin" link when `jellyfin_web_url` is null
  - Test hides community rating when null, hides runtime when null
  - Test runtime formatting: 90 → "1h 30m", 60 → "1h 0m", 45 → "45m" (no "0h" prefix for sub-60-minute films)
  - Test close via close button click
  - Test close via Escape key
  - Test close via backdrop click
  - Test `role="dialog"`, `aria-modal="true"`, `aria-labelledby` present
  - Test axe accessibility audit passes
