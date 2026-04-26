"""Unit tests for query-genre keyword detection."""

from __future__ import annotations

from app.search.genre_keywords import detect_query_genres


class TestDetectQueryGenres:
    """Map free-text query phrasing to canonical Jellyfin genre groups.

    Each detected keyword expands to a frozenset of acceptable canonical
    genres (e.g. "sci-fi" → {Science Fiction, Sci-Fi & Fantasy}). The
    function returns a deduped, deterministically-ordered list of groups.
    """

    def test_no_genre_keywords_returns_empty(self) -> None:
        assert detect_query_genres("something good") == []
        assert detect_query_genres("") == []

    def test_single_keyword_comedy(self) -> None:
        groups = detect_query_genres("a comedy")
        assert groups == [frozenset({"Comedy"})]

    def test_sci_fi_hyphenated_maps_to_science_fiction(self) -> None:
        groups = detect_query_genres("sci-fi adventure")
        # sci-fi → Science Fiction (and the synonym genre Sci-Fi & Fantasy
        # that some Jellyfin libraries use)
        assert frozenset({"Science Fiction", "Sci-Fi & Fantasy"}) in groups

    def test_scifi_unhyphenated_maps_to_science_fiction(self) -> None:
        groups = detect_query_genres("scifi")
        assert frozenset({"Science Fiction", "Sci-Fi & Fantasy"}) in groups

    def test_full_phrase_science_fiction_matches(self) -> None:
        groups = detect_query_genres("a science fiction film")
        assert frozenset({"Science Fiction", "Sci-Fi & Fantasy"}) in groups

    def test_two_genres_returns_two_groups(self) -> None:
        groups = detect_query_genres("sci-fi comedy")
        assert frozenset({"Science Fiction", "Sci-Fi & Fantasy"}) in groups
        assert frozenset({"Comedy"}) in groups
        assert len(groups) == 2

    def test_synonyms_for_same_genre_dedupe(self) -> None:
        # "sci-fi" and "scifi" both map to the same group; should not
        # appear twice.
        groups = detect_query_genres("sci-fi scifi science fiction movie")
        sf = frozenset({"Science Fiction", "Sci-Fi & Fantasy"})
        assert groups.count(sf) == 1

    def test_word_boundary_avoids_false_positives(self) -> None:
        # "warning" should not match "war"; "scientific" should not match
        # "science fiction" or "sci-fi"; "drama" should not match within
        # arbitrary text fragments.
        assert detect_query_genres("warning lights are on") == []
        assert detect_query_genres("a scientific documentary about") == [
            frozenset({"Documentary"})
        ]

    def test_case_insensitive(self) -> None:
        groups = detect_query_genres("HORROR Comedy")
        assert frozenset({"Horror"}) in groups
        assert frozenset({"Comedy"}) in groups

    def test_rom_com_shorthand(self) -> None:
        groups = detect_query_genres("a rom-com please")
        assert frozenset({"Romance"}) in groups
        assert frozenset({"Comedy"}) in groups

    def test_output_is_deterministic(self) -> None:
        # Same input → same output, same order. Repeated calls must agree.
        for _ in range(3):
            assert detect_query_genres("sci-fi comedy horror") == detect_query_genres(
                "sci-fi comedy horror"
            )
