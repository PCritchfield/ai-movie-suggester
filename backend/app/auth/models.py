"""Data models for session management."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel


@dataclass(frozen=True, slots=True)
class SessionRow:
    """Complete session record including decrypted token."""

    session_id: str
    user_id: str
    username: str
    server_name: str
    token: str
    csrf_token: str
    created_at: int
    expires_at: int


@dataclass(frozen=True, slots=True)
class SessionMeta:
    """Session metadata without the Jellyfin token — safe for /me responses."""

    session_id: str
    user_id: str
    username: str
    server_name: str
    expires_at: int


# --- API request/response models ---


class LoginRequest(BaseModel):
    """POST /api/auth/login request body."""

    username: str
    password: str


class LoginResponse(BaseModel):
    """Successful login / /me response body."""

    user_id: str
    username: str
    server_name: str


class LogoutResponse(BaseModel):
    """POST /api/auth/logout response body."""

    detail: str


class ErrorResponse(BaseModel):
    """Error response body."""

    detail: str


# --- Session store protocol ---


class SessionStoreProtocol(Protocol):
    """Structural interface for session storage backends."""

    async def init(self) -> None: ...

    async def close(self) -> None: ...

    async def create(
        self,
        *,
        session_id: str,
        user_id: str,
        username: str,
        server_name: str,
        token: str,
        csrf_token: str,
        expires_at: int,
    ) -> None: ...

    async def get(self, session_id: str) -> SessionRow | None: ...

    async def get_metadata(self, session_id: str) -> SessionMeta | None: ...

    async def delete(self, session_id: str) -> None: ...

    async def get_expired(self) -> list[SessionRow]: ...

    async def count_by_user(self, user_id: str) -> int: ...

    async def oldest_by_user(self, user_id: str) -> SessionRow | None: ...

    async def delete_all_by_user(self, user_id: str) -> int: ...
