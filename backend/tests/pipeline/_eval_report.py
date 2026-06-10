"""Orchestration + reporting for the Spec 26 retrieval eval (Tasks 4.0 / 5.0).

Pure post-search logic shared by the pytest harness (`test_retrieval_eval.py`)
and the CLI (`scripts/eval_retrieval.py`): resolve golden titles to ids, score
with `_eval_scoring`, decide the regression gate (excluding the
non-deterministic LLM-rewrite-path cases), compare to the versioned baseline,
and format the report. The async search loop itself lives in each caller — this
module is pure and unit-testable without a live stack.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.search.intent import detect_intent
from tests.pipeline._eval_baseline import (
    DEFAULT_THRESHOLD,
    find_regressions,
    load_baseline,
    mean_scores,
    select_baseline,
)
from tests.pipeline._eval_scoring import QueryEvalInput, compute_metrics

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from app.search.person_index import PersonIndex
    from tests.pipeline._eval_baseline import BaselineRecord, Regression, VecMeta
    from tests.pipeline._eval_loader import GoldenCase


def hits_rewrite_path(
    query: str,
    person_index: PersonIndex,
    home_countries: Sequence[str],
) -> bool:
    """True if the query takes the non-deterministic LLM rewrite path.

    Mirrors ``SearchService._route_query``: the rewriter runs only when the
    detected intent is paraphrastic AND carries no structured signal. Such
    cases are reported but excluded from the regression gate (Task 5.0 / 5.4).
    ``detect_intent`` is pure (regex/keyword), so this makes no LLM call.
    """
    intent = detect_intent(query, person_index, home_countries=list(home_countries))
    return intent.is_paraphrastic and not intent.has_signals()


@dataclass(frozen=True, slots=True)
class CaseOutcome:
    query: str
    intent: str
    gated: bool
    scores: dict[str, float]
    missed_titles: list[str]


@dataclass(frozen=True, slots=True)
class EvalOutcome:
    cases: list[CaseOutcome]
    full_mean: dict[str, float]
    gated_mean: dict[str, float]
    metrics: list[str]


@dataclass(frozen=True, slots=True)
class GateResult:
    comparable: bool
    regressions: list[Regression]
    baseline: BaselineRecord | None = None


def evaluate(
    cases: Sequence[GoldenCase],
    ranked_ids_by_query: Mapping[str, list[str]],
    title_index: Mapping[str, list[str]],
    person_index: PersonIndex,
    home_countries: Sequence[str],
    ks: Sequence[int] = (5, 10, 20),
) -> EvalOutcome:
    """Score every golden case against its retrieved ranking.

    ``ranked_ids_by_query`` maps each case's query to the jellyfin_ids the
    pipeline returned, in rank order. Title resolution failures raise loudly
    (the loader contract), so a typo or ambiguous label cannot silently skew
    the scores.
    """
    inputs: list[QueryEvalInput] = []
    relevant_by_query: dict[str, set[str]] = {}
    unresolved: list[str] = []
    for case in cases:
        try:
            relevant = set(case.resolve_relevant_ids(title_index))
        except ValueError as exc:
            # Collect every unresolved title so one run reports the full picture
            # (not just the first) — distinguishes a single typo from a corpus/
            # sync membership problem.
            unresolved.append(str(exc))
            relevant = set()
        relevant_by_query[case.query] = relevant
        inputs.append(
            QueryEvalInput(
                query_id=case.query,
                relevant_ids=relevant,
                ranked_ids=list(ranked_ids_by_query.get(case.query, [])),
            )
        )
    if unresolved:
        joined = "\n  - ".join(unresolved)
        msg = (
            f"{len(unresolved)} golden title(s) did not resolve against the "
            f"corpus ({len(title_index)} distinct titles):\n  - {joined}"
        )
        raise ValueError(msg)

    result = compute_metrics(inputs, ks=tuple(ks))
    top_k = max(ks)

    outcomes: list[CaseOutcome] = []
    gated_scores: list[dict[str, float]] = []
    for case in cases:
        gated = not hits_rewrite_path(case.query, person_index, home_countries)
        scores = result.per_query.get(case.query, {})
        ranked_top = set(ranked_ids_by_query.get(case.query, [])[:top_k])
        relevant = relevant_by_query[case.query]
        # Map a relevant id back to a title for the "missed" report.
        id_to_title = {
            ids[0]: title
            for title, ids in title_index.items()
            if len(ids) == 1 and ids[0] in relevant
        }
        missed = sorted(id_to_title[rid] for rid in relevant if rid not in ranked_top)
        outcomes.append(
            CaseOutcome(
                query=case.query,
                intent=case.intent,
                gated=gated,
                scores=scores,
                missed_titles=missed,
            )
        )
        if gated:
            gated_scores.append(scores)

    return EvalOutcome(
        cases=outcomes,
        full_mean=result.mean,
        gated_mean=mean_scores(gated_scores),
        metrics=list(result.mean.keys()),
    )


def gate(
    gated_mean: Mapping[str, float],
    baseline_path: str,
    current: VecMeta,
    threshold: float = DEFAULT_THRESHOLD,
) -> GateResult:
    """Compare the gated aggregate to the matching-version baseline record."""
    records = load_baseline(baseline_path)
    base = select_baseline(records, current)
    if base is None:
        return GateResult(comparable=False, regressions=[], baseline=None)
    regressions = find_regressions(gated_mean, base.scores, threshold)
    return GateResult(comparable=True, regressions=regressions, baseline=base)


def format_report(
    outcome: EvalOutcome,
    gate_result: GateResult,
    ks: Sequence[int] = (5, 10, 20),
) -> str:
    """Render a reviewer-friendly per-query + aggregate report."""
    primary_k = 10 if 10 in ks else max(ks)
    cols = [
        f"precision@{primary_k}",
        f"recall@{primary_k}",
        f"mrr@{primary_k}",
        f"ndcg@{primary_k}",
    ]
    lines: list[str] = []
    lines.append(f"Retrieval eval — per query (metrics @{primary_k})")
    lines.append("-" * 96)
    header = (
        f"{'intent':12} {'gate':6} "
        + " ".join(f"{c.split('@')[0]:>9}" for c in cols)
        + "  query"
    )
    lines.append(header)
    for c in outcome.cases:
        cells = " ".join(f"{c.scores.get(col, 0.0):>9.3f}" for col in cols)
        tag = "gated" if c.gated else "UNGATED"
        lines.append(f"{c.intent:12} {tag:6} {cells}  {c.query}")
        if c.missed_titles:
            lines.append(f"{'':28}   missed: {', '.join(c.missed_titles)}")
    lines.append("-" * 96)
    lines.append("Aggregate (all cases):   " + _fmt_means(outcome.full_mean, cols))
    lines.append("Aggregate (gated only):  " + _fmt_means(outcome.gated_mean, cols))
    lines.append("")
    lines.append(_format_gate(gate_result))
    return "\n".join(lines)


def _fmt_means(mean: Mapping[str, float], cols: Sequence[str]) -> str:
    return "  ".join(f"{col}={mean.get(col, 0.0):.3f}" for col in cols)


def _format_gate(gate_result: GateResult) -> str:
    if not gate_result.comparable:
        return (
            "GATE: no baseline record matches the current _vec_meta "
            "(model/template/dims) — scores not directly comparable; "
            "not flagging a regression."
        )
    if not gate_result.regressions:
        return "GATE: no regressions beyond threshold. OK."
    out = ["GATE: REGRESSION(S) detected:"]
    for r in gate_result.regressions:
        out.append(
            f"  {r.metric}: {r.baseline:.3f} -> {r.current:.3f} (drop {r.drop:.3f})"
        )
    return "\n".join(out)
