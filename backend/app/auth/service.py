"""Session creation, eviction, and expiry logic."""

from __future__ import annotations

import logging
import secrets
import time
from typing import TYPE_CHECKING

from app.auth.crypto import derive_keys
from app.auth.models import LoginResponse

if TYPE_CHECKING:
    from app.auth.session_store import SessionStore
    from app.jellyfin.client import JellyfinClient

logger = logging.getLogger(__name__)


class AuthService:
    """Orchestrates session lifecycle — login, cap enforcement, cleanup."""

    def __init__(
        self,
        session_store: SessionStore,
        jellyfin_client: JellyfinClient,
        session_secret: str,
        session_expiry_hours: int,
        max_sessions_per_user: int,
    ) -> None:
        self._store = session_store
        self._jf = jellyfin_client
        self._cookie_key, self._column_key = derive_keys(session_secret)
        self._expiry_hours = session_expiry_hours
        self._max_sessions = max_sessions_per_user

    @property
    def cookie_key(self) -> bytes:
        """Cookie-signing Fernet key (for encrypting session ID in cookie)."""
        return self._cookie_key

    async def login(
        self, username: str, password: str
    ) -> tuple[str, str, LoginResponse]:
        """Authenticate and create a session.

        Returns:
            (session_id, csrf_token, login_response)
        """
        auth_result = await self._jf.authenticate(username, password)
        server_name = await self._jf.get_server_name()

        session_id = secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(32)
        now = int(time.time())
        expires_at = now + self._expiry_hours * 3600

        await self._store.create(
            session_id=session_id,
            user_id=auth_result.user_id,
            username=auth_result.user_name,
            server_name=server_name,
            token=auth_result.access_token,
            csrf_token=csrf_token,
            expires_at=expires_at,
        )

        logger.info("user_login user_id=%s", auth_result.user_id)

        return (
            session_id,
            csrf_token,
            LoginResponse(
                user_id=auth_result.user_id,
                username=auth_result.user_name,
                server_name=server_name,
            ),
        )
