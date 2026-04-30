"""Country name ↔ ISO 3166-1 alpha-2 code conversion.

Single canonical mapping shared by the sync engine (write path, mapping
Jellyfin's ``ProductionLocations`` strings to ISO codes for storage) and
the query router (read path, mapping user-entered country phrases to ISO
codes for filter SQL).

Backed by ``pycountry`` — an offline ISO 3166 / 4217 / 639 lookup table.
No outbound API calls; safe under the project's "no third-party metadata
enrichment" rule (see ``CLAUDE.md`` / ``ARCHITECTURE.md``).

Spec 25 — country/language filter dimension. See
``docs/specs/25-spec-country-language-filter/`` for the full design and
the architectural review that established this module's responsibilities.
"""

from __future__ import annotations

from functools import lru_cache

import pycountry

# A library sync surfaces the same country name (e.g. ``"United States of
# America"``, repeated thousands of times) over and over; ``search_fuzzy`` is
# pycountry's heaviest path. Caching by the cleaned input string makes the
# hot path effectively a dict lookup on the second call onwards. Bounded
# explicitly: the world has ~250 ISO countries plus a few common Jellyfin
# variants — 512 is generous head-room with no meaningful memory cost.
_NAME_CACHE_SIZE = 512


@lru_cache(maxsize=_NAME_CACHE_SIZE)
def _name_to_iso_cached(cleaned: str) -> str | None:
    """Cache hot path. ``cleaned`` is whitespace-trimmed (case preserved).

    Direct lookup is tried first (matches Jellyfin's canonical names). On
    miss, ``search_fuzzy`` handles variants like ``"United States"`` ↔
    ``"United States of America"``.
    """
    direct = pycountry.countries.get(name=cleaned)
    if direct is not None:
        return direct.alpha_2

    try:
        matches = pycountry.countries.search_fuzzy(cleaned)
    except LookupError:
        return None
    if not matches:
        return None
    return matches[0].alpha_2


def name_to_iso(name: str) -> str | None:
    """Return the ISO 3166-1 alpha-2 code for a country name, or ``None``.

    Accepts canonical English names as returned by Jellyfin's
    ``ProductionLocations`` field (e.g., ``"United States of America"``,
    ``"Japan"``) and common variants. Case-insensitive; whitespace-trimmed.
    Returns ``None`` for unmappable input (empty string, unknown name) so
    the caller can apply skip-and-log handling per Spec 25's design.

    Repeated calls for the same name are served from an in-process LRU
    cache (sized to comfortably hold every ISO country plus common
    Jellyfin variants), so a 1800-item library sync only pays the
    ``search_fuzzy`` cost ~250 times rather than 1800.
    """
    if not name:
        return None
    cleaned = name.strip()
    if not cleaned:
        return None
    return _name_to_iso_cached(cleaned)


def iso_to_name(iso: str) -> str | None:
    """Return the canonical English country name for an ISO alpha-2 code.

    Used for operator-facing logging (warnings about unmappable names from
    Jellyfin) and operator-facing config display. Not in any user-facing
    response path. Case-insensitive on input; whitespace-trimmed.
    """
    if not iso:
        return None
    cleaned = iso.strip().upper()
    if not cleaned:
        return None
    country = pycountry.countries.get(alpha_2=cleaned)
    if country is None:
        return None
    return country.name
