"""Jellyfin API client package."""

from __future__ import annotations

from app.jellyfin.client import JellyfinClient
from app.jellyfin.errors import (
    JellyfinAuthError,
    JellyfinConnectionError,
    JellyfinError,
)
from app.jellyfin.models import AuthResult, LibraryItem, PaginatedItems, UserInfo

__all__ = [
    "AuthResult",
    "JellyfinAuthError",
    "JellyfinClient",
    "JellyfinConnectionError",
    "JellyfinError",
    "LibraryItem",
    "PaginatedItems",
    "UserInfo",
]
