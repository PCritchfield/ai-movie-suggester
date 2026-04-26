#!/usr/bin/env python3
"""Run the Spec 24 query-router eval cases against the live backend.

Loads ``backend/tests/fixtures/query_router_cases.json`` via the shared
loader, hits the live ``/api/search`` endpoint for each case, and prints
a per-case pass/fail table. Exits 0 when every case passes; non-zero
otherwise.

Usage:
    python scripts/eval_router.py [--base-url http://localhost:8000]
                                  [--user USER] [--password PASS]
                                  [--limit 10]

The user/password authenticate against Jellyfin so the search endpoint
gets a real session. Without credentials the script prints the cases
and exits 0 (path-only smoke for CI).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from tests.pipeline._router_eval_loader import (  # noqa: E402
    QueryRouterCase,
    load_cases,
)


def _supports_color() -> bool:
    return sys.stdout.isatty()


_GREEN = "\033[32m" if _supports_color() else ""
_RED = "\033[31m" if _supports_color() else ""
_DIM = "\033[2m" if _supports_color() else ""
_RESET = "\033[0m" if _supports_color() else ""


async def _login(
    client: httpx.AsyncClient, base_url: str, user: str, password: str
) -> dict[str, str]:
    """Return cookie + CSRF dicts after a successful Jellyfin login."""
    resp = await client.post(
        f"{base_url}/api/auth/login",
        json={"username": user, "password": password},
    )
    resp.raise_for_status()
    csrf = resp.cookies.get("csrf_token")
    return {"csrf": csrf or ""}


async def _run_search(
    client: httpx.AsyncClient,
    base_url: str,
    csrf: str,
    query: str,
    limit: int,
) -> list[dict[str, object]]:
    resp = await client.post(
        f"{base_url}/api/search",
        json={"query": query, "limit": limit},
        headers={"X-CSRF-Token": csrf},
    )
    if resp.status_code != 200:
        return []
    payload = resp.json()
    return list(payload.get("results", []))


def _evaluate_case(case: QueryRouterCase, titles: list[str]) -> tuple[bool, list[str]]:
    """Return (passed, failure_reasons) for this case against the result titles."""
    failures: list[str] = []
    for required in case.must_include_titles:
        if required not in titles:
            failures.append(f"missing {required!r}")
    for forbidden in case.must_exclude_titles:
        if forbidden in titles:
            failures.append(f"forbidden {forbidden!r} present")
    return (not failures, failures)


def _print_row(case: QueryRouterCase, titles: list[str], passed: bool) -> None:
    mark = f"{_GREEN}PASS{_RESET}" if passed else f"{_RED}FAIL{_RESET}"
    title_list = ", ".join(titles[:5]) or "<empty>"
    print(f"{mark}  [{case.expected_path:<8}] {case.query[:60]:<60}")
    print(f"      {_DIM}top-5: {title_list}{_RESET}")


async def _amain(args: argparse.Namespace) -> int:
    cases = load_cases(args.fixtures)
    print(f"Loaded {len(cases)} cases from {args.fixtures or '<default>'}")

    if not args.user or not args.password:
        print(
            "No credentials supplied — printing case summary and exiting 0.\n"
            "Pass --user and --password to run against the live backend."
        )
        for case in cases:
            print(
                f"  [{case.expected_path:<8}] {case.query[:70]:<70} "
                f"include={case.must_include_titles}"
            )
        return 0

    timeout = httpx.Timeout(connect=5.0, read=60.0, write=10.0, pool=5.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        try:
            await _login(client, args.base_url, args.user, args.password)
        except httpx.HTTPStatusError as exc:
            print(f"Login failed: {exc}")
            return 2
        csrf = client.cookies.get("csrf_token") or ""

        passed = 0
        failed = 0
        for case in cases:
            results = await _run_search(
                client, args.base_url, csrf, case.query, args.limit
            )
            titles = [r.get("title", "") for r in results if isinstance(r, dict)]
            ok, reasons = _evaluate_case(case, titles)
            _print_row(case, titles, ok)
            if not ok:
                failed += 1
                for reason in reasons:
                    print(f"      {_RED}- {reason}{_RESET}")
            else:
                passed += 1

    total = passed + failed
    summary = f"\npassed={passed} failed={failed} total={total}"
    print(summary)
    return 0 if failed == 0 else 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Spec 24 query-router eval cases against the live backend."
    )
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="Backend base URL (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--user",
        default=None,
        help="Jellyfin username (omit for path-only smoke).",
    )
    parser.add_argument(
        "--password",
        default=None,
        help="Jellyfin password.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Top-N results per query (default: 10).",
    )
    parser.add_argument(
        "--fixtures",
        default=None,
        help=(
            "Override fixture path. Defaults to "
            "backend/tests/fixtures/query_router_cases.json."
        ),
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(_amain(args)))


if __name__ == "__main__":
    main()
