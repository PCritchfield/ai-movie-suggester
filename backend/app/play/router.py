"""POST /api/play router — playback dispatch for Epic 4.

Orchestration layering (Granny-B4 ruling, Spec 24 audit Run 3):

    The router — not the playback client — calls ``list_controllable``
    first to resolve ``device_name``, then calls ``dispatch_play``.
    ``JellyfinSessionsClient`` and ``JellyfinPlaybackClient`` stay
    single-purpose and unit-testable in isolation; the router owns
    cross-client orchestration. Do NOT collapse the two calls into one
    client — that couples two capability clients, bloats the mock
    surface, and offers negligible performance benefit at 3/min/user.

Flow per spec §5.3:

    1. ``sessions_client.list_controllable(jellyfin_token)``
    2. If ``body.session_id`` is not in the returned list →
       return 409 ``{"error": "device_offline"}`` *without* invoking
       ``dispatch_play`` (**pre-dispatch 409** — distinct code path
       from the post-dispatch ``DeviceOfflineError`` branch).
    3. ``playback_client.dispatch_play(session_id, item_id, jellyfin_token)``
    4. Log INFO ``"play dispatched"`` with
       ``extra={"device_name": ..., "device_type": ...}``
       (no item IDs / titles / tokens — per the no-PII-in-logs rule).
    5. Return ``PlayResponse(status="ok", device_name=...)``.

Error mapping (step 1 — list_controllable):

    * ``JellyfinAuthError``       → 401 ``{"error": "jellyfin_auth_failed"}``
    * ``JellyfinConnectionError`` → 503 ``{"error": "jellyfin_unreachable"}``
    * ``JellyfinError`` (catch-all) → 502 ``{"error": "jellyfin_error"}``

Error mapping (post-dispatch):

    * ``DeviceOfflineError`` → 409 ``{"error": "device_offline"}``
      (Jellyfin rejected the play because the session evaporated
      between steps 1 and 3 — same response shape as the pre-dispatch
      409, different code path.)
    * ``PlaybackAuthError``   → 401 ``{"error": "jellyfin_auth_failed"}``
    * ``PlaybackDispatchError`` → 500 ``{"error": "playback_failed"}``

Rate limit: 3/min per client IP (slowapi default — see #204 for
planned per-user migration of auth-gated endpoints). Tighter than
the 10/min on reads; reflects the playback-dispatch blast radius on
a publicly-routable Jellyfin — IP-based limiting still constrains
stolen-credential flooding from a single source.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from slowapi import Limiter  # noqa: TC002

from app.auth.dependencies import get_current_session
from app.jellyfin.errors import (
    DeviceOfflineError,
    JellyfinAuthError,
    JellyfinConnectionError,
    JellyfinError,
    PlaybackAuthError,
    PlaybackDispatchError,
)
from app.play.models import PlayRequest, PlayResponse  # noqa: TC001

if TYPE_CHECKING:
    from app.auth.models import SessionMeta
    from app.config import Settings

logger = logging.getLogger(__name__)

# Hard-coded per spec — not env-backed; see Open Question 2 in
# `24-spec-remote-control-backend.md`.
_PLAY_RATE_LIMIT = "3/minute"


def get_sessions_client(request: Request) -> Any:
    """Return the app-scoped Jellyfin sessions client (DI seam).

    The provider lives in ``app.main``; tests override this dependency
    directly via ``app.dependency_overrides`` with an ``AsyncMock``.
    """
    return request.app.state.jellyfin_sessions_client


def get_playback_client(request: Request) -> Any:
    """Return the app-scoped Jellyfin playback client (DI seam)."""
    return request.app.state.jellyfin_playback_client


def create_play_router(
    settings: Settings,  # noqa: ARG001 — kept for parity with peer routers
    limiter: Limiter | None = None,
) -> APIRouter:
    """Build the POST /api/play APIRouter with a 3/min rate limit.

    Rate limit is per client IP (slowapi default). See #204 to migrate
    auth-gated endpoints to per-user keying.
    """
    router = APIRouter(prefix="/api", tags=["play"])
    _limit = limiter.limit(_PLAY_RATE_LIMIT) if limiter else (lambda f: f)

    @router.post(
        "/play",
        response_model=PlayResponse,
        responses={
            200: {"description": "Playback command accepted"},
            401: {"description": "Not authenticated or Jellyfin auth failed"},
            403: {"description": "CSRF token missing or invalid"},
            409: {"description": "Target device is offline"},
            422: {"description": "Validation error"},
            429: {"description": "Rate limit exceeded"},
            500: {"description": "Playback dispatch failed"},
            502: {"description": "Upstream Jellyfin error during device resolution"},
            503: {"description": "Jellyfin unreachable during device resolution"},
        },
    )
    @_limit
    async def play(
        body: PlayRequest,
        request: Request,
        session: SessionMeta = Depends(get_current_session),  # noqa: B008
        sessions_client: Any = Depends(get_sessions_client),  # noqa: B008
        playback_client: Any = Depends(get_playback_client),  # noqa: B008
    ) -> PlayResponse | JSONResponse:
        """Dispatch a Jellyfin play command to a controllable session."""
        session_store = request.app.state.session_store
        token = await session_store.get_token(session.session_id)
        if token is None:
            raise HTTPException(status_code=401, detail="Not authenticated")

        # Step 1: enumerate controllable sessions (user-token auth).
        # Router-level orchestration owns error mapping across capability
        # clients (Granny-B4 ruling) — the sessions client raises typed
        # JellyfinError subclasses; the router translates to HTTP. Uses
        # JSONResponse to match the ``{"error": "..."}`` body shape emitted
        # by the post-dispatch handlers below.
        try:
            devices = await sessions_client.list_controllable(token)
        except JellyfinAuthError:
            return JSONResponse(
                status_code=401,
                content={"error": "jellyfin_auth_failed"},
            )
        except JellyfinConnectionError:
            return JSONResponse(
                status_code=503,
                content={"error": "jellyfin_unreachable"},
            )
        except JellyfinError:
            return JSONResponse(
                status_code=502,
                content={"error": "jellyfin_error"},
            )

        # Step 2: find the requested device. If absent → pre-dispatch 409
        # WITHOUT calling dispatch_play.
        device = next(
            (d for d in devices if d.session_id == body.session_id),
            None,
        )
        if device is None:
            return JSONResponse(
                status_code=409,
                content={"error": "device_offline"},
            )

        # Step 3: dispatch (maps Jellyfin/httpx errors to typed exceptions).
        try:
            await playback_client.dispatch_play(body.session_id, body.item_id, token)
        except DeviceOfflineError:
            # Post-dispatch 409 — session evaporated between steps 1 and 3.
            return JSONResponse(
                status_code=409,
                content={"error": "device_offline"},
            )
        except PlaybackAuthError:
            return JSONResponse(
                status_code=401,
                content={"error": "jellyfin_auth_failed"},
            )
        except PlaybackDispatchError:
            return JSONResponse(
                status_code=500,
                content={"error": "playback_failed"},
            )

        # Step 4: INFO log — ONLY device_name + device_type.
        # No item IDs / titles / tokens (per no-PII-in-logs rule).
        logger.info(
            "play dispatched",
            extra={
                "device_name": device.name,
                "device_type": device.device_type,
            },
        )

        # Step 5: happy response.
        return PlayResponse(status="ok", device_name=device.name)

    return router
