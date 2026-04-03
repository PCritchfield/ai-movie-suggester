"""Request models for the chat endpoint."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """POST /api/chat request body."""

    message: str = Field(min_length=1, max_length=1000)
