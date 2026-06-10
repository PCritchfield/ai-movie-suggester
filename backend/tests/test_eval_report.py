"""Unit tests for the eval orchestration/report pipeline (Spec 26 Tasks 4.0/5.0).

Pure — no live stack. Synthetic rankings exercise resolve -> score -> gate ->
format end-to-end, so the wiring is verified in CI even though the live harness
(`make eval-retrieval`) is deferred until Ollama + Jellyfin are available.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import pytest

from app.search.person_index import PersonIndex
from tests.pipeline._eval_baseline import (
    BaselineRecord,
    VecMeta,
    save_baseline,
)
from tests.pipeline._eval_loader import GoldenCase
from tests.pipeline._eval_report import evaluate, format_report, gate

if TYPE_CHECKING:
    from pathlib import Path

HOME = ["US"]
TITLE_INDEX = {
    "Galaxy Quest": ["gq"],
    "Ghostbusters": ["gb"],
    "Alien": ["al"],
    "Midsomer Murders": ["mm"],
    "Death in Paradise": ["dp"],
    "Good Will Hunting": ["gwh"],
}

CASES = [
    GoldenCase(
        query="a sci-fi comedy",  # genre -> has signals -> gated (deterministic)
        intent="genre",
        relevant_titles=["Galaxy Quest", "Ghostbusters"],
    ),
    GoldenCase(
        query="something cozy for a rainy night",  # paraphrastic -> rewrite -> ungated
        intent="paraphrastic",
        relevant_titles=["Midsomer Murders", "Death in Paradise", "Good Will Hunting"],
    ),
]
RANKED = {
    "a sci-fi comedy": ["gq", "gb", "al"],  # both relevant in top -> recall 1.0
    "something cozy for a rainy night": ["al", "gq", "gb"],  # all missed -> recall 0
}


@pytest.fixture
def outcome() -> object:
    return evaluate(CASES, RANKED, TITLE_INDEX, PersonIndex(names=frozenset()), HOME)


class TestEvaluate:
    def test_gating_flags_match_route(self, outcome: object) -> None:
        by_query = {c.query: c for c in outcome.cases}  # type: ignore[attr-defined]
        assert by_query["a sci-fi comedy"].gated is True
        assert by_query["something cozy for a rainy night"].gated is False

    def test_gated_mean_excludes_rewrite_case(self, outcome: object) -> None:
        # full mean averages both (1.0 and 0.0); gated mean keeps only the
        # deterministic genre case (1.0).
        assert outcome.full_mean["recall@10"] == pytest.approx(0.5)  # type: ignore[attr-defined]
        assert outcome.gated_mean["recall@10"] == pytest.approx(1.0)  # type: ignore[attr-defined]

    def test_missed_titles_reported(self, outcome: object) -> None:
        by_query = {c.query: c for c in outcome.cases}  # type: ignore[attr-defined]
        assert by_query["a sci-fi comedy"].missed_titles == []
        assert by_query["something cozy for a rainy night"].missed_titles == [
            "Death in Paradise",
            "Good Will Hunting",
            "Midsomer Murders",
        ]


class TestGate:
    def _baseline(self, tmp_path: Path, scores: dict[str, float]) -> str:
        path = tmp_path / "eval_baseline.json"
        save_baseline(
            path,
            [
                BaselineRecord(
                    vec_meta=VecMeta("nomic-embed-text", 4, 768),
                    scores=scores,
                    date=date.today().isoformat(),
                )
            ],
        )
        return str(path)

    def test_regression_flagged_against_matching_version(
        self, tmp_path: Path, outcome: object
    ) -> None:
        # Baseline recall@10 was 0.9; gated is 1.0 -> improvement, no regression.
        # Baseline precision@10 0.9 vs gated ~0.2 -> regression.
        path = self._baseline(tmp_path, {"recall@10": 0.9, "precision@10": 0.9})
        result = gate(outcome.gated_mean, path, VecMeta("nomic-embed-text", 4, 768))  # type: ignore[attr-defined]
        assert result.comparable is True
        flagged = {r.metric for r in result.regressions}
        assert "precision@10" in flagged
        assert "recall@10" not in flagged

    def test_not_comparable_when_version_differs(
        self, tmp_path: Path, outcome: object
    ) -> None:
        path = self._baseline(tmp_path, {"recall@10": 0.9})
        # current template version 9 has no matching baseline record
        result = gate(outcome.gated_mean, path, VecMeta("nomic-embed-text", 9, 768))  # type: ignore[attr-defined]
        assert result.comparable is False
        assert result.regressions == []


def test_format_report_marks_ungated_and_gate(outcome: object) -> None:
    path_gate = gate(outcome.gated_mean, "/nonexistent.json", VecMeta("x", 1, 768))  # type: ignore[attr-defined]
    report = format_report(outcome, path_gate)  # type: ignore[arg-type]
    assert "UNGATED" in report
    assert "GATE:" in report
    assert "a sci-fi comedy" in report
