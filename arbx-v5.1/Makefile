.PHONY: help install dev brain worker worker-file worker-pipe \
        manager frontend test docker-up docker-down docker-rebuild \
        docker-logs docker-worker-logs docker-worker-logs-binance \
        docker-worker-logs-kraken docker-worker-logs-uniswap docker-logs-all \
        gen-worker clean ports

# ─── Load config/.env then config/.env.local so local overrides win ─────────
# Priority (highest → lowest): CLI arg > .env.local > .env > built-in default
# Any variable in .env.local silently overrides the same variable in .env.
-include config/.env
-include config/.env.local
export

# ─── Defaults (only used if not set in config/.env or CLI) ─────────────────
EXCHANGE        ?= binance
PAIRS           ?= BTC/USDT,ETH/USDT
BRAIN_API_PORT  ?= 8000
BRAIN_METRICS_PORT ?= 9090
FRONTEND_PORT   ?= 3000
REDIS_PORT      ?= 6379
POSTGRES_PORT   ?= 5432

help:
	@echo ""
	@echo "  ARBX v4.7 — Available Commands"
	@echo "  ══════════════════════════════════════════════════════════════"
	@echo ""
	@echo "  Setup"
	@echo "  ─────────────────────────────────────────────────────────────"
	@echo "  make install          Install Python dependencies"
	@echo "  make dev              Install + dev extras (pytest, black, ruff)"
	@echo ""
	@echo "  Run locally"
	@echo "  ─────────────────────────────────────────────────────────────"
	@echo "  make brain            Start brain (uses BRAIN_API_PORT env var)"
	@echo "  make brain BRAIN_API_PORT=8080   Brain on custom port"
	@echo ""
	@echo "  make worker           Start worker (env var pairs)"
	@echo "  make worker EXCHANGE=kraken PAIRS=BTC/USDT,ETH/USDT"
	@echo ""
	@echo "  make worker-file EXCHANGE=binance FILE=config/pairs/binance.txt"
	@echo "  make worker-pipe EXCHANGE=binance   (reads pairs from stdin)"
	@echo ""
	@echo "  make manager          Start worker manager daemon"
	@echo "  make frontend         Start Vite dev server"
	@echo ""
	@echo "  Docker"
	@echo "  ─────────────────────────────────────────────────────────────"
	@echo "  make docker-up        Start all services"
	@echo "  make docker-up BRAIN_API_PORT=8080 FRONTEND_PORT=3100"
	@echo "  (Metrics exposed at BRAIN_METRICS_PORT, default 9090)"
	@echo "  make docker-down      Stop all services"
	@echo "  make docker-rebuild   Force full rebuild (no cache) — use after upgrades"
	@echo "  make docker-logs             Tail brain logs"
	@echo "  make docker-worker-logs      Tail all worker logs"
	@echo "  make docker-worker-logs-binance  Binance only"
	@echo "  make docker-worker-logs-kraken   Kraken only"
	@echo "  make docker-logs-all         Tail all container logs"
	@echo ""
	@echo "  make ports            Show current port configuration"
	@echo ""
	@echo "  Other"
	@echo "  ─────────────────────────────────────────────────────────────"
	@echo "  make test             Run all tests (44 tests)"
	@echo "  make gen-worker ID=w-01 EXCHANGE=binance PAIRS='BTC ETH'"
	@echo "  make clean            Remove caches and build artifacts"
	@echo ""
	@echo "  Port env vars (set in config/.env or on command line):"
	@echo "    BRAIN_API_PORT      (default 8000)"
	@echo "    BRAIN_METRICS_PORT  (default 9090)"
	@echo "    FRONTEND_PORT       (default 3000)"
	@echo "    REDIS_PORT          (default 6379)"
	@echo "    POSTGRES_PORT       (default 5432)"
	@echo ""

# ─── Install ───────────────────────────────────────────────────────────────

install:
	pip install -r requirements.txt

dev:
	pip install -r requirements.txt pytest pytest-asyncio black ruff pytz

# ─── Brain ─────────────────────────────────────────────────────────────────

brain:
	BRAIN_API_PORT=$(BRAIN_API_PORT) \
	BRAIN_METRICS_PORT=$(BRAIN_METRICS_PORT) \
	python -m scripts.run_brain

