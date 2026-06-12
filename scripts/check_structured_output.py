#!/usr/bin/env python3
"""Spec 27 real-inference check: does Ollama's ``format`` constrain the chat model?

Sends a set of representative chat prompts (typical / vague / follow-up
phrasings) through ``OllamaChatClient.chat_structured`` against a LIVE Ollama,
and verifies every response parses into ``StructuredChatResponse``. This is the
Task 1.5 gate: grammar-constrained decoding is the load-bearing assumption of
the whole spec, so we confirm it holds on the target model before building on it.

PASS BAR (Granny condition): zero parse/schema failures across all prompts.
Any failure exits non-zero — the spec returns to council before further work.

Privacy: prints COUNTS ONLY. The model's ``reasoning`` / ``introductory_message``
text is never printed or logged — only pass/fail and recommendation counts.

Usage:
    python scripts/check_structured_output.py
        [--ollama-host http://localhost:11434] [--model llama3.1:8b]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.chat.models import (  # noqa: E402
    RECOMMENDATION_RESPONSE_SCHEMA,
    StructuredChatResponse,
)
from app.ollama.chat_client import OllamaChatClient  # noqa: E402
from app.ollama.errors import OllamaError  # noqa: E402

# A small fixed candidate set with [ID:...] prefixes, mirroring the production
# prompt's candidate context. These are synthetic — not real library data.
_CANDIDATES = [
    "[ID:cand-01] Alien (1979) [Horror, Sci-Fi]: A crew is hunted by a creature.",
    "[ID:cand-02] Galaxy Quest (1999) [Comedy, Sci-Fi]: Washed-up actors save aliens.",
    "[ID:cand-03] The Thing (1982) [Horror, Sci-Fi]: A shape-shifter stalks a base.",
    "[ID:cand-04] Ghostbusters (1984) [Comedy]: Parapsychologists fight ghosts.",
    "[ID:cand-05] Tremors (1990) [Comedy, Horror]: A town battles burrowing monsters.",
    "[ID:cand-06] Predator (1987) [Action, Sci-Fi]: Commandos vs. an alien hunter.",
]

# >=10 prompts spanning the phrasings the spec calls out.
_PROMPTS: list[tuple[str, str]] = [
    ("typical-1", "Something like Alien but funny"),
    ("typical-2", "A spooky sci-fi horror from the 80s"),
    ("typical-3", "I want a comedy with aliens in it"),
    ("typical-4", "Recommend a creature feature for movie night"),
    ("vague-1", "Surprise me"),
    ("vague-2", "idk, something good"),
    ("vague-3", "I'm bored, pick something"),
    ("vague-4", "whatever you think I'd like"),
    ("followup-1", "more like the second one"),
    ("followup-2", "something a bit funnier than that"),
    ("followup-3", "no, the scarier option please"),
]

_SCHEMA_TEXT = json.dumps(RECOMMENDATION_RESPONSE_SCHEMA)


def _build_messages(query: str) -> list[dict[str, str]]:
    system = (
        "You recommend movies ONLY from the candidate list below. Respond with "
        "JSON matching this schema; use the exact jellyfin_id values from the "
        "candidates.\n\n"
        f"Schema:\n{_SCHEMA_TEXT}\n\n"
        "Candidates:\n" + "\n".join(_CANDIDATES)
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": query},
    ]


async def _amain(args: argparse.Namespace) -> int:
    print(
        f"Checking structured-output compliance on '{args.model}' "
        f"at {args.ollama_host} across {len(_PROMPTS)} prompts.\n"
    )

    timeout = httpx.Timeout(connect=5.0, read=120.0, write=10.0, pool=5.0)
    passed = 0
    failed = 0

    async with httpx.AsyncClient(timeout=timeout) as http:
        client = OllamaChatClient(
            base_url=args.ollama_host, http_client=http, chat_model=args.model
        )
        if not await client.health():
            print(f"FAIL: Ollama not reachable at {args.ollama_host}")
            return 2

        for label, query in _PROMPTS:
            try:
                result: StructuredChatResponse = await client.chat_structured(
                    _build_messages(query), StructuredChatResponse
                )
            except OllamaError as exc:
                failed += 1
                # Print the error CLASS only — never the payload/content.
                print(f"  [FAIL] {label}: {type(exc).__name__}")
                continue
            passed += 1
            # Counts only — no reasoning / introductory_message text.
            print(f"  [PASS] {label}: {len(result.recommendations)} recommendation(s)")

    total = passed + failed
    print(f"\n{passed}/{total} prompts produced schema-valid structured output.")
    if failed:
        print("RESULT: FAIL — grammar constraint did not hold on every prompt.")
        print("Per the spec, return to council before building on structured output.")
        return 1
    print("RESULT: PASS — format constrains the model on every prompt.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Spec 27 structured-output real-inference check (counts only)."
    )
    parser.add_argument("--ollama-host", default="http://localhost:11434")
    parser.add_argument("--model", default="llama3.1:8b")
    args = parser.parse_args()
    sys.exit(asyncio.run(_amain(args)))


if __name__ == "__main__":
    main()
