"""Content hash computation for library items.

The content hash is a SHA-256 digest of a deterministic string built from
item fields. This drives incremental sync — if the hash changes, the item
needs re-embedding.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.library.models import LibraryItemRow


def compute_content_hash(item: LibraryItemRow) -> str:
    """Compute a deterministic SHA-256 hash from a library item's fields.

    # TODO: Replace with text_builder from Spec 07
    # When the text_builder module lands (app/ollama/text_builder.py),
    # replace this placeholder with hashing the composite text output.
    # A template change will cause all hashes to differ, triggering a
    # full re-embed — this is intentional.

    Field ordering (deterministic):
    1. title
    2. overview (or empty string)
    3. production_year (or empty string)
    4. genres (sorted JSON array)
    5. tags (sorted JSON array)
    6. studios (sorted JSON array)
    7. community_rating (or empty string)
    8. people (sorted JSON array)

    All JSON arrays are sorted to ensure determinism regardless of input order.
    """
    parts = [
        item.title,
        item.overview or "",
        str(item.production_year) if item.production_year is not None else "",
        json.dumps(sorted(item.genres)),
        json.dumps(sorted(item.tags)),
        json.dumps(sorted(item.studios)),
        str(item.community_rating) if item.community_rating is not None else "",
        json.dumps(sorted(item.people)),
    ]
    composite = "|".join(parts)
    return hashlib.sha256(composite.encode()).hexdigest()
