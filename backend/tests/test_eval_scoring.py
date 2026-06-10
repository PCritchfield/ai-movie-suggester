"""Unit tests for the retrieval eval scoring engine (Spec 26, Task 3.0).

These tests are PURE — no Ollama, no Jellyfin, no live inference. They run in
normal CI (no ``@pytest.mark.pipeline`` marker). They pin a fixed toy example
with hand-computed expected IR metric values and assert that BOTH the
hand-rolled implementation AND the ``ranx`` engine agree with those values.

``ranx`` is a dev/test-only dependency and is the correctness oracle. The
hand-rolled implementation is the learning artifact; cross-checking the two
against independently hand-computed numbers is the point of the exercise.

Worked toy example (binary relevance)
=====================================

Query ``q1``
    relevant = {d1, d3}
    ranked   = [d2, d1, d3, d4, d5, d6, d7, d8, d9, d10, d11]
               (d2 irrelevant, d1 relevant@rank2, d3 relevant@rank3, rest noise)

    precision@5  = (#relevant in top 5) / 5     = 2 / 5  = 0.4
    precision@10 = (#relevant in top 10) / 10   = 2 / 10 = 0.2
    precision@20 = (#relevant in top 20) / 20   = 2 / 20 = 0.1  (only 11 ranked)
    recall@5     = (#relevant in top 5) / 2     = 2 / 2  = 1.0
    recall@10    = recall@20                    = 1.0
    mrr (first relevant at rank 2)              = 1/2    = 0.5
      (rank cut-off >= 2 does not change MRR here, so mrr@{5,10,20} = 0.5)

    NDCG@k uses gain=1 per relevant, discount = 1/log2(rank+1):
      DCG@5  = 1/log2(2+1) + 1/log2(3+1)
             = 0.6309297535714574 + 0.5
             = 1.1309297535714573
      IDCG@5 = ideal ordering puts both relevant at ranks 1,2:
               1/log2(1+1) + 1/log2(2+1)
             = 1.0 + 0.6309297535714574
             = 1.6309297535714573
      NDCG@5 = 1.1309297535714573 / 1.6309297535714573
             = 0.6934264036172708
      (no further relevant beyond rank 3, so NDCG@10 = NDCG@20 = NDCG@5)

Query ``q2``
    relevant = {dA}
    ranked   = [dA, dB, dC]   (relevant doc ranked first)

    precision@5  = 1 / 5  = 0.2
    precision@10 = 1 / 10 = 0.1
    precision@20 = 1 / 20 = 0.05
    recall@{5,10,20} = 1 / 1 = 1.0
    mrr@{5,10,20}    = 1 / 1 = 1.0
    NDCG@{5,10,20}   = 1.0   (perfect: only relevant doc is at rank 1)

Aggregate means (over q1, q2)
    precision@5  = (0.4 + 0.2) / 2  = 0.3
    precision@10 = (0.2 + 0.1) / 2  = 0.15
    precision@20 = (0.1 + 0.05) / 2 = 0.075
    recall@{5,10,20} = (1.0 + 1.0) / 2 = 1.0
    mrr@{5,10,20}    = (0.5 + 1.0) / 2 = 0.75
    ndcg@5/10/20     = (0.6934264036172708 + 1.0) / 2 = 0.8467132018086354
"""

from __future__ import annotations

import math

import pytest

from app.search.models import (
    SearchResponse,
    SearchResultItem,
    SearchStatus,
)
from tests.pipeline._eval_scoring import (
    QueryEvalInput,
    compute_metrics,
    mrr,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    to_qrels,
    to_run,
)

# --- Fixed toy example ---------------------------------------------------

Q1_RELEVANT = {"d1", "d3"}
Q1_RANKED = [
    "d2",
    "d1",
    "d3",
    "d4",
    "d5",
    "d6",
    "d7",
    "d8",
    "d9",
    "d10",
    "d11",
]

Q2_RELEVANT = {"dA"}
Q2_RANKED = ["dA", "dB", "dC"]

# Hand-computed expected per-query values (see module docstring).
_NDCG_Q1 = 0.6934264036172708

EXPECTED_Q1 = {
    "precision@5": 0.4,
    "precision@10": 0.2,
    "precision@20": 0.1,
    "recall@5": 1.0,
    "recall@10": 1.0,
    "recall@20": 1.0,
    "mrr@5": 0.5,
    "mrr@10": 0.5,
    "mrr@20": 0.5,
    "ndcg@5": _NDCG_Q1,
    "ndcg@10": _NDCG_Q1,
    "ndcg@20": _NDCG_Q1,
}

EXPECTED_Q2 = {
    "precision@5": 0.2,
    "precision@10": 0.1,
    "precision@20": 0.05,
    "recall@5": 1.0,
    "recall@10": 1.0,
    "recall@20": 1.0,
    "mrr@5": 1.0,
    "mrr@10": 1.0,
    "mrr@20": 1.0,
    "ndcg@5": 1.0,
    "ndcg@10": 1.0,
    "ndcg@20": 1.0,
}

