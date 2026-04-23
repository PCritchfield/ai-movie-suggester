"""Request/response models for the play-dispatch endpoint."""

from __future__ import annotations

from pydantic import BaseModel


class PlayRequest(BaseModel):
    """POST /api/play request body."""

    item_id: str
    session_id: str


class PlayResponse(BaseModel):
    """POST /api/play success response body."""

    status: str
    device_name: str
