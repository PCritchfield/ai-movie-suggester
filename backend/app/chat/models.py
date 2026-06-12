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


# ---------------------------------------------------------------------------
# Structured chat output (Spec 27)
#
# The chat LLM emits a grammar-constrained payload matching this schema via
# Ollama's `format` parameter. The backend validates every jellyfin_id against
# the permission-filtered candidate set, then renders both cards and prose from
# the validated payload — eliminating prose/card divergence at the source.
# ---------------------------------------------------------------------------


class StructuredRecommendation(BaseModel):
    """A single movie the LLM chose to recommend.

    `jellyfin_id` is validated against the candidate set before use — a value
    here is a *claim*, not a trusted reference.
    """

    jellyfin_id: str = Field(min_length=1)
    reasoning: str = Field(min_length=1, max_length=300)


class StructuredChatResponse(BaseModel):
    """The full structured payload returned by the chat LLM.

    Bounds are deliberately tight: `recommendations` is capped so the response
    stays within the conversation token budget, and free-text fields are
    length-limited. These are advisory to the model (the grammar enforces them)
    and a guard against pathological output.
    """

    introductory_message: str | None = Field(default=None, max_length=400)
    recommendations: list[StructuredRecommendation] = Field(
        default_factory=list, max_length=5
    )


# JSON Schema for the structured response, derived from the Pydantic model.
# Exported for embedding (as text) in the system prompt — Ollama guidance is to
# pass the schema both via the `format` parameter AND in the prompt to ground
# the model. This MUST remain a static constant: no user input or movie metadata
# is ever interpolated into it, so it cannot become an injection carrier.
RECOMMENDATION_RESPONSE_SCHEMA = StructuredChatResponse.model_json_schema()
