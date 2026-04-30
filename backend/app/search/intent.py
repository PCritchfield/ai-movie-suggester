"""Query-intent detection — Spec 24, Unit 1.

Composes existing genre detection with regex-based era / rating signal
extraction and ``PersonIndex`` for cast/crew. The result is a small
Pydantic model the search service uses to decide which routing strategy
to take (structured pre-filter vs paraphrastic LLM rewrite vs raw cosine).

Regex strategy (Q-set 1, picks B/D/B/B/B/B; Q-set 2, picks D/C/D/C/C):
- Era: ``\\b(\\d{2})s\\b`` for 2-digit decades, ``\\b(\\d{4})s\\b`` for
  4-digit decades, ``\\b(early|late)\\s+(\\d{2})s\\b`` for prefixed
  decades, ``\\b(19|20)\\d{2}\\b`` for explicit year.
- Rating: token-based ``\\b(G|PG|PG-13|R|NC-17)\\b`` (case-insensitive)
  plus ``r-rated`` / ``r rated`` / ``pg-13 rated`` colloquialisms.

Paraphrastic flag is True only when every other signal is empty AND the
query has more than three words — short queries with no signals are most
likely keyword fragments, not paraphrastic descriptions.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from app.library.country_codes import name_to_iso
from app.search.genre_keywords import detect_query_genres

if TYPE_CHECKING:
    from app.search.person_index import PersonIndex


_DECADE_2_DIGIT_RE = re.compile(r"\b(\d{2})s\b")
_DECADE_4_DIGIT_RE = re.compile(r"\b(\d{2})(\d{2})s\b")
_DECADE_PREFIXED_RE = re.compile(r"\b(early|late)\s+(\d{2})s\b", re.IGNORECASE)
_EXPLICIT_YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")

# Rating tokens. Order matters in the alternation — longer tokens first
# so PG-13 wins against PG when both could match the same span.
# IGNORECASE matches user input like "pg-13", "r", "nc-17" — the
# canonical UPPER form is restored in ``_detect_ratings``.
_RATING_TOKEN_RE = re.compile(r"\b(NC-17|PG-13|PG|G|R)\b", re.IGNORECASE)
_RATING_COLLOQUIAL_RE = re.compile(r"\b(NC-17|PG-13|PG|G|R)[- ]rated\b", re.IGNORECASE)

# Per-token disambiguation patterns for bare 'PG' / 'G' / 'R'. Precompiled
# once at module load — _detect_ratings is on the per-query hot path and
# the previous inline ``re.compile(...)`` recompiled both patterns for
# every match the rating finditer produced.
_RATED_PREFIX_RES: dict[str, re.Pattern[str]] = {
    token: re.compile(rf"\brated\s+{token}\b", re.IGNORECASE)
    for token in ("PG", "G", "R")
}
_RATING_NOUN_SUFFIX_RES: dict[str, re.Pattern[str]] = {
    token: re.compile(rf"\b{token}\b\s+(movie|film|rated)", re.IGNORECASE)
    for token in ("PG", "G", "R")
}

_PARAPHRASTIC_MIN_WORDS = 4


# Spec 25 — country/demonym → ISO 3166-1 alpha-2 lookup. The full English
# names are mapped via ``country_codes.name_to_iso``; demonyms (adjectival
# forms) need a hand-curated mapping because pycountry's
# ``official_name``/``common_name`` fields don't carry the adjective form
# universally. Start with the 20 most common; expandable. Keys are
# lowercase tokens — matching is case-insensitive on the query side.
#
# British/English/Scottish all collapse to GB: ISO 3166-1 has no codes
# for the constituent UK nations, so the demonym layer pre-resolves them
# to the country code the SQL filter actually stores.
_DEMONYM_TO_ISO: dict[str, str] = {
    "japanese": "JP",
    "korean": "KR",
    "french": "FR",
    "british": "GB",
    "english": "GB",
    "scottish": "GB",
    "german": "DE",
    "italian": "IT",
    "spanish": "ES",
    "mexican": "MX",
    "brazilian": "BR",
    "russian": "RU",
    "chinese": "CN",
    "indian": "IN",
    "australian": "AU",
    "canadian": "CA",
    "american": "US",
    "swedish": "SE",
    "danish": "DK",
    "norwegian": "NO",
    "polish": "PL",
    "iranian": "IR",
    "thai": "TH",
}

# Gating allow-list of country-name tokens. We could call ``name_to_iso``
# on every token in the query, but that would route arbitrary words
# (``the``, ``movie``, …) into pycountry's ``search_fuzzy`` path, which
# the ``country_codes`` module documents as the heavy branch. Limiting
# the ``name_to_iso`` invocation to known canonical names keeps the
# query-router hot path effectively a pair of dict lookups per token.
_COUNTRY_NAME_TOKENS: tuple[str, ...] = (
    "japan",
    "korea",
    "france",
    "britain",
    "germany",
    "italy",
    "spain",
    "mexico",
    "brazil",
    "russia",
    "china",
    "india",
    "australia",
    "canada",
    "sweden",
    "denmark",
    "norway",
    "poland",
    "iran",
    "thailand",
)

# Plot-setting markers — when one appears within ~5 tokens before a
# country mention, the country is a setting (``set in Japan``,
# ``during the Cold War``, ``about France``), not a production-country
# signal. Tokenisation is whitespace + punctuation strip; window size of 5
# tokens covers ``set in / during / about <country>`` plus 1–2
# determiners or prepositions.
_PLOT_SETTING_MARKERS: frozenset[str] = frozenset(
    {"set", "in", "during", "about", "takes", "place"}
)
_PLOT_SETTING_WINDOW = 5

_FOREIGN_FILM_RE = re.compile(
    r"\bforeign\s+(film|films|movie|movies|cinema)\b", re.IGNORECASE
)

# Token-punctuation strip used by ``_tokenise``. Hoisted to module scope
# so the regex isn't even hashed against the per-call cache for every
# token in every query.
_TOKEN_PUNCT_RE = re.compile(r"[^\w-]")


class QueryIntent(BaseModel):
    """Structured signals extracted from a free-text search query.

    Spec 25 adds two country-related fields:

    - ``countries``: the list of ISO 3166-1 alpha-2 codes the user named
      (positive matches OR the home set when ``countries_negate`` fires).
      Always a concrete list — never ``None`` — so callers can pass it
      straight through to ``LibraryStore.search_filtered_ids``.
    - ``countries_negate``: ``True`` only for ``foreign film`` /
      ``foreign cinema`` queries, signalling the SQL layer to use the
      ``NOT EXISTS`` predicate against the home set.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    genres: list[frozenset[str]] = Field(default_factory=list)
    people: list[str] = Field(default_factory=list)
    year_range: tuple[int, int] | None = None
    ratings: list[str] = Field(default_factory=list)
    countries: list[str] = Field(default_factory=list)
    countries_negate: bool = False
    is_paraphrastic: bool = False

    def has_signals(self) -> bool:
        """True when at least one structured filter signal fired."""
        return bool(
            self.genres
            or self.people
            or self.year_range
            or self.ratings
            or self.countries
        )


