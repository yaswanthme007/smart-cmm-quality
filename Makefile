# Smart CMM Quality: developer commands. Run `make help` for the list.

SHELL := /bin/bash
COMPOSE := docker compose
CMMS := CMM-01 CMM-02

.DEFAULT_GOAL := help
.PHONY: help env dirs up down logs migrate seed demo-reset test lint fmt bench gen

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

env: ## Create .env from .env.example if missing
	@test -f .env || (cp .env.example .env && echo "Created .env from .env.example; edit the secrets.")

dirs: ## Create runtime data folders (gitignored)
	@mkdir -p data/uploads data/evidence $(foreach c,$(CMMS),data/inbox/$(c) data/processed/$(c) data/failed/$(c))

up: env dirs ## Start the stack (db, mailpit, api, web)
	$(COMPOSE) up -d --build

down: ## Stop the stack
	$(COMPOSE) --profile worker --profile prod down

logs: ## Follow logs of all services
	$(COMPOSE) logs -f --tail=100

migrate: ## Apply database migrations
	$(COMPOSE) exec api alembic upgrade head

seed: ## Seed demo masters and users
	@echo "seed: not implemented yet (C08)"

demo-reset: ## Reset the database to the demo storyline state
	@echo "demo-reset: not implemented yet (C36)"

test: ## Run backend and frontend tests
	@if [ -f backend/pyproject.toml ]; then cd backend && uv run pytest; else echo "backend: no tests yet"; fi
	@if [ -f frontend/package.json ]; then cd frontend && npm test --if-present; else echo "frontend: no tests yet"; fi

lint: ## Lint backend (ruff) and frontend (eslint, tsc)
	@if [ -f backend/pyproject.toml ]; then cd backend && uv run ruff check . && uv run ruff format --check .; else echo "backend: nothing to lint yet"; fi
	@if [ -f frontend/package.json ]; then cd frontend && npm run lint --if-present; else echo "frontend: nothing to lint yet"; fi

fmt: ## Format backend and frontend code
	@if [ -f backend/pyproject.toml ]; then cd backend && uv run ruff format . && uv run ruff check --fix .; fi
	@if [ -f frontend/package.json ]; then cd frontend && npm run fmt --if-present; fi

bench: ## Run ingest-to-alert benchmark
	@echo "bench: not implemented yet (C35)"

gen: ## Generate synthetic CMM report files into samples/
	@echo "gen: not implemented yet (C10)"
