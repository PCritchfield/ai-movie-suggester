"""Live retrieval eval harness — Spec 26, Tasks 4.0 / 5.0.

Runs every golden case through ``SearchService.search`` against the embedded
fixture library, scores with ranx, prints a per-query + aggregate report, and
gates against the versioned baseline.

Marked ``@pytest.mark.pipeline`` — skips in CI via the ``_check_ollama``
pre-flight; run via ``make eval-retrieval``. Regression gating is a **warning
by default**; set ``EVAL_STRICT=1`` to fail the test on a regression beyond
threshold. Cases that take the non-deterministic LLM rewrite path are reported
but excluded from the gate.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from tests.pipeline._eval_baseline import (
    BaselineRecord,
    VecMeta,
    append_record,
    load_baseline,
    save_baseline,
)
from tests.pipeline._eval_loader import load_golden_set
from tests.pipeline._eval_report import evaluate, format_report, gate
from tests.pipeline.conftest import EMBED_MODEL

if TYPE_CHECKING:
    from app.library.store import LibraryStore
    from app.search.service import SearchService
    from app.vectors.repository import SqliteVecRepository

_BASELINE_PATH = str(
    Path(__file__).resolve().parents[1] / "fixtures" / "eval_baseline.json"
)
_KS = (5, 10, 20)
_DIMENSIONS = 768


@pytest.mark.pipeline
async def test_retrieval_eval(
    eval_search_service: SearchService,
    embedded_library: SqliteVecRepository,
    pipeline_library_store: LibraryStore,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Score the golden set against the live pipeline and gate on regressions."""
    cases = load_golden_set()
    title_index = await pipeline_library_store.get_title_index()

    ranked: dict[str, list[str]] = {}
    for case in cases:
        response = await eval_search_service.search(
            case.query, limit=max(_KS), user_id="eval", token="eval-token"
        )
        ranked[case.query] = [r.jellyfin_id for r in response.results]

    person_index = eval_search_service.person_index
    assert person_index is not None
    home_countries = eval_search_service.home_countries

    outcome = evaluate(cases, ranked, title_index, person_index, home_countries, ks=_KS)

    current = VecMeta(
        model=EMBED_MODEL,
        template_version=await embedded_library.get_template_version(),
        dimensions=_DIMENSIONS,
    )
    gate_result = gate(outcome.gated_mean, _BASELINE_PATH, current)
    report = format_report(outcome, gate_result, ks=_KS)

    with capsys.disabled():
        print("\n" + report)

    # Seed/re-bless the committed baseline from THIS run's fixture-corpus scores
    # (the baseline must reflect the corpus the harness actually scores, so
    # seeding happens here, not via the script's separate library.db).
    if os.environ.get("EVAL_UPDATE_BASELINE") == "1":
        records = load_baseline(_BASELINE_PATH)
        today = datetime.now(UTC).date().isoformat()
        save_baseline(
            _BASELINE_PATH,
            append_record(
                records,
                BaselineRecord(vec_meta=current, scores=outcome.gated_mean, date=today),
            ),
        )
        with capsys.disabled():
            print(f"\nAppended baseline record ({today}) to {_BASELINE_PATH}")

    # Warn by default (the report shows regressions); fail only under EVAL_STRICT.
    if gate_result.regressions and os.environ.get("EVAL_STRICT") == "1":
        pytest.fail(
            f"EVAL_STRICT: {len(gate_result.regressions)} metric regression(s) "
            f"beyond threshold — see report above."
        )
