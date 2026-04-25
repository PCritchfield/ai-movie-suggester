# backend/tests/test_text_builder.py
"""Unit + snapshot tests for build_sections() and TEMPLATE_VERSION."""

from __future__ import annotations

import logging

import httpx
import pytest

from app.ollama.text_builder import TEMPLATE_VERSION, build_sections

# ---------------------------------------------------------------------------
# Template v4 — cast, crew, studios, tags
# ---------------------------------------------------------------------------


class TestBuildSectionsNewFields:
    """Cast, directors, writers, composers, studios, tags in the template."""

    def test_cast_section_present_when_populated(self) -> None:
        text = build_sections(
            title="Alien",
            overview=None,
            genres=[],
            production_year=None,
            cast=["Sigourney Weaver", "Tom Skerritt"],
        )
        assert text == "Title: Alien. Cast: Sigourney Weaver, Tom Skerritt."

    def test_cast_section_caps_at_ten(self) -> None:
        cast = [f"Actor {i}" for i in range(15)]
        text = build_sections(
            title="Ensemble Film",
            overview=None,
            genres=[],
            production_year=None,
            cast=cast,
        )
        for i in range(10):
            assert f"Actor {i}" in text
        for i in range(10, 15):
            assert f"Actor {i}" not in text

    def test_directors_section(self) -> None:
        text = build_sections(
            title="Piranha",
            overview=None,
            genres=[],
            production_year=None,
            directors=["Roger Corman"],
        )
        assert text == "Title: Piranha. Directed by: Roger Corman."

    def test_writers_section(self) -> None:
        text = build_sections(
            title="Alien",
            overview=None,
            genres=[],
            production_year=None,
            writers=["Dan O'Bannon", "Ronald Shusett"],
        )
        assert text == "Title: Alien. Written by: Dan O'Bannon, Ronald Shusett."

    def test_composers_section(self) -> None:
        text = build_sections(
            title="Star Wars",
            overview=None,
            genres=[],
            production_year=None,
            composers=["John Williams"],
        )
        assert text == "Title: Star Wars. Music by: John Williams."

    def test_studios_section(self) -> None:
        text = build_sections(
            title="Alien",
            overview=None,
            genres=[],
            production_year=None,
            studios=["20th Century Fox", "Brandywine Productions"],
        )
        assert text == (
            "Title: Alien. Studios: 20th Century Fox, Brandywine Productions."
        )

    def test_tags_section(self) -> None:
        text = build_sections(
            title="Alien",
            overview=None,
            genres=[],
            production_year=None,
            tags=["classic", "space"],
        )
        assert text == "Title: Alien. Tags: classic, space."

    def test_empty_lists_omit_sections(self) -> None:
        text = build_sections(
            title="Alien",
            overview=None,
            genres=[],
            production_year=None,
            cast=[],
            directors=[],
            writers=[],
            composers=[],
            studios=[],
            tags=[],
        )
        assert text == "Title: Alien."

    def test_none_defaults_omit_sections(self) -> None:
        text = build_sections(
            title="Alien",
            overview=None,
            genres=[],
            production_year=None,
        )
        assert text == "Title: Alien."

    def test_section_ordering(self) -> None:
        """Sections appear in: title, overview, genres, year, runtime,
        cast, directed by, written by, music by, studios, tags."""
        text = build_sections(
            title="Alien",
            overview="Space horror.",
            genres=["Horror"],
            production_year=1979,
            runtime_minutes=117,
            cast=["Sigourney Weaver"],
            directors=["Ridley Scott"],
            writers=["Dan O'Bannon"],
            composers=["Jerry Goldsmith"],
            studios=["20th Century Fox"],
            tags=["classic"],
        )
        assert text == (
            "Title: Alien. Space horror. Genres: Horror. Year: 1979. "
            "Runtime: 117 minutes. Cast: Sigourney Weaver. "
            "Directed by: Ridley Scott. Written by: Dan O'Bannon. "
            "Music by: Jerry Goldsmith. Studios: 20th Century Fox. Tags: classic."
        )


class TestTemplateVersion:
    """TEMPLATE_VERSION drift detection."""

    def test_is_version_4(self) -> None:
        assert TEMPLATE_VERSION == 4


