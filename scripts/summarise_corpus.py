#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# ///
"""Summarise the test-media corpus: breakdown by genre, decade, country, rating.

Reads every ``movie.nfo`` and ``tvshow.nfo`` under ``tests/fixtures/media/``
and prints deterministic coverage tables. Read-only; no side effects. Useful
for sanity-checking that the generated corpus actually spans the dimensions
the eval golden set exercises (genre / person / year / country intents).

stdlib only: ``xml.etree.ElementTree``, ``pathlib``, ``collections``.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_MEDIA_ROOT = _REPO_ROOT / "tests" / "fixtures" / "media"

_RATING_BANDS = (
    ("9.0-10.0", 9.0, 10.01),
    ("8.0-8.9", 8.0, 9.0),
    ("7.0-7.9", 7.0, 8.0),
    ("6.0-6.9", 6.0, 7.0),
    ("5.0-5.9", 5.0, 6.0),
    ("<5.0", 0.0, 5.0),
)


def _decade(year: int) -> str:
    """Return the decade label for a year (e.g. 1985 -> '1980s')."""
    return f"{(year // 10) * 10}s"


def _rating_band(rating: float) -> str:
    """Return the rating band label for a numeric rating."""
    for label, low, high in _RATING_BANDS:
        if low <= rating < high:
            return label
    return "unknown"


_Collected = tuple[Counter[str], Counter[str], Counter[str], Counter[str], int, int]


def _collect() -> _Collected:
    """Parse all NFOs, returning counters + (movie_count, show_count)."""
    genres: Counter[str] = Counter()
    decades: Counter[str] = Counter()
    countries: Counter[str] = Counter()
    ratings: Counter[str] = Counter()

    nfo_paths = sorted(_MEDIA_ROOT.glob("movies/*/movie.nfo")) + sorted(
        _MEDIA_ROOT.glob("shows/*/tvshow.nfo")
    )
    movie_count = 0
    show_count = 0
    for path in nfo_paths:
        root = ET.parse(path).getroot()  # noqa: S314 — local trusted fixtures
        if root.tag == "movie":
            movie_count += 1
        else:
            show_count += 1
        for genre_el in root.findall("genre"):
            if genre_el.text:
                genres[genre_el.text.strip()] += 1
        year_text = root.findtext("year")
        if year_text and year_text.isdigit():
            decades[_decade(int(year_text))] += 1
        for country_el in root.findall("country"):
            if country_el.text:
                countries[country_el.text.strip()] += 1
        rating_text = root.findtext("rating")
        if rating_text:
            ratings[_rating_band(float(rating_text))] += 1

    return genres, decades, countries, ratings, movie_count, show_count


def _print_table(title: str, counter: Counter[str], *, sort_by_key: bool) -> None:
    """Print a single coverage table, deterministically ordered."""
    print(f"\n{title}")
    print("-" * len(title))
    items = (
        sorted(counter.items())
        if sort_by_key
        else sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
    )
    for name, count in items:
        print(f"  {name:<28} {count:>4}")


def main() -> None:
    """Print the full corpus coverage breakdown."""
    genres, decades, countries, ratings, movies, shows = _collect()
    total = movies + shows
    print("=" * 48)
    print("Test-media corpus coverage")
    print("=" * 48)
    print(f"Total items: {total}  ({movies} movies, {shows} shows)")

    _print_table("By genre", genres, sort_by_key=False)
    _print_table("By decade", decades, sort_by_key=True)
    _print_table("By country", countries, sort_by_key=False)
    _print_table("By rating band", ratings, sort_by_key=True)


if __name__ == "__main__":
    main()
