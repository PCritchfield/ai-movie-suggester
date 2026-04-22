---
title: Epic 4 — Remote Control (Play on TV) — Design
status: approved (brainstorming + Council review complete)
date: 2026-04-22
author: Phil Critchfield
skill: superpowers:brainstorming
council_reviewed:
  - watch-granny
  - watch-angua
  - watch-adorabelle
  - watch-carrot
  - watch-sybil
feeds:
  - epic-4-t1-backend-devices
  - epic-4-t2-frontend-picker
  - epic-4-t3-backend-play
  - epic-4-t4-frontend-dispatch
related_issues:
  - "#12 — Jellyfin session/device detection (to be rewritten per T1)"
  - "#13 — Play on TV trigger (to be rewritten per T3)"
  - "#195 — test-infra: fake playback client for Epic 4 integration tests (deferred)"
  - "#190 — restricted-user test (orthogonal, not bundled)"
milestone: Epic 4 — Remote Control
epic_label: epic:remote-control
---

# Epic 4 — Remote Control (Cast to TV)

Brainstorming design doc for Epic 4, Council-reviewed 2026-04-22. Feeds SDD-1 spec generation for four tickets. No Council vetoes; all findings incorporated.

## Council review summary

| Agent | Domain | Verdict |
|---|---|---|
| watch-granny | Architecture | Approved with conditions — shared transport required, exception placement |
| watch-angua | Security | Approved with conditions — self-session correlation, rate-limit tightened, auth-failure split |
| watch-adorabelle | UX | Approved with conditions — button label, aria-live, focus return; Open Questions ruled |
| watch-carrot | Coding/tests | Approved with conditions — file organization, edge cases |
| watch-sybil | Docs | Publication-ready after one graph-direction fix |

No minority reports. No escalations.

## Scope (locked-in)

| Decision | Chosen |
|---|---|
| Epic boundary | **Fire-and-forget only** — detect devices + start playback. No pause/stop/resume/volume. |
| Device-picker UX | **Modal on tap** from card-detail; fresh fetch on open; no persistent device state. |
| Empty-state behavior | Modal stays open with "No devices found…" message + prominent text-labeled **Refresh** action. |
| Error handling | **Device-offline** → 409 → in-place refetch; **auth failure** → 401 → re-login prompt; all other errors → 500 → generic notification. |
| Play-button label | **"Cast to TV"** — platform convention; "Play on Device" rejected as unintuitive. |
| Success notification | **`sonner`** library (3kb, accessible by default); 4s duration; responsive placement. |
| Test strategy | Unit tests + mocks for Epic 4; integration-test hardening deferred to #195. |
| Related test work | #190 stays separate (Epic 3 permission-filter hardening). |

### Out of scope (explicit)

