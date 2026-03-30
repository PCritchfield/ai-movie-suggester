"""FastAPI dependencies and helpers for the permission service."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastapi.responses import JSONResponse

if TYPE_CHECKING:
    from fastapi import Request

    from app.auth.session_store import SessionStore
    from app.config import Settings
    from app.permissions.service import PermissionService

logger = logging.getLogger(__name__)


async def get_permission_service(request: Request) -> PermissionService:
    """Retrieve the PermissionService from app state."""
    return request.app.state.permission_service


async def handle_permission_auth_error(
    session_id: str,
    session_store: SessionStore,
    permission_service: PermissionService,
    user_id: str,
    settings: Settings,
) -> JSONResponse:
    """Destroy session and return 401 when Jellyfin token is invalid.

    Clears the session from the store, invalidates the permission cache,
    and returns a 401 JSONResponse with the session cookie deleted.

    Idempotent: safe to call even if the session has already been deleted.
    """
    await session_store.delete(session_id)
    permission_service.invalidate_user_cache(user_id)
    logger.warning(
        "session_destroyed_token_invalid session_id=%s user_id=%s",
        session_id,
        user_id,
    )
    resp = JSONResponse(status_code=401, content={"detail": "Session expired"})
    # Clear session cookie at current and legacy paths
    for path in ("/", "/api"):
        resp.delete_cookie(
            key="session_id",
            httponly=True,
            samesite="lax",
            secure=settings.session_secure_cookie,
            path=path,
        )
    # Clear CSRF cookie at current and legacy paths
    for path in ("/", "/api"):
        resp.delete_cookie(
            key="csrf_token",
            samesite="lax",
            secure=settings.session_secure_cookie,
            path=path,
        )
    return resp
