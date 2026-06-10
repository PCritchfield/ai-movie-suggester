"""Loader for the Spec 26 retrieval-eval golden query set.

Shared by the pipeline pytest harness (``test_retrieval_eval.py``) and the
CLI script (``scripts/eval_retrieval.py``) so the fixture format stays
single-sourced — mirrors the Spec 24 ``_router_eval_loader.py`` pattern.

The golden set is the *answer key*: for each query, the set of genuinely
relevant titles (plus intended distractors that the corpus must also
contain). Titles are resolved to ``jellyfin_id`` at load time against a
title index, and a title matching zero or more than one item fails loudly —
an ambiguous or missing label must never resolve to an arbitrary match, or
the answer key rots silently.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

_FIXTURE_PATH = (
    Path(__file__).resolve().parents[1] / "fixtures" / "eval_golden_set.json"
)

# Intent tags a golden case may carry. ``paraphrastic`` cases exercise the
# non-deterministic LLM rewrite path and are reported-but-ungated downstream
# (Spec 26 Task 5.0).
ALLOWED_INTENTS = frozenset(
    {"genre", "person", "year", "country", "paraphrastic", "semantic"}
)


@dataclass(frozen=True, slots=True)
class GoldenCase:
    """One golden query — the answer key for a single retrieval query."""

    query: str
    intent: str
    relevant_titles: list[str]
    distractors: list[str] = field(default_factory=list)
    notes: str = ""

    def resolve_relevant_ids(self, title_index: Mapping[str, list[str]]) -> list[str]:
        """Resolve ``relevant_titles`` to ``jellyfin_id``s via a title index.

        Raises ``ValueError`` if any title matches zero or more than one item.
        """
        return resolve_titles(self.relevant_titles, title_index, query=self.query)


def resolve_titles(
    titles: list[str],
    title_index: Mapping[str, list[str]],
    *,
    query: str = "",
) -> list[str]:
    """Resolve titles to ids, failing loudly on a zero- or multi-match title.

    ``title_index`` maps a title to the list of ``jellyfin_id``s carrying that
    title (see ``LibraryStore.get_title_index``). Titles are not unique
    (remakes, same-name films), so a title resolving to != 1 id is an error,
    never a pick-the-first.
    """
    resolved: list[str] = []
    for title in titles:
        matches = title_index.get(title, [])
        if len(matches) != 1:
            kind = "unknown" if not matches else f"ambiguous ({len(matches)} matches)"
            ctx = f" for query {query!r}" if query else ""
            msg = (
                f"golden title {title!r}{ctx} is {kind}; every labelled title "
                f"must resolve to exactly one library item"
            )
            raise ValueError(msg)
        resolved.append(matches[0])
    return resolved


def load_golden_set(path: Path | str | None = None) -> list[GoldenCase]:
    """Parse the golden-set fixture into typed cases.

    Raises ``ValueError`` if any case is missing a required field, declares an
    unknown ``intent``, or has an empty ``relevant_titles``.
    """
    src = Path(path) if path is not None else _FIXTURE_PATH
    with src.open() as fh:
        raw = json.load(fh)

    cases: list[GoldenCase] = []
    for i, row in enumerate(raw):
        for required in ("query", "intent", "relevant_titles"):
            if required not in row:
                msg = f"case[{i}] missing required field {required!r}"
                raise ValueError(msg)
        if row["intent"] not in ALLOWED_INTENTS:
            msg = (
                f"case[{i}] has unknown intent={row['intent']!r}; "
                f"allowed: {sorted(ALLOWED_INTENTS)}"
            )
            raise ValueError(msg)
        if not row["relevant_titles"]:
            msg = f"case[{i}] ({row['query']!r}) has empty relevant_titles"
            raise ValueError(msg)
        cases.append(
            GoldenCase(
                query=row["query"],
                intent=row["intent"],
                relevant_titles=list(row["relevant_titles"]),
                distractors=list(row.get("distractors", [])),
                notes=row.get("notes", ""),
            )
        )
    return cases
