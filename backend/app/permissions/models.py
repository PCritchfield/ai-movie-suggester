"""Domain models and protocols for the permission service."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class PermissionServiceProtocol(Protocol):
    """Structural interface for permission-checking backends."""

    async def filter_permitted(
        self, user_id: str, token: str, candidate_ids: list[str]
    ) -> list[str]: ...

    def invalidate_user_cache(self, user_id: str) -> None: ...