EXPECTED_MEAN = {
    "precision@5": 0.3,
    "precision@10": 0.15,
    "precision@20": 0.075,
    "recall@5": 1.0,
    "recall@10": 1.0,
    "recall@20": 1.0,
    "mrr@5": 0.75,
    "mrr@10": 0.75,
    "mrr@20": 0.75,
    "ndcg@5": (_NDCG_Q1 + 1.0) / 2,
    "ndcg@10": (_NDCG_Q1 + 1.0) / 2,
    "ndcg@20": (_NDCG_Q1 + 1.0) / 2,
}

KS = (5, 10, 20)


def _make_response(ranked_ids: list[str]) -> SearchResponse:
    """Build a SearchResponse whose results carry descending scores.

    Scores must be strictly descending so rank order is unambiguous when the
    ranx adapter rebuilds rank from score.
    """
    n = len(ranked_ids)
    items = [
        SearchResultItem(
            jellyfin_id=jid,
            title=f"Movie {jid}",
            overview=None,
            genres=[],
            year=None,
            score=float(n - idx),  # n, n-1, ... 1 — strictly descending
            poster_url=f"/poster/{jid}.jpg",
        )
        for idx, jid in enumerate(ranked_ids)
    ]
    return SearchResponse(
        status=SearchStatus.OK,
        results=items,
        total_candidates=n,
        filtered_count=0,
        query_time_ms=1,
    )


# --- 3.2 / 3.3: hand-rolled metrics match hand-computed expectations -----


@pytest.mark.parametrize("k", KS)
def test_handrolled_precision_at_k(k: int) -> None:
    assert precision_at_k(Q1_RELEVANT, Q1_RANKED, k) == pytest.approx(
        EXPECTED_Q1[f"precision@{k}"]
    )
    assert precision_at_k(Q2_RELEVANT, Q2_RANKED, k) == pytest.approx(
        EXPECTED_Q2[f"precision@{k}"]
    )


@pytest.mark.parametrize("k", KS)
def test_handrolled_recall_at_k(k: int) -> None:
    assert recall_at_k(Q1_RELEVANT, Q1_RANKED, k) == pytest.approx(
        EXPECTED_Q1[f"recall@{k}"]
    )
    assert recall_at_k(Q2_RELEVANT, Q2_RANKED, k) == pytest.approx(
        EXPECTED_Q2[f"recall@{k}"]
    )


@pytest.mark.parametrize("k", KS)
def test_handrolled_mrr(k: int) -> None:
    assert mrr(Q1_RELEVANT, Q1_RANKED, k) == pytest.approx(EXPECTED_Q1[f"mrr@{k}"])
    assert mrr(Q2_RELEVANT, Q2_RANKED, k) == pytest.approx(EXPECTED_Q2[f"mrr@{k}"])


@pytest.mark.parametrize("k", KS)
def test_handrolled_ndcg_at_k(k: int) -> None:
    assert ndcg_at_k(Q1_RELEVANT, Q1_RANKED, k) == pytest.approx(
        EXPECTED_Q1[f"ndcg@{k}"]
    )
    assert ndcg_at_k(Q2_RELEVANT, Q2_RANKED, k) == pytest.approx(
        EXPECTED_Q2[f"ndcg@{k}"]
    )


# --- Hand-rolled edge cases ----------------------------------------------


def test_zero_relevant_docs_yields_zero() -> None:
    """No relevant docs => recall/precision/mrr/ndcg are all 0.0 (not NaN)."""
    relevant: set[str] = set()
    ranked = ["d1", "d2", "d3"]
    assert precision_at_k(relevant, ranked, 5) == 0.0
    assert recall_at_k(relevant, ranked, 5) == 0.0
    assert mrr(relevant, ranked, 5) == 0.0
    assert ndcg_at_k(relevant, ranked, 5) == 0.0


def test_fewer_results_than_k() -> None:
    """precision still divides by k even when fewer than k results exist."""
    relevant = {"d1"}
    ranked = ["d1"]  # only one result, k=5
    assert precision_at_k(relevant, ranked, 5) == pytest.approx(1 / 5)
    assert recall_at_k(relevant, ranked, 5) == pytest.approx(1.0)
    assert mrr(relevant, ranked, 5) == pytest.approx(1.0)
    assert ndcg_at_k(relevant, ranked, 5) == pytest.approx(1.0)


def test_empty_ranked_list() -> None:
    relevant = {"d1"}
    ranked: list[str] = []
    assert precision_at_k(relevant, ranked, 5) == 0.0
    assert recall_at_k(relevant, ranked, 5) == 0.0
    assert mrr(relevant, ranked, 5) == 0.0
    assert ndcg_at_k(relevant, ranked, 5) == 0.0


def test_ndcg_perfect_ordering_is_one() -> None:
    relevant = {"d1", "d2"}
    ranked = ["d1", "d2", "d3", "d4"]
    assert ndcg_at_k(relevant, ranked, 5) == pytest.approx(1.0)


