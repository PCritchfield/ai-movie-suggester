"""Jellyfin API client package."""

from __future__ import annotations

from app.jellyfin.errors import (
    JellyfinAuthError,
    JellyfinConnectionError,
    JellyfinError,
)

__all__ = [
    "JellyfinAuthError",
    "JellyfinConnectionError",
    "JellyfinError",
]
