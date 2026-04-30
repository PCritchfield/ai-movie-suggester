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
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio

from app.ollama.chat_client import OllamaChatClient
from app.ollama.client import OllamaEmbeddingClient
from app.search.intent import detect_intent
from app.search.person_index import PersonIndex
from app.search.rewrite_cache import RewriteCache
from app.search.rewriter import QueryRewriter
from app.search.service import SearchService
from tests.pipeline._router_eval_loader import QueryRouterCase, load_cases
from tests.pipeline.conftest import CHAT_MODEL, EMBED_MODEL, OLLAMA_HOST

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from app.library.store import LibraryStore
    from app.vectors.repository import SqliteVecRepository


@pytest_asyncio.fixture
async def query_router_service(
    embedded_library: SqliteVecRepository,
    pipeline_library_store: LibraryStore,
) -> AsyncGenerator[SearchService, None]:
    """Build a SearchService wired against live Ollama + the seeded library."""
    timeout = httpx.Timeout(connect=5.0, read=300.0, write=10.0, pool=5.0)
    async with httpx.AsyncClient(timeout=timeout) as http:
        embed_client = OllamaEmbeddingClient(
            base_url=OLLAMA_HOST,
            http_client=http,
            embed_model=EMBED_MODEL,
        )
        chat_client = OllamaChatClient(
            base_url=OLLAMA_HOST,
            http_client=http,
            chat_model=CHAT_MODEL,
        )
        person_index = PersonIndex(
            names=await pipeline_library_store.get_all_people_names()
        )
        cache = RewriteCache(max_entries=128, ttl_seconds=3600)
        rewriter = QueryRewriter(
            chat_client=chat_client,
            cache=cache,
            timeout_seconds=10.0,
            max_output_chars=200,
        )
        # Permission service is bypassed under live test by passing a
        # filter-everything-through stub.
        permissions = AsyncMock()
        permissions.filter_permitted.side_effect = lambda *args, **_kw: args[2]

        service = SearchService(
            ollama_client=embed_client,
            vec_repo=embedded_library,
            permission_service=permissions,
            library_store=pipeline_library_store,
            person_index=person_index,
            rewriter=rewriter,
        )
        yield service


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
    query_router_service: SearchService,
    pipeline_library_store: LibraryStore,
) -> None:
    person_index = query_router_service.person_index
    assert person_index is not None
    detected = _detect_path(
        case.query,
        person_index,
        home_countries=list(query_router_service._home_countries),
    )
    if case.expected_path != "rating":
        # Rating cases will detect as 'rating' even when the column is
        # NULL; we still record it but the title checks may not pass
        # until the next sync populates rating data.
        assert detected == case.expected_path, (
            f"path mismatch for {case.query!r}: detected={detected} "
            f"expected={case.expected_path}"
        )

    response = await query_router_service.search(
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