def _detect_year_range(query: str) -> tuple[int, int] | None:
    """Return the year span detected in ``query``, or ``None``.

    The four detectors run in declared precedence order and the first
    match wins:

    1. **Prefixed decade** (``early 90s`` / ``late 70s``) — half-decade
       span. Most specific because it carries an explicit modifier.
    2. **4-digit decade** (``1980s``) — full decade.
    3. **2-digit decade** (``80s``) — full decade.
    4. **Explicit 4-digit year** (``1985``) — single year.

    Note: with this ordering, a query containing both a decade and an
    explicit year (e.g. ``"1980s film like 1985"``) yields the decade
    span. The eval fixtures don't currently exercise that case; if you
    want the narrower span to win, swap rules 4 and 1–3.
    """
    prefix = _DECADE_PREFIXED_RE.search(query)
    if prefix:
        which = prefix.group(1).lower()
        decade_short = int(prefix.group(2))
        century = 1900 if decade_short >= 30 else 2000
        decade_start = century + decade_short
        if which == "early":
            return decade_start, decade_start + 4
        return decade_start + 5, decade_start + 9

    decade_4 = _DECADE_4_DIGIT_RE.search(query)
    if decade_4:
        century = int(decade_4.group(1)) * 100
        decade = int(decade_4.group(2))
        decade_start = century + decade
        return decade_start, decade_start + 9

    decade_2 = _DECADE_2_DIGIT_RE.search(query)
    if decade_2:
        decade_short = int(decade_2.group(1))
        century = 1900 if decade_short >= 30 else 2000
        decade_start = century + decade_short
        return decade_start, decade_start + 9

    explicit = _EXPLICIT_YEAR_RE.search(query)
    if explicit:
        year = int(explicit.group(1))
        return year, year

    return None


