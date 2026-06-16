"""Offline cross-encoder rerank experiment — Spec 28 (#253).

Reconstructs the pre-truncation, pre-genre-rerank permitted candidate pool over
the seeded fixture corpus, then scores THREE orderings of each pool through the
Spec 26 eval harness (``_eval_report.evaluate``):

  1. pure-cosine      — the bi-encoder ordering as-retrieved
  2. genre-heuristic   — the current ``SearchService._rerank_by_genre`` tiering
  3. cross-encoder     — ``sentence-transformers`` CrossEncoder re-scoring

…and measures rerank latency as a function of candidate-pool size. Runs fully
offline (local Ollama for query embedding + a local CrossEncoder); no Jellyfin,
no Docker, no outbound calls.

**No file under ``backend/app/`` is modified or imported-for-heavy-deps** — the
``sentence_transformers`` import is lazy (inside ``make_cross_encoder_scorer``),
and ``test_rerank_spike.py`` guards against any heavy import leaking into
``app/``.

This is the deliverable's measurement engine; ``test_rerank_spike.py`` drives it
under ``-m pipeline`` and prints the sanitized (metrics-only) report.
"""

from __future__ import annotations

import os

# Offline-by-default Hugging Face: these MUST be set before huggingface_hub is
# imported (the CrossEncoder import is lazy, well after this module loads).
# ``setdefault`` so the ONE-TIME weight fetch can override with HF_HUB_OFFLINE=0;
# every subsequent scoring run inherits offline=1 and proves local-only serving.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"

import time  # noqa: E402 — env vars above must be set before any HF import
from dataclasses import dataclass  # noqa: E402
from typing import TYPE_CHECKING  # noqa: E402

from app.ollama.text_builder import build_sections  # noqa: E402
from app.search.genre_keywords import detect_query_genres  # noqa: E402
from app.search.models import QUERY_PREFIX  # noqa: E402
from app.search.person_index import PersonIndex  # noqa: E402
from app.search.service import SearchService  # noqa: E402
from tests.pipeline._eval_loader import GoldenCase, load_golden_set  # noqa: E402
from tests.pipeline._eval_report import EvalOutcome, evaluate  # noqa: E402

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from app.library.models import LibraryItemRow
    from app.library.store import LibraryStore
    from app.ollama.client import OllamaEmbeddingClient
    from app.vectors.repository import SqliteVecRepository

    Scorer = Callable[[Sequence[tuple[str, str]]], Sequence[float]]
    PermitFn = Callable[[list[str]], list[str]]

# Pinned cross-encoder. ms-marco-MiniLM-L-6-v2 is the canonical small reranker
# (~80MB, CPU-friendly). MODEL_REVISION pins the *weights* by Hub commit SHA —
# the axis that actually fixes the scores — and is recorded in the findings.
MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"
# Pinned Hub commit SHA (resolved at the one-time fetch in Task 1.8) — fixes the
# exact weights so the scores below are reproducible.
MODEL_REVISION: str | None = "c5ee24cb16019beea0893ab7796b1df96625c6b8"

# Small-pool data point for the latency-vs-pool-size curve: the pure-semantic
# regime reranks only limit*overfetch candidates (5 * 3 = 15 in prod defaults),
# vs the whole-corpus filtered regime (≈ corpus size). Captures both ends.
SMALL_POOL_SIZE = 15

_HOME_COUNTRIES = ("US",)  # Settings.foreign_film_home_countries default


# --------------------------------------------------------------------------- #
# Pure rerank helper (Task 1.3/1.4) — pair-build + score-and-sort, no heavy deps
# --------------------------------------------------------------------------- #
def build_rerank_pairs(
    query: str, candidates: Sequence[tuple[str, str]]
) -> list[tuple[str, str]]:
    """Build ``(query, document)`` pairs for cross-encoder scoring."""
    return [(query, doc) for _, doc in candidates]


def rerank(
    query: str,
    candidates: Sequence[tuple[str, str]],
    scorer: Scorer,
) -> list[str]:
    """Reorder ``candidates`` by descending cross-encoder score.

    ``candidates`` is a sequence of ``(jellyfin_id, document_text)``. Pure: all
    model work is delegated to ``scorer`` (a real CrossEncoder in the experiment,
    a deterministic stub in the unit test). Stable on ties — equal scores keep
    their input (cosine) order, matching ``_rerank_by_genre`` semantics.
    """
    if not candidates:
        return []
    scores = list(scorer(build_rerank_pairs(query, candidates)))
    order = sorted(range(len(candidates)), key=lambda i: scores[i], reverse=True)
    return [candidates[i][0] for i in order]


def composite_text(row: LibraryItemRow) -> str:
    """Cross-encoder document side: the SAME composite template used for
    embeddings (``build_sections``), minus the ``search_document:`` prefix.

    That prefix is a nomic-embed-text asymmetric-retrieval artifact — meaningless
    to a ms-marco cross-encoder, which was trained on natural query/passage text.
    Using the identical section template otherwise keeps the comparison honest:
    the cross-encoder sees the same content the bi-encoder embedded.
    """
    return build_sections(
        title=row.title,
        overview=row.overview,
        genres=row.genres,
        production_year=row.production_year,
        runtime_minutes=row.runtime_minutes,
        cast=row.people,
        directors=row.directors,
        writers=row.writers,
        composers=row.composers,
        studios=row.studios,
        tags=row.tags,
    )


