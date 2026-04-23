"""Devices API route — list Jellyfin sessions that can receive Play commands.

Authenticated read endpoint (CSRF-exempt per the project's Double-Submit
policy, which only applies to state-changing requests).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Request
from slowapi import Limiter  # noqa: TC002

from app.auth.dependencies import get_current_session
from app.jellyfin.device_models import Device  # noqa: TC001
from app.jellyfin.errors import (
    JellyfinAuthError,
    JellyfinConnectionError,
    JellyfinError,
)
from app.jellyfin.sessions import JellyfinSessionsClient  # noqa: TC001

if TYPE_CHECKING:
    from app.auth.models import SessionMeta

logger = logging.getLogger(__name__)

# 10 requests/minute per client IP — consistent with existing read endpoints
# (search). Rate limit is hard-coded, matching the `CHAT_RATE_LIMIT` /
# `LOGIN_RATE_LIMIT` pattern for per-endpoint tightening that is not
# operator-tunable. Non-blocking per Spec 24 Open Question 2.
#
# Rate limit is per client IP (slowapi default). See #204 to migrate
# auth-gated endpoints to per-user keying.
_DEVICES_RATE_LIMIT = "10/minute"


def get_sessions_client(request: Request) -> JellyfinSessionsClient:
    """Dependency factory for ``JellyfinSessionsClient``.

    Reads the already-built client off ``request.app.state``. Centralises
    the lookup so tests can override it via FastAPI ``dependency_overrides``.
    """
    return request.app.state.jellyfin_sessions_client  # type: ignore[no-any-return]


def create_devices_router(limiter: Limiter | None = None) -> APIRouter:
    """Build the devices APIRouter.

    Rate limit is hard-coded at 10/min per client IP (see module docstring).
    """
    router = APIRouter(prefix="/api", tags=["devices"])
    _limit = limiter.limit(_DEVICES_RATE_LIMIT) if limiter else (lambda f: f)

    @router.get(
        "/devices",
        response_model=list[Device],
        responses={
            401: {"description": "Not authenticated"},
            429: {"description": "Rate limit exceeded"},
            502: {"description": "Jellyfin upstream error"},
            503: {"description": "Jellyfin unreachable"},
        },
    )
    @_limit
    async def list_devices(
        request: Request,
        session: SessionMeta = Depends(get_current_session),  # noqa: B008
        sessions_client: JellyfinSessionsClient = Depends(get_sessions_client),  # noqa: B008
    ) -> list[Device]:
        """Return this user's controllable Jellyfin sessions.

        Filters on ``SupportsRemoteControl == True``; classifies each
        session by client string into a coarse ``DeviceType``.

        Rate limit is per client IP (slowapi default). See #204 to migrate
        auth-gated endpoints to per-user keying.
        """
        session_store = request.app.state.session_store
        token = await session_store.get_token(session.session_id)
        if token is None:
            raise HTTPException(status_code=401, detail="Not authenticated")

        try:
            return await sessions_client.list_controllable(token)
        except JellyfinAuthError as exc:
            # Revoked/expired Jellyfin token — surface as 401 so the
            # frontend can trigger re-login. Mirrors the auth-failure
            # split pattern used in auth/login and play routers.
            raise HTTPException(status_code=401, detail="jellyfin_auth_failed") from exc
        except JellyfinConnectionError as exc:
            raise HTTPException(status_code=503, detail="jellyfin_unreachable") from exc
        except JellyfinError as exc:
            # Catch-all for upstream protocol/parse failures.
            raise HTTPException(status_code=502, detail="jellyfin_error") from exc

    return router
