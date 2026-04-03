"""Request models for the chat endpoint."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class SSEEventType(StrEnum):
    """SSE event type identifiers for the chat stream."""

    METADATA = "metadata"
    TEXT = "text"
    DONE = "done"
    ERROR = "error"


class ChatErrorCode(StrEnum):
    """Error codes sent in SSE error events."""

    GENERATION_TIMEOUT = "generation_timeout"
    OLLAMA_UNAVAILABLE = "ollama_unavailable"
    SEARCH_UNAVAILABLE = "search_unavailable"
    STREAM_INTERRUPTED = "stream_interrupted"


class ChatRequest(BaseModel):
    """POST /api/chat request body."""

    message: str = Field(min_length=1, max_length=1000)
