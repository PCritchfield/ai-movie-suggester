"""Jellyfin API client exceptions."""

from __future__ import annotations


class JellyfinError(Exception):
    """Base exception for Jellyfin API errors."""


class JellyfinAuthError(JellyfinError):
    """Authentication failed — invalid credentials or expired token."""


class JellyfinConnectionError(JellyfinError):
    """Cannot reach the Jellyfin server."""


class DeviceOfflineError(JellyfinError):
    """Target Jellyfin session is no longer available (404/400 on session ID)."""


class PlaybackAuthError(JellyfinError):
    """Playback dispatch rejected by Jellyfin auth (401/403 mid-flight)."""


class PlaybackDispatchError(JellyfinError):
    """Playback dispatch failed for a non-auth, non-offline reason."""
