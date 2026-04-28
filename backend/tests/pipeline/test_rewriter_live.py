"""Live-Ollama rewriter integration test — Spec 24, Task 4.13.

Marked ``@pytest.mark.pipeline`` because it requires a running Ollama
with the configured chat model. Skipped automatically when Ollama is
unreachable (see ``conftest._check_ollama``).

Asserts the basic safety contract on representative queries: each
rewrite is non-empty, ≤200 chars, contains no XML-like tokens.
"""

from __future__ import annotations

import httpx
import pytest

from app.ollama.chat_client import OllamaChatClient
from app.search.rewrite_cache import RewriteCache
from app.search.rewriter import QueryRewriter
from tests.pipeline.conftest import CHAT_MODEL, OLLAMA_HOST

_QUERIES = [
    "something like Alien but funny",
    "a fun movie to watch with my 5 year old",
    "a john Hughes comedy",
    "Eddie Murphy films",
]


@pytest.mark.pipeline
@pytest.mark.asyncio
async def test_rewriter_produces_safe_outputs_against_live_ollama(
    _ensure_models: None,  # type: ignore[no-untyped-def] - session fixture
) -> None:
    """Each fixture query yields a non-empty, bounded, tag-free rewrite."""
    timeout = httpx.Timeout(connect=5.0, read=300.0, write=10.0, pool=5.0)
    async with httpx.AsyncClient(timeout=timeout) as http:
        chat = OllamaChatClient(
            base_url=OLLAMA_HOST,
            http_client=http,
            chat_model=CHAT_MODEL,
        )
        cache = RewriteCache(max_entries=64, ttl_seconds=60)
        rewriter = QueryRewriter(
            chat_client=chat,
            cache=cache,
            timeout_seconds=10.0,  # generous for cold-load on CI
            max_output_chars=200,
        )

        for query in _QUERIES:
            rewrite = await rewriter.rewrite(query)
            assert rewrite, f"empty rewrite for: {query!r}"
            assert len(rewrite) <= 200, (
                f"oversized rewrite ({len(rewrite)} chars) for: {query!r}"
            )
            assert "<" not in rewrite and ">" not in rewrite, (
                f"tag-like token in rewrite for: {query!r}"
            )
