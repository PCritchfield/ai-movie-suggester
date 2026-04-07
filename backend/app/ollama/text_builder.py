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

TEMPLATE_VERSION: int = 3
"""Template version constant. Bumping this signals that all embeddings
built with an older version are stale and should be regenerated.

Version history:
  1 — Initial template (plain composite text, no prefix).
  2 — Added ``search_document:`` prefix at the embedding call-site
      for nomic-embed-text asymmetric retrieval (Spec 11).
  3 — Added runtime section to composite text (Spec 19).
"""

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


def _build_runtime_section(runtime_minutes: int | None) -> str | None:
    """Build the runtime section, or None if not set."""
    if runtime_minutes is not None:
        return f"Runtime: {runtime_minutes} minutes."
    return None


def build_sections(
    title: str,
    overview: str | None,
    genres: list[str],
    production_year: int | None,
    runtime_minutes: int | None = None,
) -> str:
    """Assemble composite text from raw field values.

    Shared core used by both ``build_composite_text`` (for LibraryItem)
    and the embedding worker (for LibraryItemRow).  Changes here
    automatically propagate to both callers — bump ``TEMPLATE_VERSION``
    when the template structure changes.
    """
    sections: list[str] = [_build_title_section(title)]

    ov = _build_overview_section(overview)
    if ov is not None:
        sections.append(ov)

    g = _build_genres_section(genres)
    if g is not None:
        sections.append(g)

    y = _build_year_section(production_year)
    if y is not None:
        sections.append(y)

    rt = _build_runtime_section(runtime_minutes)
    if rt is not None:
        sections.append(rt)

    return " ".join(sections)


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
    runtime_minutes = (
        item.run_time_ticks // 600_000_000 if item.run_time_ticks is not None else None
    )
    text = build_sections(
        title=item.name,
        overview=item.overview,
        genres=item.genres,
        production_year=item.production_year,
        runtime_minutes=runtime_minutes,
    )

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
