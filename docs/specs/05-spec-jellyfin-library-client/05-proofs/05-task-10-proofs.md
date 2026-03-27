# Task 1.0 Proof Artifacts — Extended LibraryItem Model + Auto-Paginated Client

## Test Results

```
155 passed, 17 warnings in 0.65s
```

All unit tests pass (excluding integration tests).

## Tests Added

### TestLibraryItem (model extensions)
- `test_parse_all_extended_fields` — All new fields (tags, studios, community_rating, people) parse from representative Jellyfin JSON
- `test_extended_fields_default_when_absent` — New fields default correctly (tags=[], studios=[], community_rating=None, people=[])
- `test_studios_validator_extracts_names_from_objects` — Studios validator extracts Name from `[{"Name": "Pixar", "Id": "abc"}]` -> `["Pixar"]`
- `test_studios_validator_handles_plain_string_list` — Studios validator passes through plain string list
- `test_people_field_parses_raw_jellyfin_array` — People field parses raw Jellyfin People array with Name, Role, Type dicts

### TestGetAllItems (auto-pagination)
- `test_two_pages_yields_both` — Mock get_items() returning 200 + 50 items (total_count=250), verifies exactly two PaginatedItems yielded, stops after second page
- `test_empty_library` — Empty library yields one page with zero items and stops
- `test_auth_error_propagates` — JellyfinAuthError on first page propagates immediately
- `test_mid_pagination_error` — JellyfinConnectionError on second page propagates after first page yielded
- `test_item_fields_includes_extended_fields` — _ITEM_FIELDS includes Tags, Studios, CommunityRating, People

### Config
- `test_library_sync_page_size_default` — library_sync_page_size defaults to 200

## Verification

- `_ITEM_FIELDS` in `backend/app/jellyfin/client.py`: `"Overview,Genres,ProductionYear,Tags,Studios,CommunityRating,People"`
- `LIBRARY_SYNC_PAGE_SIZE` in `backend/app/config.py`: defaults to `200`

## Lint / Format

- `ruff check app/ tests/` — All checks passed
- `ruff format --check app/ tests/` — All files formatted
