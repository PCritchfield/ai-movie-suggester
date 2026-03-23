"""Data models for session management."""

from __future__ import annotations

from dataclasses import dataclass


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
