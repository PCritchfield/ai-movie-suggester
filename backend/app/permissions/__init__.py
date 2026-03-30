"""Permission service — public API re-exports."""

from app.permissions.errors import (
    PermissionAuthError,
    PermissionCheckError,
    PermissionError,  # noqa: A004
    PermissionTimeoutError,
)
from app.permissions.models import PermissionServiceProtocol
from app.permissions.service import PermissionService

__all__ = [
    "PermissionAuthError",
    "PermissionCheckError",
    "PermissionError",
    "PermissionService",
    "PermissionServiceProtocol",
    "PermissionTimeoutError",
]
