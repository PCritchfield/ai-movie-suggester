.PHONY: help dev dev-full dev-ui dev-down build test lint ci clean logs health hooks jellyfin-up jellyfin-down test-integration test-integration-full test-injection validate-pipeline pipeline-up pipeline-down eval-router

.DEFAULT_GOAL := help

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*##"}; {printf "  \033[36m%-24s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------------------
# Port 8096 guard — localdev Jellyfin and test Jellyfin share this port
# ---------------------------------------------------------------------------
_check_port_8096 = @curl -sf http://localhost:8096/health > /dev/null 2>&1 \
	&& { echo "ERROR: Port 8096 already in use (another Jellyfin stack running?)"; \
	     echo "  Run: make dev-down  or  make jellyfin-down  first"; exit 1; } \
	|| true

dev: ## Self-contained local stack (no .env needed)
	$(_check_port_8096)
	docker compose -f docker-compose.yml -f docker-compose.dev.yml -f docker-compose.localdev.yml up

dev-down: ## Stop the local dev stack
	docker compose -f docker-compose.yml -f docker-compose.dev.yml -f docker-compose.localdev.yml down

dev-full: ## Full stack with hot reload (requires .env)
	docker compose -f docker-compose.yml -f docker-compose.dev.yml -f docker-compose.ollama.yml up

dev-ui: ## Frontend only (no Ollama needed)
	docker compose -f docker-compose.yml -f docker-compose.dev.yml up --no-deps frontend

build: ## Build production Docker images
	docker compose build

test: ## Run unit tests (backend + frontend)
	docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm backend pytest -m "not integration and not pipeline"
	docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm frontend npm test

lint: ## Lint both runtimes
	docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm backend ruff check .
	docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm frontend npm run lint

ci: ## Build + test + lint (prod images)
	$(MAKE) build
	$(MAKE) test
	$(MAKE) lint

logs: ## Tail Docker Compose logs
	docker compose logs -f

health: ## Check backend health endpoint
	@curl -sf http://localhost:8000/health | python3 -m json.tool 2>/dev/null || echo "Backend not reachable"

hooks: ## Install pre-commit hooks
	git config core.hooksPath .githooks
	@echo "Pre-commit hooks installed (.githooks/pre-commit)"

# ---------------------------------------------------------------------------
# Integration test targets (Jellyfin test stack)
# ---------------------------------------------------------------------------

jellyfin-up: ## Start disposable Jellyfin for tests
	$(_check_port_8096)
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

jellyfin-down: ## Stop Jellyfin test stack
	docker compose -p ai-movie-suggester-test -f docker-compose.test.yml down -v

test-integration: ## Run integration tests (requires jellyfin-up)
	cd backend && JELLYFIN_TEST_URL=http://localhost:8096 uv run pytest -m "integration and not pipeline" -v

test-integration-full: ## Start Jellyfin, test, teardown
	@$(MAKE) jellyfin-up && $(MAKE) test-integration; ret=$$?; $(MAKE) jellyfin-down; exit $$ret

# ---------------------------------------------------------------------------
# Pipeline validation (requires Ollama running locally)
# ---------------------------------------------------------------------------

pipeline-up: ## Start Jellyfin + check Ollama
	@$(MAKE) jellyfin-up
	@echo "Checking Ollama at http://localhost:11434/ ..."
	@curl -sf http://localhost:11434/ > /dev/null 2>&1 \
		&& echo "Ollama is running" \
		|| { echo "WARNING: Ollama not reachable at http://localhost:11434/"; \
		     echo "  macOS:  ollama serve"; \
		     echo "  Linux:  docker compose -f docker-compose.yml -f docker-compose.ollama.yml up -d ollama"; \
		     echo "Start Ollama, then run: make validate-pipeline"; exit 1; }
	@echo "Pipeline infrastructure ready — run: make validate-pipeline"

pipeline-down: ## Stop pipeline infrastructure
	@$(MAKE) jellyfin-down

validate-pipeline: ## Full RAG pipeline validation (one-shot)
	@curl -sf http://localhost:11434/ > /dev/null 2>&1 || { echo "ERROR: Ollama not reachable at http://localhost:11434/"; echo "Start Ollama first, or run: make pipeline-up"; exit 1; }
	@$(MAKE) jellyfin-up && JELLYFIN_TEST_URL=http://localhost:8096 uv run --directory backend pytest -m pipeline -v ; ret=$$?; $(MAKE) jellyfin-down; exit $$ret

eval-router: ## Run query-router eval cases against live stack (Spec 24)
	@curl -sf http://localhost:11434/ > /dev/null 2>&1 || { echo "ERROR: Ollama not reachable at http://localhost:11434/"; echo "Start Ollama first, or run: make pipeline-up"; exit 1; }
	@$(MAKE) jellyfin-up && JELLYFIN_TEST_URL=http://localhost:8096 uv run --directory backend pytest -m pipeline -v tests/pipeline/test_query_router_eval.py ; ret=$$?; $(MAKE) jellyfin-down; exit $$ret

# ---------------------------------------------------------------------------
# Adversarial injection test harness
# ---------------------------------------------------------------------------

test-injection: ## Run prompt injection adversarial payloads
	cd backend && uv run python ../scripts/test_injection.py

# ---------------------------------------------------------------------------

clean: ## Tear down everything including volumes
	docker compose down -v --remove-orphans
