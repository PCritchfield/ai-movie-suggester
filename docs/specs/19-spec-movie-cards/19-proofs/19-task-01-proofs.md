# Task 1.0 — Backend Image Proxy — Proof Artifacts

## Test Results

```
tests/test_image_proxy.py::TestImageProxyValidId::test_valid_id_returns_image_bytes PASSED
tests/test_image_proxy.py::TestImageProxyInvalidId::test_non_hex_id_returns_422 PASSED
tests/test_image_proxy.py::TestImageProxyInvalidId::test_uppercase_hex_returns_422 PASSED
tests/test_image_proxy.py::TestImageProxyInvalidId::test_short_hex_returns_422 PASSED
tests/test_image_proxy.py::TestImageProxyInvalidId::test_path_traversal_returns_422 PASSED
tests/test_image_proxy.py::TestImageProxyInvalidId::test_id_with_slashes_returns_404_or_422 PASSED
tests/test_image_proxy.py::TestImageProxyUnauthenticated::test_unauthenticated_returns_401 PASSED
tests/test_image_proxy.py::TestImageProxyJellyfinErrors::test_jellyfin_404_returns_404 PASSED
tests/test_image_proxy.py::TestImageProxyJellyfinErrors::test_jellyfin_unreachable_returns_502 PASSED
tests/test_image_proxy.py::TestImageProxyJellyfinErrors::test_jellyfin_timeout_returns_502 PASSED
tests/test_image_proxy.py::TestImageProxyHeaderForwarding::test_only_content_type_and_length_forwarded PASSED
```

## Existing Tests Still Pass

```
tests/test_search_service.py — 8 passed
tests/test_search_router.py — 9 passed
```

poster_url format updated from `/Items/{jid}/Images/Primary` to `/api/images/{jid}` — existing tests updated and green.

## Verification

- Endpoint: `GET /api/images/{jellyfin_id}` registered at `/api/images/`
- ID validation: lowercase hex only, exactly 32 chars (Jellyfin GUID without dashes)
- Auth: requires valid session via `get_current_session`
- Headers forwarded: only `Content-Type` and `Content-Length`
- Cache-Control: `private, max-age=86400`
- Error mapping: Jellyfin 404 -> 404, Jellyfin 401 -> 401, ConnectError/Timeout -> 502