def make_cross_encoder_scorer(
    model_name: str = MODEL_NAME, revision: str | None = MODEL_REVISION
) -> Scorer:
    """Build a scorer backed by a local CrossEncoder (heavy import, lazy).

    Imported here so ``sentence_transformers``/``torch`` never load at module
    import time — keeping plain ``pytest``/CI (which lacks the ``spike`` extra)
    able to collect this module and run the pure-helper unit test.
    """
    from sentence_transformers import CrossEncoder

    model = CrossEncoder(model_name, revision=revision)

    def scorer(pairs: Sequence[tuple[str, str]]) -> list[float]:
        return [float(s) for s in model.predict(list(pairs))]

    return scorer


# --------------------------------------------------------------------------- #
# Pool reconstruction (Task 1.5)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class Pool:
    """The pre-truncation, permitted, pre-genre-rerank candidate pool."""

    query: str
    intent: str
    ids: list[str]  # cosine-ordered (vec0 distance ASC)
    rows: dict[str, LibraryItemRow]

    @property
    def size(self) -> int:
        return len(self.ids)


def _identity_permit(ids: list[str]) -> list[str]:
    """Permit-all permission filter — the only Jellyfin touch, mocked off."""
    return ids


async def reconstruct_pool(
    case: GoldenCase,
    store: LibraryStore,
    vec_repo: SqliteVecRepository,
    ollama_client: OllamaEmbeddingClient,
    permit: PermitFn = _identity_permit,
) -> Pool:
    """Rebuild one query's candidate pool by replicating ``SearchService``'s
    retrieval-up-to-permission-filter stages — WITHOUT calling ``search()``.

    Uses a raised fetch window (whole corpus) so the pool is the worst-case
    filtered regime; the pure-semantic top-k is simply a prefix of this
    cosine-ordered list. Mirrors ``service.py:154`` (query prefix + embed),
    ``:177-182`` (fetch window) and the permission filter, stopping *before*
    ``_rerank_by_genre`` + ``[:limit]`` (``:227-228``).
    """
    embedding = await ollama_client.embed(QUERY_PREFIX + case.query)
    corpus_size = await vec_repo.count()
    candidates = await vec_repo.search(embedding.vector, limit=corpus_size)
    permitted = permit([c.jellyfin_id for c in candidates])
    rows = {r.jellyfin_id: r for r in await store.get_many(permitted)}
    # Keep only ids whose metadata resolved (mirrors service.py's item_map join).
    ordered = [jid for jid in permitted if jid in rows]
    return Pool(query=case.query, intent=case.intent, ids=ordered, rows=rows)


# --------------------------------------------------------------------------- #
# The three orderings (Task 1.6)
# --------------------------------------------------------------------------- #
def order_pure_cosine(pool: Pool) -> list[str]:
    """As-retrieved cosine order (the bi-encoder baseline)."""
    return list(pool.ids)


def order_genre_heuristic(pool: Pool) -> list[str]:
    """Current production reranker: genre-tier bucket sort.

    Calls the live ``SearchService._rerank_by_genre`` static method over the same
    pool, with genres detected the same way ``service.py:226`` does for the
    no-structured-intent path (``detect_query_genres``).
    """
    groups = detect_query_genres(pool.query)
    return SearchService._rerank_by_genre(groups, pool.ids, pool.rows)  # noqa: SLF001


def order_cross_encoder(pool: Pool, scorer: Scorer) -> list[str]:
    """Cross-encoder re-scoring of the pool."""
    candidates = [(jid, composite_text(pool.rows[jid])) for jid in pool.ids]
    return rerank(pool.query, candidates, scorer)


# --------------------------------------------------------------------------- #
# Experiment orchestration (Tasks 1.6 + 1.7)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class LatencySample:
    query_index: int  # keyed by index, NEVER query text (privacy)
    pool_size: int
    seconds: float


@dataclass(frozen=True, slots=True)
class ExperimentResult:
    cosine: EvalOutcome
    heuristic: EvalOutcome
    cross_encoder: EvalOutcome
    latencies: list[LatencySample]  # large (whole-corpus) pool
    small_latencies: list[LatencySample]  # small (semantic) pool
    pool_sizes: list[int]
    metrics: list[str]
    offline_env: dict[str, str | None]


