"""Precomputed cast/director/writer name index for query intent matching.

Built once at startup from ``LibraryStore.get_all_people_names()`` and
rebuilt on every ``sync-completed`` event so newly-synced names become
discoverable without a backend restart.

Single-token names (``Cher``, ``Madonna``) are gated behind an explicit
intent token (``movie``, ``film``, ``starring``, …) elsewhere in the
query — Spec 24 Q1-D resolution. Without this gate a query like
``"a may evening drama"`` would falsely match the actor ``May``.

Names shorter than 3 characters are skipped at build time — anything
shorter is too noisy to safely word-boundary match.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.library.store import LibraryStore

logger = logging.getLogger(__name__)

_MIN_NAME_LEN = 3

# Tokens that promote a single-token name from "ambiguous noun" to
# "person reference". Mirrors the spec's Q1-D gating set.
_INTENT_TOKENS: frozenset[str] = frozenset(
    {"movie", "movies", "film", "films", "with", "starring", "stars"}
)

_INTENT_TOKEN_RE = re.compile(
    r"\b(" + "|".join(re.escape(t) for t in _INTENT_TOKENS) + r")\b",
    re.IGNORECASE,
)


class PersonIndex:
    """Word-boundary regex match over a frozen set of cast/crew names.

    The set of names is held as a private attribute and replaced atomically
    on rebuild. Callers should NEVER mutate the underlying set directly.

    Performance: a single combined alternation regex is compiled at build
    time covering every name in the index. ``match()`` runs one
    ``finditer`` over the query rather than one ``re.compile`` + search
    per name — the previous shape was O(N) compiles per query on what is
    expected to be a thousands-of-names index.
    """

    def __init__(self, names: frozenset[str]) -> None:
        self._names: frozenset[str] = self._filter_short(names)
        self._combined_re = self._compile_combined(self._names)

    @staticmethod
    def _filter_short(names: frozenset[str]) -> frozenset[str]:
        return frozenset(n for n in names if len(n) >= _MIN_NAME_LEN)

    @staticmethod
    def _compile_combined(names: frozenset[str]) -> re.Pattern[str] | None:
        """Build a single ``\\b(name1|name2|...)\\b`` alternation regex.

        Longer names sort first so a multi-token name shadows any
        single-token substring of itself in the alternation. Returns
        ``None`` for an empty index — callers must short-circuit.
        """
        if not names:
            return None
        ordered = sorted(names, key=lambda n: (-len(n), n))
        alternation = "|".join(re.escape(n) for n in ordered)
        return re.compile(rf"\b({alternation})\b", re.IGNORECASE)

    def contains(self, name: str) -> bool:
        """Return True if ``name`` (lowercased) is in the index."""
        return name.lower() in self._names

    def match(self, query: str) -> list[str]:
        """Return all index names that appear in ``query`` as whole-word
        phrases.

        Multi-token names always require strict word-boundary phrase match.
        Single-token names additionally require at least one intent token
        elsewhere in the query (per Spec 24 Q1-D).

        The returned list is deterministic: names appear in the order they
        occur in ``query``, deduplicated. Callers can safely compare two
        lists for equality.
        """
        if self._combined_re is None:
            return []

        has_intent_token = bool(_INTENT_TOKEN_RE.search(query))
        matched: list[str] = []
        seen: set[str] = set()

        for raw_match in self._combined_re.finditer(query):
            name = raw_match.group(1).lower()
            if name in seen:
                continue
            is_single_token = " " not in name
            if is_single_token and not has_intent_token:
                continue
            matched.append(name)
            seen.add(name)
        return matched

    async def rebuild_from_store(self, store: LibraryStore) -> None:
        """Re-fetch names from the store and atomically swap the underlying set.

        Wired into the sync-completed event so newly-synced cast / crew
        becomes match-able without a backend restart.
        """
        new_names = await store.get_all_people_names()
        self._names = self._filter_short(new_names)
        self._combined_re = self._compile_combined(self._names)
        logger.info("person_index_built count=%d", len(self._names))