def test_ndcg_value_matches_manual_dcg() -> None:
    """Independent re-derivation of the q1 NDCG@5 from first principles."""
    dcg = 1 / math.log2(2 + 1) + 1 / math.log2(3 + 1)
    idcg = 1 / math.log2(1 + 1) + 1 / math.log2(2 + 1)
    expected = dcg / idcg
    assert ndcg_at_k(Q1_RELEVANT, Q1_RANKED, 5) == pytest.approx(expected)


# --- 3.2 / 3.3: ranx engine matches the same hand-computed expectations ---


def test_ranx_per_query_matches_expected() -> None:
    inputs = [
        QueryEvalInput(
            query_id="q1",
            relevant_ids=Q1_RELEVANT,
            ranked_ids=Q1_RANKED,
        ),
        QueryEvalInput(
            query_id="q2",
            relevant_ids=Q2_RELEVANT,
            ranked_ids=Q2_RANKED,
        ),
    ]
    result = compute_metrics(inputs, ks=KS)

    for metric, expected in EXPECTED_Q1.items():
        assert result.per_query["q1"][metric] == pytest.approx(expected), metric
    for metric, expected in EXPECTED_Q2.items():
        assert result.per_query["q2"][metric] == pytest.approx(expected), metric


def test_ranx_mean_matches_expected() -> None:
    inputs = [
        QueryEvalInput(
            query_id="q1",
            relevant_ids=Q1_RELEVANT,
            ranked_ids=Q1_RANKED,
        ),
        QueryEvalInput(
            query_id="q2",
            relevant_ids=Q2_RELEVANT,
            ranked_ids=Q2_RANKED,
        ),
    ]
    result = compute_metrics(inputs, ks=KS)
    for metric, expected in EXPECTED_MEAN.items():
        assert result.mean[metric] == pytest.approx(expected), metric


def test_handrolled_equals_ranx() -> None:
    """The two independent implementations must agree (the cross-check)."""
    cases = [
        (Q1_RELEVANT, Q1_RANKED, "q1"),
        (Q2_RELEVANT, Q2_RANKED, "q2"),
    ]
    inputs = [
        QueryEvalInput(query_id=qid, relevant_ids=rel, ranked_ids=ranked)
        for rel, ranked, qid in cases
    ]
    ranx_result = compute_metrics(inputs, ks=KS)

    for relevant, ranked, qid in cases:
        for k in KS:
            assert precision_at_k(relevant, ranked, k) == pytest.approx(
                ranx_result.per_query[qid][f"precision@{k}"]
            )
            assert recall_at_k(relevant, ranked, k) == pytest.approx(
                ranx_result.per_query[qid][f"recall@{k}"]
            )
            assert mrr(relevant, ranked, k) == pytest.approx(
                ranx_result.per_query[qid][f"mrr@{k}"]
            )
            assert ndcg_at_k(relevant, ranked, k) == pytest.approx(
                ranx_result.per_query[qid][f"ndcg@{k}"]
            )


# --- 3.4: adapter correctness --------------------------------------------


def test_to_run_preserves_rank_order_from_response() -> None:
    """SearchResponse -> Run must keep the items in their original rank order
    (highest score first), regardless of dict insertion order."""
    response = _make_response(Q1_RANKED)
    run = to_run(response, query_id="q1")
    # ranx Run stores per-query {doc_id: score}; recover rank order by score.
    scored = run.run["q1"]
    recovered_order = sorted(scored, key=lambda d: scored[d], reverse=True)
    assert recovered_order == Q1_RANKED


def test_to_run_accepts_raw_result_list() -> None:
    response = _make_response(Q2_RANKED)
    run = to_run(response.results, query_id="q2")
    scored = run.run["q2"]
    recovered_order = sorted(scored, key=lambda d: scored[d], reverse=True)
    assert recovered_order == Q2_RANKED


def test_to_run_scores_match_item_scores() -> None:
    response = _make_response(["x", "y", "z"])
    run = to_run(response, query_id="q1")
    scored = run.run["q1"]
    for item in response.results:
        assert scored[item.jellyfin_id] == pytest.approx(item.score)


def test_to_qrels_is_binary() -> None:
    qrels = to_qrels({"q1": Q1_RELEVANT, "q2": Q2_RELEVANT})
    assert qrels.qrels["q1"] == {"d1": 1, "d3": 1}
    assert qrels.qrels["q2"] == {"dA": 1}
    # every relevance grade is exactly 1 (binary)
    for per_query in qrels.qrels.values():
        assert all(grade == 1 for grade in per_query.values())


def test_aggregate_mean_equals_mean_of_per_query() -> None:
    """The reported mean must equal the arithmetic mean of per-query scores."""
    inputs = [
        QueryEvalInput(
            query_id="q1",
            relevant_ids=Q1_RELEVANT,
            ranked_ids=Q1_RANKED,
        ),
        QueryEvalInput(
            query_id="q2",
            relevant_ids=Q2_RELEVANT,
            ranked_ids=Q2_RANKED,
        ),
    ]
    result = compute_metrics(inputs, ks=KS)
    for metric in result.mean:
        per_query_values = [
            result.per_query["q1"][metric],
            result.per_query["q2"][metric],
        ]
        assert result.mean[metric] == pytest.approx(
            sum(per_query_values) / len(per_query_values)
        )
