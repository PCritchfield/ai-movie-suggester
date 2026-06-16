"""Tests + experiment driver for the Spec 28 (#253) cross-encoder rerank spike.

Two layers:

* **Unit (plain ``pytest`` / ``make test``)** — the pure rerank helper
  (pair-build + score-and-sort) with a deterministic stub scorer, and an
  import-isolation guard asserting no ``sentence_transformers``/``torch`` import
  leaks under ``backend/app/``. These need NO heavy deps and NO Ollama.

* **Experiment (``@pytest.mark.pipeline`` / ``make spike-rerank``)** — seeds the
  182 NFO fixtures via local Ollama (no Jellyfin/Docker), runs the three-way
  quality + latency-by-pool-size experiment offline, prints the sanitized
  report, and sanity-checks the reconstructed pool against the live
  ``SearchService`` for two queries (audit FLAG).
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import httpx
import pytest

from app.config import Settings
from tests.pipeline.conftest import EMBED_MODEL, OLLAMA_HOST
from tests.pipeline.rerank_spike import (
    build_rerank_pairs,
    make_cross_encoder_scorer,
    rerank,
    run_experiment,
)
from tests.pipeline.seed_fixtures import build_seeded_stack, load_fixture_rows

if TYPE_CHECKING:
    from collections.abc import Sequence

_APP_DIR = Path(__file__).resolve().parents[2] / "app"
# 64 hex chars: ≥32 long, >2 distinct chars, no blocklist word — passes the
# SESSION_SECRET validator. Not a real secret (this stack faces no network).
_SPIKE_SECRET = "0123456789abcdef" * 4


# --------------------------------------------------------------------------- #
# Unit: pure rerank helper (Task 1.3 / 1.4) — no heavy deps, no Ollama
# --------------------------------------------------------------------------- #
def _stub_scorer(score_by_doc: dict[str, float]):
    def scorer(pairs: Sequence[tuple[str, str]]) -> list[float]:
        return [score_by_doc[doc] for _q, doc in pairs]

    return scorer


def test_build_rerank_pairs_uses_query_and_doc() -> None:
    pairs = build_rerank_pairs("funny aliens", [("id1", "docA"), ("id2", "docB")])
    assert pairs == [("funny aliens", "docA"), ("funny aliens", "docB")]


def test_rerank_orders_by_descending_score() -> None:
    candidates = [("a", "docA"), ("b", "docB"), ("c", "docC")]
    scorer = _stub_scorer({"docA": 0.1, "docB": 0.9, "docC": 0.5})
    # Highest score first: B (0.9), C (0.5), A (0.1).
    assert rerank("q", candidates, scorer) == ["b", "c", "a"]


def test_rerank_is_stable_on_ties() -> None:
    candidates = [("a", "docA"), ("b", "docB"), ("c", "docC")]
    scorer = _stub_scorer({"docA": 0.5, "docB": 0.5, "docC": 0.5})
    # All equal — input (cosine) order preserved, matching _rerank_by_genre.
    assert rerank("q", candidates, scorer) == ["a", "b", "c"]


def test_rerank_empty_pool_returns_empty() -> None:
    assert rerank("q", [], _stub_scorer({})) == []


def test_no_heavy_imports_under_app() -> None:
    """Guard: torch / sentence_transformers must NEVER be imported under app/.

    The spike's heavy deps live in the ``spike`` extra and load lazily inside
    ``make_cross_encoder_scorer`` — production code stays torch-free.
    """
    offenders: list[str] = []
    for py in _APP_DIR.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith(("import ", "from ")) and (
                "sentence_transformers" in stripped or "torch" in stripped
            ):
                offenders.append(f"{py.relative_to(_APP_DIR.parent)}: {stripped}")
    assert not offenders, "heavy-dep import leaked under app/:\n" + "\n".join(offenders)


# --------------------------------------------------------------------------- #
# Experiment driver (Task 1.5–1.8) — pipeline-marked
# --------------------------------------------------------------------------- #
def _spike_settings() -> Settings:
    # Cached DB path persists across runs so re-embedding the 182 fixtures is
    # paid once per machine, not once per invocation.
    db_dir = Path(tempfile.gettempdir()) / "spike_rerank_253"
    db_dir.mkdir(parents=True, exist_ok=True)
    return Settings(
        jellyfin_url="http://localhost:8096",  # unused — no Jellyfin calls
        session_secret=_SPIKE_SECRET,
        ollama_host=OLLAMA_HOST,
        ollama_embed_model=EMBED_MODEL,
        library_db_path=str(db_dir / "library.db"),
        log_level="debug",
    )


@pytest.mark.pipeline
async def test_rerank_spike_experiment(capsys: pytest.CaptureFixture[str]) -> None:
    """Seed offline, run the three-way + latency experiment, print the report."""
    settings = _spike_settings()
    expected_corpus = len(load_fixture_rows())

    timeout = httpx.Timeout(connect=5.0, read=300.0, write=10.0, pool=5.0)
    async with httpx.AsyncClient(timeout=timeout) as http:
        store, vec_repo, ollama_client = await build_seeded_stack(settings, http)
        try:
            assert await store.count() >= expected_corpus
            assert await vec_repo.count() >= expected_corpus

            scorer = make_cross_encoder_scorer()
            result = await run_experiment(store, vec_repo, ollama_client, scorer)

            from tests.pipeline.rerank_spike import format_report

            with capsys.disabled():
                print("\n" + format_report(result))

            # Every golden case scored under all three orderings.
            assert len(result.cosine.cases) == len(result.cross_encoder.cases)
            assert all(size > 0 for size in result.pool_sizes)
            assert result.latencies and result.small_latencies
            # Ran offline (post one-time fetch).
            assert result.offline_env["HF_HUB_OFFLINE"] == "1"

            await _sanity_check_pool(store, vec_repo, ollama_client, capsys)
        finally:
            await store.close()
            await vec_repo.close()


async def _sanity_check_pool(
    store, vec_repo, ollama_client, capsys: pytest.CaptureFixture[str]
) -> None:
    """Audit FLAG: cross-check the replica pool vs. the live SearchService.

    Builds a SearchService with a permit-all permission mock (the only Jellyfin
    touch) and compares its top-k output to our genre-heuristic ordering for one
    semantic + one genre query. Best-effort: divergence is printed as a confound,
    not failed, per the SDD-2 audit guidance.
    """
    from app.search.person_index import PersonIndex
    from app.search.service import SearchService
    from tests.pipeline._eval_loader import GoldenCase
    from tests.pipeline.rerank_spike import (
        order_genre_heuristic,
        reconstruct_pool,
    )

    permissions = AsyncMock()
    permissions.filter_permitted.side_effect = lambda *args, **_kw: args[2]
    service = SearchService(
        ollama_client=ollama_client,
        vec_repo=vec_repo,
        permission_service=permissions,
        library_store=store,
        person_index=PersonIndex(names=await store.get_all_people_names()),
    )

    probes = [
        GoldenCase(
            query="a sci-fi comedy", intent="genre", relevant_titles=["Galaxy Quest"]
        ),
        GoldenCase(
            query="a movie about loneliness",
            intent="semantic",
            relevant_titles=["Lost in Translation"],
        ),
    ]
    notes: list[str] = []
    for case in probes:
        response = await service.search(
            case.query, limit=10, user_id="spike", token="spike-token"
        )
        service_top = [r.jellyfin_id for r in response.results]
        pool = await reconstruct_pool(case, store, vec_repo, ollama_client)
        replica_top = order_genre_heuristic(pool)[:10]
        overlap = len(set(service_top) & set(replica_top))
        notes.append(
            f"  [{case.intent}] service_top={len(service_top)} "
            f"replica∩service={overlap}/{len(service_top)} (pool={pool.size})"
        )
    with capsys.disabled():
        print("\nPool-reconstruction sanity check (replica vs live SearchService):")
        print("\n".join(notes))
