"""FastAPI dependencies for session validation."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from fastapi import HTTPException, Request

from app.auth.crypto import decrypt_cookie

if TYPE_CHECKING:
    from app.auth.models import SessionMeta


async def get_current_session(request: Request) -> SessionMeta:
    """Extract and validate the session from the request cookie.

    Returns SessionMeta on success.
    Raises HTTPException(401) on missing, invalid, or expired session.
    """
    cookie_key: bytes = request.app.state.cookie_key
    session_store = request.app.state.session_store

    session_id = decrypt_cookie(cookie_key, request.cookies.get("session_id"))
    if session_id is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    meta = await session_store.get_metadata(session_id)
    if meta is None or meta.expires_at < int(time.time()):
        raise HTTPException(status_code=401, detail="Not authenticated")

    return meta
