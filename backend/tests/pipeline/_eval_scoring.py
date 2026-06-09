"""Retrieval eval scoring engine (Spec 26, Task 3.0).

Pure, dependency-light IR-metric scoring for retrieval eval. Two parallel
implementations live here:

1. **Hand-rolled metrics** (``precision_at_k``, ``recall_at_k``, ``mrr``,
   ``ndcg_at_k``) over ``(relevant_ids: set[str], ranked_ids: list[str])``.
   Binary relevance. This is the learning artifact and the readable reference.

2. **A ``ranx`` adapter** (``to_qrels``, ``to_run``, ``compute_metrics``).
   ``ranx`` is the correctness oracle — a published, tested IR-metrics library.
   The unit tests assert hand-rolled == ranx == hand-computed expectations.

``ranx`` is a dev/test-only dependency. It MUST NEVER be imported anywhere
under ``backend/app/`` (enforced by ``tests/test_app_no_ranx_import.py``).
Importing it here, under ``backend/tests/``, is fine.

Metric definitions (binary relevance, rank starts at 1)
-------------------------------------------------------
* precision@k = (# relevant docs in the top-k) / k
* recall@k    = (# relevant docs in the top-k) / (total # relevant docs)
* MRR (cut at k) = 1 / rank-of-first-relevant-doc within the top-k, else 0
* NDCG@k = DCG@k / IDCG@k, where
      DCG@k  = sum over ranks i (1..k) of rel_i / log2(i + 1)
      IDCG@k = DCG of the ideal ordering (all relevant docs first)
  with binary gain (rel_i in {0, 1}).

All metrics return 0.0 (never NaN) when there are no relevant docs or no
results, so aggregates stay well-defined.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

import numpy as np
from ranx import Qrels, Run, evaluate

from app.search.models import SearchResponse, SearchResultItem

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from numpy.typing import NDArray

# --- Hand-rolled metrics --------------------------------------------------


def precision_at_k(
    relevant_ids: set[str],
    ranked_ids: Sequence[str],
    k: int,
) -> float:
    """Fraction of the top-k results that are relevant.

    Divides by ``k`` (not by the number of results), so a short result list is
    penalised — the standard precision@k convention.
    """
    if k <= 0:
        return 0.0
    top_k = ranked_ids[:k]
    hits = sum(1 for doc_id in top_k if doc_id in relevant_ids)
    return hits / k


def recall_at_k(
    relevant_ids: set[str],
    ranked_ids: Sequence[str],
    k: int,
) -> float:
    """Fraction of all relevant docs that appear in the top-k results."""
    if not relevant_ids or k <= 0:
        return 0.0
    top_k = ranked_ids[:k]
    hits = sum(1 for doc_id in top_k if doc_id in relevant_ids)
    return hits / len(relevant_ids)


def mrr(
    relevant_ids: set[str],
    ranked_ids: Sequence[str],
    k: int,
) -> float:
    """Reciprocal rank of the first relevant doc within the top-k (else 0)."""
    if not relevant_ids or k <= 0:
        return 0.0
    for index, doc_id in enumerate(ranked_ids[:k]):
        if doc_id in relevant_ids:
            return 1.0 / (index + 1)  # rank is 1-based
    return 0.0


def ndcg_at_k(
    relevant_ids: set[str],
    ranked_ids: Sequence[str],
    k: int,
) -> float:
    """Normalised discounted cumulative gain at k (binary relevance).

    Gain is 1 for a relevant doc, 0 otherwise; discount is ``1/log2(rank+1)``.
    The ideal DCG places every relevant doc (capped at k) at the top ranks.
    """
    if not relevant_ids or k <= 0:
        return 0.0

    dcg = 0.0
    for index, doc_id in enumerate(ranked_ids[:k]):
        if doc_id in relevant_ids:
            rank = index + 1  # 1-based
            dcg += 1.0 / math.log2(rank + 1)

    ideal_hits = min(len(relevant_ids), k)
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    if idcg == 0.0:
        return 0.0
    return dcg / idcg


# --- ranx adapter ---------------------------------------------------------


@dataclass(frozen=True, slots=True)
class QueryEvalInput:
    """One query's golden relevant set and the system's ranked output.

    ``ranked_ids`` is in rank order (best first). When building a ranx Run we
    synthesise strictly descending scores from this order so rank is preserved
    regardless of the original similarity scores.
    """

    query_id: str
    relevant_ids: set[str]
    ranked_ids: list[str]


@dataclass(frozen=True, slots=True)
class MetricResult:
    """Per-query and mean-aggregate scores keyed by ranx metric name."""

    per_query: dict[str, dict[str, float]]
    mean: dict[str, float]
    metrics: list[str] = field(default_factory=list)


def metric_names(ks: Iterable[int]) -> list[str]:
    """Build the ranx metric-name strings for the given cut-offs.

    Verified against ranx 0.3.21: the exact strings are ``precision@k``,
    ``recall@k``, ``mrr@k`` and ``ndcg@k``.
    """
    names: list[str] = []
    for k in ks:
        names.extend(
            (
                f"precision@{k}",
                f"recall@{k}",
                f"mrr@{k}",
                f"ndcg@{k}",
            )
        )
    return names


def to_qrels(golden: Mapping[str, set[str]]) -> Qrels:
    """Convert ``{query_id: relevant_id_set}`` into a binary ranx ``Qrels``.

    Every relevant doc gets relevance grade 1 (binary relevance).
    """
    mapping: dict[str, dict[str, int]] = {
        query_id: {doc_id: 1 for doc_id in relevant_ids}
        for query_id, relevant_ids in golden.items()
    }
    return Qrels(mapping)


def to_run(
    response_or_results: SearchResponse | Sequence[SearchResultItem],
    query_id: str,
) -> Run:
    """Convert a ``SearchResponse`` (or its result list) into a ranx ``Run``.

    Rank order is preserved by synthesising strictly descending scores from the
    result order (rank 1 gets the highest score). ranx ranks by score, so this
    guarantees the original retrieval order is honoured even if the upstream
    similarity scores were equal or non-monotonic.
    """
    if isinstance(response_or_results, SearchResponse):
        results: Sequence[SearchResultItem] = response_or_results.results
    else:
        results = response_or_results

    n = len(results)
    scored: dict[str, float] = {
        item.jellyfin_id: float(n - index) for index, item in enumerate(results)
    }
    return Run({query_id: scored})


def compute_metrics(
    per_query_inputs: Sequence[QueryEvalInput],
    ks: Sequence[int] = (5, 10, 20),
) -> MetricResult:
    """Score a batch of queries with ranx, returning per-query + mean scores.

    Uses ``to_run``'s rank-preserving score synthesis so ranx honours each
    query's ranked order. Returns both the per-query breakdown and the mean
    aggregate, keyed by the exact ranx metric-name strings.
    """
    metrics = metric_names(ks)

    golden: dict[str, set[str]] = {
        item.query_id: item.relevant_ids for item in per_query_inputs
    }
    qrels = to_qrels(golden)

    combined_run: dict[str, dict[str, float]] = {}
    for item in per_query_inputs:
        n = len(item.ranked_ids)
        combined_run[item.query_id] = {
            doc_id: float(n - index) for index, doc_id in enumerate(item.ranked_ids)
        }
    run = Run(combined_run)

    # Per-query scores: evaluate once per metric with return_mean=False, which
    # yields per-query scores ordered by the qrels' query iteration order.
    # ``np.atleast_1d`` normalises the single-query scalar case to a 1-D array.
    query_order = list(qrels.qrels.keys())
    per_query: dict[str, dict[str, float]] = {qid: {} for qid in query_order}
    mean: dict[str, float] = {}
    for metric in metrics:
        # With return_mean=False and a single metric, ranx returns a per-query
        # ndarray (the dev stubs over-narrow this to Dict | float — cast it).
        per_q_scores = cast(
            "NDArray[Any]",
            evaluate(qrels, run, metric, return_mean=False),
        )
        values = [float(v) for v in np.atleast_1d(per_q_scores)]
        for qid, value in zip(query_order, values, strict=True):
            per_query[qid][metric] = value
        mean[metric] = sum(values) / len(values) if values else 0.0

    return MetricResult(per_query=per_query, mean=mean, metrics=metrics)
