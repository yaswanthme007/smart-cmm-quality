# Smart CMM Quality: developer commands. Run `make help` for the list.

SHELL := /bin/bash
COMPOSE := docker compose
CMMS := CMM-01 CMM-02

.DEFAULT_GOAL := help
.PHONY: help env dirs up down logs migrate seed demo-reset demo-drop test e2e lint fmt bench gen

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

env: ## Create .env from .env.example if missing
	@test -f .env || (cp .env.example .env && echo "Created .env from .env.example; edit the secrets.")

dirs: ## Create runtime data folders (gitignored; writable by the containers' user)
	@mkdir -p data/uploads data/evidence $(foreach c,$(CMMS),data/inbox/$(c) data/processed/$(c) data/failed/$(c))
	@chmod -R a+rwX data 2>/dev/null || true

up: env dirs ## Start the stack (db, mailpit, api, web)
	$(COMPOSE) up -d --build

down: ## Stop the stack
	$(COMPOSE) --profile worker --profile prod down

logs: ## Follow logs of all services
	$(COMPOSE) logs -f --tail=100

migrate: ## Apply database migrations
	$(COMPOSE) exec api alembic upgrade head

seed: ## Seed demo masters, users, mapping profiles and settings (synthetic)
	$(COMPOSE) exec api python -m app.seed masters

demo-reset: dirs ## Reset to the demo storyline: masters + 30 days synthetic history + N3 drift
	$(COMPOSE) exec api alembic upgrade head
	$(COMPOSE) exec api python -m app.seed storyline

demo-drop: ## Live demo step: drop DC101_SN0457_chr.txt (C-03 = 72.034, Not OK) into CMM-01 inbox
	cd backend && uv run python ../tools/generator/generate.py --style calypso --part DC-101 \
		--machine VMC-02 --serial-start 457 --count 1 --set C-03=72.034 --flat --out ../data/inbox/CMM-01

test: ## Run backend and frontend tests
	@if [ -f backend/pyproject.toml ]; then cd backend && uv run pytest; else echo "backend: no tests yet"; fi
	@if [ -f frontend/package.json ]; then cd frontend && npm test --if-present; else echo "frontend: no tests yet"; fi

e2e: ## Playwright smoke test against the running stack (after make demo-reset)
	cd frontend && npx playwright test

lint: ## Lint backend (ruff) and frontend (eslint, tsc)
	@if [ -f backend/pyproject.toml ]; then cd backend && uv run ruff check . ../tools && uv run ruff format --check . ../tools; else echo "backend: nothing to lint yet"; fi
	@if [ -f frontend/package.json ]; then cd frontend && npm run lint --if-present; else echo "frontend: nothing to lint yet"; fi

fmt: ## Format backend and frontend code
	@if [ -f backend/pyproject.toml ]; then cd backend && uv run ruff format . ../tools && uv run ruff check --fix . ../tools; fi
	@if [ -f frontend/package.json ]; then cd frontend && npm run fmt --if-present; fi

bench: ## Measure Section 17 targets against the running stack (writes docs/BENCHMARKS.md)
	cd backend && uv run python ../tools/bench/ingest_bench.py --uploads 30

GEN := cd backend && uv run python ../tools/generator/generate.py

gen: ## Generate synthetic CMM report files into samples/ (demo data)
	$(GEN) --style csv --count 3 --out ../samples
	$(GEN) --style calypso --count 3 --out ../samples
	$(GEN) --style aqdef --count 3 --out ../samples
	$(GEN) --style pcdmis --part DC-101 --count 3 --decimal-comma --machine HMC-01 --out ../samples
