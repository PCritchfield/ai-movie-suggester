# backend/tests/test_text_builder.py
"""Unit + snapshot tests for build_composite_text()."""

from __future__ import annotations

import logging

import httpx
import pytest

from app.jellyfin.models import LibraryItem
from app.ollama.models import EmbeddingSource
from app.ollama.text_builder import (
    TEMPLATE_VERSION,
    CompositeTextResult,
    build_composite_text,
)

# ---------------------------------------------------------------------------
# Helpers — reusable LibraryItem constructors
# ---------------------------------------------------------------------------


def _make_item(**overrides: object) -> LibraryItem:
    """Build a LibraryItem with sensible defaults, overridable per-field."""
    defaults: dict[str, object] = {
        "Id": "item-1",
        "Name": "Test Movie",
        "Type": "Movie",
    }
    defaults.update(overrides)
    return LibraryItem.model_validate(defaults)


# ---------------------------------------------------------------------------
# Core unit tests
# ---------------------------------------------------------------------------


class TestBuildCompositeText:
    """Core logic tests for build_composite_text()."""

    def test_full_item_produces_expected_template(self) -> None:
        item = _make_item(
            Name="Galaxy Quest",
            Overview="A great comedy about actors in space.",
            Genres=["Comedy", "Sci-Fi"],
            ProductionYear=1999,
        )
        result = build_composite_text(item)
        assert result.text == (
            "Title: Galaxy Quest. A great comedy about actors in space. "
            "Genres: Comedy, Sci-Fi. Year: 1999."
        )

    def test_template_version_matches_constant(self) -> None:
        item = _make_item()
        result = build_composite_text(item)
        assert result.template_version == TEMPLATE_VERSION

    def test_source_is_jellyfin_only(self) -> None:
        item = _make_item()
        result = build_composite_text(item)
        assert result.source == EmbeddingSource.JELLYFIN_ONLY

    def test_returns_composite_text_result(self) -> None:
        item = _make_item()
        result = build_composite_text(item)
        assert isinstance(result, CompositeTextResult)

    def test_minimal_item_produces_title_only(self) -> None:
        """Item with only required fields produces 'Title: {name}.' only."""
        item = _make_item(Name="Alien")
        result = build_composite_text(item)
        assert result.text == "Title: Alien."

    def test_no_trailing_whitespace_minimal(self) -> None:
        item = _make_item(Name="Alien")
        result = build_composite_text(item)
        assert result.text == result.text.rstrip()

    def test_no_trailing_empty_sections(self) -> None:
        """No empty section markers (e.g., 'Genres: .' or 'Year: .')."""
        item = _make_item(Name="Alien")
        result = build_composite_text(item)
        assert "Genres:" not in result.text
        assert "Year:" not in result.text


# ---------------------------------------------------------------------------
# Missing field combinations
# ---------------------------------------------------------------------------


class TestMissingFieldCombinations:
    """Verify omission of empty/missing sections."""

    def test_no_overview_omits_overview(self) -> None:
        item = _make_item(
            Name="Alien",
            Genres=["Sci-Fi", "Horror"],
            ProductionYear=1979,
        )
        result = build_composite_text(item)
        assert result.text == "Title: Alien. Genres: Sci-Fi, Horror. Year: 1979."

    def test_empty_genres_omits_genres(self) -> None:
        item = _make_item(
            Name="Alien",
            Overview="In space, no one can hear you scream.",
            Genres=[],
            ProductionYear=1979,
        )
        result = build_composite_text(item)
        assert result.text == (
            "Title: Alien. In space, no one can hear you scream. Year: 1979."
        )
        assert "Genres:" not in result.text

    def test_no_production_year_omits_year(self) -> None:
        item = _make_item(
            Name="Alien",
            Overview="In space, no one can hear you scream.",
            Genres=["Sci-Fi", "Horror"],
        )
        result = build_composite_text(item)
        assert result.text == (
            "Title: Alien. In space, no one can hear you scream. "
            "Genres: Sci-Fi, Horror."
        )
        assert "Year:" not in result.text

    def test_only_overview_no_genres_no_year(self) -> None:
        item = _make_item(
            Name="Alien",
            Overview="In space, no one can hear you scream.",
        )
        result = build_composite_text(item)
        assert result.text == "Title: Alien. In space, no one can hear you scream."

    def test_only_genres_no_overview_no_year(self) -> None:
        item = _make_item(
            Name="Alien",
            Genres=["Sci-Fi", "Horror"],
        )
        result = build_composite_text(item)
        assert result.text == "Title: Alien. Genres: Sci-Fi, Horror."

    def test_only_year_no_overview_no_genres(self) -> None:
        item = _make_item(
            Name="Alien",
            ProductionYear=1979,
        )
        result = build_composite_text(item)
        assert result.text == "Title: Alien. Year: 1979."

    def test_empty_overview_string_treated_as_missing(self) -> None:
        item = _make_item(
            Name="Alien",
            Overview="",
        )
        result = build_composite_text(item)
        assert result.text == "Title: Alien."

    def test_whitespace_only_overview_treated_as_missing(self) -> None:
        item = _make_item(
            Name="Alien",
            Overview="   ",
        )
        result = build_composite_text(item)
        assert result.text == "Title: Alien."


