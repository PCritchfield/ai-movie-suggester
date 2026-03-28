"""Auth API routes — login, me, logout."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Request, Response
from slowapi import Limiter  # noqa: TC002

from app.auth.crypto import decrypt_cookie, fernet_encrypt
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
    from app.permissions.service import PermissionService

logger = logging.getLogger(__name__)


def create_auth_router(
    auth_service: AuthService,
    session_store: SessionStore,
    settings: Settings,
    cookie_key: bytes,
    limiter: Limiter | None = None,
    permission_service: PermissionService | None = None,
) -> APIRouter:
    """Build the auth APIRouter with closures over service dependencies."""
    router = APIRouter(prefix="/api/auth", tags=["auth"])
    _limit = limiter.limit(settings.login_rate_limit) if limiter else (lambda f: f)

    def _set_session_cookie(response: Response, session_id: str) -> None:
        encrypted = fernet_encrypt(cookie_key, session_id).decode("utf-8")
        response.set_cookie(
            key="session_id",
            value=encrypted,
            httponly=True,
            samesite="lax",
            secure=settings.session_secure_cookie,
            path="/",
            max_age=settings.session_expiry_hours * 3600,
        )

    def _clear_session_cookie(response: Response) -> None:
        response.delete_cookie(
            key="session_id",
            httponly=True,
            samesite="lax",
            secure=settings.session_secure_cookie,
            path="/",
        )

    def _decrypt_session_cookie(request: Request) -> str | None:
        """Extract and decrypt the session_id cookie. Returns None on failure."""
        return decrypt_cookie(cookie_key, request.cookies.get("session_id"))

    @router.post(
        "/login",
        response_model=LoginResponse,
        responses={
            401: {"model": ErrorResponse},
            502: {"model": ErrorResponse},
        },
    )
    @_limit
    async def login(
        request: Request, body: LoginRequest, response: Response
    ) -> LoginResponse:
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
        # Clean up stale session cookie at old path=/api
        response.delete_cookie(
            key="session_id",
            httponly=True,
            samesite="lax",
            secure=settings.session_secure_cookie,
            path="/api",
        )
        # Set CSRF token cookie (readable by JS on all pages)
        response.set_cookie(
            key="csrf_token",
            value=csrf_token,
            httponly=False,
            samesite="lax",
            secure=settings.session_secure_cookie,
            path="/",
            max_age=settings.session_expiry_hours * 3600,
        )
        # Clean up stale CSRF cookie at old path=/api
        response.delete_cookie(
            key="csrf_token",
            samesite="lax",
            secure=settings.session_secure_cookie,
            path="/api",
        )
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
        # Clean up stale session cookie at old path=/api
        response.delete_cookie(
            key="session_id",
            httponly=True,
            samesite="lax",
            secure=settings.session_secure_cookie,
            path="/api",
        )
        # Clear CSRF cookie at current path=/
        response.delete_cookie(
            key="csrf_token",
            samesite="lax",
            secure=settings.session_secure_cookie,
            path="/",
        )
        # Clean up stale CSRF cookie at old path=/api
        response.delete_cookie(
            key="csrf_token",
            samesite="lax",
            secure=settings.session_secure_cookie,
            path="/api",
        )

        if session_id is None:
            return LogoutResponse(detail="Logged out")

        session = await session_store.get(session_id)
        if session is None:
            return LogoutResponse(detail="Logged out")

        await session_store.delete(session_id)
        logger.info("user_logout user_id=%s", session.user_id)

        # Invalidate permission cache for the user
        if permission_service is not None:
            permission_service.invalidate_user_cache(session.user_id)

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
