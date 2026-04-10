.PHONY: dev dev-full dev-ui build test lint ci clean logs health hooks jellyfin-up jellyfin-down test-integration test-integration-full test-injection validate-pipeline

# Default dev target — full stack with Ollama
dev: dev-full

# Full stack: backend + frontend + Ollama sidecar
dev-full:
	docker compose -f docker-compose.yml -f docker-compose.dev.yml -f docker-compose.ollama.yml up

# Frontend only — for UI work without Ollama/models
dev-ui:
	docker compose -f docker-compose.yml -f docker-compose.dev.yml up --no-deps frontend

# Build production images
build:
	docker compose build

# Run all tests
test:
	docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm backend pytest -m "not integration and not pipeline"
	docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm frontend npm test

# Lint both runtimes
lint:
	docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm backend ruff check .
	docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm frontend npm run lint

# CI: build prod images then run tests (ensures prod Dockerfile isn't broken)
ci:
	$(MAKE) build
	$(MAKE) test
	$(MAKE) lint

# View logs
logs:
	docker compose logs -f

# Check service health
health:
	@curl -sf http://localhost:8000/health | python3 -m json.tool 2>/dev/null || echo "Backend not reachable"

# Install pre-commit hooks
hooks:
	git config core.hooksPath .githooks
	@echo "Pre-commit hooks installed (.githooks/pre-commit)"

# ---------------------------------------------------------------------------
# Integration test targets (Jellyfin test stack)
# ---------------------------------------------------------------------------

# Start disposable Jellyfin for integration tests
jellyfin-up:
	docker compose -p ai-movie-suggester-test -f docker-compose.test.yml up -d jellyfin
	@echo "Waiting for Jellyfin to become healthy..."
	@timeout=120; while [ $$timeout -gt 0 ]; do \
		status=$$(docker compose -p ai-movie-suggester-test -f docker-compose.test.yml ps --format json 2>/dev/null | python3 -c "import sys,json; data=json.load(sys.stdin); print(data['Health'] if isinstance(data,dict) else next((s['Health'] for s in data if s['Service']=='jellyfin'),'unknown'))" 2>/dev/null || echo "unknown"); \
		if [ "$$status" = "healthy" ]; then \
			echo "Jellyfin available at http://localhost:8096"; \
			exit 0; \
		fi; \
		sleep 2; \
		timeout=$$((timeout - 2)); \
	done; \
	echo "ERROR: Jellyfin did not become healthy within 120s"; exit 1

# Stop Jellyfin test stack and remove volumes
jellyfin-down:
	docker compose -p ai-movie-suggester-test -f docker-compose.test.yml down -v

# Run integration tests (requires Jellyfin via jellyfin-up)
# Runs on host (same as CI) — Jellyfin is on localhost:8096
test-integration:
	cd backend && JELLYFIN_TEST_URL=http://localhost:8096 uv run pytest -m "integration and not pipeline" -v

# Full cycle: start Jellyfin, run integration tests, teardown (unconditional)
# WARNING: This MUST remain a single logical line. Make runs each recipe line
# in a separate shell — splitting this would break unconditional teardown.
test-integration-full:
	@$(MAKE) jellyfin-up && $(MAKE) test-integration; ret=$$?; $(MAKE) jellyfin-down; exit $$ret

# ---------------------------------------------------------------------------
# Pipeline validation (requires Ollama running locally)
# ---------------------------------------------------------------------------

# Full RAG pipeline validation: embed → search → chat against real Ollama
# Checks Ollama health BEFORE starting Jellyfin to fail fast
validate-pipeline:
	@curl -sf http://localhost:11434/ > /dev/null 2>&1 || { echo "ERROR: Ollama not reachable at http://localhost:11434/"; echo "Start Ollama with: ollama serve"; exit 1; }
	@$(MAKE) jellyfin-up && cd backend && JELLYFIN_TEST_URL=http://localhost:8096 uv run pytest -m pipeline -v ; ret=$$?; cd .. && $(MAKE) jellyfin-down; exit $$ret

# ---------------------------------------------------------------------------
# Adversarial injection test harness
# ---------------------------------------------------------------------------

# Run prompt injection adversarial payloads (no LLM needed)
test-injection:
	cd backend && uv run python ../scripts/test_injection.py

# ---------------------------------------------------------------------------

# Tear down everything including volumes
clean:
	docker compose down -v --remove-orphans
