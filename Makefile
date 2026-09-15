# YuE2 Music Studio — local development.
# Every target has a plain-command equivalent documented in docs/setup-linux.md.

SHELL := /bin/bash
ROOT  := $(shell pwd)
API_VENV    := $(ROOT)/.venv-api
WORKER_VENV := $(ROOT)/.venv-yue2
WEB         := $(ROOT)/apps/web

.DEFAULT_GOAL := help
.PHONY: help install install-api install-worker install-web models env \
        dev backend worker frontend test test-unit test-integration test-worker mapping \
        smoke-test lint format typecheck clean-data stop

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
	  awk 'BEGIN{FS=":.*?## "}{printf "  \033[1m%-18s\033[0m %s\n", $$1, $$2}'

env: ## Create .env from the example if it does not exist
	@test -f .env || (cp .env.example .env && echo "created .env")

install: env install-api install-worker install-web ## Install everything

install-api: ## Build .venv-api (FastAPI; no torch)
	./scripts/setup_api_env.sh

install-worker: ## Build .venv-yue2 (torch 2.10 cu126 + yue2-infer)
	./scripts/setup_yue2_env.sh

install-web: ## Install frontend dependencies
	cd $(WEB) && npm install

mapping: ## Regenerate configs/workflow-mapping.json from the registry + workflow
	python3 scripts/generate_workflow_mapping.py

models: ## Download YuE2-3B and YuE2-Vae into ./models
	./scripts/download_models.sh

dev: ## Run the API, the worker and the frontend together
	@trap 'kill 0' EXIT INT TERM; \
	./scripts/dev_api.sh --reload & \
	./scripts/dev_worker.sh & \
	cd $(WEB) && npm run dev & \
	wait

backend: ## Run the API only
	./scripts/dev_api.sh --reload

worker: ## Run the GPU worker only
	./scripts/dev_worker.sh

frontend: ## Run the frontend only
	cd $(WEB) && npm run dev

test: test-unit test-integration test-worker ## Run every test that does not need a GPU

test-unit: ## Unit tests
	$(API_VENV)/bin/python -m pytest tests/unit -q

test-integration: ## Integration tests against the mock backend
	$(API_VENV)/bin/python -m pytest tests/integration -q

test-worker: ## Worker-environment tests (model residency; no GPU work)
	$(WORKER_VENV)/bin/python -m pytest tests/unit/test_model_manager.py -q

smoke-test: ## Real GPU generation, end to end
	$(WORKER_VENV)/bin/python scripts/smoke_test.py --seconds 30 --report logs/smoke_report.json

typecheck: ## TypeScript type checking
	cd $(WEB) && npx tsc --noEmit

lint: typecheck ## Lint the frontend and check Python syntax
	cd $(WEB) && npm run lint
	$(API_VENV)/bin/python -m compileall -q packages services scripts

format: ## Format the frontend sources
	cd $(WEB) && npx prettier --write "app/**/*.{ts,tsx,css}" "components/**/*.tsx" "features/**/*.tsx" "lib/**/*.ts"

stop: ## Stop the API and worker started by `make dev`
	-pkill -f "uvicorn app.main:app"
	-pkill -f "services.yue2_worker.worker"

clean-data: ## Delete every generation. Irreversible.
	@read -p "Delete everything under data/? [y/N] " answer; \
	  [ "$$answer" = "y" ] && rm -rf data/projects data/jobs data/uploads data/worker && echo "data cleared" || echo "cancelled"
