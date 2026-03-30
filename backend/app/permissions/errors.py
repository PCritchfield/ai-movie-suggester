"""Permission service exceptions.

All permission-domain exceptions derive from PermissionError so callers
can catch the base class for blanket handling.
"""

from __future__ import annotations


class PermissionError(Exception):  # noqa: A001
    """Base exception for permission service failures."""


class PermissionCheckError(PermissionError):
    """Jellyfin returned an unexpected error during permission check."""


class PermissionTimeoutError(PermissionError):
    """Jellyfin did not respond within the configured timeout."""


class PermissionAuthError(PermissionError):
    """The user's Jellyfin token is invalid or expired."""
