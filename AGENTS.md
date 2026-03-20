# ai-movie-suggester — Project Context

A self-hosted AI companion for Jellyfin that uses RAG to provide conversational movie recommendations based on a user's library and watch history.

## Tech Stack

| Component | Technology | Notes |
|-----------|-----------|-------|
| Backend | Python (FastAPI) | RAG orchestration, Jellyfin proxy, session management |
| Frontend | Next.js (App Router) | PWA, mobile-first |
| Vector DB | SQLite-vec | In-process with backend, WAL mode |
| Embeddings | Ollama (nomic-embed-text) | Local inference only |
| Chat LLM | Ollama (llama3.1:8b) | Local inference only |
| Orchestration | Docker Compose | Three-file pattern (base, ollama sidecar, dev) |
| Python deps | uv + pyproject.toml | Deterministic lockfile |

@ARCHITECTURE.md

## Architecture Decisions

- **TMDb enrichment is opt-in** (off by default). The app works with Jellyfin metadata only. Privacy-first.
- **SQLite-vec** behind a repository abstraction. WAL mode for concurrent reads. Swap to Qdrant should be a one-module change.
- **Jellyfin tokens never persisted to disk.** Stored in server-side encrypted sessions only. Frontend never sees raw tokens.
- **Permission filtering at query time**, not index time. Vector DB stores all items; results filtered against Jellyfin's permission API per-user.
- **Incremental sync** in v1. Track per-item content hash. Re-embed only changed items.
- **OpenAPI spec** defines the frontend-backend contract. This is the only shared artifact between runtimes.
- **CPU-only is the default** deployment. GPU support is opt-in via `docker-compose.ollama.yml`.

## Build & Run

```bash
# Development (full stack with Ollama)
make dev

# Development (frontend only, no Ollama needed)
make dev-ui

# Production
cp .env.example .env  # fill in values
docker compose up -d  # if you already have Ollama
# or
docker compose -f docker-compose.yml -f docker-compose.ollama.yml up -d

# Tests
make test

# Lint
make lint
```

### Integration Tests

Integration tests run against a real Jellyfin instance. A disposable container is provided via Docker Compose.

```bash
# Start a disposable Jellyfin for testing
make jellyfin-up

# Run integration tests (Jellyfin must be running)
make test-integration

# Full cycle: start Jellyfin, run tests, teardown
make test-integration-full

# Stop and remove the test Jellyfin
make jellyfin-down
```

The test suite automatically completes the Jellyfin first-run wizard and provisions test users on first run. Subsequent runs are idempotent.

**Prerequisites:** Docker running, port 8096 available, `uv` installed.

## Coding Standards

### Python (Backend)
- Always use `async/await` for I/O operations
- Type hints on all function signatures
- Use Pydantic models for request/response schemas
- Tests use pytest with async support
- Lint with ruff
- Mock Jellyfin API in unit tests; integration tests use a real instance
- Never log PII, chat messages, or tokens

### TypeScript (Frontend)
- Strict TypeScript — no `any` types
- React Server Components by default; `"use client"` only when needed
- Tests with vitest + React Testing Library
- Lint with eslint + prettier

### General
- Conventional commits (feat:, fix:, docs:, chore:, etc.)
- No secrets in code — all config via environment variables
- OpenAPI spec is the source of truth for API contracts

## Things to Avoid

These are firm constraints, not preferences. AI assistants and contributors alike should treat violations as requiring explicit justification and review.

- No `any` types in TypeScript — use proper types or generics
- No plaintext token storage — Jellyfin tokens in server-side encrypted sessions only
- No `allow_origins=["*"]` in CORS — restrict to the frontend origin
- No ad-hoc `os.environ` calls — all config via Pydantic `BaseSettings`
- No committing `.env` files — use `.env.example` for documentation
- No mocking the Jellyfin API in integration tests — mocks for unit tests only
- No persisting Jellyfin `AccessToken`s to disk
- No logging PII, chat messages, or tokens
- No raw string concatenation for embeddings — use templated composite strings

## SDD Workflow

This project uses Spec-Driven Development. Spec artifacts live in `docs/specs/`.

| Stage | Command |
|-------|---------|
| Spec | `/SDD-1-generate-spec` |
| Tasks | `/SDD-2-generate-task-list-from-spec` |
| Execute | `/SDD-3-manage-tasks` |
| Validate | `/SDD-4-validate-spec-implementation` |

## Project Structure

```
backend/          # Python FastAPI
  app/            # Application code
  tests/          # pytest tests
  Dockerfile
  pyproject.toml
frontend/         # Next.js
  src/            # Application code
  tests/          # vitest tests
  Dockerfile
  package.json
docs/
  specs/          # SDD spec artifacts
scripts/          # Helper scripts (not runtime)
docker-compose.yml          # Base: backend + frontend
docker-compose.ollama.yml   # Opt-in: Ollama sidecar with GPU
docker-compose.dev.yml      # Dev: bind mounts + hot reload
```
