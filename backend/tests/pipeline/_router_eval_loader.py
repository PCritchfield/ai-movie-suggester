"""Shared loader for the Spec 24 query-router eval cases.

Both the pipeline pytest harness and the CLI script in
``scripts/eval_router.py`` consume this loader so the fixture format
stays single-sourced.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

_FIXTURE_PATH = (
    Path(__file__).resolve().parents[1] / "fixtures" / "query_router_cases.json"
)

# Recognised values for ``expected_path``. Keep aligned with the spec's
# six router strategies.
ALLOWED_PATHS = frozenset(
    {"keyword", "person", "year", "rating", "rewrite", "semantic"}
)


@dataclass(frozen=True, slots=True)
class QueryRouterCase:
    """Typed representation of a fixture row."""

    query: str
    expected_path: str
    expected_genres: list[str] = field(default_factory=list)
    must_include_titles: list[str] = field(default_factory=list)
    must_exclude_titles: list[str] = field(default_factory=list)
    notes: str = ""


def load_cases(path: Path | str | None = None) -> list[QueryRouterCase]:
    """Parse the fixture JSON into typed cases.

    Raises ``ValueError`` if any case is missing a required field or
    declares an unknown ``expected_path``.
    """
    src = Path(path) if path is not None else _FIXTURE_PATH
    with src.open() as fh:
        raw = json.load(fh)

    cases: list[QueryRouterCase] = []
    for i, row in enumerate(raw):
        for required in ("query", "expected_path"):
            if required not in row:
                msg = f"case[{i}] missing required field '{required}'"
                raise ValueError(msg)
        if row["expected_path"] not in ALLOWED_PATHS:
            msg = (
                f"case[{i}] has unknown expected_path={row['expected_path']!r}; "
                f"allowed: {sorted(ALLOWED_PATHS)}"
            )
            raise ValueError(msg)
        cases.append(
            QueryRouterCase(
                query=row["query"],
                expected_path=row["expected_path"],
                expected_genres=list(row.get("expected_genres", [])),
                must_include_titles=list(row.get("must_include_titles", [])),
                must_exclude_titles=list(row.get("must_exclude_titles", [])),
                notes=row.get("notes", ""),
            )
        )
    return cases
