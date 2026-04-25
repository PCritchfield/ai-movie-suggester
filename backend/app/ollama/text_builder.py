"""Composite text builder for Ollama embedding input.

Transforms library metadata into deterministic, embeddable strings
using a structured template. Missing/empty fields are omitted entirely
— no placeholders, no "N/A", no empty delimiters.

The builder uses structured section builders (a list of optional sections
joined with a space), NOT raw f-string concatenation, per CLAUDE.md rules.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

TEMPLATE_VERSION: int = 4
"""Template version constant. Bumping this signals that all embeddings
built with an older version are stale and should be regenerated.

Version history:
  1 — Initial template (plain composite text, no prefix).
  2 — Added ``search_document:`` prefix at the embedding call-site
      for nomic-embed-text asymmetric retrieval (Spec 11).
  3 — Added runtime section to composite text (Spec 19).
  4 — Added cast, directors, writers, composers, studios, tags sections
      (#217).
"""

_CAST_CAP = 10

_LENGTH_WARNING_THRESHOLD = 6000


def _build_title_section(name: str) -> str:
    """Build the mandatory title section."""
    return f"Title: {name}."


def _build_overview_section(overview: str | None) -> str | None:
    """Build the overview section, or None if empty/missing."""
    if overview and overview.strip():
        return overview.strip()
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


def _build_labeled_list_section(
    label: str, values: list[str] | None, *, cap: int | None = None
) -> str | None:
    """Build a comma-joined ``Label: a, b, c.`` section, or None if empty."""
    if not values:
        return None
    items = values[:cap] if cap is not None else values
    return f"{label}: " + ", ".join(items) + "."


def build_sections(
    title: str,
    overview: str | None,
    genres: list[str],
    production_year: int | None,
    runtime_minutes: int | None = None,
    cast: list[str] | None = None,
    directors: list[str] | None = None,
    writers: list[str] | None = None,
    composers: list[str] | None = None,
    studios: list[str] | None = None,
    tags: list[str] | None = None,
) -> str:
    """Assemble composite text from raw field values.

    Called directly by the embedding worker for each ``LibraryItemRow``.
    Changes here propagate — bump ``TEMPLATE_VERSION`` when the
    template structure changes so the worker's
    ``check_template_version`` re-enqueues every item for re-embedding
    on its next startup/cycle.
    """
    sections: list[str] = [_build_title_section(title)]

    ov = _build_overview_section(overview)
    if ov is not None:
        sections.append(ov)

    y = _build_year_section(production_year)
    rt = _build_runtime_section(runtime_minutes)

    for section in (
        _build_labeled_list_section("Genres", genres),
        y,
        rt,
        _build_labeled_list_section("Cast", cast, cap=_CAST_CAP),
        _build_labeled_list_section("Directed by", directors),
        _build_labeled_list_section("Written by", writers),
        _build_labeled_list_section("Music by", composers),
        _build_labeled_list_section("Studios", studios),
        _build_labeled_list_section("Tags", tags),
    ):
        if section is not None:
            sections.append(section)

    text = " ".join(sections)

    if len(text) > _LENGTH_WARNING_THRESHOLD:
        logger.warning("composite_text_long title=%s length=%d", title, len(text))

    return text