def _detect_ratings(query: str) -> list[str]:
    """Return canonical rating tokens detected in ``query``.

    Recognises bare tokens (``rated R``, ``PG-13``) and colloquial
    suffixes (``r-rated``, ``pg-13 rated``). Output is deterministic and
    deduped, ordered by canonical priority (NC-17, PG-13, PG, G, R).
    """
    canonical_order = ("NC-17", "PG-13", "PG", "G", "R")
    found: set[str] = set()

    for match in _RATING_COLLOQUIAL_RE.finditer(query):
        found.add(match.group(1).upper())

    for match in _RATING_TOKEN_RE.finditer(query):
        token = match.group(1).upper()
        # Bare 'PG' or 'G' or 'R' is too noisy without context — only count
        # them when paired with the word "rated" anywhere within a small
        # window, OR when the token is a multi-character rating like PG-13.
        if token in {"PG-13", "NC-17"}:
            found.add(token)
            continue
        if _RATED_PREFIX_RES[token].search(query):
            found.add(token)
            continue
        # Allow 'PG' / 'R' / 'G' alone if the query is short and the token
        # is the only candidate — e.g. "a PG movie for kids".
        if _RATING_NOUN_SUFFIX_RES[token].search(query):
            found.add(token)
            continue
        # 'R-rated' / 'r rated' colloquial form already handled above.

    return [r for r in canonical_order if r in found]


def _tokenise(query: str) -> list[str]:
    """Lowercase whitespace-split tokens with punctuation stripped."""
    return [_TOKEN_PUNCT_RE.sub("", t).lower() for t in query.split() if t]


def _has_plot_setting_marker(tokens: list[str], match_index: int) -> bool:
    """Return True iff a plot-setting marker sits within ``_PLOT_SETTING_WINDOW``
    tokens *before* ``match_index``.

    Window scans backwards because plot markers always precede the country
    they govern in English (``set in Japan``, never ``Japan set in``).
    """
    start = max(0, match_index - _PLOT_SETTING_WINDOW)
    return any(tok in _PLOT_SETTING_MARKERS for tok in tokens[start:match_index])


def _detect_countries(query: str) -> list[str]:
    """Return ISO codes for country names + demonyms in ``query``.

    Suppresses extraction when a plot-setting marker (``set in``,
    ``during``, ``about``, ``takes place in``) sits within five tokens
    before the match. Output preserves first-occurrence order and dedupes.
    """
    tokens = _tokenise(query)
    found: list[str] = []
    seen: set[str] = set()

    for i, tok in enumerate(tokens):
        iso: str | None = None
        if tok in _DEMONYM_TO_ISO:
            iso = _DEMONYM_TO_ISO[tok]
        elif tok in _COUNTRY_NAME_TOKENS:
            iso = name_to_iso(tok)
        else:
            continue

        if iso is None or iso in seen:
            continue
        if _has_plot_setting_marker(tokens, i):
            continue
        seen.add(iso)
        found.append(iso)

    return found


def detect_intent(
    query: str,
    library_index: PersonIndex,
    *,
    home_countries: list[str] | None = None,
) -> QueryIntent:
    """Extract structured search signals from a free-text query.

    Args:
        query: The raw user query.
        library_index: Precomputed ``PersonIndex`` (built at startup,
            rebuilt on sync). Pass an empty index to skip person matching.
        home_countries: Operator-configured ISO codes for the
            foreign-film negation route. When ``foreign film`` (or a
            recognised variant) appears in the query, the returned
            ``countries`` list is set to this set and ``countries_negate``
            is ``True``. Pass ``None`` or an empty list to disable the
            foreign-film route — the query then falls through unchanged.

    Returns:
        A ``QueryIntent`` with whichever signals fired. ``is_paraphrastic``
        is True only when every other signal is empty AND the query has
        more than three words.
    """
    genres = detect_query_genres(query)
    year_range = _detect_year_range(query)
    ratings = _detect_ratings(query)
    people = library_index.match(query)

    countries: list[str] = []
    countries_negate = False
    if home_countries and _FOREIGN_FILM_RE.search(query):
        # Foreign-film route is exclusive: explicit country mentions in
        # the same query are ignored. Spec 25 scoped negation to the
        # ``foreign`` keyword family; widening to ``non-American`` etc.
        # is tracked as a documented follow-up in the live router cases.
        countries = list(home_countries)
        countries_negate = True
    else:
        countries = _detect_countries(query)

    has_signals = bool(genres or people or year_range or ratings or countries)
    word_count = len(query.split())
    is_paraphrastic = (not has_signals) and word_count >= _PARAPHRASTIC_MIN_WORDS

    return QueryIntent(
        genres=genres,
        people=people,
        year_range=year_range,
        ratings=ratings,
        countries=countries,
        countries_negate=countries_negate,
        is_paraphrastic=is_paraphrastic,
    )
