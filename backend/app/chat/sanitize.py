"""Pre-processing layer for user input before it enters the chat pipeline.

Strips control characters that could break SSE framing or confuse the LLM
tokenizer, and provides observability for suspected injection attempts via
pattern detection (log-only, never blocks).
"""

from __future__ import annotations

import re

from app.chat.prompts import TAG_CONTEXT, TAG_HISTORY, TAG_QUERY, TAG_SYSTEM

__all__ = ["sanitize_user_input", "check_injection_patterns"]

# Build translation table: map control chars to None (delete them)
# Preserve \x0A (newline) — legitimate in multi-sentence queries
_CONTROL_CHAR_TABLE = str.maketrans(
    {i: None for i in range(0x00, 0x20) if i != 0x0A}  # \x00-\x1F except \n
    | {0x7F: None}  # DEL
)


def sanitize_user_input(text: str) -> str:
    """Strip ASCII control characters from user input, preserving newlines."""
    return text.translate(_CONTROL_CHAR_TABLE)


# ---------------------------------------------------------------------------
# Injection pattern observability (log-only — never blocks requests)
# ---------------------------------------------------------------------------

INJECTION_PATTERNS: dict[str, re.Pattern[str]] = {
    "instruction_ignore": re.compile(
        r"(?:ignore (?:previous|all) instructions"
        r"|disregard your instructions"
        r"|forget your instructions)",
        re.IGNORECASE,
    ),
    "role_override": re.compile(
        r"(?:you are now|act as|pretend you are|your new role)",
        re.IGNORECASE,
    ),
    "system_prompt_leak": re.compile(
        r"(?:show me your system prompt"
        r"|repeat your instructions"
        r"|output your prompt"
        r"|what are your instructions)",
        re.IGNORECASE,
    ),
    "delimiter_escape": re.compile(
        rf"</(?:{TAG_SYSTEM}|{TAG_CONTEXT}|{TAG_QUERY}|{TAG_HISTORY})>",
        re.IGNORECASE,
    ),
}


def check_injection_patterns(text: str) -> list[str]:
    """Return names of injection patterns matched in *text*.

    Does not modify input. Used for observability logging only.
    """
    return [
        name for name, pattern in INJECTION_PATTERNS.items() if pattern.search(text)
    ]
