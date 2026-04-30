"""Unit tests for ``detect_intent`` — Spec 24, Unit 1.

Functional Requirements covered (per spec 24, Unit 1):
- FR-1.1 (genres): reuses ``detect_query_genres`` for genre signal
- FR-1.2 (era — decade): ``80s`` / ``\\b\\d{2}s\\b`` → ``year_range``
- FR-1.3 (era — early/late prefix): ``early 90s``, ``late 70s``
- FR-1.4 (era — explicit year): 4-digit literal year
- FR-1.5 (rating tokens): ``rated R``, ``PG-13``
- FR-1.6 (rating colloquialisms): ``r-rated``, ``r rated``
- FR-1.7 (people): delegates to ``PersonIndex.match``
- FR-1.8 (paraphrastic flag): no signals AND len(words) > 3
- FR-1.9 (combination): multiple signals coexist on the same intent
"""

from __future__ import annotations

from app.search.intent import QueryIntent, detect_intent
from app.search.person_index import PersonIndex

_EMPTY_INDEX = PersonIndex(names=frozenset())


class TestQueryIntentModel:
    """The Pydantic ``QueryIntent`` model itself."""

    def test_default_is_empty(self) -> None:
        intent = QueryIntent()
        assert intent.genres == []
        assert intent.people == []
        assert intent.year_range is None
        assert intent.ratings == []
        assert intent.is_paraphrastic is False

    def test_has_signals_true_when_any_field_set(self) -> None:
        assert QueryIntent(genres=[frozenset({"Comedy"})]).has_signals() is True
        assert QueryIntent(people=["eddie murphy"]).has_signals() is True
        assert QueryIntent(year_range=(1980, 1989)).has_signals() is True
        assert QueryIntent(ratings=["R"]).has_signals() is True

    def test_has_signals_false_when_paraphrastic_only(self) -> None:
        assert QueryIntent(is_paraphrastic=True).has_signals() is False


class TestDetectIntentGenres:
    """FR-1.1 — genre detection delegates to ``detect_query_genres``."""

    def test_keyword_only_query(self) -> None:
        intent = detect_intent("a comedy movie", _EMPTY_INDEX)
        assert frozenset({"Comedy"}) in intent.genres
        assert intent.is_paraphrastic is False


class TestDetectIntentEra:
    """FR-1.2, FR-1.3, FR-1.4 — decade / early-late / explicit year."""

    def test_decade_2_digit(self) -> None:
        intent = detect_intent("an 80s movie", _EMPTY_INDEX)
        assert intent.year_range == (1980, 1989)

    def test_early_decade(self) -> None:
        intent = detect_intent("early 90s thriller", _EMPTY_INDEX)
        assert intent.year_range == (1990, 1994)

    def test_late_decade(self) -> None:
        intent = detect_intent("late 70s drama", _EMPTY_INDEX)
        assert intent.year_range == (1975, 1979)

    def test_explicit_4_digit_year(self) -> None:
        intent = detect_intent("a 1985 horror", _EMPTY_INDEX)
        assert intent.year_range == (1985, 1985)

    def test_decade_with_century(self) -> None:
        # "1980s" should also be recognised
        intent = detect_intent("1980s sci-fi", _EMPTY_INDEX)
        assert intent.year_range == (1980, 1989)

    def test_decade_wins_over_explicit_year_when_both_present(self) -> None:
        """Pin the documented precedence (Copilot #1).

        The docstring on ``_detect_year_range`` declares decade > explicit
        year. This test guards against an accidental rewrite reversing
        that precedence.
        """
        intent = detect_intent("a 1980s film like 1985 in vibe", _EMPTY_INDEX)
        # 1980s wins; the trailing 1985 is ignored.
        assert intent.year_range == (1980, 1989)


