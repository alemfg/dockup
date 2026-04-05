"""
v2 Config loader — typed Pydantic settings for the full distributed system.

Priority order for every setting (highest wins):
  1. Environment variable  (e.g. BRAIN_API_PORT=8080)
  2. config.yaml value
  3. Pydantic default
"""
from __future__ import annotations
import os
from functools import lru_cache
import threading
from pathlib import Path
from typing import Dict, List, Optional
import yaml
from enum import Enum
from pydantic import BaseModel, Field


class TradingMode(str, Enum):
    DISABLED = "disabled"   # no orders sent, not even logged
    SIMULATE = "simulate"   # orders computed and logged, never sent to exchange
    LIVE     = "live"       # real orders sent via CCXT
from dotenv import load_dotenv

_ENV_PATH       = Path(__file__).parent / ".env"
_ENV_LOCAL_PATH = Path(__file__).parent / ".env.local"

# Load base defaults first, then local overrides.
# .env       — shipped with every release (safe defaults, no secrets)
# .env.local — your personal file: API keys + your overrides, never overwritten
if _ENV_PATH.exists():
    load_dotenv(dotenv_path=_ENV_PATH)
if _ENV_LOCAL_PATH.exists():
    load_dotenv(dotenv_path=_ENV_LOCAL_PATH, override=True)


def _read_version() -> str:
    """Read version from the VERSION file at the project root."""
    p = Path(__file__).parent.parent / "VERSION"
    return p.read_text().strip() if p.exists() else "0.0.0"


def _env_int(key: str, default: int) -> int:
    v = os.getenv(key)
    return int(v) if v and v.strip().isdigit() else default


def _env_float(key: str, default: float) -> float:
    v = os.getenv(key)
    try:
        return float(v) if v and v.strip() else default
    except ValueError:
        return default


def _env_str(key: str, default: str) -> str:
    return os.getenv(key, default)


