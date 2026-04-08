# Task 4.0 — Card Detail Sheet — Proof Artifacts

## Frontend Test Results

```
Test Files   3 passed (3)
Tests        26 passed (26)
Duration     1.10s
```

### card-detail.test.tsx (12 tests)

- Renders all fields with full data (title, year, genres, overview, rating, runtime, Jellyfin link)
- Hides "View in Jellyfin" when jellyfin_web_url is null
- Hides community rating when null
- Hides runtime when null
- Runtime formatting: 90 → "1h 30m"
- Runtime formatting: 60 → "1h 0m"
- Runtime formatting: 45 → "45m" (no "0h" prefix)
- Close via close button click
- Close via Escape key
- Has role="dialog"
- Has aria-labelledby referencing title
- Passes axe accessibility audit

## Backend Test Results

```
19 passed (test_search_service.py + test_search_router.py)
```

### New Tests

- `test_jellyfin_web_url_populated_when_configured` — URL constructed correctly
- `test_jellyfin_web_url_none_when_not_configured` — null when no JELLYFIN_WEB_URL

## Components Created / Modified

- `card-detail.tsx` — Dialog (centered modal desktop, bottom sheet mobile) with full details
- `dialog.tsx` — shadcn/ui Dialog component (Radix UI Dialog primitive)
- `message-list.tsx` — selectedMovie state, CardDetail rendered once at end
- `config.py` — JELLYFIN_WEB_URL setting (optional, falls back to JELLYFIN_URL)
- `search/service.py` — jellyfin_web_url populated in search results
- `.env.example` — JELLYFIN_WEB_URL documented
