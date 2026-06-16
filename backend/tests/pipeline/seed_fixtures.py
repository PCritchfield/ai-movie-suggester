"""Jellyfin-free seed for the Spec 28 (#253) cross-encoder rerank spike.

Parses the synthetic NFO fixtures (Spec 22 — 182 movies + 18 series under
``tests/fixtures/media``) directly into ``LibraryItemRow``s and embeds them via
**local Ollama**, with no Jellyfin and no Docker. The retrieval/rerank path has
no hard Jellyfin dependency — only the permission filter does, and the spike
mocks that permit-all (see ``rerank_spike.py``).

Fidelity: the NFO -> ``LibraryItemRow`` mapping mirrors
``app.sync.engine.to_library_row`` (same field semantics, same
``compute_content_hash`` over a content_hash="" seed row), and embedding goes
through the production ``EmbeddingWorker`` + ``build_sections`` composite-text
template — so seeded vectors are representative of the canonical corpus. The
golden set resolves by **title**, so synthesized ``jellyfin_id``s are fine.

This module is dev/test-only and lives under ``tests/`` — it imports nothing
that ``backend/app/`` shouldn't.
"""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import time
from pathlib import Path
from typing import TYPE_CHECKING
from xml.etree import ElementTree as ET

from app.embedding.worker import EmbeddingWorker
from app.library.country_codes import name_to_iso
from app.library.hashing import compute_content_hash
from app.library.models import LibraryItemRow
from app.library.store import LibraryStore
from app.ollama.client import OllamaEmbeddingClient
from app.vectors.repository import SqliteVecRepository

if TYPE_CHECKING:
    import httpx

    from app.config import Settings

# backend/tests/pipeline/seed_fixtures.py -> repo root is parents[3].
_REPO_ROOT = Path(__file__).resolve().parents[3]
MEDIA_DIR = _REPO_ROOT / "tests" / "fixtures" / "media"
# Corpus = movies (movie.nfo) + series (tvshow.nfo). The golden set scores both
# (e.g. "Babylon 5", "Midsomer Murders"), matching what a real Jellyfin sync of
# these fixtures indexes — so the seed must include both trees.
_NFO_GLOBS = ("movies/*/movie.nfo", "shows/*/tvshow.nfo")


def synthesize_id(title: str, year: int | None) -> str:
    """Deterministic stable id for a fixture (no Jellyfin to assign one).

    Stable across runs so re-seeding the same corpus produces the same ids;
    unique across the distinct (title, year) pairs in the corpus.
    """
    digest = hashlib.sha1(f"{title}|{year}".encode()).hexdigest()
    return f"spike-{digest[:16]}"


def _texts(movie: ET.Element, tag: str) -> list[str]:
    """All non-empty text values for a repeated child tag."""
    out: list[str] = []
    for el in movie.findall(tag):
        if el.text and el.text.strip():
            out.append(el.text.strip())
    return out


def _text(movie: ET.Element, tag: str) -> str | None:
    el = movie.find(tag)
    if el is not None and el.text and el.text.strip():
        return el.text.strip()
    return None


def parse_nfo(nfo_path: Path) -> LibraryItemRow:
    """Parse one ``movie.nfo`` into a ``LibraryItemRow``.

    Mirrors ``app.sync.engine.to_library_row``: actor names -> ``people``,
    ``<director>`` -> ``directors``, country names -> ISO alpha-2 via
    ``name_to_iso`` (skip-and-drop unmappable), and ``content_hash`` recomputed
    over a content_hash="" seed row (the engine's exact pattern). The NFO schema
    carries no writers/composers/tags/official_rating, so those stay empty —
    matching what a Jellyfin scan of these same files would produce.
    """
    movie = ET.parse(nfo_path).getroot()

    title = _text(movie, "title") or nfo_path.parent.name
    year_text = _text(movie, "year")
    production_year = int(year_text) if year_text and year_text.isdigit() else None

    rating_text = _text(movie, "rating")
    community_rating = float(rating_text) if rating_text else None

    runtime_text = _text(movie, "runtime")
    runtime_minutes = (
        int(runtime_text) if runtime_text and runtime_text.isdigit() else None
    )

    people = [
        name
        for actor in movie.findall("actor")
        if (el := actor.find("name")) is not None
        and el.text
        and (name := el.text.strip())
    ]

    production_countries = [
        iso
        for country in _texts(movie, "country")
        if (iso := name_to_iso(country)) is not None
    ]

    now = int(time.time())
    row = LibraryItemRow(
        jellyfin_id=synthesize_id(title, production_year),
        title=title,
        overview=_text(movie, "plot"),
        production_year=production_year,
        genres=_texts(movie, "genre"),
        tags=[],
        studios=_texts(movie, "studio"),
        community_rating=community_rating,
        people=people,
        content_hash="",
        synced_at=now,
        runtime_minutes=runtime_minutes,
        directors=_texts(movie, "director"),
        writers=[],
        composers=[],
        official_rating=None,
        production_countries=production_countries,
        country_synced_at=now,
    )
    return dataclasses.replace(row, content_hash=compute_content_hash(row))


