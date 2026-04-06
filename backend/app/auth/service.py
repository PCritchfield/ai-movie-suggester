"""Session creation, eviction, and expiry logic."""

from __future__ import annotations

import logging
import secrets
import time
from typing import TYPE_CHECKING

from app.auth.models import LoginResponse
from app.jellyfin.errors import JellyfinError

if TYPE_CHECKING:
    from app.auth.session_store import SessionStore
    from app.chat.conversation_store import ConversationStore
    from app.jellyfin.client import JellyfinClient

logger = logging.getLogger(__name__)


class AuthService:
    """Orchestrates session lifecycle — login, cap enforcement, cleanup."""

    def __init__(
        self,
        session_store: SessionStore,
        jellyfin_client: JellyfinClient,
        session_expiry_hours: int,
        max_sessions_per_user: int,
        conversation_store: ConversationStore | None = None,
    ) -> None:
        self._store = session_store
        self._jf = jellyfin_client
        self._expiry_hours = session_expiry_hours
        self._max_sessions = max_sessions_per_user
        self._conversation_store = conversation_store

    async def _enforce_session_cap(self, user_id: str) -> None:
        """Evict oldest sessions until count < max_sessions_per_user."""
        while await self._store.count_by_user(user_id) >= self._max_sessions:
            oldest = await self._store.oldest_by_user(user_id)
            if oldest is None:
                break
            # Best-effort Jellyfin token revocation
            try:
                await self._jf.logout(oldest.token)
            except JellyfinError:
                logger.warning(
                    "jellyfin unreachable during eviction user_id=%s",
                    user_id,
                )
            await self._store.delete(oldest.session_id)
            if self._conversation_store is not None:
                self._conversation_store.purge_session(oldest.session_id)
            count = await self._store.count_by_user(user_id)
            logger.info(
                "session_evicted user_id=%s sessions_count=%d",
                user_id,
                count,
            )

    async def login(
        self, username: str, password: str
    ) -> tuple[str, str, LoginResponse]:
        """Authenticate and create a session.

        Returns:
            (session_id, csrf_token, login_response)
        """
        auth_result = await self._jf.authenticate(username, password)
        server_name = await self._jf.get_server_name()

        # Enforce session cap before creating new session
        await self._enforce_session_cap(auth_result.user_id)

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


async def cleanup_expired_sessions(
    store: SessionStore,
    jf_client: JellyfinClient,
    conversation_store: ConversationStore | None = None,
) -> None:
    """Delete expired sessions and attempt Jellyfin token revocation."""
    expired = await store.get_expired()
    for session in expired:
        try:
            await jf_client.logout(session.token)
        except JellyfinError:
            logger.warning(
                "jellyfin unreachable during expiry cleanup user_id=%s",
                session.user_id,
            )
        await store.delete(session.session_id)
        if conversation_store is not None:
            conversation_store.purge_session(session.session_id)
        logger.info("session_expired user_id=%s", session.user_id)
