"""Paraphrastic query rewriter — Spec 24, Unit 5.

Wraps :class:`OllamaChatClient` with a 2-second timeout, a 200-character
output cap, tag-token rejection, and a raw-query fallback for *every*
error class. Successful rewrites are cached via :class:`RewriteCache`
keyed by the normalised query and the few-shot prompt's version hash.

Security framing (Q5-B + Angua follow-up):
  - User input is wrapped in ``<user-query>...</user-query>`` inside the
    user message.
  - The system prompt instructs the model to treat that block as DATA.
  - The output is rejected if it contains ``<...>`` substrings, on the
    assumption that no legitimate paraphrase needs XML-like tokens.

This is a soft mitigation. Deeper sandboxing tracked in issue #114.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import TYPE_CHECKING

from app.ollama.errors import (
    OllamaConnectionError,
    OllamaError,
    OllamaModelError,
    OllamaStreamError,
    OllamaTimeoutError,
)
from app.search.rewriter_prompts import (
    REWRITE_PROMPT_VERSION_HASH,
    REWRITE_SYSTEM_PROMPT,
)

if TYPE_CHECKING:
    from app.ollama.chat_client import OllamaChatClient
    from app.search.rewrite_cache import RewriteCache

logger = logging.getLogger(__name__)

_TAG_TOKEN_RE = re.compile(r"<[^>]*>")


class QueryRewriter:
    """Paraphrastic LLM rewriter with strict fallback semantics."""

    def __init__(
        self,
        *,
        chat_client: OllamaChatClient,
        cache: RewriteCache,
        timeout_seconds: float,
        max_output_chars: int,
    ) -> None:
        self._chat = chat_client
        self._cache = cache
        self._timeout = timeout_seconds
        self._max_chars = max_output_chars

    async def rewrite(self, query: str) -> str:
        """Return a rewritten query (cached) or the raw query on any failure.

        Never raises — paraphrastic rewriting is best-effort.
        """
        cached = self._cache.get(query, REWRITE_PROMPT_VERSION_HASH)
        if cached is not None:
            return cached

        try:
            rewritten = await asyncio.wait_for(
                self._stream_rewrite(query),
                timeout=self._timeout,
            )
        except TimeoutError:
            logger.warning("rewrite_fallback reason=timeout query_len=%d", len(query))
            return query
        except (
            OllamaTimeoutError,
            OllamaConnectionError,
            OllamaModelError,
            OllamaStreamError,
            OllamaError,
        ) as exc:
            logger.warning(
                "rewrite_fallback reason=%s query_len=%d",
                type(exc).__name__,
                len(query),
            )
            return query

        clean = rewritten.strip()
        if not clean:
            logger.warning("rewrite_fallback reason=empty query_len=%d", len(query))
            return query
        if len(clean) > self._max_chars:
            logger.warning("rewrite_fallback reason=oversized chars=%d", len(clean))
            return query
        if _TAG_TOKEN_RE.search(clean):
            logger.warning(
                "rewrite_fallback reason=tag_injection query_len=%d", len(query)
            )
            return query

        self._cache.set(query, clean, REWRITE_PROMPT_VERSION_HASH)
        return clean

    async def _stream_rewrite(self, query: str) -> str:
        """Issue the chat call, accumulate streaming tokens, return the result."""
        messages = [
            {"role": "system", "content": REWRITE_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"<user-query>{_sanitise_for_tag(query)}</user-query>",
            },
        ]
        chunks: list[str] = []
        async for chunk in self._chat.chat_stream(messages):
            chunks.append(chunk)
        return "".join(chunks)


def _sanitise_for_tag(query: str) -> str:
    """Strip ``<`` and ``>`` from user input before wrapping in tag delimiters.

    Without this, a user query containing a stray ``</user-query>`` could
    terminate the framing block and let subsequent text be interpreted as
    instructions rather than data (Copilot review #4). The downstream
    ``_TAG_TOKEN_RE`` filter catches model-side tag injection; this is the
    matching input-side defence.
    """
    return query.replace("<", "").replace(">", "")