def load_fixture_rows(media_dir: Path = MEDIA_DIR) -> list[LibraryItemRow]:
    """Parse every movie + series NFO under ``media_dir`` into rows."""
    nfos = sorted(p for glob in _NFO_GLOBS for p in media_dir.glob(glob))
    if not nfos:
        msg = f"no movie/tvshow NFO fixtures found under {media_dir}"
        raise FileNotFoundError(msg)
    return [parse_nfo(p) for p in nfos]


async def seed_embeddings(
    store: LibraryStore,
    vec_repo: SqliteVecRepository,
    ollama_client: OllamaEmbeddingClient,
    settings: Settings,
    rows: list[LibraryItemRow],
    *,
    max_cycles: int = 200,
) -> int:
    """Upsert ``rows`` and drain the embedding queue via Ollama (idempotent).

    Returns the number of embedded vectors. Uses the production
    ``EmbeddingWorker`` so the composite-text template and vec0 upsert match
    the real pipeline exactly. Cheap to call on a warm cache: nothing is
    re-embedded unless an item is new or the composite-text template changed.
    """
    upserted = await store.upsert_many(rows)

    worker = EmbeddingWorker(
        library_store=store,
        vec_repo=vec_repo,
        ollama_client=ollama_client,
        settings=settings,
        sync_event=asyncio.Event(),
        pause_counter=None,
    )

    # Re-enqueue everything if the composite-text template version changed
    # (mirrors production startup) and stamp the version — process_cycle alone
    # never does this, so without it a warm cache would silently score stale
    # vectors after a template bump.
    await worker.check_template_version()
    # Enqueue when anything is new or content-changed (upsert_many does NOT
    # auto-enqueue updated ids — that's the sync engine's job in prod, so a
    # fixture edit would otherwise leave a stale embedding) or the cache is
    # incomplete. Fully-warm + unchanged → skip (created==updated==0, count==N).
    if upserted.created or upserted.updated or await vec_repo.count() < len(rows):
        await store.enqueue_for_embedding([r.jellyfin_id for r in rows])

    cycles = 0
    while await store.count_pending_embeddings() > 0 and cycles < max_cycles:
        await worker.process_cycle()
        cycles += 1

    pending = await store.count_pending_embeddings()
    if pending > 0:
        msg = (
            f"embedding queue did not drain after {cycles} cycles "
            f"({pending} pending) — is `ollama serve` up with nomic-embed-text?"
        )
        raise RuntimeError(msg)
    return await vec_repo.count()


async def build_seeded_stack(
    settings: Settings,
    http_client: httpx.AsyncClient,
    *,
    media_dir: Path = MEDIA_DIR,
) -> tuple[LibraryStore, SqliteVecRepository, OllamaEmbeddingClient]:
    """Construct + initialize store/repo/client and seed the corpus.

    Idempotent: ``seed_embeddings`` self-skips when the cached ``library_db_path``
    is already fully embedded at the current template version, and re-embeds only
    new or template-stale items. Caller owns closing the returned store + repo.
    """
    store = LibraryStore(settings.library_db_path)
    await store.init()
    vec_repo = SqliteVecRepository(
        settings.library_db_path,
        expected_model=settings.ollama_embed_model,
        expected_dimensions=settings.ollama_embed_dimensions,
    )
    await vec_repo.init()
    ollama_client = OllamaEmbeddingClient(
        base_url=settings.ollama_host,
        http_client=http_client,
        embed_model=settings.ollama_embed_model,
    )

    rows = load_fixture_rows(media_dir)
    await seed_embeddings(store, vec_repo, ollama_client, settings, rows)

    return store, vec_repo, ollama_client