brain-debug:
	BRAIN_API_PORT=$(BRAIN_API_PORT) LOG_LEVEL=DEBUG python -m scripts.run_brain

# ─── Worker — multiple pair input methods ──────────────────────────────────

# Method 1: env var (default)
worker:
	@echo "Starting $(EXCHANGE) worker with pairs: $(PAIRS)"
	EXCHANGE=$(EXCHANGE) PAIRS=$(PAIRS) python -m scripts.run_worker

# Method 2: CLI args
worker-args:
	@echo "Usage: make worker-args EXCHANGE=binance PAIRS='BTC/USDT ETH/USDT'"
	python -m scripts.run_worker --exchange $(EXCHANGE) --pairs $(PAIRS)

# Method 3: pairs file
worker-file:
	@echo "Usage: make worker-file EXCHANGE=binance FILE=config/pairs/binance.txt"
	python -m scripts.run_worker --exchange $(EXCHANGE) --pairs-file $(FILE)

# Method 4: stdin pipe
worker-pipe:
	@echo "Usage: cat config/pairs/binance.txt | make worker-pipe EXCHANGE=binance"
	python -m scripts.run_worker --exchange $(EXCHANGE) --pairs-stdin

# Convenience: start with the pre-made pairs files
worker-binance:
	python -m scripts.run_worker --exchange binance --pairs-file config/pairs/binance.txt

worker-kraken:
	python -m scripts.run_worker --exchange kraken --pairs-file config/pairs/kraken.txt

worker-uniswap:
	python -m scripts.run_worker --exchange uniswap --pairs-file config/pairs/uniswap.txt

# ─── Other services ────────────────────────────────────────────────────────

manager:
	python -m scripts.run_worker_manager

frontend:
	cd frontend && npm install && npm run dev

# ─── Test ──────────────────────────────────────────────────────────────────

test:
	pytest tests/ -v --tb=short

test-cov:
	pytest tests/ -v --cov=. --cov-report=term-missing

# ─── Docker ────────────────────────────────────────────────────────────────

docker-up:
	@if [ ! -f config/.env ]; then \
		cp config/.env.example config/.env; \
		echo "  Created config/.env from example. Edit it to add API keys."; \
	fi
	docker compose -f docker/docker-compose.yml --env-file config/.env $(if $(wildcard config/.env.local),--env-file config/.env.local,) up --build -d
	@echo ""
	@echo "  ✅ ARBX started:"
	@echo ""
	@echo "     Dashboard      → http://localhost:$(FRONTEND_PORT)"
	@echo "     API            → http://localhost:$(BRAIN_API_PORT)"
	@echo "     API Docs       → http://localhost:$(BRAIN_API_PORT)/docs"
	@echo "     Metrics        → http://localhost:$(BRAIN_METRICS_PORT)/metrics"
	@echo ""

docker-rebuild:
	@echo "  Force-rebuilding all images (no cache)..."
	ARBX_VERSION=$(shell cat VERSION) BUILD_DATE=$(shell date -u +%Y-%m-%dT%H:%M:%SZ) \
	  docker compose -f docker/docker-compose.yml --env-file config/.env $(if $(wildcard config/.env.local),--env-file config/.env.local,) build --no-cache
	ARBX_VERSION=$(shell cat VERSION) \
	  docker compose -f docker/docker-compose.yml --env-file config/.env $(if $(wildcard config/.env.local),--env-file config/.env.local,) up -d --force-recreate
	@echo "  ✅ Rebuild complete — version $(shell cat VERSION)"

docker-down:
	@echo "  Stopping auto-spawned worker containers..."
	@docker ps -a --filter ancestor=arbx-worker:latest --format "{{.Names}}" \
	  | xargs -r docker stop 2>/dev/null || true
	@docker ps -a --filter ancestor=arbx-worker:latest --format "{{.Names}}" \
	  | xargs -r docker rm   2>/dev/null || true
	@echo "  Flushing Redis streams (spawn + heartbeat + prices)..."
	@docker exec arb-redis redis-cli DEL \
	  stream:spawn_requests stream:heartbeats stream:registration \
	  stream:prices stream:candles 2>/dev/null || true
	@echo "  Stopping Compose services..."
	docker compose -f docker/docker-compose.yml down

docker-logs:
	docker compose -f docker/docker-compose.yml --env-file config/.env logs -f brain

