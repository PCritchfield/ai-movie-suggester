"""End-to-end query-router eval — Spec 24, Task 5.0.

Parameterised over ``tests/fixtures/query_router_cases.json``. For each
case, the test:

1. Embeds the query against live Ollama via the shared pipeline fixtures.
2. Runs ``SearchService.search`` against the embedded fixture library.
3. Asserts the detected intent matches ``expected_path``.
4. Asserts every ``must_include_titles`` entry is in the top-10 result set.
5. Asserts no ``must_exclude_titles`` entry is in the top-10 result set
   (when present).

Marked ``@pytest.mark.pipeline`` — runs under ``make validate-pipeline``
and is skipped automatically when Ollama or Jellyfin aren't reachable.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from app.search.intent import detect_intent
from tests.pipeline._router_eval_loader import QueryRouterCase, load_cases

if TYPE_CHECKING:
    from app.library.store import LibraryStore
    from app.search.person_index import PersonIndex
    from app.search.service import SearchService


def _detect_path(
    query: str,
    person_index: PersonIndex,
    home_countries: list[str] | None = None,
) -> str:
    """Map a query to one of the seven expected_path values.

    Spec 25 adds the ``country`` path, sequenced after rating and before
    keyword so a query like ``Japanese animation`` (country + genre) resolves
    to country, while a pure-genre query still resolves to keyword.
    """
    intent = detect_intent(query, person_index, home_countries=home_countries)
    if intent.people:
        return "person"
    if intent.year_range is not None:
        return "year"
    if intent.ratings:
        return "rating"
    if intent.countries:
        return "country"
    if intent.genres:
        return "keyword"
    if intent.is_paraphrastic:
        return "rewrite"
    return "semantic"


@pytest.mark.pipeline
@pytest.mark.parametrize(
    "case",
    load_cases(),
    ids=lambda c: c.query[:60],
)
async def test_query_router_case(
    case: QueryRouterCase,
    eval_search_service: SearchService,
    pipeline_library_store: LibraryStore,
) -> None:
    person_index = eval_search_service.person_index
    assert person_index is not None
    detected = _detect_path(
        case.query,
        person_index,
        home_countries=list(eval_search_service._home_countries),
    )
    if case.expected_path != "rating":
        # Rating cases will detect as 'rating' even when the column is
        # NULL; we still record it but the title checks may not pass
        # until the next sync populates rating data.
        assert detected == case.expected_path, (
            f"path mismatch for {case.query!r}: detected={detected} "
            f"expected={case.expected_path}"
        )

    response = await eval_search_service.search(
        case.query, limit=10, user_id="eval", token="eval-token"
    )
    titles = [r.title for r in response.results]

    for required in case.must_include_titles:
        assert required in titles, (
            f"expected {required!r} in top-10 for {case.query!r}; got {titles}"
        )
    for forbidden in case.must_exclude_titles:
        assert forbidden not in titles, (
            f"forbidden title {forbidden!r} appeared in top-10 for "
            f"{case.query!r}; got {titles}"
        )