- Pause, stop, resume, seek, volume commands — future epic
- Ongoing playback state tracking ("is the movie still playing?")
- Resume-from-position UX (Jellyfin's own client handles this)
- Codec/format compatibility checks (Jellyfin handles transcoding server-side)
- Cross-device queueing
- Any persisted "last-used device" state
- End-to-end integration test against a live playback client (see #195)

## Architecture

Two endpoints, two capability clients **sharing an extracted Jellyfin transport** with the existing `backend/app/jellyfin/client.py`, one frontend Dialog. No new persistence, no background workers, no conversation-store involvement. Stateless query/command pair.

```mermaid
sequenceDiagram
    participant U as User (Phone)
    participant F as Frontend (card-detail)
    participant P as DevicePicker
    participant B as Backend
    participant S as JellyfinSessionsClient
    participant C as JellyfinPlaybackClient
    participant J as Jellyfin

    U->>F: Tap "Cast to TV" in card-detail
    F->>P: Open picker dialog
    P->>B: GET /api/devices
    B->>S: list_controllable(user_token, user_id, device_id)
    S->>J: GET /Sessions
    J-->>S: All active sessions
    Note over S: Filter: SupportsRemoteControl==true<br/>Exclude: Session.UserId==user AND<br/>Session.DeviceId==caller's DeviceId
    S-->>B: [Device{session_id, name, client, type}]
    B-->>P: 200 [devices]
    P-->>U: Render list (or empty + Refresh)

    U->>P: Tap "Living Room TV"
    P->>B: POST /api/play {item_id, session_id}
    B->>C: dispatch_play(session_id, item_id, user_token)
    C->>J: POST /Sessions/{session_id}/Playing?itemIds=...
    J-->>C: 204 (or error)
    C-->>B: ok / DeviceOfflineError / PlaybackAuthError / PlaybackDispatchError
    B-->>P: 200 / 409 / 401 / 500
    P-->>F: Close picker; emit sonner notification
    F-->>U: Toast visible (sonner, bottom-center mobile / top-right desktop)
```

### Key architectural decisions

- **User-token auth** for device listing and dispatch, not the admin API key. Matches the existing permission-service pattern. Token is request-scoped and never persisted into objects, never logged.
- **Filter on `SupportsRemoteControl == true`** — devices without remote-control capability cannot receive play commands.
- **Self-session exclusion via server-side correlation.** Caller's own session is excluded by matching `Session.UserId == current user AND Session.DeviceId == caller's Jellyfin DeviceId issued at login`. The frontend **never** supplies its own session_id to this filter — that would be spoofable. The Jellyfin DeviceId is derived from the backend's encrypted session payload, established at login.
- **Jellyfin re-validates item access** on `POST /Sessions/{id}/Playing` using the user's token. No app-side permission check is added in the dispatch path; we rely on Jellyfin to reject playback of items the user can't access. If this turns out to be untrue for any item type, T3 must add an explicit check.
- **Error-to-status mapping:**
  - Jellyfin 404/400 on session ID → `DeviceOfflineError` → HTTP 409
  - Jellyfin 401/403 (token revoked mid-flight) → `PlaybackAuthError` → HTTP 401 (triggers frontend re-login)
  - Network, 5xx, unknown → `PlaybackDispatchError` → HTTP 500
- **Shared Jellyfin transport.** T1 extracts `_headers`/`_request`/error-mapping from the existing `JellyfinClient` into a reusable helper (composition preferred over inheritance). New capability clients (`JellyfinSessionsClient`, `JellyfinPlaybackClient`) consume the helper. One transport, three capability clients.
- **No optimistic UI** — dispatch is typically sub-second; we wait for the backend response before closing the picker.

## Backend components

### Shared transport (refactor — landed in T1 before new clients)

Extract from `backend/app/jellyfin/client.py`:
- MediaBrowser `Authorization` header builder (`_headers`)
- `_request` method with 401 → `JellyfinAuthError`, transport errors → `JellyfinConnectionError`
- JSON-shape error wrapping

Shape (composition): a module-level helper or a small `_JellyfinTransport` class that `JellyfinClient` is refactored to use and that new clients consume.

### New files

```
backend/app/jellyfin/sessions.py         # JellyfinSessionsClient.list_controllable + _classify_device
backend/app/jellyfin/playback.py         # JellyfinPlaybackClient.dispatch_play
backend/app/jellyfin/device_models.py    # Device, DeviceType
backend/app/routers/devices.py           # GET /api/devices
backend/app/routers/play.py              # POST /api/play
backend/app/play/__init__.py             # package marker
backend/app/play/models.py               # PlayRequest, PlayResponse
```

**Note:** file organization follows the existing module-local `models.py` convention (see `auth/`, `search/`, `chat/`, `sync/`, `embedding/`) — no top-level `schemas/` directory. Jellyfin-domain types live in `jellyfin/device_models.py`; `/api/play` request/response shapes live in the new `play/` module.

### Modified files

- `backend/app/jellyfin/errors.py` — add `DeviceOfflineError`, `PlaybackAuthError`, `PlaybackDispatchError` — all subclass `JellyfinError`
- `backend/app/jellyfin/client.py` — extract shared transport helper, refactor existing `JellyfinClient` to use it
- `backend/app/main.py` — wire new routers

### API shapes

**`GET /api/devices`** (auth required, no CSRF, rate-limited 10/min per user)

```json
// 200 OK
[
  {
    "session_id": "a1b2c3d4…",
    "name": "Living Room TV",
    "client": "Jellyfin Android TV",
    "device_type": "Tv"
  }
]
```

- Empty list is a normal 200 response.
- `name` = Jellyfin's `DeviceName`.
- `device_type` ∈ `{"Tv", "Mobile", "Tablet", "Other"}` derived via private `_classify_device(client: str, device_id: str) -> DeviceType` function in `sessions.py`. Classifier uses string matching on Jellyfin's `Client` field against a small lookup table (e.g., `"AndroidTV" / "KodiTV" / "SamsungTV" → Tv`; `"Mobile" / "iOS" / "Android" without "TV" → Mobile`; `"iPad" / "Tablet" → Tablet`; else `Other`). Table-driven, unit-tested against fixtures of real Jellyfin client strings.

**`POST /api/play`** (auth required, CSRF required, rate-limited **3/min per user**)

```json
// Request
{"item_id": "f4e3d2c1…", "session_id": "a1b2c3d4…"}
```

| Response | Condition | Picker behavior |
|---|---|---|
| `200 {"status":"ok","device_name":"Living Room TV"}` | Jellyfin accepted | Close picker; sonner success `Now playing on Living Room TV` |
| `401 {"error":"jellyfin_auth_failed"}` | Jellyfin 401/403 mid-flight (token revoked) | Close picker; sonner error; frontend auth context triggers re-login flow |
| `409 {"error":"device_offline"}` | Jellyfin 404/400 on session ID | Stay open; re-fetch device list; show `aria-live="assertive"` banner `That device just went offline — pick another` |
| `500 {"error":"playback_failed"}` | Network, Jellyfin 5xx, unknown | Close picker; sonner generic error |

The 3/min rate limit on `POST /api/play` (vs. 10/min on other endpoints) reflects blast radius: play dispatch affects other people's screens on a family server with publicly-routable Jellyfin. `GET /api/devices` keeps 10/min — reads are self-affecting.

### Config

No new environment variables.

### Logging

INFO on dispatch logs target device name + type only. **No item titles, no item IDs, no user tokens.** httpx exception messages (which can contain URLs with auth params) are **scrubbed** before logging — T3 unit tests assert this.

## Frontend components

### New dependency

**`sonner`** (≈3kb) for success/error notifications. Accessible by default (`role="status"` + live region). Project-wide `<Toaster />` mounts in the root layout in T2; becomes the notification primitive for all future features.

### New files

```
frontend/src/components/chat/device-picker-dialog.tsx   # New component
frontend/src/lib/api/devices.ts                          # fetchDevices + postPlay
```

### Edits

```
frontend/src/lib/api/types.ts                            # Add Device, PlayRequest, PlayResponse types
frontend/src/components/chat/card-detail.tsx            # Add "Cast to TV" button + dialog wiring
frontend/src/app/layout.tsx                              # Mount <Toaster /> from sonner (T2)
```

### `device-picker-dialog.tsx` — states

| State | Display | User action | A11y |
|---|---|---|---|
| Loading | Skeleton list | None | — |
| List (populated) | Rows: name (line 1) + client + type (line 2); min 44px tap height | Tap to dispatch | Real `<button>` with `aria-label="Cast {title} to {name}, {client}"` |
| Empty | "No devices found. Open Jellyfin on your TV or phone, then refresh." + prominent text-labeled **Refresh** button | Refresh | — |
| Fetch error | "Couldn't load devices. Try again." + Refresh | Refresh | — |
| Dispatching | Inline spinner on tapped row; other rows disabled; a second tap during in-flight is a no-op | Wait | — |
| Device-offline | Banner at top `That device just went offline — pick another`; **list re-fetched in place** | Pick another or Refresh | `aria-live="assertive"` — user is mid-interaction, needs prompt announcement |

Closes on: successful dispatch, generic error (after sonner toast), auth failure (after re-login trigger), explicit close, or tap outside. State owned by dialog: devices list, `selectedSessionId` during dispatch, transient offline banner.

### `card-detail.tsx` — diff shape

Button renamed to **"Cast to TV"**:

```tsx
<button
  type="button"
  onClick={() => setPickerOpen(true)}
  className="inline-flex min-h-11 items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
>
  Cast to TV
</button>
<DevicePickerDialog
  open={pickerOpen}
  item={item}
  onClose={() => setPickerOpen(false)}
  onDispatched={(deviceName) => {
    toast.success(`Now playing on ${deviceName}`); // sonner
    setPickerOpen(false);
  }}
/>
```

Two dialogs stacking (card-detail → device-picker) is supported by the Radix Dialog primitive. Existing `card-detail.tsx` confirms the pattern works.

### API client

Two thin functions: `fetchDevices(): Promise<Device[]>` and `postPlay(req: PlayRequest): Promise<PlayResponse>`. Both use `apiFetch` — same session cookie, CSRF header, error-handling conventions as chat and search. `postPlay` maps `401 → JellyfinAuthError` (triggers auth context re-login), `409 → DeviceOfflineError`, `500 → PlaybackFailedError`.

### Success/error notifications (sonner)

| Event | sonner call | Duration | Placement |
|---|---|---|---|
| Play dispatch succeeded | `toast.success(…)` | 4s | Responsive default (bottom-center mobile, top-right desktop) |
| Generic error (500) | `toast.error(…)` | 5s | Same |
| Auth failure (401) | `toast.error(…)` + trigger re-login | 5s | Same |
| Device offline (409) | **Not a toast** — in-picker banner with `aria-live="assertive"` | Persistent until resolved | — |

### Device-type icons

Use Lucide icons (`Tv`, `Smartphone`, `Tablet`, `MonitorSmartphone` for Other) if `lucide-react` is already a project dependency. Four-line mapping from `device_type` → icon component. If `lucide-react` is not imported, ship without icons and open a follow-up issue during T2 implementation.

### Accessibility

- **Focus trap** inside picker — handled by Radix Dialog default.
- **Focus return on close** — rely on Radix Dialog's default `returnFocus` behavior; T2 must **not suppress it**. T2 includes a verification step ensuring focus returns to the "Cast to TV" button after picker close.
- **Offline banner** — `aria-live="assertive"` (user is mid-interaction; politeness causes missed announcements).
- **Success notifications** — sonner's default `role="status"` + `aria-live="polite"` for non-critical confirmations.
- **Picker items** — real `<button>` elements; `aria-label` includes movie title + device name + client for context.
- **Min 44px tap targets** per existing convention in `movie-card.tsx`.

## Testing strategy

### Backend unit tests (`unittest.mock`)

| Subject | Covers |
|---|---|
| Shared transport helper | Auth header formatting; 401 → `JellyfinAuthError`; transport error → `JellyfinConnectionError`; JSON error wrapping |
| `JellyfinSessionsClient` | Happy path; `SupportsRemoteControl` filter; **self-session exclusion by UserId+DeviceId correlation**; 401; empty list |
| `_classify_device` | Fixture table: AndroidTV/KodiTV/SamsungTV → Tv; iOS/Android/Mobile → Mobile; iPad/Tablet → Tablet; unknown → Other |
| `JellyfinPlaybackClient` | Happy path (204 → ok); 404/400 → `DeviceOfflineError`; **401/403 → `PlaybackAuthError`** (new); 5xx → `PlaybackDispatchError`; timeout → `PlaybackDispatchError`; exception message scrubbing |
| `GET /api/devices` router | Unauthenticated → 401; authenticated → list shape; empty list → `200 []`; 10/min rate limit |
| `POST /api/play` router | Unauthenticated → 401; missing CSRF → 403; **3/min** rate limit → 429; happy path → 200 with `device_name`; `DeviceOfflineError` → 409; **`PlaybackAuthError` → 401** (new); `PlaybackDispatchError` → 500 |

All Jellyfin interactions mocked with `unittest.mock` (`AsyncMock`, `MagicMock`, `patch`) — matches existing pattern in `backend/tests/test_sync_engine.py` and related files.

### Backend integration tests (real disposable Jellyfin)

Two tests:

1. **`GET /api/devices` returns empty list** against fresh disposable Jellyfin — proves the client connects and returns the empty-case shape correctly.
2. **`GET /api/devices` field-name mapping** — confirms the real Jellyfin response carries the fields we assume (`Id`, `UserId`, `DeviceId`, `DeviceName`, `Client`, `SupportsRemoteControl`). Uses a synthetic session injected via Jellyfin's own admin API during test setup, or asserts the absence of missing fields against a known-empty response. If Jellyfin rejects the synthetic session approach, the test narrows to schema validation on the empty case.

Playback dispatch is **not** integration-tested in Epic 4 — deferred to #195.

### Frontend unit tests (vitest + Testing Library, `vi.stubGlobal("fetch")` mocks)

| Subject | Covers |
|---|---|
| `device-picker-dialog` | Loading → list; empty + refresh; fetch error + retry; dispatch with correct payload; inline spinner on dispatching row; **concurrent-dispatch race** (second tap during in-flight is no-op); device-offline banner + in-place refetch; `aria-live="assertive"` on banner; closes and emits `onDispatched(deviceName)` on success; sonner error notification on 500; 401 triggers re-login |
| `card-detail` (diff) | "Cast to TV" renders; tap opens picker; `onDispatched` fires `toast.success` (sonner); **focus returns to "Cast to TV" button after picker close** |
| `lib/api/devices` | `fetchDevices` passes session cookie + handles non-200; `postPlay` sends CSRF header + maps 401 → `JellyfinAuthError`, 409 → `DeviceOfflineError`, 500 → `PlaybackFailedError` |

## Ticket breakdown

Four tickets, each ≤3pt, single-PR ≤500 LOC, two demoable beats.

### T1 — Backend: shared transport + `GET /api/devices` (~3pt)

**Rewrites:** #12

**Deliverables:**
- **Refactor**: extract shared Jellyfin transport helper from existing `backend/app/jellyfin/client.py`; refactor `JellyfinClient` to use it. Unit tests for the shared helper land here.
- `backend/app/jellyfin/sessions.py` — `JellyfinSessionsClient.list_controllable(user_token, current_user_id, current_device_id)` with server-side self-exclusion via UserId+DeviceId correlation
- `backend/app/jellyfin/sessions.py` — private `_classify_device(client, device_id)` with fixture tests
- `backend/app/jellyfin/device_models.py` — `Device`, `DeviceType`
- `backend/app/jellyfin/errors.py` — add `DeviceOfflineError` (subclass `JellyfinError`)
- `backend/app/routers/devices.py` — `GET /api/devices`, auth required, 10/min rate limit
- Wire into `backend/app/main.py`
- Unit tests: shared transport (auth header, 401, transport error, JSON error wrap); sessions client (happy path, filter, UserId+DeviceId correlation, 401, empty); `_classify_device` fixture table; router (auth, empty, rate limit)
- **Two** integration tests: empty-list shape + field-mapping verification
- OpenAPI spec update

**Done when:** endpoint returns empty list against real Jellyfin; field mapping verified; all unit tests pass; OpenAPI includes `GET /api/devices`.

**Blocks:** T2

### T2 — Frontend: device-picker Dialog + sonner (~3pt)

**New issue**

**Deliverables:**
- `npm install sonner` + mount `<Toaster />` in root layout
- `frontend/src/lib/api/devices.ts` — `fetchDevices` only (no `postPlay` yet)
- `frontend/src/lib/api/types.ts` — add `Device` type
- `frontend/src/components/chat/device-picker-dialog.tsx` — full component; `aria-live="assertive"` on offline banner; real `fetchDevices` call
- `frontend/src/components/chat/card-detail.tsx` — "Cast to TV" button; opens picker; `onDispatched` stubbed to log + close picker
- **Focus-return verification:** test asserts focus returns to "Cast to TV" button after picker dismissal
- Device-type icons from Lucide if `lucide-react` is already in `frontend/package.json`; otherwise open a follow-up issue
- Empty-state copy per spec
- vitest tests: all picker states; card-detail diff; focus-return; loading/empty/error
- Fetch stubs for `/api/devices` via `vi.stubGlobal("fetch", ...)`

**Demoable beat:** User opens card-detail, taps "Cast to TV", sees live device states (empty, populated, refresh, error). Tapping a device logs the intent + closes picker. Sonner toasts not yet wired (T4).

**Depends on:** T1
**Blocks:** T4

### T3 — Backend: `POST /api/play` (~3pt)

**Rewrites:** #13 (backend-only slice)

**Deliverables:**
- `backend/app/jellyfin/playback.py` — `JellyfinPlaybackClient.dispatch_play(session_id, item_id, user_token)` raising `DeviceOfflineError` / `PlaybackAuthError` / `PlaybackDispatchError`
- `backend/app/jellyfin/errors.py` — add `PlaybackAuthError`, `PlaybackDispatchError` (subclass `JellyfinError`)
- `backend/app/play/__init__.py`, `backend/app/play/models.py` — `PlayRequest`, `PlayResponse`
- `backend/app/routers/play.py` — `POST /api/play`, auth + CSRF + **3/min** rate limit; returns 200 / 401 / 409 / 500 per error mapping
- Wire into `backend/app/main.py`
- Unit tests: auth, CSRF, 3/min rate limit, happy path with `device_name`, `DeviceOfflineError → 409`, `PlaybackAuthError → 401`, `PlaybackDispatchError → 500`, exception message scrubbing
- **No integration test** — deferred to #195
- OpenAPI spec update

**Done when:** all unit tests pass; OpenAPI includes `POST /api/play` with all four response shapes documented.

**Blocks:** T4

### T4 — Frontend: real dispatch + notifications (~2pt)

**New issue**

**Deliverables:**
- `frontend/src/lib/api/devices.ts` — add `postPlay`; map 401 → `JellyfinAuthError`, 409 → `DeviceOfflineError`, 500 → `PlaybackFailedError`
- `frontend/src/components/chat/device-picker-dialog.tsx` — replace stub with real dispatch; inline spinner; `onDispatched(device_name)` on success; offline banner + in-place refetch on 409; sonner error toast on 500; 401 triggers auth-context re-login
- `frontend/src/components/chat/card-detail.tsx` — wire `toast.success(\`Now playing on ${deviceName}\`)` (sonner) on `onDispatched`
- Expanded vitest coverage: all outcome paths (200/401/409/500); concurrent-dispatch race
- Fetch stubs for `/api/play` happy/401/409/500

**Demoable beat (Epic 4 complete):** Full flow — chat → recommendation → tap card → "Cast to TV" → pick device → movie starts on TV. Offline triggers in-place re-fetch without losing context. Generic errors surface as sonner toasts. Revoked-token triggers re-login.

**Depends on:** T2 and T3

### Dependency graph

```
T1 (backend: transport + GET /api/devices)
      │
      └────────────┐
                   │
                   ▼
                  T2 (frontend: picker + sonner)
                   │
T3 (backend: POST /api/play) (parallel with T1)
                   │                              │
                   └──────────────────────────────┤
                                                  ▼
                                               T4 (frontend: real dispatch + notifications)
```

- **T1 ∥ T3** run in parallel (independent files, independent test suites).
- **T2** depends only on T1 (needs `GET /api/devices` live).
- **T4** depends on T2 and T3 (needs both the picker scaffold and the dispatch endpoint).
- Max parallelism: T1 ∥ T3 → T2 → T4.

### GitHub issue mapping

| Ticket | Current GH issue | Action |
|---|---|---|
| T1 | #12 | **Rewrite body** to match T1 scope (shared transport + devices endpoint); size 3pt; remove "polling mechanism" |
| T2 | (none) | **Open new issue** — frontend picker + sonner |
| T3 | #13 | **Rewrite body** to match T3 (backend-only slice); size 3pt; remove frontend requirements |
| T4 | (none) | **Open new issue** — frontend real dispatch + notifications |

Already filed: **#195** (fake playback client, deferred tech debt).

## Review notes for SDD-1

- **Frontend specs (T2, T4):** Adorabelle already ruled on the three major UX questions (button label, notification library, refresh affordance) during this Council review. SDD-1 question sessions can skip those and focus on implementation detail.
- **Backend specs (T1, T3):** Granny, Angua, Carrot findings have been incorporated inline. Watch Council still reviews PRs at merge time per standard workflow.
- **Cross-ticket:** Confirm OpenAPI spec updates land in the same PR as the endpoint changes, per project convention.

## Open questions (resolved)

- **Success-notification mechanism:** ✅ `sonner` — 3kb, accessible by default. Ruled by Adorabelle.
- **Toast durations:** ✅ 4s success, 5s error. Placement: sonner responsive defaults (bottom-center mobile, top-right desktop). Ruled by Adorabelle.
- **Refresh button affordance:** ✅ Prominent, text-labeled "Refresh". Ruled by Adorabelle.
- **Button label:** ✅ "Cast to TV" — platform convention; "Play on Device" rejected. Ruled by Adorabelle.
- **Self-session exclusion mechanism:** ✅ Server-side UserId+DeviceId correlation; frontend never supplies session_id for exclusion. Ruled by Angua + Granny + Carrot consensus.
- **File organization:** ✅ Module-local `models.py` (no top-level `schemas/`). Ruled by Carrot.
- **Shared Jellyfin transport:** ✅ Extract from existing `JellyfinClient`; new clients compose against it. Ruled by Granny.
- **Exception placement and naming:** ✅ `DeviceOfflineError`, `PlaybackAuthError`, `PlaybackDispatchError` in `jellyfin/errors.py`, all subclass `JellyfinError`. Ruled by Granny.
- **Rate limit on `POST /api/play`:** ✅ 3/min (vs. 10/min on other endpoints). Reflects disruption blast radius. Ruled by Angua.
- **Auth-failure error status:** ✅ Split 401 from generic 500 bucket. Ruled by Angua.

## Open questions (deferred to T2 implementation — non-blocking)

- **Device-type icons:** include Lucide icons in T2 if `lucide-react` is already imported; otherwise open a follow-up issue during T2. Not blocking the epic.