async def run_experiment(
    store: LibraryStore,
    vec_repo: SqliteVecRepository,
    ollama_client: OllamaEmbeddingClient,
    scorer: Scorer,
    *,
    permit: PermitFn = _identity_permit,
    ks: tuple[int, ...] = (5, 10, 20),
) -> ExperimentResult:
    """Reconstruct pools, score the three orderings, and time the reranks."""
    cases = load_golden_set()
    title_index = await store.get_title_index()
    person_index = PersonIndex(names=await store.get_all_people_names())

    pools = [
        await reconstruct_pool(case, store, vec_repo, ollama_client, permit)
        for case in cases
    ]

    cosine_ranked: dict[str, list[str]] = {}
    heuristic_ranked: dict[str, list[str]] = {}
    cross_ranked: dict[str, list[str]] = {}
    latencies: list[LatencySample] = []
    small_latencies: list[LatencySample] = []

    for idx, pool in enumerate(pools):
        cosine_ranked[pool.query] = order_pure_cosine(pool)
        heuristic_ranked[pool.query] = order_genre_heuristic(pool)

        # Large (whole-corpus) pool — the worst-case latency point.
        start = time.perf_counter()
        cross_ranked[pool.query] = order_cross_encoder(pool, scorer)
        latencies.append(LatencySample(idx, pool.size, time.perf_counter() - start))

        # Small (pure-semantic) pool — top limit*overfetch of the same pool.
        small = Pool(pool.query, pool.intent, pool.ids[:SMALL_POOL_SIZE], pool.rows)
        start = time.perf_counter()
        order_cross_encoder(small, scorer)
        small_latencies.append(
            LatencySample(idx, small.size, time.perf_counter() - start)
        )

    cosine = evaluate(
        cases, cosine_ranked, title_index, person_index, _HOME_COUNTRIES, ks=ks
    )
    heuristic = evaluate(
        cases, heuristic_ranked, title_index, person_index, _HOME_COUNTRIES, ks=ks
    )
    cross = evaluate(
        cases, cross_ranked, title_index, person_index, _HOME_COUNTRIES, ks=ks
    )

    return ExperimentResult(
        cosine=cosine,
        heuristic=heuristic,
        cross_encoder=cross,
        latencies=latencies,
        small_latencies=small_latencies,
        pool_sizes=[p.size for p in pools],
        metrics=cosine.metrics,
        offline_env={
            "HF_HUB_OFFLINE": os.environ.get("HF_HUB_OFFLINE"),
            "TRANSFORMERS_OFFLINE": os.environ.get("TRANSFORMERS_OFFLINE"),
            "HF_HUB_DISABLE_TELEMETRY": os.environ.get("HF_HUB_DISABLE_TELEMETRY"),
        },
    )


# --------------------------------------------------------------------------- #
# Reporting (metrics-only — never prints query text)
# --------------------------------------------------------------------------- #
def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = (len(ordered) - 1) * pct
    lo = int(rank)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (rank - lo)


def _report_metrics(ks: tuple[int, ...]) -> list[str]:
    cols: list[str] = []
    for k in ks:
        cols.append(f"ndcg@{k}")
    for k in ks:
        cols.append(f"recall@{k}")
    cols.append(f"mrr@{max(ks)}")
    return cols


def format_report(result: ExperimentResult, ks: tuple[int, ...] = (5, 10, 20)) -> str:
    cols = _report_metrics(ks)
    systems = [
        ("pure-cosine", result.cosine),
        ("genre-heuristic", result.heuristic),
        ("cross-encoder", result.cross_encoder),
    ]
    lines: list[str] = []
    lines.append("Cross-encoder rerank spike — three-way quality (gated-mean)")
    lines.append("=" * 92)
    header = f"{'system':18}" + "".join(f"{c:>12}" for c in cols)
    lines.append(header)
    for name, outcome in systems:
        row = f"{name:18}" + "".join(
            f"{outcome.gated_mean.get(c, 0.0):>12.3f}" for c in cols
        )
        lines.append(row)
    lines.append("-" * 92)

    primary = f"ndcg@{10 if 10 in ks else max(ks)}"
    base = result.heuristic.gated_mean.get(primary, 0.0)
    ce = result.cross_encoder.gated_mean.get(primary, 0.0)
    lines.append(
        f"Δ {primary} (cross-encoder − genre-heuristic): {ce - base:+.3f} "
        f"(heuristic={base:.3f}, cross-encoder={ce:.3f})"
    )
    lines.append("")

    lines.append("Rerank latency by candidate-pool size")
    lines.append("=" * 92)
    lines.append(f"{'pool regime':22}{'pool size':>12}{'p50 (s)':>12}{'p95 (s)':>12}")
    for label, samples in (
        ("small (semantic)", result.small_latencies),
        ("large (filtered)", result.latencies),
    ):
        secs = [s.seconds for s in samples]
        sizes = [s.pool_size for s in samples]
        size_repr = (
            f"{min(sizes)}-{max(sizes)}"
            if sizes and min(sizes) != max(sizes)
            else str(sizes[0] if sizes else 0)
        )
        lines.append(
            f"{label:22}{size_repr:>12}"
            f"{_percentile(secs, 0.50):>12.3f}{_percentile(secs, 0.95):>12.3f}"
        )
    lines.append("")
    lines.append(f"Offline mode at scoring time: {result.offline_env}")
    lines.append(f"Model: {MODEL_NAME} (revision={MODEL_REVISION})")
    return "\n".join(lines)
