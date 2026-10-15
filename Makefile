# Everyday commands. Needs uv (https://docs.astral.sh/uv/) and Docker.
.DEFAULT_GOAL := help
BACKEND := cd backend &&
COMPOSE_DEV := docker compose -f deploy/compose.dev.yml

help: ## List commands
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-18s %s\n", $$1, $$2}'

setup: ## Install backend and web dependencies
	$(BACKEND) uv sync
	cd web && npm ci

lint: ## Lint, format check and type check
	$(BACKEND) uv run ruff check src tests
	$(BACKEND) uv run ruff format --check src tests
	$(BACKEND) uv run mypy

format: ## Fix formatting and simple lint issues
	$(BACKEND) uv run ruff check --fix src tests
	$(BACKEND) uv run ruff format src tests

test: ## Unit tests (no Docker), with the 90% coverage gate on domain logic
	$(BACKEND) uv run pytest --cov=transitlive.domain --cov=transitlive.gtfs --cov-fail-under=90

test-integration: ## Collector -> database -> API tests (starts a throwaway PostgreSQL in Docker)
	$(BACKEND) uv run pytest -m integration

web-dev: ## Run the web app (needs make dev or make dev-replay running), http://localhost:5180
	cd web && npm run dev

web-check: ## Web app lint, type check, tests and build
	cd web && npm run lint && npm run typecheck && npm test && npm run build

e2e: ## End-to-end tests: real web app + backend on recorded feeds (Docker, no network)
	deploy/e2e.sh

api-types: ## Regenerate the web app's API types from the backend
	$(BACKEND) uv run transitlive openapi > ../web/src/api/openapi.json
	cd web && npm run -s api-types

tiles: ## Cut the Sea-to-Sky map tiles into web/public/tiles (needs the pmtiles CLI)
	deploy/tiles/build.sh web/public/tiles/sea-to-sky.pmtiles

test-all: lint test test-integration web-check e2e ## Everything CI runs

fixtures: ## Re-record the replay fixtures from the real feeds (MINUTES=10)
	rm -rf backend/tests/fixtures/archive
	$(BACKEND) uv run transitlive capture tests/fixtures/archive --minutes $(or $(MINUTES),10)

dev: ## Run the stack locally, collecting from BC Transit
	$(COMPOSE_DEV) --profile live up --build

dev-replay: ## Run the stack locally, replaying the fixtures (no network)
	$(COMPOSE_DEV) --profile replay up --build

down: ## Stop the local stack
	$(COMPOSE_DEV) --profile live --profile replay down

.PHONY: help setup lint format test test-integration test-all fixtures dev dev-replay down web-dev web-check e2e api-types tiles
