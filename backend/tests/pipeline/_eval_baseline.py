"""Versioned baseline + regression gating for the Spec 26 eval harness.

Pure module (no live stack) — unit-tested in CI. The baseline is a *versioned
list* of records keyed by ``_vec_meta`` (embedding model + template version +
dimensions): the most recent record matching the current vec-meta is the
comparison point, so embedding/template experiments (#255) can be compared
across versions without destroying prior numbers. ``--update-baseline``
appends a record; it never blind-overwrites (council finding B).

Paraphrastic cases are excluded from the gated aggregate because the LLM
rewrite step is non-deterministic (Spec 26 Task 5.0); they are still reported,
just not gated.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

DEFAULT_THRESHOLD = 0.05
PARAPHRASTIC = "paraphrastic"


@dataclass(frozen=True, slots=True)
class VecMeta:
    """Embedding identity a baseline record was produced under."""

    model: str
    template_version: int | None
    dimensions: int

    def comparable_to(self, other: VecMeta) -> bool:
        """True only if model + dimensions match AND both carry a concrete
        (non-None) equal template version.

        A ``None`` template version means "unversioned" — it is never coerced
        to 0 and never treated as comparable, so a fresh/unstamped database
        cannot masquerade as matching a real baseline (Vimes finding).
        """
        if self.template_version is None or other.template_version is None:
            return False
        return (
            self.model == other.model
            and self.dimensions == other.dimensions
            and self.template_version == other.template_version
        )


@dataclass(frozen=True, slots=True)
class BaselineRecord:
    vec_meta: VecMeta
    scores: dict[str, float]
    date: str


@dataclass(frozen=True, slots=True)
class Regression:
    metric: str
    baseline: float
    current: float
    drop: float


def load_baseline(path: Path | str) -> list[BaselineRecord]:
    """Load the versioned baseline list (empty list if the file is absent)."""
    p = Path(path)
    if not p.exists():
        return []
    raw = json.loads(p.read_text())
    records: list[BaselineRecord] = []
    for row in raw:
        vm = row["vec_meta"]
        records.append(
            BaselineRecord(
                vec_meta=VecMeta(
                    model=vm["model"],
                    template_version=vm.get("template_version"),
                    dimensions=vm["dimensions"],
                ),
                scores=dict(row["scores"]),
                date=row["date"],
            )
        )
    return records


def save_baseline(path: Path | str, records: Sequence[BaselineRecord]) -> None:
    """Write the versioned baseline list as pretty JSON."""
    payload = [
        {"vec_meta": asdict(r.vec_meta), "scores": r.scores, "date": r.date}
        for r in records
    ]
    Path(path).write_text(json.dumps(payload, indent=2) + "\n")


def append_record(
    records: Sequence[BaselineRecord], new: BaselineRecord
) -> list[BaselineRecord]:
    """Return a new list with ``new`` appended — never mutates or overwrites."""
    return [*records, new]


def select_baseline(
    records: Sequence[BaselineRecord], current: VecMeta
) -> BaselineRecord | None:
    """Most recent record whose vec-meta is comparable to ``current``, else None.

    "Most recent" = last matching entry in list order (records are append-only,
    so later == newer). Returns ``None`` when nothing matches (including when
    template versions are ``None``); the caller then reports "not directly
    comparable" rather than a false regression.
    """
    match: BaselineRecord | None = None
    for r in records:
        if r.vec_meta.comparable_to(current):
            match = r
    return match


def find_regressions(
    current: Mapping[str, float],
    baseline: Mapping[str, float],
    threshold: float = DEFAULT_THRESHOLD,
) -> list[Regression]:
    """Metrics whose current score dropped more than ``threshold`` below baseline."""
    regressions: list[Regression] = []
    for metric, base_val in baseline.items():
        cur = current.get(metric)
        if cur is None:
            continue
        drop = base_val - cur
        if drop > threshold:
            regressions.append(
                Regression(metric=metric, baseline=base_val, current=cur, drop=drop)
            )
    return regressions


def aggregate_gated(
    rows: Iterable[tuple[str, Mapping[str, float]]],
    *,
    exclude_intents: tuple[str, ...] = (PARAPHRASTIC,),
) -> dict[str, float]:
    """Mean score per metric across rows, EXCLUDING the given intents.

    ``rows`` is an iterable of ``(intent, {metric: score})``. Paraphrastic
    cases are excluded from the gated aggregate (their LLM-rewrite wobble would
    flake the gate); they remain in the full report.
    """
    kept = [dict(scores) for intent, scores in rows if intent not in exclude_intents]
    if not kept:
        return {}
    metrics = list(kept[0].keys())
    return {m: sum(s[m] for s in kept) / len(kept) for m in metrics}