def _resolve(obj):
    if isinstance(obj, dict):
        return {k: _resolve(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve(i) for i in obj]
    if isinstance(obj, str) and obj.startswith("${") and obj.endswith("}"):
        return os.getenv(obj[2:-1], "")
    return obj


# ─── Sub-models ──────────────────────────────────────────────────────────────

class PortsConfig(BaseModel):
    """
    All listen/published ports — every one overridable via environment variable.

    Environment variable → default:
      BRAIN_API_PORT        → 8000   (FastAPI REST + WebSocket)
      BRAIN_METRICS_PORT    → 9090   (Prometheus scrape target)
      FRONTEND_PORT         → 3000   (nginx serving React)
      REDIS_PORT            → 6379
      POSTGRES_PORT         → 5432
    """
    brain_api:     int = 8000
    brain_metrics: int = 9090
    frontend:      int = 3000
    redis:         int = 6379
    postgres:      int = 5432


class RedisConfig(BaseModel):
    host: str = "localhost"
    port: int = 6379
    db:   int = 0
    opportunity_ttl_seconds: int = 10
    fallback_memory: bool = True


class PostgresConfig(BaseModel):
    enabled:  bool = True
    host:     str = "localhost"
    port:     int = 5432
    database: str = "arbitrage"
    user:     str = "arbitrage"
    password: str = ""

    @property
    def dsn(self) -> str:
        pw = os.getenv("POSTGRES_PASSWORD", self.password)
        return f"postgresql+asyncpg://{self.user}:{pw}@{self.host}:{self.port}/{self.database}"


class SecurityConfig(BaseModel):
    enabled:            bool = True
    ca_cert_path:       str = "config/certs/ca.crt"
    brain_cert_path:    str = "config/certs/brain.crt"
    brain_key_path:     str = "config/certs/brain.key"
    nonce_ttl_seconds:  int = 30
    heartbeat_ttl:      int = 45   # 3× heartbeat_interval (5s) + buffer — override: HEARTBEAT_TTL
    require_mtls:       bool = True


class BrainConfig(BaseModel):
    name:                   str = "ARBX"
    version:                str = Field(default_factory=_read_version)
    dry_run:                bool = True
    log_level:              str = "INFO"
    api_host:               str = "0.0.0.0"
    api_port:               int = 8000   # overridden by BRAIN_API_PORT env var
    metrics_port:           int = 9090   # overridden by BRAIN_METRICS_PORT env var
    stale_data_threshold_s: int = 30
    heartbeat_miss_count:   int = 3


class WorkerConfig(BaseModel):
    version:              str = Field(default_factory=_read_version)
    heartbeat_interval:   int = 5
    reconnect_delay:      int = 3
    max_pairs_per_worker: int = 10

class WorkersConfig(BaseModel):
    """
    Controls which exchanges get workers auto-spawned at brain startup.

    Set EXCHANGES=binance,kraken,bybit in .env and the brain will
    automatically spawn one worker container per exchange via the
    worker_manager. No docker-compose worker blocks needed.

    Leave empty to use only manually declared docker-compose workers.
    """
    exchanges:         List[str] = []   # populated from EXCHANGES env var
    pairs_worker_size: int       = 200  # max pairs per worker; excess triggers multi-worker split


class PluginConfig(BaseModel):
    enabled: bool = True
    weight:  float = 0.15
    params:  Dict = {}


class CR9AMConfig(BaseModel):
    enabled:          bool = True
    weight:           float = 0.30
    timezone:         str = "America/New_York"
    active_from_hour: int = 9
    active_to_hour:   int = 10
    min_setup_score:  float = 0.55
    pairs:            List[str] = ["BTC/USDT", "ETH/USDT"]


class AnalysisConfig(BaseModel):
    enabled: bool = True
    plugins: Dict[str, PluginConfig] = {}
    cr_9am:  CR9AMConfig = CR9AMConfig()


class AlertsConfig(BaseModel):
    console:            bool = True
    ntfy_enabled:       bool = False
    ntfy_url:           str  = "https://ntfy.sh"
    ntfy_topic:         str  = ""
    slack_enabled:      bool = False
    slack_webhook:      str  = ""
    discord_enabled:    bool = False
    discord_webhook:    str  = ""
    telegram_enabled:   bool = False
    telegram_bot_token: str  = ""
    telegram_chat_id:   str  = ""
    email_enabled:      bool = False
    email_smtp_host:    str  = ""
    email_smtp_port:    int  = 587
    email_tls_mode:     str  = "starttls"   # starttls | ssl | none
    email_from:         str  = ""
    email_to:           str  = ""
    email_password:     str  = ""
    webhook_enabled:    bool = False
    webhook_url:        str  = ""


class TradingConfig(BaseModel):
    min_profit_percent: float = 0.5
    max_position_usd:   float = 10000.0
    default_volume:     float = 0.5
    slippage_percent:   float = 0.1
    # v3.2 — trading mode switch
    mode:               TradingMode = TradingMode.DISABLED
    exchange_enabled:   Dict[str, bool] = {}   # per-exchange override, e.g. {"binance": true}


class GraphConfig(BaseModel):
    """
    Graph arbitrage engine configuration.
    All fields are overridable via environment variables — see load_config().
    """
    # Algorithm selection
    algorithm:          str   = "bellman_ford"   # bellman_ford | floyd_warshall
    fw_interval_s:      int   = 45               # FW full-scan interval (seconds)

    # Cycle constraints
    max_hops:           int   = 5
    min_hops:           int   = 3
    min_profit_pct:     float = 0.25             # net profit floor (after all fees)
    capital_usd:        float = 10_000.0         # simulation capital for profit calc

    # Graph quality
    stale_edge_s:       int   = 15               # drop edges older than this
    start_asset:        str   = "USDT"           # prefer cycles returning to this asset
    hub_assets:         List[str] = ["USDT", "BTC", "ETH", "BNB", "SOL", "XRP"]

    # Per-exchange fee overrides (taker %, e.g. 0.075 means 0.075%)
    fee_binance_pct:    float = 0.075
    fee_kraken_pct:     float = 0.16
    fee_bybit_pct:      float = 0.10
    fee_coinbase_pct:   float = 0.40
    fee_uniswap_pct:    float = 0.30
    fee_sushiswap_pct:  float = 0.30
    fee_pancakeswap_pct: float = 0.25
    fee_curve_pct:      float = 0.04

    # DEX gas cap — skip DEX legs that cost more than this in gas
    dex_max_gas_usd:    float = 8.0

    def fee_for(self, exchange: str) -> float:
        """Return fee as a decimal fraction (e.g. 0.00075) for the given exchange."""
        pct = {
            "binance":      self.fee_binance_pct,
            "kraken":       self.fee_kraken_pct,
            "bybit":        self.fee_bybit_pct,
            "coinbase":     self.fee_coinbase_pct,
            "uniswap":      self.fee_uniswap_pct,
            "sushiswap":    self.fee_sushiswap_pct,
            "pancakeswap":  self.fee_pancakeswap_pct,
            "curve":        self.fee_curve_pct,
        }.get(exchange.lower(), 0.10)  # default 0.10% if unknown
        return pct / 100.0


class StrategiesConfig(BaseModel):
    spatial:          bool = True
    triangular:       bool = True
    dex:              bool = True
    cross_chain:      bool = True
    flashloan:        bool = True
    fx:               bool = True
    multi_country:    bool = True
    graph_arbitrage:  bool = True


class MonitoringConfig(BaseModel):
    prometheus_enabled: bool = True
    prometheus_port:    int = 9090


class DecisionConfig(BaseModel):
    """v3.3 — configurable rules for the decision engine."""
    enabled:                bool  = True
    # CR 9AM rules
    cr_min_score:           float = 0.65
    cr_min_rr:              float = 1.5
    cr_require_bos:         bool  = True
    cr_require_fvg:         bool  = False
    cr_tp_mode:             str   = "scale_out"   # tp1_only | tp2_only | scale_out
    cr_tp1_close_pct:       float = 0.5           # fraction to close at TP1
    # Graph arb rules
    graph_min_profit_pct:   float = 0.15
    graph_max_age_ms:       int   = 5000          # discard opportunity older than this
    # General
    max_capital_per_trade:  float = 1000.0        # USD
    max_concurrent_orders:  int   = 3
    cooldown_seconds:       int   = 60            # min time between orders on same pair
    order_ttl_seconds:      int   = 30            # expire unexecuted orders after this


class RiskConfig(BaseModel):
    """v3.3 — circuit breaker limits."""
    enabled:                bool  = True
    max_daily_loss_usd:     float = 500.0
    max_drawdown_pct:       float = 10.0          # % drop from peak balance triggers halt
    max_consecutive_losses: int   = 5
    max_exchange_exposure:  float = 0.6           # max fraction of total capital on one exchange
    max_pair_exposure_usd:  float = 2000.0        # max open position USD per pair
    alert_on_trigger:       bool  = True


# ─── Root ─────────────────────────────────────────────────────────────────────

class AppConfig(BaseModel):
    ports:      PortsConfig      = PortsConfig()
    brain:      BrainConfig      = BrainConfig()
    worker:     WorkerConfig     = WorkerConfig()
    workers:    WorkersConfig    = WorkersConfig()
    redis:      RedisConfig      = RedisConfig()
    postgres:   PostgresConfig   = PostgresConfig()
    security:   SecurityConfig   = SecurityConfig()
    analysis:   AnalysisConfig   = AnalysisConfig()
    alerts:     AlertsConfig     = AlertsConfig()
    trading:    TradingConfig    = TradingConfig()
    strategies: StrategiesConfig = StrategiesConfig()
    monitoring: MonitoringConfig = MonitoringConfig()
    decision:   DecisionConfig   = DecisionConfig()
    risk:       RiskConfig       = RiskConfig()
    graph:      GraphConfig      = GraphConfig()
    risk:       RiskConfig       = RiskConfig()


# ─── Config cache + hot-reload ───────────────────────────────────────────────

_config_lock = threading.Lock()
_cached_config: Optional[AppConfig] = None
_config_path: Optional[str] = None


def reload_config() -> AppConfig:
    """
    Force reload config from disk. Called by hot-reload API endpoint.
    Clears the cache, re-reads .env (so new API keys take effect immediately),
    then re-reads config.yaml + env vars.
    Returns the new AppConfig instance.
    """
    global _cached_config, _config_path
    # Re-read both env files with override=True so new/changed values
    # (e.g. BINANCE_API_KEY added to .env.local after startup) apply immediately.
    if _ENV_PATH.exists():
        load_dotenv(dotenv_path=_ENV_PATH, override=True)
    if _ENV_LOCAL_PATH.exists():
        load_dotenv(dotenv_path=_ENV_LOCAL_PATH, override=True)
    with _config_lock:
        _cached_config = None
    return load_config(_config_path)


def load_config(path: Optional[str] = None) -> AppConfig:
    global _cached_config, _config_path
    with _config_lock:
        if _cached_config is not None and path == _config_path:
            return _cached_config

    _config_path = path
    config_path = Path(path) if path else Path(__file__).parent / "config.yaml"
    if not config_path.exists():
        cfg = AppConfig()
    else:
        with open(config_path) as f:
            raw = yaml.safe_load(f) or {}
        cfg = AppConfig(**_resolve(raw))

    # ── Environment variable overrides (highest priority) ─────────────────────
    # Ports
    cfg.ports.brain_api     = _env_int("BRAIN_API_PORT",     cfg.ports.brain_api)
    cfg.ports.brain_metrics = _env_int("BRAIN_METRICS_PORT", cfg.ports.brain_metrics)
    cfg.ports.frontend      = _env_int("FRONTEND_PORT",      cfg.ports.frontend)
    cfg.ports.redis         = _env_int("REDIS_PORT",         cfg.ports.redis)
    cfg.ports.postgres      = _env_int("POSTGRES_PORT",      cfg.ports.postgres)

    # Brain
    cfg.brain.version       = _read_version()           # always read from VERSION file
    cfg.brain.api_port      = _env_int("BRAIN_API_PORT",     cfg.brain.api_port)
    cfg.brain.metrics_port  = _env_int("BRAIN_METRICS_PORT", cfg.brain.metrics_port)
    cfg.brain.api_host      = _env_str("BRAIN_API_HOST",     cfg.brain.api_host)
    cfg.brain.log_level     = _env_str("LOG_LEVEL",          cfg.brain.log_level)
    cfg.brain.dry_run       = os.getenv("DRY_RUN", "true").lower() != "false"

    # Workers auto-spawn list
    _exchanges_raw = os.getenv("EXCHANGES", "").strip()
    if _exchanges_raw:
        cfg.workers.exchanges = [e.strip().lower() for e in _exchanges_raw.split(",") if e.strip()]
    cfg.workers.pairs_worker_size = _env_int("PAIRS_WORKER_SIZE", cfg.workers.pairs_worker_size)

    # Redis
    cfg.redis.host          = _env_str("REDIS_HOST",         cfg.redis.host)
    cfg.redis.port          = _env_int("REDIS_PORT",         cfg.redis.port)

    # Postgres
    cfg.postgres.host       = _env_str("POSTGRES_HOST",      cfg.postgres.host)
    cfg.postgres.port       = _env_int("POSTGRES_PORT",      cfg.postgres.port)

    # Security
    cfg.security.heartbeat_ttl = _env_int("HEARTBEAT_TTL",  cfg.security.heartbeat_ttl)

    # Trading mode
    _tm = os.getenv("TRADING_MODE", "").lower()
    if _tm in ("disabled", "simulate", "live"):
        cfg.trading.mode = TradingMode(_tm)

    # Alerts — env vars take priority; also auto-enable if the key is set
    cfg.alerts.ntfy_url           = _env_str("NTFY_URL",            cfg.alerts.ntfy_url)
    cfg.alerts.ntfy_topic         = _env_str("NTFY_TOPIC",          cfg.alerts.ntfy_topic)
    cfg.alerts.slack_webhook      = _env_str("SLACK_WEBHOOK_URL",   cfg.alerts.slack_webhook)
    cfg.alerts.discord_webhook    = _env_str("DISCORD_WEBHOOK_URL", cfg.alerts.discord_webhook)
    cfg.alerts.telegram_bot_token = _env_str("TELEGRAM_BOT_TOKEN",  cfg.alerts.telegram_bot_token)
    cfg.alerts.telegram_chat_id   = _env_str("TELEGRAM_CHAT_ID",    cfg.alerts.telegram_chat_id)
    cfg.alerts.webhook_url        = _env_str("WEBHOOK_URL",         cfg.alerts.webhook_url)
    cfg.alerts.email_smtp_host    = _env_str("EMAIL_SMTP_HOST",     cfg.alerts.email_smtp_host)
    cfg.alerts.email_smtp_port    = _env_int("EMAIL_SMTP_PORT",     cfg.alerts.email_smtp_port)
    cfg.alerts.email_tls_mode     = _env_str("EMAIL_TLS_MODE",      cfg.alerts.email_tls_mode)
    cfg.alerts.email_from         = _env_str("EMAIL_FROM",          cfg.alerts.email_from)
    cfg.alerts.email_to           = _env_str("EMAIL_TO",            cfg.alerts.email_to)
    cfg.alerts.email_password     = _env_str("EMAIL_PASSWORD",      cfg.alerts.email_password)
    if os.getenv("NTFY_TOPIC"):           cfg.alerts.ntfy_enabled      = True
    if os.getenv("SLACK_WEBHOOK_URL"):    cfg.alerts.slack_enabled     = True
    if os.getenv("DISCORD_WEBHOOK_URL"):  cfg.alerts.discord_enabled   = True
    if os.getenv("TELEGRAM_BOT_TOKEN"):   cfg.alerts.telegram_enabled  = True
    if os.getenv("WEBHOOK_URL"):          cfg.alerts.webhook_enabled   = True
    if os.getenv("EMAIL_SMTP_HOST"):      cfg.alerts.email_enabled     = True

    # ── Graph arbitrage ───────────────────────────────────────────────────────
    cfg.graph.algorithm       = _env_str  ("GRAPH_ALGORITHM",       cfg.graph.algorithm)
    cfg.graph.fw_interval_s   = _env_int  ("GRAPH_FW_INTERVAL_S",   cfg.graph.fw_interval_s)
    cfg.graph.max_hops        = _env_int  ("GRAPH_MAX_HOPS",        cfg.graph.max_hops)
    cfg.graph.min_hops        = _env_int  ("GRAPH_MIN_HOPS",        cfg.graph.min_hops)
    cfg.graph.min_profit_pct  = _env_float("GRAPH_MIN_SPREAD_PCT",  cfg.graph.min_profit_pct)
    cfg.graph.stale_edge_s    = _env_int  ("GRAPH_STALE_EDGE_S",    cfg.graph.stale_edge_s)
    cfg.graph.dex_max_gas_usd = _env_float("UNISWAP_MAX_GAS_USD",   cfg.graph.dex_max_gas_usd)

    _hub = os.getenv("GRAPH_HUB_ASSETS", "")
    if _hub:
        cfg.graph.hub_assets = [a.strip().upper() for a in _hub.split(",") if a.strip()]
    _sa = os.getenv("GRAPH_START_ASSET", "")
    if _sa:
        cfg.graph.start_asset = _sa.strip().upper()

    # Per-exchange fee overrides (env unit: percent, e.g. "0.075" means 0.075%)
    cfg.graph.fee_binance_pct      = _env_float("FEE_BINANCE_PCT",      cfg.graph.fee_binance_pct)
    cfg.graph.fee_kraken_pct       = _env_float("FEE_KRAKEN_PCT",       cfg.graph.fee_kraken_pct)
    cfg.graph.fee_bybit_pct        = _env_float("FEE_BYBIT_PCT",        cfg.graph.fee_bybit_pct)
    cfg.graph.fee_coinbase_pct     = _env_float("FEE_COINBASE_PCT",     cfg.graph.fee_coinbase_pct)
    cfg.graph.fee_uniswap_pct      = _env_float("FEE_UNISWAP_PCT",      cfg.graph.fee_uniswap_pct)
    cfg.graph.fee_sushiswap_pct    = _env_float("FEE_SUSHISWAP_PCT",    cfg.graph.fee_sushiswap_pct)
    cfg.graph.fee_pancakeswap_pct  = _env_float("FEE_PANCAKESWAP_PCT",  cfg.graph.fee_pancakeswap_pct)
    cfg.graph.fee_curve_pct        = _env_float("FEE_CURVE_PCT",        cfg.graph.fee_curve_pct)

    # Keep decision engine graph threshold in sync with graph config
    if not os.getenv("GRAPH_MIN_PROFIT_PCT"):
        cfg.decision.graph_min_profit_pct = cfg.graph.min_profit_pct

    with _config_lock:
        _cached_config = cfg
    return cfg