# ---------------------------------------------------------------------------
# Core template shape
# ---------------------------------------------------------------------------


class TestBuildSections:
    """Core template shape for the classic fields (title/overview/genres/year)."""

    def test_full_produces_expected_template(self) -> None:
        text = build_sections(
            title="Galaxy Quest",
            overview="A great comedy about actors in space.",
            genres=["Comedy", "Sci-Fi"],
            production_year=1999,
        )
        assert text == (
            "Title: Galaxy Quest. A great comedy about actors in space. "
            "Genres: Comedy, Sci-Fi. Year: 1999."
        )

    def test_minimal_produces_title_only(self) -> None:
        text = build_sections(
            title="Alien",
            overview=None,
            genres=[],
            production_year=None,
        )
        assert text == "Title: Alien."

    def test_no_trailing_whitespace_minimal(self) -> None:
        text = build_sections(
            title="Alien",
            overview=None,
            genres=[],
            production_year=None,
        )
        assert text == text.rstrip()

    def test_no_trailing_empty_sections(self) -> None:
        text = build_sections(
            title="Alien",
            overview=None,
            genres=[],
            production_year=None,
        )
        assert "Genres:" not in text
        assert "Year:" not in text


class TestMissingFieldCombinations:
    """Verify omission of empty/missing sections."""

    def test_no_overview_omits_overview(self) -> None:
        text = build_sections(
            title="Alien",
            overview=None,
            genres=["Sci-Fi", "Horror"],
            production_year=1979,
        )
        assert text == "Title: Alien. Genres: Sci-Fi, Horror. Year: 1979."

    def test_empty_genres_omits_genres(self) -> None:
        text = build_sections(
            title="Alien",
            overview="In space, no one can hear you scream.",
            genres=[],
            production_year=1979,
        )
        assert text == (
            "Title: Alien. In space, no one can hear you scream. Year: 1979."
        )
        assert "Genres:" not in text

    def test_no_production_year_omits_year(self) -> None:
        text = build_sections(
            title="Alien",
            overview="In space, no one can hear you scream.",
            genres=["Sci-Fi", "Horror"],
            production_year=None,
        )
        assert text == (
            "Title: Alien. In space, no one can hear you scream. "
            "Genres: Sci-Fi, Horror."
        )
        assert "Year:" not in text

    def test_only_overview_no_genres_no_year(self) -> None:
        text = build_sections(
            title="Alien",
            overview="In space, no one can hear you scream.",
            genres=[],
            production_year=None,
        )
        assert text == "Title: Alien. In space, no one can hear you scream."

    def test_only_genres_no_overview_no_year(self) -> None:
        text = build_sections(
            title="Alien",
            overview=None,
            genres=["Sci-Fi", "Horror"],
            production_year=None,
        )
        assert text == "Title: Alien. Genres: Sci-Fi, Horror."

    def test_only_year_no_overview_no_genres(self) -> None:
        text = build_sections(
            title="Alien",
            overview=None,
            genres=[],
            production_year=1979,
        )
        assert text == "Title: Alien. Year: 1979."

    def test_runtime_included_when_present(self) -> None:
        text = build_sections(
            title="Alien",
            overview=None,
            genres=[],
            production_year=1979,
            runtime_minutes=116,
        )
        assert "Runtime: 116 minutes." in text

    def test_runtime_omitted_when_none(self) -> None:
        text = build_sections(
            title="Alien",
            overview=None,
            genres=[],
            production_year=1979,
        )
        assert "Runtime:" not in text

    def test_empty_overview_string_treated_as_missing(self) -> None:
        text = build_sections(
            title="Alien",
            overview="",
            genres=[],
            production_year=None,
        )
        assert text == "Title: Alien."

    def test_whitespace_only_overview_treated_as_missing(self) -> None:
        text = build_sections(
            title="Alien",
            overview="   ",
            genres=[],
            production_year=None,
        )
        assert text == "Title: Alien."


# ---------------------------------------------------------------------------
# Snapshot / golden tests
# ---------------------------------------------------------------------------


