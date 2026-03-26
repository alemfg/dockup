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

load_dotenv(dotenv_path=Path(__file__).parent / ".env")


def _read_version() -> str:
    """Read version from the VERSION file at the project root."""
    p = Path(__file__).parent.parent / "VERSION"
    return p.read_text().strip() if p.exists() else "0.0.0"


def _env_int(key: str, default: int) -> int:
    v = os.getenv(key)
    return int(v) if v and v.strip().isdigit() else default


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
      PROMETHEUS_PORT       → 9091   (Prometheus UI)
      GRAFANA_PORT          → 3001
    """
    brain_api:     int = 8000
    brain_metrics: int = 9090
    frontend:      int = 3000
    redis:         int = 6379
    postgres:      int = 5432
    prometheus:    int = 9091
    grafana:       int = 3001


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
    console:         bool = True
    ntfy_enabled:    bool = False
    ntfy_url:        str  = "https://ntfy.sh"   # base URL — override: NTFY_URL
    ntfy_topic:      str  = ""
    email_enabled:   bool = False
    slack_enabled:   bool = False
    slack_webhook:   str  = ""
    webhook_enabled: bool = False
    webhook_url:     str  = ""


class TradingConfig(BaseModel):
    min_profit_percent: float = 0.5
    max_position_usd:   float = 10000.0
    default_volume:     float = 0.5
    slippage_percent:   float = 0.1
    # v3.2 — trading mode switch
    mode:               TradingMode = TradingMode.DISABLED
    exchange_enabled:   Dict[str, bool] = {}   # per-exchange override, e.g. {"binance": true}


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


@lru_cache(maxsize=1)
def load_config(path: Optional[str] = None) -> AppConfig:
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
    cfg.ports.prometheus    = _env_int("PROMETHEUS_PORT",    cfg.ports.prometheus)
    cfg.ports.grafana       = _env_int("GRAFANA_PORT",       cfg.ports.grafana)

    # Brain
    cfg.brain.version       = _read_version()           # always read from VERSION file
    cfg.brain.api_port      = _env_int("BRAIN_API_PORT",     cfg.brain.api_port)
    cfg.brain.metrics_port  = _env_int("BRAIN_METRICS_PORT", cfg.brain.metrics_port)
    cfg.brain.api_host      = _env_str("BRAIN_API_HOST",     cfg.brain.api_host)
    cfg.brain.log_level     = _env_str("LOG_LEVEL",          cfg.brain.log_level)
    cfg.brain.dry_run       = os.getenv("DRY_RUN", "true").lower() != "false"

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
    cfg.alerts.ntfy_url      = _env_str("NTFY_URL",          cfg.alerts.ntfy_url)
    cfg.alerts.ntfy_topic    = _env_str("NTFY_TOPIC",        cfg.alerts.ntfy_topic)
    cfg.alerts.slack_webhook = _env_str("SLACK_WEBHOOK_URL", cfg.alerts.slack_webhook)
    cfg.alerts.webhook_url   = _env_str("WEBHOOK_URL",       cfg.alerts.webhook_url)
    if os.getenv("NTFY_TOPIC"):
        cfg.alerts.ntfy_enabled    = True
    if os.getenv("SLACK_WEBHOOK_URL"):
        cfg.alerts.slack_enabled   = True
    if os.getenv("WEBHOOK_URL"):
        cfg.alerts.webhook_enabled = True

    return cfg
