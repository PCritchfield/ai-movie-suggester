"""FastAPI dependencies for sync admin authorization."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import HTTPException, Request

from app.auth.dependencies import get_current_session
from app.jellyfin.errors import (
    JellyfinAuthError,
    JellyfinConnectionError,
)

if TYPE_CHECKING:
    from app.auth.models import SessionMeta


async def require_admin(request: Request) -> SessionMeta:
    """Validate that the current user is a Jellyfin administrator.

    1. Extracts and validates the session cookie (via get_current_session).
    2. Retrieves the full session row (including the decrypted Jellyfin token).
    3. Calls Jellyfin /Users/Me to check Policy.IsAdministrator.

    Raises HTTPException(401) if not authenticated or token expired.
    Raises HTTPException(403) if authenticated but not an admin.
    Raises HTTPException(503) if Jellyfin is unreachable.
    """
    session = await get_current_session(request)

    # Get the full session row (includes decrypted token)
    session_store = request.app.state.session_store
    session_row = await session_store.get(session.session_id)
    if session_row is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    # Check admin status via Jellyfin
    jf_client = request.app.state.jellyfin_client
    try:
        user_info = await jf_client.get_user(session_row.token)
    except JellyfinAuthError as exc:
        raise HTTPException(status_code=401, detail="Not authenticated") from exc
    except JellyfinConnectionError as exc:
        raise HTTPException(
            status_code=503, detail="Jellyfin server unavailable"
        ) from exc

    if not user_info.policy.is_administrator:
        raise HTTPException(status_code=403, detail="Admin access required")

    return session
