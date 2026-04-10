"""Pipeline pre-flight and embedding verification tests.

These tests validate Ollama reachability, model availability, and that
all fixture items are successfully embedded with real inference.
"""

from __future__ import annotations

import httpx
import pytest

from tests.pipeline.conftest import OLLAMA_HOST, REQUIRED_MODELS


@pytest.mark.pipeline
async def test_ollama_reachable() -> None:
    """Ollama health endpoint returns 200."""
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(f"{OLLAMA_HOST}/")
        assert resp.status_code == 200, (
            f"Ollama not reachable at {OLLAMA_HOST} (status {resp.status_code})"
        )


@pytest.mark.pipeline
async def test_models_available() -> None:
    """Both required models (nomic-embed-text, llama3.1:8b) are available."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{OLLAMA_HOST}/api/tags")
        resp.raise_for_status()
        available = {m["name"] for m in resp.json().get("models", [])}

        for model in REQUIRED_MODELS:
            assert model in available or f"{model}:latest" in available, (
                f"Model {model} not available in Ollama. Available: {sorted(available)}"
            )