# ---------------------------------------------------------------------------
# Snapshot / golden tests
# ---------------------------------------------------------------------------


class TestCompositeTextSnapshots:
    """Golden tests that lock down exact template output.

    These detect accidental whitespace, punctuation, or ordering drift
    that would invalidate content hashes and trigger unnecessary
    re-embedding.
    """

    def test_snapshot_full_scifi_movie(self) -> None:
        item = _make_item(
            Id="alien-1979",
            Name="Alien",
            Type="Movie",
            Overview=(
                "In space, no one can hear you scream. A crew aboard a "
                "deep-space vessel encounters a terrifying alien lifeform."
            ),
            Genres=["Science Fiction", "Horror"],
            ProductionYear=1979,
        )
        result = build_composite_text(item)
        assert result.text == (
            "Title: Alien. In space, no one can hear you scream. A crew aboard a "
            "deep-space vessel encounters a terrifying alien lifeform. "
            "Genres: Science Fiction, Horror. Year: 1979."
        )

    def test_snapshot_minimal_item(self) -> None:
        item = _make_item(
            Id="unknown-1",
            Name="Untitled Film",
            Type="Movie",
        )
        result = build_composite_text(item)
        assert result.text == "Title: Untitled Film."

    def test_snapshot_long_overview(self) -> None:
        long_overview = "A thrilling adventure. " * 50  # ~1150 chars
        item = _make_item(
            Id="long-1",
            Name="The Long Film",
            Type="Movie",
            Overview=long_overview.strip(),
            Genres=["Adventure"],
            ProductionYear=2020,
        )
        result = build_composite_text(item)
        expected = (
            f"Title: The Long Film. {long_overview.strip()} "
            "Genres: Adventure. Year: 2020."
        )
        assert result.text == expected

    def test_snapshot_many_genres(self) -> None:
        item = _make_item(
            Id="genre-heavy-1",
            Name="Genre Mashup",
            Type="Movie",
            Genres=[
                "Action",
                "Comedy",
                "Drama",
                "Horror",
                "Romance",
                "Sci-Fi",
                "Thriller",
            ],
            ProductionYear=2023,
        )
        result = build_composite_text(item)
        assert result.text == (
            "Title: Genre Mashup. "
            "Genres: Action, Comedy, Drama, Horror, Romance, Sci-Fi, Thriller. "
            "Year: 2023."
        )

    def test_snapshot_name_and_overview_only(self) -> None:
        item = _make_item(
            Id="simple-1",
            Name="Simple Drama",
            Type="Movie",
            Overview="A touching story about family and forgiveness.",
        )
        result = build_composite_text(item)
        assert result.text == (
            "Title: Simple Drama. A touching story about family and forgiveness."
        )


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_same_input_produces_identical_output(self) -> None:
        item = _make_item(
            Name="Aliens",
            Overview="This time it's war.",
            Genres=["Action", "Sci-Fi"],
            ProductionYear=1986,
        )
        result1 = build_composite_text(item)
        result2 = build_composite_text(item)
        assert result1.text == result2.text


# ---------------------------------------------------------------------------
# 6000-char warning
# ---------------------------------------------------------------------------


class TestLengthWarning:
    def test_long_text_triggers_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        long_overview = "X" * 6000
        item = _make_item(
            Name="The Very Long Film",
            Overview=long_overview,
        )
        with caplog.at_level(logging.WARNING, logger="app.ollama.text_builder"):
            build_composite_text(item)

        warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warning_records) >= 1
        msg = warning_records[0].message
        assert "The Very Long Film" in msg
        assert "6" in msg  # length contains "6" somewhere (6020+)

    def test_short_text_no_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        item = _make_item(
            Name="Short Film",
            Overview="Brief.",
        )
        with caplog.at_level(logging.WARNING, logger="app.ollama.text_builder"):
            build_composite_text(item)

        warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warning_records) == 0


# ---------------------------------------------------------------------------
# Integration test (requires real Ollama)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestTextBuilderIntegration:
    """Integration: build text, embed via Ollama, verify vector dimensions."""

    async def test_embed_composite_text_returns_768_dims(self) -> None:
        from app.ollama.client import OllamaEmbeddingClient

        item = _make_item(
            Name="Galaxy Quest",
            Overview="A great comedy about actors in space.",
            Genres=["Comedy", "Sci-Fi"],
            ProductionYear=1999,
        )
        result = build_composite_text(item)

        async with httpx.AsyncClient(timeout=120) as http:
            client = OllamaEmbeddingClient(
                base_url="http://localhost:11434",
                http_client=http,
            )
            embedding = await client.embed(result.text)

        assert embedding.dimensions == 768
        assert len(embedding.vector) == 768