class TestBuildSectionsSnapshots:
    """Golden tests that lock down exact template output.

    These detect accidental whitespace, punctuation, or ordering drift
    that would invalidate content hashes and trigger unnecessary
    re-embedding.
    """

    def test_snapshot_full_scifi_movie(self) -> None:
        text = build_sections(
            title="Alien",
            overview=(
                "In space, no one can hear you scream. A crew aboard a "
                "deep-space vessel encounters a terrifying alien lifeform."
            ),
            genres=["Science Fiction", "Horror"],
            production_year=1979,
        )
        assert text == (
            "Title: Alien. In space, no one can hear you scream. A crew aboard a "
            "deep-space vessel encounters a terrifying alien lifeform. "
            "Genres: Science Fiction, Horror. Year: 1979."
        )

    def test_snapshot_minimal(self) -> None:
        text = build_sections(
            title="Untitled Film",
            overview=None,
            genres=[],
            production_year=None,
        )
        assert text == "Title: Untitled Film."

    def test_snapshot_long_overview(self) -> None:
        long_overview = "A thrilling adventure. " * 50  # ~1150 chars
        text = build_sections(
            title="The Long Film",
            overview=long_overview.strip(),
            genres=["Adventure"],
            production_year=2020,
        )
        expected = (
            f"Title: The Long Film. {long_overview.strip()} "
            "Genres: Adventure. Year: 2020."
        )
        assert text == expected

    def test_snapshot_many_genres(self) -> None:
        text = build_sections(
            title="Genre Mashup",
            overview=None,
            genres=[
                "Action",
                "Comedy",
                "Drama",
                "Horror",
                "Romance",
                "Sci-Fi",
                "Thriller",
            ],
            production_year=2023,
        )
        assert text == (
            "Title: Genre Mashup. "
            "Genres: Action, Comedy, Drama, Horror, Romance, Sci-Fi, Thriller. "
            "Year: 2023."
        )

    def test_snapshot_name_and_overview_only(self) -> None:
        text = build_sections(
            title="Simple Drama",
            overview="A touching story about family and forgiveness.",
            genres=[],
            production_year=None,
        )
        assert text == (
            "Title: Simple Drama. A touching story about family and forgiveness."
        )


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_same_input_produces_identical_output(self) -> None:
        kwargs: dict[str, object] = {
            "title": "Aliens",
            "overview": "This time it's war.",
            "genres": ["Action", "Sci-Fi"],
            "production_year": 1986,
        }
        text1 = build_sections(**kwargs)  # type: ignore[arg-type]
        text2 = build_sections(**kwargs)  # type: ignore[arg-type]
        assert text1 == text2


# ---------------------------------------------------------------------------
# 6000-char warning
# ---------------------------------------------------------------------------


class TestLengthWarning:
    def test_long_text_triggers_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        long_overview = "X" * 6000
        with caplog.at_level(logging.WARNING, logger="app.ollama.text_builder"):
            build_sections(
                title="The Very Long Film",
                overview=long_overview,
                genres=[],
                production_year=None,
            )

        warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warning_records) >= 1
        msg = warning_records[0].message
        assert "The Very Long Film" in msg
        assert "6" in msg  # length contains "6" somewhere (6020+)

    def test_short_text_no_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING, logger="app.ollama.text_builder"):
            build_sections(
                title="Short Film",
                overview="Brief.",
                genres=[],
                production_year=None,
            )

        warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warning_records) == 0


# ---------------------------------------------------------------------------
# Integration test (requires real Ollama)
# ---------------------------------------------------------------------------


@pytest.mark.ollama_integration
class TestTextBuilderIntegration:
    """Integration: build text, embed via Ollama, verify vector dimensions."""

    async def test_embed_composite_text_returns_768_dims(self) -> None:
        from app.ollama.client import OllamaEmbeddingClient

        text = build_sections(
            title="Galaxy Quest",
            overview="A great comedy about actors in space.",
            genres=["Comedy", "Sci-Fi"],
            production_year=1999,
        )

        async with httpx.AsyncClient(timeout=120) as http:
            client = OllamaEmbeddingClient(
                base_url="http://localhost:11434",
                http_client=http,
            )
            embedding = await client.embed(text)

        assert embedding.dimensions == 768
        assert len(embedding.vector) == 768
