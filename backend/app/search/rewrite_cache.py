"""In-memory LRU+TTL cache for paraphrastic LLM rewrites — Spec 24, Unit 6.

Keys are SHA-256 digests of the *normalised* query (case-folded, whitespace
collapsed). Entries are invalidated on prompt-version mismatch — a change
to the few-shot system prompt bumps the version hash, which causes every
cached rewrite to miss until it's recomputed under the new prompt.

The cache is intentionally process-local and ephemeral: chat history and
queries are PII-adjacent and are explicitly NOT persisted to disk.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from collections import OrderedDict
from dataclasses import dataclass

logger = logging.getLogger(__name__)


_WHITESPACE_RE = re.compile(r"\s+")


def _normalise(query: str) -> str:
    """Lowercase, strip, and collapse whitespace runs to a single space."""
    return _WHITESPACE_RE.sub(" ", query.strip().lower())


def _hash_key(query: str) -> str:
    return hashlib.sha256(_normalise(query).encode()).hexdigest()


@dataclass(slots=True, frozen=True)
class _Entry:
    rewrite: str
    prompt_version: str
    expires_at: float


class RewriteCache:
    """Process-local LRU + TTL cache keyed by SHA-256(normalise(query))."""

    def __init__(self, *, max_entries: int, ttl_seconds: int) -> None:
        self._max = max_entries
        self._ttl = ttl_seconds
        self._entries: OrderedDict[str, _Entry] = OrderedDict()

    def get(self, query: str, prompt_version: str) -> str | None:
        """Return the cached rewrite or ``None`` on miss / version mismatch
        / expiry.

        A miss never raises — the rewriter falls back to a live call.
        """
        key = _hash_key(query)
        entry = self._entries.get(key)
        if entry is None:
            return None
        if entry.prompt_version != prompt_version:
            return None
        if entry.expires_at <= time.monotonic():
            # purge the stale entry on read so memory doesn't grow unbounded
            self._entries.pop(key, None)
            return None
        # mark as recently used
        self._entries.move_to_end(key)
        return entry.rewrite

    def set(self, query: str, rewrite: str, prompt_version: str) -> None:
        """Store a rewrite under the normalised key.

        Evicts the LRU entry when the cache is at capacity. Logs at DEBUG
        only — never at INFO/WARNING/ERROR to avoid leaking PII via stdout.
        """
        key = _hash_key(query)
        expires = time.monotonic() + self._ttl
        if key in self._entries:
            # update in place + bump LRU position
            self._entries[key] = _Entry(rewrite, prompt_version, expires)
            self._entries.move_to_end(key)
            return

        self._entries[key] = _Entry(rewrite, prompt_version, expires)
        if len(self._entries) > self._max:
            self._entries.popitem(last=False)
        logger.debug("rewrite_cache_set entries=%d", len(self._entries))

    def clear(self) -> None:
        """Drop every cached entry — called from the logout cascade."""
        self._entries.clear()
        logger.debug("rewrite_cache_cleared")
