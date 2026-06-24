"""Cross-encoder reranker (Spec 29 / #276).

Re-scores the top cosine candidates with a local cross-encoder
(``cross-encoder/ms-marco-MiniLM-L-6-v2``) for sharply better ranking than the
genre heuristic (spike #253: NDCG@10 0.338 -> 0.591). The heavy
``sentence_transformers`` / ``torch`` dependency lives in the opt-in ``rerank``
extra and is imported **lazily** inside :class:`CrossEncoderReranker` — so this
module (and every other module under ``app/``) stays torch-free at import time,
and the flag-OFF path never pays the import cost. ``test_no_heavy_imports_under_app``
guards the boundary.

Seam discipline: the public contract is :class:`RerankerProtocol` —
``rerank(query, [(jellyfin_id, document_text)]) -> reordered ids``. The inference
backend (torch now, ONNX in Spec 30) and the model **load timing** are internal
details of :class:`CrossEncoderReranker`; they do not appear in the Protocol or in
the way callers construct/inject the reranker, so Spec 30 can swap either without
touching the seam.
"""

from __future__ import annotations

import os
import threading

# Offline-by-default Hugging Face: these MUST be set before huggingface_hub is
# imported. The CrossEncoder import is lazy (inside ``_ensure_scorer``), well
# after this module loads, so setting them here guarantees they win.
# ``setdefault`` for the offline flags so a deliberate ONE-TIME weight fetch can
# override with HF_HUB_OFFLINE=0; every normal run inherits offline=1 and proves
# local-only serving. Telemetry is disabled UNCONDITIONALLY (plain assignment,
# not setdefault) — it must never be re-enabled by an outer environment.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"

from typing import TYPE_CHECKING, Protocol, runtime_checkable  # noqa: E402

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    # A scorer maps ``(query, document)`` pairs to relevance scores. The real
    # implementation is a CrossEncoder; unit tests inject a deterministic stub.
    Scorer = Callable[[Sequence[tuple[str, str]]], Sequence[float]]

# Pinned cross-encoder. ms-marco-MiniLM-L-6-v2 is the canonical small reranker
# (~80MB, CPU-friendly). MODEL_REVISION pins the *weights* by Hub commit SHA —
# the axis that fixes the scores — matching the merged spike (#253).
MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"
MODEL_REVISION = "c5ee24cb16019beea0893ab7796b1df96625c6b8"


def reorder_by_scores(
    query: str,
    candidates: Sequence[tuple[str, str]],
    scorer: Scorer,
) -> list[str]:
    """Reorder ``candidates`` by descending cross-encoder score.

    ``candidates`` is a sequence of ``(jellyfin_id, document_text)``. Pure: all
    model work is delegated to ``scorer`` (a real CrossEncoder in production, a
    deterministic stub in unit tests). Stable on ties — equal scores keep their
    input (cosine) order, matching ``SearchService._rerank_by_genre`` semantics.
    Returns the reordered ``jellyfin_id``s only (never document text).
    """
    if not candidates:
        return []
    pairs = [(query, doc) for _id, doc in candidates]
    scores = list(scorer(pairs))
    order = sorted(range(len(candidates)), key=lambda i: scores[i], reverse=True)
    return [candidates[i][0] for i in order]


@runtime_checkable
class RerankerProtocol(Protocol):
    """Reorders ``(jellyfin_id, document_text)`` candidates by relevance.

    The only contract callers (SearchService) depend on. Implementations own
    their model/backend/load-timing internally.
    """

    def rerank(
        self, query: str, candidates: Sequence[tuple[str, str]]
    ) -> list[str]: ...


class CrossEncoderReranker:
    """A :class:`RerankerProtocol` backed by a local ``sentence_transformers``
    CrossEncoder.

    The model is imported and loaded **lazily** on first ``rerank`` call and
    cached for reuse. Load timing is an internal detail (Spec 30 may move it to
    eager-at-startup) and is intentionally not exposed through the Protocol.
    """

    def __init__(
        self, model_name: str = MODEL_NAME, revision: str = MODEL_REVISION
    ) -> None:
        self._model_name = model_name
        self._revision = revision
        self._scorer: Scorer | None = None
        # Guards lazy init: ``_ensure_scorer`` runs inside ``asyncio.to_thread``
        # workers, so concurrent first-use requests could otherwise each load a
        # separate model. Double-checked locking loads exactly one. (Serialising
        # ``model.predict`` itself — a throughput question under concurrency — is
        # deferred to Spec 30 alongside the real-hardware latency measurement.)
        self._lock = threading.Lock()

    def _ensure_scorer(self) -> Scorer:
        """Build (once) and cache the CrossEncoder-backed scorer.

        The ``sentence_transformers`` import is here — never at module load — so
        importing this module stays torch-free. ``automodel_args`` forwards
        ``use_safetensors=True`` to ``from_pretrained``: it forces the
        safetensors weight file (no pickle deserialization surface) and fails
        loud if the pinned revision has none — the desired behaviour, not a
        silent fallback.
        """
        if self._scorer is None:
            with self._lock:
                if self._scorer is None:  # double-checked under the lock
                    from sentence_transformers import CrossEncoder

                    model = CrossEncoder(
                        self._model_name,
                        revision=self._revision,
                        automodel_args={"use_safetensors": True},
                    )

                    def scorer(pairs: Sequence[tuple[str, str]]) -> list[float]:
                        return [float(s) for s in model.predict(list(pairs))]

                    self._scorer = scorer
        return self._scorer

    def rerank(self, query: str, candidates: Sequence[tuple[str, str]]) -> list[str]:
        """Reorder candidates by cross-encoder relevance (loads the model on
        first call)."""
        return reorder_by_scores(query, candidates, self._ensure_scorer())
