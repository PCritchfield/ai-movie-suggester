"""Pre-processing layer for user input before it enters the chat pipeline.

Strips control characters that could break SSE framing or confuse the LLM tokenizer.
Does NOT pattern-match semantic injection phrases — that's handled by prompt
delineation and observability logging.
"""

from __future__ import annotations

__all__ = ["sanitize_user_input"]

# Build translation table: map control chars to None (delete them)
# Preserve \x0A (newline) — legitimate in multi-sentence queries
_CONTROL_CHAR_TABLE = str.maketrans(
    {i: None for i in range(0x00, 0x20) if i != 0x0A}  # \x00-\x1F except \n
    | {0x7F: None}  # DEL
)


def sanitize_user_input(text: str) -> str:
    """Strip ASCII control characters from user input, preserving newlines."""
    return text.translate(_CONTROL_CHAR_TABLE)
