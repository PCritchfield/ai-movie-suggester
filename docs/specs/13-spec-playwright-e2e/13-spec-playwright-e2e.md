# 13-spec-playwright-e2e

## Introduction/Overview

This spec adds a Playwright end-to-end test framework to the ai-movie-suggester frontend, covering the full auth lifecycle against a real Jellyfin instance. It provides the project's first browser-level integration tests, catching regressions that component-level Vitest tests cannot (cookie handling, redirects, real API round-trips, cross-browser rendering). The framework is designed for both local developer iteration and fully self-contained CI execution.

## Goals

- Install and configure Playwright with Chromium, Firefox, and WebKit browser projects in `frontend/`.
- Implement a `globalSetup`/`globalTeardown` pattern that optionally spins up the Docker Compose stack (backend + frontend + Jellyfin) when no `PLAYWRIGHT_BASE_URL` is set, or targets an already-running dev server when the variable is present.
- Establish a `storageState`-based auth fixture so non-auth tests skip the login UI entirely, while auth-specific tests exercise the real login flow.
- Ship a separate `.github/workflows/e2e.yml` CI workflow that runs Chromium + Firefox on PRs to main (skipping drafts) and supports `workflow_dispatch` for manual runs.
- Deliver five auth lifecycle E2E tests (happy login, invalid credentials, logout, protected page redirect, session expiry redirect) within a ~500-line implementation budget.
