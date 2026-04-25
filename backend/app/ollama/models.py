"""Pydantic models for Ollama embedding responses."""

from __future__ import annotations

from pydantic import BaseModel, model_validator


class EmbeddingResult(BaseModel):
    """Result of an Ollama embedding request."""

    vector: list[float]
    dimensions: int
    model: str

    @model_validator(mode="after")
    def _check_dimensions_match(self) -> EmbeddingResult:
        """Assert that len(vector) == dimensions."""
        if len(self.vector) != self.dimensions:
            msg = (
                f"dimensions={self.dimensions} does not match "
                f"len(vector)={len(self.vector)}"
            )
            raise ValueError(msg)
        return self
