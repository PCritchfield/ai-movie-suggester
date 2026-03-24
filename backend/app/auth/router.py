"""Auth API routes — login, me, logout."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Request, Response

from app.auth.crypto import fernet_decrypt, fernet_encrypt
from app.auth.dependencies import get_current_session
from app.auth.models import (
    ErrorResponse,
    LoginRequest,
    LoginResponse,
    LogoutResponse,
    SessionMeta,
)
from app.jellyfin.errors import JellyfinAuthError, JellyfinConnectionError

if TYPE_CHECKING:
    from app.auth.service import AuthService
    from app.auth.session_store import SessionStore
    from app.config import Settings

logger = logging.getLogger(__name__)


def create_auth_router(
    auth_service: AuthService,
    session_store: SessionStore,
    settings: Settings,
    cookie_key: bytes,
) -> APIRouter:
    """Build the auth APIRouter with closures over service dependencies."""
    router = APIRouter(prefix="/api/auth", tags=["auth"])

    def _set_session_cookie(response: Response, session_id: str) -> None:
        encrypted = fernet_encrypt(cookie_key, session_id).decode("utf-8")
        response.set_cookie(
            key="session_id",
            value=encrypted,
            httponly=True,
            samesite="lax",
            secure=settings.session_secure_cookie,
            path="/api",
            max_age=settings.session_expiry_hours * 3600,
        )

    def _clear_session_cookie(response: Response) -> None:
        response.delete_cookie(
            key="session_id",
            httponly=True,
            samesite="lax",
            secure=settings.session_secure_cookie,
            path="/api",
        )

    def _decrypt_session_cookie(request: Request) -> str | None:
        """Extract and decrypt the session_id cookie. Returns None on failure."""
        cookie_value = request.cookies.get("session_id")
        if not cookie_value:
            return None
        try:
            return fernet_decrypt(cookie_key, cookie_value.encode("utf-8"))
        except Exception:
            return None

    @router.post(
        "/login",
        response_model=LoginResponse,
        responses={401: {"model": ErrorResponse}, 502: {"model": ErrorResponse}},
    )
    async def login(body: LoginRequest, response: Response) -> LoginResponse:
        try:
            session_id, csrf_token, login_resp = await auth_service.login(
                body.username, body.password
            )
        except JellyfinAuthError:
            return Response(  # type: ignore[return-value]
                content='{"detail":"Invalid username or password"}',
                status_code=401,
                media_type="application/json",
            )
        except JellyfinConnectionError:
            return Response(  # type: ignore[return-value]
                content='{"detail":"Jellyfin server is unreachable"}',
                status_code=502,
                media_type="application/json",
            )
        _set_session_cookie(response, session_id)
        return login_resp

    @router.get(
        "/me",
        response_model=LoginResponse,
        responses={401: {"model": ErrorResponse}},
    )
    async def me(
        session: SessionMeta = Depends(get_current_session),  # noqa: B008
    ) -> LoginResponse:
        return LoginResponse(
            user_id=session.user_id,
            username=session.username,
            server_name=session.server_name,
        )

    @router.post(
        "/logout",
        response_model=LogoutResponse,
        responses={},
    )
    async def logout(request: Request, response: Response) -> LogoutResponse:
        session_id = _decrypt_session_cookie(request)
        _clear_session_cookie(response)

        if session_id is None:
            return LogoutResponse(detail="Logged out")

        session = await session_store.get(session_id)
        if session is None:
            return LogoutResponse(detail="Logged out")

        await session_store.delete(session_id)
        logger.info("user_logout user_id=%s", session.user_id)

        # Best-effort Jellyfin token revocation
        try:
            jf = request.app.state.jellyfin_client
            await jf.logout(session.token)
        except JellyfinConnectionError:
            logger.warning(
                "jellyfin unreachable during logout user_id=%s",
                session.user_id,
            )

        return LogoutResponse(detail="Logged out")

    return router
