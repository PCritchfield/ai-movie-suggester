"""Validate NFO fixture files have required fields and well-formed XML.

Runs against the fixture directory at tests/fixtures/media/ — not against
Jellyfin. Parametrized: one test invocation per NFO file, so failures
report the exact file and missing field.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from tests.integration.conftest import EXPECTED_MOVIES, EXPECTED_SHOWS

# Fixture media lives at repo root, not inside backend/
_REPO_ROOT = Path(__file__).resolve().parents[3]
_MEDIA_ROOT = _REPO_ROOT / "tests" / "fixtures" / "media"

_MOVIE_NFOS = sorted(_MEDIA_ROOT.glob("movies/*/movie.nfo"))
_SHOW_NFOS = sorted(_MEDIA_ROOT.glob("shows/*/tvshow.nfo"))
_EPISODE_NFOS = sorted(_MEDIA_ROOT.glob("shows/*/Season 01/*.nfo"))

# Minimum plot length to ensure embedding quality
_MIN_PLOT_LENGTH = 50

# Required fields per NFO type
_MOVIE_REQUIRED = [
    "title",
    "year",
    "plot",
    "genre",
    "director",
    "studio",
    "rating",
    "runtime",
]
_SHOW_REQUIRED = [
    "title",
    "year",
    "plot",
    "genre",
    "studio",
    "rating",
]
_EPISODE_REQUIRED = [
    "title",
    "season",
    "episode",
    "plot",
]


def _nfo_id(path: Path) -> str:
    """Human-readable test ID from file path."""
    return str(path.relative_to(_MEDIA_ROOT))


def _assert_required_fields(root: ET.Element, fields: list[str], filename: str) -> None:
    """Assert all required fields exist and have non-empty text."""
    for field in fields:
        elem = root.find(field)
        assert elem is not None, f"Missing <{field}> in {filename}"
        assert elem.text and elem.text.strip(), f"Empty <{field}> in {filename}"


def _assert_actors(root: ET.Element, min_count: int, filename: str) -> None:
    """Assert at least min_count actors with <name> elements."""
    actors = root.findall("actor")
    assert len(actors) >= min_count, (
        f"Need >= {min_count} <actor> entries in {filename}, got {len(actors)}"
    )
    for actor in actors:
        name = actor.find("name")
        assert name is not None and name.text, f"Actor missing <name> in {filename}"


def _assert_min_plot_length(root: ET.Element, filename: str) -> None:
    """Assert plot text meets minimum length."""
    plot = root.findtext("plot", default="")
    assert len(plot) >= _MIN_PLOT_LENGTH, (
        f"Plot too short ({len(plot)} chars, need {_MIN_PLOT_LENGTH}): {filename}"
    )


@pytest.mark.integration
def test_fixture_counts_match_expected() -> None:
    """Guard: fixture directory has the expected number of NFO files.

    Prevents silent zero-test pass if fixtures are missing (e.g. fresh
    clone without media files). Runs only with -m integration.
    """
    assert len(_MOVIE_NFOS) >= EXPECTED_MOVIES, (
        f"Expected {EXPECTED_MOVIES} movie NFOs, found {len(_MOVIE_NFOS)}. "
        f"Is tests/fixtures/media/ populated?"
    )
    assert len(_SHOW_NFOS) >= EXPECTED_SHOWS, (
        f"Expected {EXPECTED_SHOWS} show NFOs, found {len(_SHOW_NFOS)}. "
        f"Is tests/fixtures/media/ populated?"
    )


@pytest.mark.integration
@pytest.mark.parametrize("nfo_path", _MOVIE_NFOS, ids=_nfo_id)
def test_movie_nfo_has_required_fields(nfo_path: Path) -> None:
    """Each movie.nfo parses as valid XML with all required fields."""
    tree = ET.parse(nfo_path)  # noqa: S314
    root = tree.getroot()
    assert root.tag == "movie", f"Expected <movie> root, got <{root.tag}>"

    _assert_required_fields(root, _MOVIE_REQUIRED, nfo_path.name)
    _assert_actors(root, 2, nfo_path.name)
    _assert_min_plot_length(root, nfo_path.name)


@pytest.mark.integration
@pytest.mark.parametrize("nfo_path", _SHOW_NFOS, ids=_nfo_id)
def test_show_nfo_has_required_fields(nfo_path: Path) -> None:
    """Each tvshow.nfo parses as valid XML with all required fields."""
    tree = ET.parse(nfo_path)  # noqa: S314
    root = tree.getroot()
    assert root.tag == "tvshow", f"Expected <tvshow> root, got <{root.tag}>"

    _assert_required_fields(root, _SHOW_REQUIRED, nfo_path.name)
    _assert_actors(root, 2, nfo_path.name)
    _assert_min_plot_length(root, nfo_path.name)


@pytest.mark.integration
@pytest.mark.parametrize("nfo_path", _EPISODE_NFOS, ids=_nfo_id)
def test_episode_nfo_has_required_fields(nfo_path: Path) -> None:
    """Each episode .nfo parses as valid XML with required fields."""
    tree = ET.parse(nfo_path)  # noqa: S314
    root = tree.getroot()
    assert root.tag == "episodedetails", (
        f"Expected <episodedetails> root, got <{root.tag}>"
    )

    _assert_required_fields(root, _EPISODE_REQUIRED, nfo_path.name)
    _assert_min_plot_length(root, nfo_path.name)
