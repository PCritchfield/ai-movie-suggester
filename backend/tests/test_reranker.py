"""Unit tests for the cross-encoder reranker module (Spec 29 / #276).

All tests here run under plain ``pytest`` / ``make test`` with **no** ``rerank``
extra installed (no torch): the pure reorder logic is exercised with a
deterministic stub scorer, and an import-isolation guard asserts no heavy import
leaks under ``backend/app/``. The heavy ``CrossEncoderReranker`` path is exercised
by the pipeline eval (task 5.x), not here.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path
from typing import TYPE_CHECKING

from app.search.reranker import RerankerProtocol, reorder_by_scores

if TYPE_CHECKING:
    from collections.abc import Sequence

_APP_DIR = Path(__file__).resolve().parents[1] / "app"


# --------------------------------------------------------------------------- #
# Pure reorder logic — deterministic stub scorer, no heavy deps
# --------------------------------------------------------------------------- #
def _stub_scorer(score_by_doc: dict[str, float]):
    def scorer(pairs: Sequence[tuple[str, str]]) -> list[float]:
        return [score_by_doc[doc] for _q, doc in pairs]

    return scorer


def test_reorder_by_descending_score() -> None:
    candidates = [("a", "docA"), ("b", "docB"), ("c", "docC")]
    scorer = _stub_scorer({"docA": 0.1, "docB": 0.9, "docC": 0.5})
    # Highest score first: B (0.9), C (0.5), A (0.1).
    assert reorder_by_scores("q", candidates, scorer) == ["b", "c", "a"]


def test_reorder_is_stable_on_ties() -> None:
    candidates = [("a", "docA"), ("b", "docB"), ("c", "docC")]
    scorer = _stub_scorer({"docA": 0.5, "docB": 0.5, "docC": 0.5})
    # All equal — input (cosine) order preserved, matching _rerank_by_genre.
    assert reorder_by_scores("q", candidates, scorer) == ["a", "b", "c"]


def test_reorder_empty_pool_returns_empty() -> None:
    assert reorder_by_scores("q", [], _stub_scorer({})) == []


def test_reorder_preserves_ids_not_docs() -> None:
    """The returned values are jellyfin_ids (tuple[0]), never document text."""
    candidates = [("id-1", "doc one"), ("id-2", "doc two")]
    scorer = _stub_scorer({"doc one": 0.2, "doc two": 0.8})
    assert reorder_by_scores("q", candidates, scorer) == ["id-2", "id-1"]


def test_cross_encoder_reranker_satisfies_protocol() -> None:
    """CrossEncoderReranker is a structural RerankerProtocol (no torch needed
    to import the class — only to call ``.rerank``)."""
    from app.search.reranker import CrossEncoderReranker

    reranker: RerankerProtocol = CrossEncoderReranker()
    assert hasattr(reranker, "rerank")


# --------------------------------------------------------------------------- #
# Offline / telemetry env guards — set at module import, before any HF import
# --------------------------------------------------------------------------- #
def test_offline_and_telemetry_env_guards_set_on_import() -> None:
    """Importing the reranker module sets the HF offline + telemetry-off env
    vars in code, so a missing env var cannot silently re-enable outbound
    fetches or telemetry (Angua)."""
    import app.search.reranker  # noqa: F401 — import is the thing under test

    assert os.environ["HF_HUB_OFFLINE"] == "1"
    assert os.environ["TRANSFORMERS_OFFLINE"] == "1"
    # Telemetry is disabled UNCONDITIONALLY (plain assignment, not setdefault).
    assert os.environ["HF_HUB_DISABLE_TELEMETRY"] == "1"


# --------------------------------------------------------------------------- #
# Import-isolation guard — torch must NEVER load at module import under app/
# --------------------------------------------------------------------------- #
_HEAVY_MODULES = ("torch", "sentence_transformers")


def _module_load_heavy_imports(tree: ast.Module) -> list[str]:
    """Return heavy imports that execute at MODULE IMPORT time.

    Walks module- and class-level statements but does NOT descend into function
    or method bodies — a lazy ``import`` inside a function (e.g.
    ``CrossEncoderReranker._ensure_scorer``) runs only when called, not at
    import, so it is correctly *not* flagged. This is the precise version of the
    "no torch at import" rule; the naive line-scan it replaces could not tell a
    lazy import from a top-level one.
    """
    found: list[str] = []

    def names(node: ast.Import | ast.ImportFrom) -> list[str]:
        if isinstance(node, ast.Import):
            return [a.name for a in node.names]
        return [node.module] if node.module else []

    def visit(node: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                continue  # function body is lazy — not executed at import
            if isinstance(child, ast.Import | ast.ImportFrom):
                for name in names(child):
                    root = name.split(".")[0]
                    if root in _HEAVY_MODULES:
                        found.append(name)
            visit(child)

    visit(tree)
    return found


def test_no_heavy_imports_under_app() -> None:
    """Guard: ``torch`` / ``sentence_transformers`` must NEVER be imported at
    module load under ``backend/app/``.

    The reranker's heavy deps live in the opt-in ``rerank`` extra and load
    lazily inside ``CrossEncoderReranker`` — production code (and CI, which
    lacks the extra) stays torch-free. This is the CI-visible copy of the guard;
    the spike's copy in ``tests/pipeline/test_rerank_spike.py`` remains and only
    runs under ``make spike-rerank``.
    """
    offenders: list[str] = []
    for py in _APP_DIR.rglob("*.py"):
        tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        for imp in _module_load_heavy_imports(tree):
            offenders.append(f"{py.relative_to(_APP_DIR.parent)}: import {imp}")
    assert not offenders, "heavy-dep import leaked under app/:\n" + "\n".join(offenders)
