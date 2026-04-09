"""Shared utility functions."""

from __future__ import annotations

import hashlib


def hash_for_log(value: str, length: int = 8) -> str:
    """Return truncated SHA-256 hex digest for safe logging."""
    return hashlib.sha256(value.encode()).hexdigest()[:length]
