.PHONY: help install dev test lint fmt typecheck security docker-build docker-push clean

PYTHON   := python3
IMAGE    := ghcr.io/yourorg/dockup
VERSION  := $(shell grep '^version' pyproject.toml | head -1 | cut -d'"' -f2)

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-18s\033[0m %s\n",$$1,$$2}'

install: ## Install package
	pip install -e .

dev: ## Install with dev dependencies
	pip install -e ".[dev]"
	pre-commit install

test: ## Run tests with coverage
	pytest --cov=dockup --cov-report=term-missing -q

test-integration: ## Run integration tests only
	pytest tests/integration/ -v

lint: ## Lint with ruff
	ruff check dockup/ tests/

fmt: ## Auto-format with black + ruff
	black dockup/ tests/
	ruff check dockup/ tests/ --fix

typecheck: ## Type check with mypy
	mypy dockup/ --ignore-missing-imports

security: ## Security audit with bandit
	bandit -r dockup/ -ll

run: ## Run dockup locally (console logging)
	DOCKUP_LOG_FORMAT=console DOCKUP_API_JWT_SECRET=dev-secret dockup serve

docker-build: ## Build Docker image
	docker build -t $(IMAGE):$(VERSION) -t $(IMAGE):latest .

docker-push: ## Push Docker image
	docker push $(IMAGE):$(VERSION)
	docker push $(IMAGE):latest

docker-up: ## Start full docker-compose stack
	docker compose -f examples/compose/docker-compose.yml up -d

docker-down: ## Stop docker-compose stack
	docker compose -f examples/compose/docker-compose.yml down

clean: ## Clean build artifacts
	rm -rf dist/ build/ *.egg-info .coverage htmlcov/ .pytest_cache/ .mypy_cache/ .ruff_cache/
	find . -type d -name __pycache__ -exec rm -rf {} +
