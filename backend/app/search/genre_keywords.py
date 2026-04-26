"""Map free-text query phrasing to canonical Jellyfin genre groups.

Used by the search service to apply a soft genre rerank: candidates whose
genre tags match the query are bucket-sorted to the top of the cosine
result set, preserving cosine order within each tier.

Each entry pairs a query keyword with a frozenset of *acceptable*
canonical genres. A candidate matches the entry if its ``genres`` list
contains any one of them. ``rom-com`` and ``romcom`` appear twice
because they imply both Romance and Comedy as independent requirements.
"""

from __future__ import annotations

import re

# (keyword, canonical-genre-group). Detection uses word-boundary regex so
# ``warning`` does not match ``war`` and ``scientific`` does not match
# ``science fiction``.
_KEYWORD_GROUPS: tuple[tuple[str, frozenset[str]], ...] = (
    # sci-fi family
    ("sci-fi", frozenset({"Science Fiction", "Sci-Fi & Fantasy"})),
    ("scifi", frozenset({"Science Fiction", "Sci-Fi & Fantasy"})),
    ("science fiction", frozenset({"Science Fiction", "Sci-Fi & Fantasy"})),
    # rom-com → both Romance AND Comedy as independent groups
    ("rom-com", frozenset({"Romance"})),
    ("rom-com", frozenset({"Comedy"})),
    ("romcom", frozenset({"Romance"})),
    ("romcom", frozenset({"Comedy"})),
    # core genres
    ("comedy", frozenset({"Comedy"})),
    ("horror", frozenset({"Horror"})),
    ("romance", frozenset({"Romance"})),
    ("action", frozenset({"Action"})),
    ("thriller", frozenset({"Thriller"})),
    ("drama", frozenset({"Drama"})),
    ("animation", frozenset({"Animation"})),
    ("animated", frozenset({"Animation"})),
    ("documentary", frozenset({"Documentary"})),
    ("fantasy", frozenset({"Fantasy", "Sci-Fi & Fantasy"})),
    ("family", frozenset({"Family"})),
    ("war", frozenset({"War"})),
    ("western", frozenset({"Western"})),
    ("crime", frozenset({"Crime"})),
    ("mystery", frozenset({"Mystery"})),
    ("music", frozenset({"Music"})),
    ("musical", frozenset({"Music"})),
    ("history", frozenset({"History"})),
    ("historical", frozenset({"History"})),
    ("anime", frozenset({"Anime", "Animation"})),
    ("adventure", frozenset({"Adventure"})),
)


_COMPILED: tuple[tuple[re.Pattern[str], frozenset[str]], ...] = tuple(
    (re.compile(rf"\b{re.escape(kw)}\b", re.IGNORECASE), groups)
    for kw, groups in _KEYWORD_GROUPS
)


def detect_query_genres(query: str) -> list[frozenset[str]]:
    """Return deduped, deterministically-ordered canonical genre groups
    detected in the query.

    Each group is a frozenset of acceptable canonical genres; a candidate
    matches the group if its ``genres`` list contains any one of them.
    An empty list means no genre keywords were found — callers should
    skip the rerank entirely in that case.
    """
    matched: set[frozenset[str]] = set()
    for pattern, groups in _COMPILED:
        if pattern.search(query):
            matched.add(groups)
    return sorted(matched, key=lambda fs: tuple(sorted(fs)))
