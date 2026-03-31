"""Composite text builder — canonical re-export from app.library.

The implementation lives in app.ollama.text_builder (Spec 07).
This module provides a library-domain import path per Spec 08.
"""

from app.ollama.text_builder import (
    TEMPLATE_VERSION,
    CompositeTextResult,
    build_composite_text,
    build_sections,
)

__all__ = [
    "TEMPLATE_VERSION",
    "CompositeTextResult",
    "build_composite_text",
    "build_sections",
]
