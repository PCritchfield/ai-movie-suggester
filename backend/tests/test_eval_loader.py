"""Unit tests for the Spec 26 golden-set loader (Task 1.0).

Pure tests — no Ollama/Jellyfin, no `@pytest.mark.pipeline`. They run in CI.
Title resolution is exercised against a stub title index (a plain dict), so
no live corpus is needed.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from tests.pipeline._eval_loader import (
    ALLOWED_INTENTS,
    GoldenCase,
    load_golden_set,
    resolve_titles,
)

if TYPE_CHECKING:
    from pathlib import Path


def _write(tmp_path: Path, rows: list[dict]) -> Path:
    p = tmp_path / "golden.json"
    p.write_text(json.dumps(rows))
    return p


class TestLoadGoldenSet:
    def test_real_fixture_parses(self) -> None:
        cases = load_golden_set()
        assert len(cases) >= 15
        assert all(isinstance(c, GoldenCase) for c in cases)

    def test_real_fixture_quality(self) -> None:
        """Every case has a valid intent and >=3 relevant titles; all six
        intents are represented."""
        cases = load_golden_set()
        for c in cases:
            assert c.intent in ALLOWED_INTENTS
            assert len(c.relevant_titles) >= 3, f"{c.query!r} has <3 relevant titles"
        assert {c.intent for c in cases} == ALLOWED_INTENTS

    def test_missing_required_field_raises(self, tmp_path: Path) -> None:
        src = _write(tmp_path, [{"intent": "genre", "relevant_titles": ["X"]}])
        with pytest.raises(ValueError, match="missing required field 'query'"):
            load_golden_set(src)

    def test_unknown_intent_raises(self, tmp_path: Path) -> None:
        src = _write(
            tmp_path, [{"query": "q", "intent": "bogus", "relevant_titles": ["X"]}]
        )
        with pytest.raises(ValueError, match="unknown intent"):
            load_golden_set(src)

    def test_empty_relevant_titles_raises(self, tmp_path: Path) -> None:
        src = _write(
            tmp_path, [{"query": "q", "intent": "genre", "relevant_titles": []}]
        )
        with pytest.raises(ValueError, match="empty relevant_titles"):
            load_golden_set(src)


class TestTitleResolution:
    def test_resolves_unique_titles(self) -> None:
        index = {"Alien": ["a1"], "Blade Runner": ["b1"]}
        case = GoldenCase(
            query="a Ridley Scott film",
            intent="person",
            relevant_titles=["Alien", "Blade Runner"],
        )
        assert case.resolve_relevant_ids(index) == ["a1", "b1"]

    def test_unknown_title_fails_loud(self) -> None:
        with pytest.raises(ValueError, match="is unknown"):
            resolve_titles(["Ghost Film"], {"Alien": ["a1"]})

    def test_ambiguous_title_fails_loud(self) -> None:
        """A title matching >1 item (e.g. a remake) must fail, not pick first."""
        index = {"The Thing": ["thing-1982", "thing-2011"]}
        with pytest.raises(ValueError, match="is ambiguous"):
            resolve_titles(["The Thing"], index)
