"""Tests for the country_codes module — name↔ISO 3166-1 alpha-2 conversion.

Spec 25 — country/language filter dimension. Module is consumed by both
the sync engine (write path) and the query router (read path), so a single
canonical mapping is required. See
``docs/specs/25-spec-country-language-filter/25-spec-country-language-filter.md``.
"""

from __future__ import annotations

import pytest

from app.library.country_codes import iso_to_name, name_to_iso


class TestNameToIso:
    """Forward conversion: Jellyfin's ProductionLocations strings → ISO codes."""

    @pytest.mark.parametrize(
        ("name", "expected_iso"),
        [
            ("United States of America", "US"),
            ("Japan", "JP"),
            ("United Kingdom", "GB"),
            ("South Korea", "KR"),
            ("France", "FR"),
            ("Germany", "DE"),
            ("Brazil", "BR"),
        ],
    )
    def test_canonical_jellyfin_names_map_to_iso(
        self, name: str, expected_iso: str
    ) -> None:
        assert name_to_iso(name) == expected_iso

    def test_unmappable_name_returns_none(self) -> None:
        assert name_to_iso("Atlantis") is None

    def test_empty_string_returns_none(self) -> None:
        assert name_to_iso("") is None

    def test_case_insensitive_matching(self) -> None:
        assert name_to_iso("japan") == "JP"
        assert name_to_iso("JAPAN") == "JP"
        assert name_to_iso("united states of america") == "US"

    def test_whitespace_trimmed(self) -> None:
        assert name_to_iso("  Japan  ") == "JP"


class TestIsoToName:
    """Reverse conversion: ISO codes → canonical English names (for ops/logging)."""

    @pytest.mark.parametrize(
        ("iso", "expected_substr"),
        [
            ("US", "United States"),
            ("JP", "Japan"),
            ("GB", "United Kingdom"),
            ("FR", "France"),
            ("DE", "Germany"),
        ],
    )
    def test_iso_returns_canonical_name(self, iso: str, expected_substr: str) -> None:
        result = iso_to_name(iso)
        assert result is not None
        assert expected_substr in result

    def test_unknown_iso_returns_none(self) -> None:
        assert iso_to_name("ZZ") is None

    def test_empty_iso_returns_none(self) -> None:
        assert iso_to_name("") is None

    def test_iso_case_insensitive(self) -> None:
        # Jellyfin shouldn't pass lowercase, but be defensive
        assert iso_to_name("jp") == iso_to_name("JP")


class TestRoundTrip:
    """name → ISO → name should produce a recognisably equivalent country."""

    @pytest.mark.parametrize("iso", ["US", "JP", "GB", "KR", "FR", "DE", "BR"])
    def test_iso_to_name_to_iso_is_identity(self, iso: str) -> None:
        name = iso_to_name(iso)
        assert name is not None
        assert name_to_iso(name) == iso
