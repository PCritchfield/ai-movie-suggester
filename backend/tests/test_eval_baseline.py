"""Unit tests for the Spec 26 versioned baseline + regression gating (Task 5.0).

Pure tests — no live stack, no `@pytest.mark.pipeline`. Run in CI.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.pipeline._eval_baseline import (
    BaselineRecord,
    VecMeta,
    append_record,
    find_regressions,
    load_baseline,
    mean_scores,
    save_baseline,
    select_baseline,
)

if TYPE_CHECKING:
    from pathlib import Path


def _rec(template: int | None, scores: dict[str, float], date: str) -> BaselineRecord:
    return BaselineRecord(
        vec_meta=VecMeta("nomic-embed-text", template, 768),
        scores=scores,
        date=date,
    )


class TestPersistence:
    def test_round_trip_versioned_list(self, tmp_path: Path) -> None:
        path = tmp_path / "eval_baseline.json"
        records = [
            _rec(4, {"ndcg@10": 0.60}, "2026-06-01"),
            _rec(5, {"ndcg@10": 0.71}, "2026-06-08"),
        ]
        save_baseline(path, records)
        assert load_baseline(path) == records

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        assert load_baseline(tmp_path / "nope.json") == []

    def test_append_is_non_destructive(self) -> None:
        original = [_rec(4, {"ndcg@10": 0.60}, "2026-06-01")]
        updated = append_record(original, _rec(5, {"ndcg@10": 0.71}, "2026-06-08"))
        assert len(updated) == 2
        assert original[0] in updated  # prior record intact
        assert len(original) == 1  # input not mutated


class TestSelectBaseline:
    def test_returns_most_recent_matching_version(self) -> None:
        records = [
            _rec(4, {"ndcg@10": 0.60}, "2026-06-01"),
            _rec(4, {"ndcg@10": 0.64}, "2026-06-05"),  # newer, same version
            _rec(5, {"ndcg@10": 0.71}, "2026-06-08"),  # different version
        ]
        chosen = select_baseline(records, VecMeta("nomic-embed-text", 4, 768))
        assert chosen is not None
        assert chosen.date == "2026-06-05"

    def test_no_match_on_different_template(self) -> None:
        records = [_rec(4, {"ndcg@10": 0.60}, "2026-06-01")]
        assert select_baseline(records, VecMeta("nomic-embed-text", 9, 768)) is None

    def test_none_template_never_matches(self) -> None:
        """A None (unversioned) template is not comparable on either side —
        never coerced to 0."""
        records = [_rec(None, {"ndcg@10": 0.60}, "2026-06-01")]
        # current has a real version, baseline is None -> no match
        assert select_baseline(records, VecMeta("nomic-embed-text", 4, 768)) is None
        # current is None too -> still no match (can't trust unversioned)
        assert select_baseline(records, VecMeta("nomic-embed-text", None, 768)) is None

    def test_no_match_on_different_model_or_dims(self) -> None:
        records = [_rec(4, {"ndcg@10": 0.60}, "2026-06-01")]
        assert select_baseline(records, VecMeta("other-model", 4, 768)) is None
        assert select_baseline(records, VecMeta("nomic-embed-text", 4, 384)) is None


class TestRegressions:
    def test_flags_drop_beyond_threshold(self) -> None:
        regs = find_regressions(
            current={"ndcg@10": 0.50}, baseline={"ndcg@10": 0.60}, threshold=0.05
        )
        assert len(regs) == 1
        assert regs[0].metric == "ndcg@10"
        assert abs(regs[0].drop - 0.10) < 1e-9

    def test_ignores_within_threshold(self) -> None:
        regs = find_regressions({"ndcg@10": 0.58}, {"ndcg@10": 0.60}, threshold=0.05)
        assert regs == []

    def test_ignores_improvements(self) -> None:
        regs = find_regressions({"ndcg@10": 0.72}, {"ndcg@10": 0.60}, threshold=0.05)
        assert regs == []


class TestMeanScores:
    def test_means_per_metric(self) -> None:
        # The harness passes only the gated (deterministic) rows here; the
        # non-deterministic rewrite-path case (0.0) is filtered out upstream.
        rows = [{"ndcg@10": 0.6}, {"ndcg@10": 0.8}]
        agg = mean_scores(rows)
        assert abs(agg["ndcg@10"] - 0.7) < 1e-9

    def test_empty_rows(self) -> None:
        assert mean_scores([]) == {}