docker-worker-logs:
	docker compose -f docker/docker-compose.yml --env-file config/.env logs -f worker-binance worker-kraken worker-uniswap

docker-worker-logs-binance:
	docker compose -f docker/docker-compose.yml --env-file config/.env logs -f worker-binance

docker-worker-logs-kraken:
	docker compose -f docker/docker-compose.yml --env-file config/.env logs -f worker-kraken

docker-worker-logs-uniswap:
	docker compose -f docker/docker-compose.yml --env-file config/.env logs -f worker-uniswap

docker-logs-all:
	docker compose -f docker/docker-compose.yml --env-file config/.env logs -f

docker-ps:
	docker compose -f docker/docker-compose.yml ps

# ─── Port summary ──────────────────────────────────────────────────────────

ports:
	@echo ""
	@echo "  ARBX Port Configuration"
	@echo "  ══════════════════════════════════════════════════════════"
	@echo "  Service               Env Var              Current Value"
	@echo "  ──────────────────────────────────────────────────────────"
	@echo "  Brain API             BRAIN_API_PORT       $(BRAIN_API_PORT)"
	@echo "  Brain Metrics         BRAIN_METRICS_PORT   $(BRAIN_METRICS_PORT)"
	@echo "  Frontend              FRONTEND_PORT        $(FRONTEND_PORT)"
	@echo "  Redis                 REDIS_PORT           $(REDIS_PORT)"
	@echo "  PostgreSQL            POSTGRES_PORT        $(POSTGRES_PORT)"
	@echo "  ══════════════════════════════════════════════════════════"
	@echo "  Override: BRAIN_API_PORT=8080 make docker-up"
	@echo "  Or set in config/.env"
	@echo ""

# ─── Admin ─────────────────────────────────────────────────────────────────

gen-worker:
	@echo "Usage: make gen-worker ID=worker-binance-07 EXCHANGE=binance PAIRS='BTC/USDT ETH/USDT'"
	python scripts/generate_worker.py \
		--id       $(ID) \
		--exchange $(EXCHANGE) \
		--pairs    $(PAIRS)

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	find . -name "*.env.secret" -delete 2>/dev/null || true
	rm -rf frontend/dist frontend/node_modules 2>/dev/null || true
	@echo "Cleaned."

# ─── Price Injection (testing) ─────────────────────────────────────────────

inject:
	@echo "Usage examples:"
	@echo "  make inject-tick    EXCHANGE=binance PAIR=BTC/USDT PRICE=70000"
	@echo "  make inject-spread  PAIR=BTC/USDT BUY=binance BUY_PRICE=65000 SELL=kraken SELL_PRICE=66000"
	@echo "  make inject-scenario SCENARIO=btc_pump"
	@echo "  make inject-interactive"
	@echo ""
	@echo "  Or via curl:"
	@echo "    curl -X POST http://localhost:$(BRAIN_API_PORT)/api/inject/tick \\"
	@echo "      -H 'Content-Type: application/json' \\"
	@echo "      -d '{\"exchange\":\"binance\",\"pair\":\"BTC/USDT\",\"price\":70000}'"

inject-tick:
	@echo "Injecting: $(EXCHANGE) $(PAIR) @ $(PRICE)"
	python -m scripts.inject tick -e $(EXCHANGE) -p $(PAIR) --price $(PRICE)

inject-spread:
	python -m scripts.inject spread $(PAIR) \
		--buy $(BUY) --buy-price $(BUY_PRICE) \
		--sell $(SELL) --sell-price $(SELL_PRICE)

inject-candle:
	python -m scripts.inject candle \
		-e $(EXCHANGE) -p $(PAIR) --timeframe $(TF) \
		--open $(O) --high $(H) --low $(L) --close $(C)

inject-scenario:
	@echo "Running scenario: $(SCENARIO)"
	python -m scripts.inject scenario $(SCENARIO)

inject-interactive:
	python -m scripts.inject interactive --api-port $(BRAIN_API_PORT)

inject-list:
	python -m scripts.inject list

inject-status:
	curl -s http://localhost:$(BRAIN_API_PORT)/api/inject/status | python3 -m json.tool

inject-reset:
	curl -s -X DELETE http://localhost:$(BRAIN_API_PORT)/api/inject/reset | python3 -m json.tool