class TestDetectIntentRating:
    """FR-1.5, FR-1.6 — rating tokens + colloquial phrasings."""

    def test_explicit_rated_r(self) -> None:
        intent = detect_intent("a rated R action film", _EMPTY_INDEX)
        assert "R" in intent.ratings

    def test_pg13_token(self) -> None:
        intent = detect_intent("a PG-13 family movie", _EMPTY_INDEX)
        assert "PG-13" in intent.ratings

    def test_r_rated_colloquial(self) -> None:
        intent = detect_intent("R-rated action duos", _EMPTY_INDEX)
        assert "R" in intent.ratings

    def test_pg_token_alone(self) -> None:
        intent = detect_intent("a PG movie for kids", _EMPTY_INDEX)
        assert "PG" in intent.ratings
        # PG should not also match PG-13
        assert "PG-13" not in intent.ratings

    def test_lowercase_rating_tokens_normalised(self) -> None:
        """Spec 24 / Copilot review — `pg-13`, `nc-17`, lowercase `rated r`
        all normalise to the canonical UPPER form."""
        assert "PG-13" in detect_intent("a pg-13 film", _EMPTY_INDEX).ratings
        assert "NC-17" in detect_intent("an nc-17 thriller", _EMPTY_INDEX).ratings
        assert "R" in detect_intent("rated r movie", _EMPTY_INDEX).ratings


class TestDetectIntentPeople:
    """FR-1.7 — person detection delegates to ``PersonIndex``."""

    def test_known_person(self) -> None:
        idx = PersonIndex(names=frozenset({"eddie murphy"}))
        intent = detect_intent("Eddie Murphy films", idx)
        assert intent.people == ["eddie murphy"]


class TestDetectIntentParaphrastic:
    """FR-1.8 — paraphrastic flag is True only when no signals AND wordy."""

    def test_short_query_not_paraphrastic(self) -> None:
        # 3 words and no signals — not paraphrastic
        intent = detect_intent("something good please", _EMPTY_INDEX)
        assert intent.is_paraphrastic is False

    def test_wordy_query_with_no_signals_is_paraphrastic(self) -> None:
        intent = detect_intent(
            "something like Alien but funny and uplifting", _EMPTY_INDEX
        )
        assert intent.is_paraphrastic is True

    def test_signal_present_disables_paraphrastic(self) -> None:
        intent = detect_intent("a comedy movie I would enjoy tonight", _EMPTY_INDEX)
        assert intent.is_paraphrastic is False


class TestDetectIntentCombinations:
    """FR-1.9 — combined signals coexist."""

    def test_genre_plus_era(self) -> None:
        intent = detect_intent("an 80s adventure movie", _EMPTY_INDEX)
        assert intent.year_range == (1980, 1989)
        assert frozenset({"Adventure"}) in intent.genres

    def test_person_plus_genre(self) -> None:
        idx = PersonIndex(names=frozenset({"john hughes"}))
        intent = detect_intent("a john Hughes comedy", idx)
        assert "john hughes" in intent.people
        assert frozenset({"Comedy"}) in intent.genres

    def test_rating_plus_genre(self) -> None:
        intent = detect_intent("R-rated action duos", _EMPTY_INDEX)
        assert "R" in intent.ratings
        assert frozenset({"Action"}) in intent.genres


