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

import pycountry


def name_to_iso(name: str) -> str | None:
    """Return the ISO 3166-1 alpha-2 code for a country name, or ``None``.

    Accepts canonical English names as returned by Jellyfin's
    ``ProductionLocations`` field (e.g., ``"United States of America"``,
    ``"Japan"``) and common variants. Case-insensitive; whitespace-trimmed.
    Returns ``None`` for unmappable input (empty string, unknown name) so
    the caller can apply skip-and-log handling per Spec 25's design.
    """
    if not name:
        return None
    cleaned = name.strip()
    if not cleaned:
        return None

    # Direct lookup by name first (fast path for canonical names).
    direct = pycountry.countries.get(name=cleaned)
    if direct is not None:
        return direct.alpha_2

    # Fall back to fuzzy search for variants ("United States" vs
    # "United States of America", lowercased input, etc.). search_fuzzy
    # raises LookupError on no match — convert to None for our contract.
    try:
        matches = pycountry.countries.search_fuzzy(cleaned)
    except LookupError:
        return None
    if not matches:
        return None
    return matches[0].alpha_2


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
