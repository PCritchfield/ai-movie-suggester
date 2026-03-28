"""FastAPI dependencies for the permission service."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import Request

    from app.permissions.service import PermissionService


async def get_permission_service(request: Request) -> PermissionService:
    """Retrieve the PermissionService from app state."""
    return request.app.state.permission_service
