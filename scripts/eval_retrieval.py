#!/usr/bin/env python3
"""Run the Spec 26 retrieval eval against a live ``library.db`` + Ollama.

Builds a ``SearchService`` directly against the given SQLite library database
(read path) and a running Ollama, scores the golden set with ranx, prints a
per-query + aggregate report, and gates against the versioned baseline.

Shares the loader, scoring, report, and baseline modules with the pytest
harness (``tests/pipeline/test_retrieval_eval.py``) — no duplicated logic.

Usage:
    python scripts/eval_retrieval.py [--db data/library.db]
                                     [--ollama-host http://localhost:11434]
                                     [-k 5 10 20] [--strict] [--update-baseline]

Gating: warn by default (regressions printed); ``--strict`` exits non-zero on a
regression beyond threshold. ``--update-baseline`` appends a new versioned
record (never overwrites). Cases on the non-deterministic LLM rewrite path are
reported but excluded from the gate.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock

import httpx

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.library.store import LibraryStore  # noqa: E402
from app.ollama.chat_client import OllamaChatClient  # noqa: E402
from app.ollama.client import OllamaEmbeddingClient  # noqa: E402
from app.search.person_index import PersonIndex  # noqa: E402
from app.search.rewrite_cache import RewriteCache  # noqa: E402
from app.search.rewriter import QueryRewriter  # noqa: E402
from app.search.service import SearchService  # noqa: E402
from app.vectors.repository import SqliteVecRepository  # noqa: E402
from tests.pipeline._eval_baseline import (  # noqa: E402
    BaselineRecord,
    VecMeta,
    append_record,
    load_baseline,
    save_baseline,
)
from tests.pipeline._eval_loader import load_golden_set  # noqa: E402
from tests.pipeline._eval_report import evaluate, format_report, gate  # noqa: E402

_EMBED_MODEL = "nomic-embed-text"
_CHAT_MODEL = "llama3.1:8b"
_DIMENSIONS = 768
_BASELINE_PATH = str(BACKEND / "tests" / "fixtures" / "eval_baseline.json")


async def _amain(args: argparse.Namespace) -> int:
    cases = load_golden_set()
    print(f"Loaded {len(cases)} golden cases; scoring against {args.db}\n")

    store = LibraryStore(args.db)
    await store.init()
    repo = SqliteVecRepository(
        db_path=args.db,
        expected_model=_EMBED_MODEL,
        expected_dimensions=_DIMENSIONS,
    )
    await repo.init()

    timeout = httpx.Timeout(connect=5.0, read=300.0, write=10.0, pool=5.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as http:
            embed_client = OllamaEmbeddingClient(
                base_url=args.ollama_host, http_client=http, embed_model=_EMBED_MODEL
            )
            chat_client = OllamaChatClient(
                base_url=args.ollama_host, http_client=http, chat_model=_CHAT_MODEL
            )
            person_index = PersonIndex(names=await store.get_all_people_names())
            rewriter = QueryRewriter(
                chat_client=chat_client,
                cache=RewriteCache(max_entries=128, ttl_seconds=3600),
                timeout_seconds=10.0,
                max_output_chars=200,
            )
            permissions = AsyncMock()
            permissions.filter_permitted.side_effect = lambda *a, **_kw: a[2]
            reranker = None
            if args.rerank:
                from app.search.reranker import CrossEncoderReranker

                reranker = CrossEncoderReranker()
                print(
                    f"Cross-encoder reranking ON (pool={args.rerank_pool_size}, "
                    f"timeout={args.rerank_timeout_ms}ms)\n"
                )
            service = SearchService(
                ollama_client=embed_client,
                vec_repo=repo,
                permission_service=permissions,
                library_store=store,
                person_index=person_index,
                rewriter=rewriter,
                reranker=reranker,
                rerank_pool_size=args.rerank_pool_size,
                rerank_timeout_ms=args.rerank_timeout_ms,
            )

            ranked: dict[str, list[str]] = {}
            search_elapsed: list[float] = []
            for case in cases:
                _t0 = time.perf_counter()
                response = await service.search(
                    case.query, limit=max(args.ks), user_id="eval", token="eval-token"
                )
                search_elapsed.append(time.perf_counter() - _t0)
                ranked[case.query] = [r.jellyfin_id for r in response.results]

            if args.rerank and search_elapsed:
                ordered = sorted(search_elapsed)
                p50 = ordered[len(ordered) // 2]
                p95 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]
                # Informational only — NOT a gate. Whole-search wall-time
                # (rerank-dominated for filtered queries); grounds the
                # SEARCH_RERANK_TIMEOUT_MS default. Real-hardware p95 is Spec 30.
                print(
                    f"[informational] search wall-time incl. rerank over "
                    f"{len(search_elapsed)} queries: p50={p50 * 1000:.0f}ms "
                    f"p95={p95 * 1000:.0f}ms (not a gate)\n"
                )

            title_index = await store.get_title_index()
            outcome = evaluate(
                cases,
                ranked,
                title_index,
                person_index,
                service.home_countries,
                ks=tuple(args.ks),
            )
            current = VecMeta(
                model=_EMBED_MODEL,
                template_version=await repo.get_template_version(),
                dimensions=_DIMENSIONS,
            )
            gate_result = gate(outcome.gated_mean, _BASELINE_PATH, current)
            print(format_report(outcome, gate_result, ks=tuple(args.ks)))

            if args.update_baseline:
                records = load_baseline(_BASELINE_PATH)
                today = datetime.now(UTC).date().isoformat()
                updated = append_record(
                    records,
                    BaselineRecord(
                        vec_meta=current, scores=outcome.gated_mean, date=today
                    ),
                )
                save_baseline(_BASELINE_PATH, updated)
                print(f"\nAppended new baseline record ({today}) to {_BASELINE_PATH}")
    finally:
        await store.close()
        await repo.close()

    if gate_result.regressions and args.strict:
        print(f"\n--strict: {len(gate_result.regressions)} regression(s) — failing.")
        return 1
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the Spec 26 retrieval eval against a live library.db + Ollama."
    )
    parser.add_argument(
        "--db",
        default="data/library.db",
        help="Path to the library SQLite database (default: data/library.db).",
    )
    parser.add_argument(
        "--ollama-host",
        default="http://localhost:11434",
        help="Ollama base URL (default: http://localhost:11434).",
    )
    parser.add_argument(
        "-k",
        "--ks",
        type=int,
        nargs="+",
        default=[5, 10, 20],
        help="Metric cut-offs (default: 5 10 20).",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero if any metric regresses beyond threshold.",
    )
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="Append the current gated scores as a new baseline record.",
    )
    parser.add_argument(
        "--rerank",
        action="store_true",
        help="Engage the Spec 29 cross-encoder reranker (requires the 'rerank' "
        "extra). Off by default; matches the SEARCH_RERANK_ENABLED flag.",
    )
    parser.add_argument(
        "--rerank-pool-size",
        type=int,
        default=100,
        help="Top-N cosine candidates the reranker re-scores (default: 100).",
    )
    parser.add_argument(
        "--rerank-timeout-ms",
        type=int,
        default=5000,
        help="Per-query rerank deadline in ms (default: 5000).",
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(_amain(args)))


if __name__ == "__main__":
    main()
