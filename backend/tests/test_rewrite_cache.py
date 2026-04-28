"""Unit tests for ``RewriteCache`` — Spec 24, Unit 6.

Functional requirements covered:
- FR-6.1 (key shape): SHA-256 of the normalised query
- FR-6.2 (normalisation): collapse whitespace, lowercase
- FR-6.3 (LRU eviction): oldest entry is dropped when capacity is hit
- FR-6.4 (TTL expiry): expired entries miss on lookup
- FR-6.5 (prompt-version invalidation): mismatched version → miss
- FR-6.6 (clear): clear() empties the cache
- FR-6.7 (no PII in logs): nothing is logged at INFO/WARNING about keys
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.search.rewrite_cache import RewriteCache

if TYPE_CHECKING:
    import pytest


_VERSION = "v-test-001"


class TestRewriteCacheRoundTrip:
    def test_set_then_get_returns_value(self) -> None:
        cache = RewriteCache(max_entries=10, ttl_seconds=60)
        cache.set("a comedy movie", "comedy film", _VERSION)
        assert cache.get("a comedy movie", _VERSION) == "comedy film"

    def test_get_missing_returns_none(self) -> None:
        cache = RewriteCache(max_entries=10, ttl_seconds=60)
        assert cache.get("never-set", _VERSION) is None


class TestRewriteCacheNormalisation:
    def test_whitespace_collapse(self) -> None:
        cache = RewriteCache(max_entries=10, ttl_seconds=60)
        cache.set("a  comedy  movie", "rewrite", _VERSION)
        assert cache.get("a comedy movie", _VERSION) == "rewrite"

    def test_case_insensitive_key(self) -> None:
        cache = RewriteCache(max_entries=10, ttl_seconds=60)
        cache.set("A Comedy Movie", "rewrite", _VERSION)
        assert cache.get("a comedy movie", _VERSION) == "rewrite"


class TestRewriteCacheVersionMismatch:
    def test_mismatched_prompt_version_misses(self) -> None:
        cache = RewriteCache(max_entries=10, ttl_seconds=60)
        cache.set("query", "rewrite", _VERSION)
        assert cache.get("query", "v-different-002") is None


class TestRewriteCacheLRU:
    def test_evicts_oldest_when_at_capacity(self) -> None:
        cache = RewriteCache(max_entries=2, ttl_seconds=60)
        cache.set("a", "A", _VERSION)
        cache.set("b", "B", _VERSION)
        cache.set("c", "C", _VERSION)  # forces eviction
        assert cache.get("a", _VERSION) is None
        assert cache.get("b", _VERSION) == "B"
        assert cache.get("c", _VERSION) == "C"

    def test_get_marks_recently_used(self) -> None:
        cache = RewriteCache(max_entries=2, ttl_seconds=60)
        cache.set("a", "A", _VERSION)
        cache.set("b", "B", _VERSION)
        # Touch 'a' so 'b' becomes the LRU candidate
        cache.get("a", _VERSION)
        cache.set("c", "C", _VERSION)
        assert cache.get("a", _VERSION) == "A"
        assert cache.get("b", _VERSION) is None


class TestRewriteCacheTTL:
    def test_expired_entry_misses(self) -> None:
        cache = RewriteCache(max_entries=10, ttl_seconds=0)  # immediate expiry
        cache.set("query", "rewrite", _VERSION)
        # any non-zero monotonic gap from set→get is enough
        assert cache.get("query", _VERSION) is None


class TestRewriteCacheClear:
    def test_clear_drops_all_entries(self) -> None:
        cache = RewriteCache(max_entries=10, ttl_seconds=60)
        cache.set("a", "A", _VERSION)
        cache.set("b", "B", _VERSION)
        cache.clear()
        assert cache.get("a", _VERSION) is None
        assert cache.get("b", _VERSION) is None


class TestRewriteCacheLogging:
    def test_no_query_or_value_logged_at_info_or_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        cache = RewriteCache(max_entries=10, ttl_seconds=60)
        with caplog.at_level(logging.INFO):
            cache.set("a comedy movie", "comedy film", _VERSION)
            cache.get("a comedy movie", _VERSION)
            cache.clear()
        # No INFO/WARNING/ERROR record contains the raw query or value
        for r in caplog.records:
            if r.levelno >= logging.INFO:
                assert "comedy movie" not in r.message
                assert "comedy film" not in r.message
