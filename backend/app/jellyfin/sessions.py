"""Jellyfin sessions capability client.

Wraps GET /Sessions to produce a filtered list of controllable
``Device`` records (sessions where ``SupportsRemoteControl == True``)
for the `/api/devices` endpoint.

User tokens are **request-scoped** — they are passed as a parameter
to ``list_controllable`` and never cached on the instance. The
instance holds only a ``_JellyfinTransport`` (which itself holds no
token state) and a ``__repr__`` that returns a fixed string.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from app.jellyfin.device_models import Device, DeviceType
from app.jellyfin.errors import JellyfinError

if TYPE_CHECKING:
    from app.jellyfin.transport import _JellyfinTransport


# Table of (substring, result). Evaluated in order, case-sensitive.
# First match wins; unmatched clients fall through to ``"Other"``.
_CLASSIFICATION_TABLE: tuple[tuple[str, DeviceType], ...] = (
    # TVs — check "TV" substring before bare-Kodi or mobile checks
    ("TV", "Tv"),
    # Tablets — iPad and generic "Tablet" substring
    ("iPad", "Tablet"),
    ("Tablet", "Tablet"),
    # Mobile — iOS / Android phone clients
    ("iOS", "Mobile"),
    ("Android", "Mobile"),
)


def _classify_device(client: str) -> DeviceType:
    """Classify a Jellyfin session's device by its reported Client string.

    Returns one of ``"Tv" | "Mobile" | "Tablet" | "Other"``. Falls
    through to ``"Other"`` when no substring matches — including the
    bare ``"Kodi"`` case, which is not remote-controllable via
    ``/Sessions/{id}/Playing`` per Jellyfin's own behavior.
    """
    for substring, result in _CLASSIFICATION_TABLE:
        if substring in client:
            return result
    return "Other"


class JellyfinSessionsClient:
    """Capability client for Jellyfin's /Sessions endpoint.

    Holds no authentication state. The caller supplies the user token
    per-call; it is never persisted on the instance.
    """

    __slots__ = ("_transport",)

    def __init__(self, transport: _JellyfinTransport) -> None:
        self._transport = transport

    def __repr__(self) -> str:
        """Fixed repr — no dynamic fields, no token leakage surface."""
        return "JellyfinSessionsClient()"

    async def list_controllable(self, user_token: str) -> list[Device]:
        """Return the caller's controllable Jellyfin sessions.

        Calls ``GET /Sessions`` with the user's token and filters to
        sessions with ``SupportsRemoteControl == True``. Returns an
        empty list if no sessions match (valid case).

        Raises ``JellyfinAuthError`` on 401.
        Raises ``JellyfinConnectionError`` on transport failure.
        Raises ``JellyfinError`` if Jellyfin returns a non-JSON response
        (e.g. a reverse-proxy HTML error page).
        """
        resp = await self._transport.request(
            "GET",
            "/Sessions",
            token=user_token,
        )

        try:
            raw: Any = resp.json()
        except (json.JSONDecodeError, ValueError) as exc:
            # A reverse proxy in front of Jellyfin may return HTML on an
            # upstream error; treat as an upstream protocol failure.
            raise JellyfinError("Jellyfin returned non-JSON response") from exc
        if not isinstance(raw, list):
            # Jellyfin always returns a JSON array; if not, treat as empty
            # rather than crashing.
            return []

        devices: list[Device] = []
        for session in raw:
            if session.get("SupportsRemoteControl") is not True:
                continue
            client_str: str = session.get("Client", "") or ""
            devices.append(
                Device(
                    session_id=session["Id"],
                    name=session.get("DeviceName", "") or "",
                    client=client_str,
                    device_type=_classify_device(client_str),
                )
            )
        return devices
