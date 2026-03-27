"""Composite text builder for Ollama embedding input.

Transforms Jellyfin LibraryItem metadata into deterministic, embeddable
strings using a structured template. Missing/empty fields are omitted
entirely — no placeholders, no "N/A", no empty delimiters.

The builder uses structured section builders (a list of optional sections
joined with a space), NOT raw f-string concatenation, per CLAUDE.md rules.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pydantic import BaseModel

from app.ollama.models import EmbeddingSource

if TYPE_CHECKING:
    from app.jellyfin.models import LibraryItem

logger = logging.getLogger(__name__)

TEMPLATE_VERSION: int = 1
"""Template version constant. Bumping this signals that all embeddings
built with an older version are stale and should be regenerated."""

_LENGTH_WARNING_THRESHOLD = 6000


class CompositeTextResult(BaseModel):
    """Result of building composite text for embedding."""

    text: str
    template_version: int
    source: EmbeddingSource


def _build_title_section(name: str) -> str:
    """Build the mandatory title section."""
    return f"Title: {name}."


def _build_overview_section(overview: str | None) -> str | None:
    """Build the overview section, or None if empty/missing."""
    if overview and overview.strip():
        return overview.strip()
    return None


def _build_genres_section(genres: list[str]) -> str | None:
    """Build the genres section, or None if the list is empty."""
    if genres:
        return "Genres: " + ", ".join(genres) + "."
    return None


def _build_year_section(production_year: int | None) -> str | None:
    """Build the year section, or None if not set."""
    if production_year is not None:
        return f"Year: {production_year}."
    return None


def build_composite_text(item: LibraryItem) -> CompositeTextResult:
    """Build a composite text string from a LibraryItem for embedding.

    Uses structured section builders to assemble the text. Only the
    Title section is mandatory — all other sections are omitted if
    their source data is missing or empty.

    Args:
        item: A Jellyfin LibraryItem with metadata fields.

    Returns:
        A CompositeTextResult with the built text, template version,
        and embedding source.
    """
    sections: list[str] = [_build_title_section(item.name)]

    overview = _build_overview_section(item.overview)
    if overview is not None:
        sections.append(overview)

    genres = _build_genres_section(item.genres)
    if genres is not None:
        sections.append(genres)

    year = _build_year_section(item.production_year)
    if year is not None:
        sections.append(year)

    text = " ".join(sections)

    if len(text) > _LENGTH_WARNING_THRESHOLD:
        logger.warning(
            "composite_text_long item=%s length=%d",
            item.name,
            len(text),
        )

    logger.debug("composite_text output=%.200s length=%d", text, len(text))

    return CompositeTextResult(
        text=text,
        template_version=TEMPLATE_VERSION,
        source=EmbeddingSource.JELLYFIN_ONLY,
    )
