"""Jellyfin-domain device models for the `/api/devices` endpoint.

Keeping the `Device` Pydantic model and `DeviceType` literal here
(rather than under a top-level `schemas/` directory) follows the
project's module-local convention and matches placement of other
Jellyfin-domain types in `app.jellyfin.models`.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

DeviceType = Literal["Tv", "Mobile", "Tablet", "Other"]
"""Coarse-grained device classification used by the frontend picker."""


class Device(BaseModel):
    """A Jellyfin session that can receive playback commands."""

    session_id: str
    name: str
    client: str
    device_type: DeviceType