class TestDetectIntentCountries:
    """Spec 25 — country/origin signal extraction.

    Country phrases (full names + demonyms) map to ISO 3166-1 alpha-2 codes
    and land on ``QueryIntent.countries``. Plot-setting phrasings
    (``"set in"``, ``"during"``, ``"about"``, ``"takes place in"``)
    suppress extraction so the router doesn't filter on what is
    semantically a setting.
    """

    def test_country_name_maps_to_iso(self) -> None:
        intent = detect_intent("movies from Japan", _EMPTY_INDEX)
        assert intent.countries == ["JP"]

    def test_demonym_maps_to_iso(self) -> None:
        intent = detect_intent("Korean horror", _EMPTY_INDEX)
        assert intent.countries == ["KR"]

    def test_french_demonym(self) -> None:
        intent = detect_intent("a French comedy", _EMPTY_INDEX)
        assert intent.countries == ["FR"]

    def test_british_demonym(self) -> None:
        intent = detect_intent("British thriller", _EMPTY_INDEX)
        assert intent.countries == ["GB"]

    def test_country_intersects_with_genre(self) -> None:
        intent = detect_intent("Japanese animation", _EMPTY_INDEX)
        assert intent.countries == ["JP"]
        assert frozenset({"Animation"}) in intent.genres

    def test_plot_setting_phrase_does_not_trigger(self) -> None:
        """``set in Japan`` is a plot setting, not a production-country signal."""
        intent = detect_intent("movies set in Japan during WWII", _EMPTY_INDEX)
        assert intent.countries == []

    def test_takes_place_in_does_not_trigger(self) -> None:
        intent = detect_intent("a film that takes place in France", _EMPTY_INDEX)
        assert intent.countries == []

    def test_about_japan_does_not_trigger(self) -> None:
        intent = detect_intent("a documentary about Japan", _EMPTY_INDEX)
        assert intent.countries == []

    def test_signal_present_disables_paraphrastic(self) -> None:
        """A country signal counts as a structured signal.

        ``is_paraphrastic`` must therefore be False even when the query
        is wordy enough to satisfy the paraphrastic threshold.
        """
        intent = detect_intent("movies from Japan with a quiet mood", _EMPTY_INDEX)
        assert intent.countries == ["JP"]
        assert intent.is_paraphrastic is False
        assert intent.has_signals() is True


class TestDetectIntentForeignFilm:
    """Spec 25 — ``foreign film`` resolves to a NOT-IN intent.

    The router carries ``countries`` + ``countries_negate=True`` so
    ``LibraryStore.search_filtered_ids`` flips to ``NOT EXISTS`` against
    the home set. The home set comes from
    ``settings.foreign_film_home_countries`` and is injected by the
    caller; the intent layer reads a ``home_countries`` keyword for tests.
    """

    def test_foreign_film_resolves_to_negate(self) -> None:
        intent = detect_intent("foreign film", _EMPTY_INDEX, home_countries=["US"])
        assert intent.countries == ["US"]
        assert intent.countries_negate is True

    def test_foreign_movie_variant(self) -> None:
        intent = detect_intent(
            "looking for a foreign movie", _EMPTY_INDEX, home_countries=["US"]
        )
        assert intent.countries_negate is True

    def test_foreign_cinema_variant(self) -> None:
        intent = detect_intent(
            "good foreign cinema", _EMPTY_INDEX, home_countries=["US"]
        )
        assert intent.countries_negate is True

    def test_foreign_film_uses_multi_home_set(self) -> None:
        """Multiple home countries (e.g. ``[US, GB]``) all flow through."""
        intent = detect_intent(
            "foreign film", _EMPTY_INDEX, home_countries=["US", "GB"]
        )
        assert intent.countries == ["US", "GB"]
        assert intent.countries_negate is True

    def test_foreign_film_no_home_set_skips(self) -> None:
        """When ``home_countries`` is empty the router can't honour the negation
        — ``countries`` stays empty and the query falls through unchanged."""
        intent = detect_intent("foreign film", _EMPTY_INDEX, home_countries=[])
        assert intent.countries == []
        assert intent.countries_negate is False


class TestDetectIntentWordBoundary:
    """Word-boundary edge cases — false positives must not fire."""

    def test_warning_does_not_match_war(self) -> None:
        # 'war' is a genre keyword; 'warning' must not trip it.
        intent = detect_intent("warning lights are on", _EMPTY_INDEX)
        assert intent.genres == []

    def test_summary_does_not_match_mary(self) -> None:
        idx = PersonIndex(names=frozenset({"mary"}))
        intent = detect_intent("a summary movie", idx)
        # 'mary' must not match within 'summary'
        assert "mary" not in intent.people
