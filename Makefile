.PHONY: dev dev-full dev-ui build test lint clean logs health

# Default dev target — full stack with Ollama
dev: dev-full

# Full stack: backend + frontend + Ollama sidecar
dev-full:
	docker compose -f docker-compose.yml -f docker-compose.dev.yml -f docker-compose.ollama.yml up

# Frontend only — for UI work without Ollama/models
dev-ui:
	docker compose -f docker-compose.yml -f docker-compose.dev.yml up frontend

# Build production images
build:
	docker compose build

# Run all tests
test:
	docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm backend pytest
	docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm frontend npm test

# Lint both runtimes
lint:
	docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm backend ruff check .
	docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm frontend npm run lint

# View logs
logs:
	docker compose logs -f

# Check service health
health:
	@curl -sf http://localhost:8000/health | python3 -m json.tool 2>/dev/null || echo "Backend not reachable"

# Tear down everything including volumes
clean:
	docker compose down -v --remove-orphans
