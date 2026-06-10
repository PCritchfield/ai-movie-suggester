"""Guard test: ``ranx`` must never be imported under ``backend/app/``.

``ranx`` is a dev/test-only dependency (the IR-metrics oracle for the retrieval
eval harness, Spec 26). It is heavy (numba, pandas, matplotlib, ...) and has no
place in the production import graph. This test walks every Python source file
under ``backend/app/`` and fails if any of them import ranx.

Runs in normal CI — no markers, no Ollama, no Jellyfin.
"""

from __future__ import annotations

import ast
from pathlib import Path

_APP_DIR = Path(__file__).resolve().parents[1] / "app"


def _python_files() -> list[Path]:
    return sorted(_APP_DIR.rglob("*.py"))


def _imports_ranx(source: str) -> bool:
    """True if the parsed module imports ranx via ``import`` or ``from``.

    Uses the AST rather than substring matching so comments and string
    literals mentioning ranx do not trip the guard.
    """
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "ranx" or alias.name.startswith("ranx."):
                    return True
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "ranx" or module.startswith("ranx."):
                return True
    return False


def test_app_dir_exists() -> None:
    assert _APP_DIR.is_dir(), f"expected backend/app at {_APP_DIR}"


def test_no_ranx_import_under_app() -> None:
    offenders: list[str] = []
    for path in _python_files():
        source = path.read_text(encoding="utf-8")
        if _imports_ranx(source):
            offenders.append(str(path.relative_to(_APP_DIR.parent)))
    assert not offenders, (
        "ranx is a dev/test-only dependency and must not be imported under "
        f"backend/app/. Offending files: {offenders}"
    )
