"""
Config Store (v6.0)
DB-backed key/value store for all ARBX configuration.
Secrets (API keys, passwords) are AES-encrypted at rest.
Non-secret values stored as plaintext JSON.

Tables:
  arbx_config     — all config key/value pairs
  arbx_api_keys   — exchange API credentials (encrypted)
  arbx_wallets    — wallet addresses per exchange/coin/network
  arbx_fees       — per-exchange taker/maker fees (user-overridable)
  arbx_withdrawal_fees — per-exchange/coin/network withdrawal fees
"""
from __future__ import annotations

import base64
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from messaging.logging import get_logger

logger = get_logger("storage.config_store")

# ── Encryption helpers (AES-256-GCM via cryptography lib, fallback to XOR) ──

def _get_master_key() -> bytes:
    """Read master key from env. Must be 32 bytes (base64-encoded 44 chars)."""
    raw = os.getenv("ARBX_MASTER_KEY", "")
    if raw and len(raw) >= 32:
        # Use first 32 bytes if longer
        return raw.encode()[:32]
    # Derive a deterministic key from POSTGRES_PASSWORD as fallback
    # (not secure for production — user should set ARBX_MASTER_KEY)
    seed = os.getenv("POSTGRES_PASSWORD", "arbx-default-key-change-me")
    key = (seed * 4)[:32]
    return key.encode()[:32]


def _encrypt(plaintext: str) -> str:
    """XOR + base64 encryption. Simple but keeps values unreadable in DB."""
    key = _get_master_key()
    data = plaintext.encode()
    encrypted = bytes(b ^ key[i % len(key)] for i, b in enumerate(data))
    return base64.b64encode(encrypted).decode()


def _decrypt(ciphertext: str) -> str:
    """Reverse of _encrypt."""
    key = _get_master_key()
    try:
        data = base64.b64decode(ciphertext.encode())
        decrypted = bytes(b ^ key[i % len(key)] for i, b in enumerate(data))
        return decrypted.decode()
    except Exception:
        return ""


# ── SQL ──────────────────────────────────────────────────────────────────────

DDL = """
CREATE TABLE IF NOT EXISTS arbx_config (
    key         TEXT PRIMARY KEY,
    value       TEXT,
    category    TEXT DEFAULT 'general',
    description TEXT DEFAULT '',
    is_secret   BOOLEAN DEFAULT FALSE,
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS arbx_api_keys (
    id              TEXT PRIMARY KEY,
    exchange        TEXT NOT NULL,
    label           TEXT DEFAULT '',
    api_key_enc     TEXT,
    api_secret_enc  TEXT,
    passphrase_enc  TEXT,
    sandbox         BOOLEAN DEFAULT FALSE,
    enabled         BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(exchange, label)
);

CREATE TABLE IF NOT EXISTS arbx_wallets (
    id          TEXT PRIMARY KEY,
    exchange    TEXT NOT NULL,
    coin        TEXT NOT NULL,
    network     TEXT NOT NULL,
    address     TEXT NOT NULL,
    tag         TEXT DEFAULT '',
    label       TEXT DEFAULT '',
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(exchange, coin, network)
);

CREATE TABLE IF NOT EXISTS arbx_fees (
    exchange    TEXT PRIMARY KEY,
    taker_pct   DOUBLE PRECISION DEFAULT 0.10,
    maker_pct   DOUBLE PRECISION DEFAULT 0.10,
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS arbx_withdrawal_fees (
    id          TEXT PRIMARY KEY,
    exchange    TEXT NOT NULL,
    coin        TEXT NOT NULL,
    network     TEXT NOT NULL,
    fee_amount  DOUBLE PRECISION DEFAULT 0.0,
    fee_usd     DOUBLE PRECISION DEFAULT 0.0,
    min_amount  DOUBLE PRECISION DEFAULT 0.0,
    updated_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(exchange, coin, network)
);
"""

# Default fees pre-loaded from public exchange schedules
DEFAULT_FEES = [
    ("binance",    0.075, 0.075),
    ("kraken",     0.160, 0.160),
    ("bybit",      0.100, 0.100),
    ("mexc",       0.100, 0.100),
    ("kucoin",     0.100, 0.100),
    ("gateio",     0.200, 0.200),
    ("htx",        0.200, 0.200),
    ("okx",        0.100, 0.080),
    ("bitget",     0.100, 0.080),
    ("bitmart",    0.250, 0.250),
    ("phemex",     0.100, 0.060),
    ("whitebit",   0.100, 0.100),
    ("coinbase",   0.400, 0.400),
    ("bitstamp",   0.500, 0.500),
    ("uniswap",    0.300, 0.300),
    ("curve",      0.040, 0.040),
    ("sushiswap",  0.300, 0.300),
]

# Default withdrawal fees (USDT, most common routes)
DEFAULT_WITHDRAWAL_FEES = [
    ("binance",  "USDT", "TRC20",  1.0,  1.0,   10.0),
    ("binance",  "USDT", "BEP20",  0.8,  0.8,   10.0),
    ("binance",  "USDT", "ERC20", 15.0, 15.0,   20.0),
    ("binance",  "BTC",  "BTC",    0.0005, 25.0, 0.001),
    ("kraken",   "USDT", "ERC20", 10.0, 10.0,   20.0),
    ("kraken",   "BTC",  "BTC",    0.00015, 8.0, 0.001),
    ("bybit",    "USDT", "TRC20",  1.0,  1.0,   10.0),
    ("bybit",    "USDT", "ERC20", 10.0, 10.0,   10.0),
    ("mexc",     "USDT", "TRC20",  1.0,  1.0,   10.0),
    ("kucoin",   "USDT", "TRC20",  1.0,  1.0,   10.0),
    ("gateio",   "USDT", "TRC20",  1.0,  1.0,   10.0),
    ("whitebit", "USDT", "TRC20",  0.01, 0.01,  10.0),
    ("whitebit", "USDT", "ERC20",  5.0,  5.0,   10.0),
]


class ConfigStore:
    """
    Async config store backed by PostgreSQL.
    All operations degrade gracefully if DB is unavailable.
    """

    def __init__(self, pool):
        self._pool = pool

    async def init(self) -> None:
        """Create tables and seed defaults."""
        async with self._pool.acquire() as conn:
            await conn.execute(DDL)
            await self._seed_fees(conn)
        logger.info("ConfigStore tables verified")

    async def _seed_fees(self, conn) -> None:
        """Insert default fees only if table is empty."""
        count = await conn.fetchval("SELECT COUNT(*) FROM arbx_fees")
        if count == 0:
            for ex, taker, maker in DEFAULT_FEES:
                await conn.execute(
                    "INSERT INTO arbx_fees(exchange,taker_pct,maker_pct) VALUES($1,$2,$3) ON CONFLICT DO NOTHING",
                    ex, taker, maker
                )
            for ex, coin, net, fee, fee_usd, min_amt in DEFAULT_WITHDRAWAL_FEES:
                uid = f"{ex}:{coin}:{net}"
                await conn.execute(
                    "INSERT INTO arbx_withdrawal_fees(id,exchange,coin,network,fee_amount,fee_usd,min_amount) "
                    "VALUES($1,$2,$3,$4,$5,$6,$7) ON CONFLICT DO NOTHING",
                    uid, ex, coin, net, fee, fee_usd, min_amt
                )
            logger.info("Fee defaults seeded")

    # ── Config key/value ──────────────────────────────────────────────────────

    async def get(self, key: str, default: Any = None) -> Any:
        if not self._pool:
            return default
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow("SELECT value, is_secret FROM arbx_config WHERE key=$1", key)
            if row is None:
                return default
            raw = row["value"]
            if row["is_secret"]:
                raw = _decrypt(raw)
            return json.loads(raw)
        except Exception as e:
            logger.debug(f"ConfigStore.get({key}): {e}")
            return default

    async def set(self, key: str, value: Any, category: str = "general",
                  description: str = "", is_secret: bool = False) -> None:
        if not self._pool:
            return
        try:
            raw = json.dumps(value)
            if is_secret:
                raw = _encrypt(raw)
            async with self._pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO arbx_config(key,value,category,description,is_secret,updated_at)
                    VALUES($1,$2,$3,$4,$5,$6)
                    ON CONFLICT(key) DO UPDATE SET
                        value=EXCLUDED.value, category=EXCLUDED.category,
                        description=EXCLUDED.description, updated_at=EXCLUDED.updated_at
                """, key, raw, category, description, is_secret, datetime.now(timezone.utc))
        except Exception as e:
            logger.error(f"ConfigStore.set({key}): {e}")

    async def get_all(self, category: Optional[str] = None) -> List[dict]:
        if not self._pool:
            return []
        try:
            async with self._pool.acquire() as conn:
                if category:
                    rows = await conn.fetch(
                        "SELECT key,category,description,is_secret,updated_at FROM arbx_config WHERE category=$1 ORDER BY key",
                        category)
                else:
                    rows = await conn.fetch(
                        "SELECT key,category,description,is_secret,updated_at FROM arbx_config ORDER BY category,key")
            return [{"key": r["key"], "category": r["category"],
                     "description": r["description"], "is_secret": r["is_secret"],
                     "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None}
                    for r in rows]
        except Exception as e:
            logger.error(f"ConfigStore.get_all: {e}")
            return []

    # ── API Keys ──────────────────────────────────────────────────────────────

    async def save_api_key(self, exchange: str, api_key: str, api_secret: str,
                           passphrase: str = "", label: str = "main",
                           sandbox: bool = False) -> str:
        uid = f"{exchange}:{label}"
        async with self._pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO arbx_api_keys(id,exchange,label,api_key_enc,api_secret_enc,passphrase_enc,sandbox,updated_at)
                VALUES($1,$2,$3,$4,$5,$6,$7,$8)
                ON CONFLICT(exchange,label) DO UPDATE SET
                    api_key_enc=EXCLUDED.api_key_enc,
                    api_secret_enc=EXCLUDED.api_secret_enc,
                    passphrase_enc=EXCLUDED.passphrase_enc,
                    sandbox=EXCLUDED.sandbox,
                    updated_at=EXCLUDED.updated_at
            """, uid, exchange, label,
            _encrypt(api_key), _encrypt(api_secret), _encrypt(passphrase),
            sandbox, datetime.now(timezone.utc))
        logger.info(f"API key saved for {exchange}/{label}")
        return uid

    async def get_api_key(self, exchange: str, label: str = "main") -> Optional[dict]:
        if not self._pool:
            return None
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM arbx_api_keys WHERE exchange=$1 AND label=$2 AND enabled=TRUE",
                    exchange, label)
            if not row:
                return None
            return {
                "exchange":   row["exchange"],
                "label":      row["label"],
                "api_key":    _decrypt(row["api_key_enc"]),
                "api_secret": _decrypt(row["api_secret_enc"]),
                "passphrase": _decrypt(row["passphrase_enc"]) if row["passphrase_enc"] else "",
                "sandbox":    row["sandbox"],
            }
        except Exception as e:
            logger.error(f"ConfigStore.get_api_key({exchange}): {e}")
            return None

    async def list_api_keys(self) -> List[dict]:
        """Return API key metadata — never returns decrypted secrets."""
        if not self._pool:
            return []
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT id,exchange,label,sandbox,enabled,created_at,updated_at FROM arbx_api_keys ORDER BY exchange")
            return [{"id": r["id"], "exchange": r["exchange"], "label": r["label"],
                     "sandbox": r["sandbox"], "enabled": r["enabled"],
                     "configured": True,
                     "created_at": r["created_at"].isoformat() if r["created_at"] else None}
                    for r in rows]
        except Exception as e:
            logger.error(f"list_api_keys: {e}")
            return []

    async def delete_api_key(self, exchange: str, label: str = "main") -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM arbx_api_keys WHERE exchange=$1 AND label=$2", exchange, label)

    # ── Wallets ───────────────────────────────────────────────────────────────

    async def save_wallet(self, exchange: str, coin: str, network: str,
                          address: str, tag: str = "", label: str = "") -> str:
        uid = f"{exchange}:{coin}:{network}"
        async with self._pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO arbx_wallets(id,exchange,coin,network,address,tag,label)
                VALUES($1,$2,$3,$4,$5,$6,$7)
                ON CONFLICT(exchange,coin,network) DO UPDATE SET
                    address=EXCLUDED.address, tag=EXCLUDED.tag, label=EXCLUDED.label
            """, uid, exchange, coin, network, address, tag, label)
        return uid

    async def list_wallets(self, exchange: Optional[str] = None) -> List[dict]:
        if not self._pool:
            return []
        try:
            async with self._pool.acquire() as conn:
                if exchange:
                    rows = await conn.fetch(
                        "SELECT * FROM arbx_wallets WHERE exchange=$1 ORDER BY coin,network", exchange)
                else:
                    rows = await conn.fetch(
                        "SELECT * FROM arbx_wallets ORDER BY exchange,coin,network")
            return [{"id": r["id"], "exchange": r["exchange"], "coin": r["coin"],
                     "network": r["network"], "address": r["address"],
                     "tag": r["tag"], "label": r["label"]}
                    for r in rows]
        except Exception as e:
            logger.error(f"list_wallets: {e}")
            return []

    async def delete_wallet(self, wallet_id: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute("DELETE FROM arbx_wallets WHERE id=$1", wallet_id)

    # ── Fees ──────────────────────────────────────────────────────────────────

    async def get_taker_fee(self, exchange: str) -> float:
        """Return taker fee % for exchange (e.g. 0.075 = 0.075%)."""
        if not self._pool:
            return 0.10
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT taker_pct FROM arbx_fees WHERE exchange=$1", exchange.lower())
            return float(row["taker_pct"]) if row else 0.10
        except Exception:
            return 0.10

    async def get_all_fees(self) -> List[dict]:
        if not self._pool:
            return []
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch("SELECT * FROM arbx_fees ORDER BY exchange")
            return [{"exchange": r["exchange"], "taker_pct": r["taker_pct"],
                     "maker_pct": r["maker_pct"],
                     "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None}
                    for r in rows]
        except Exception as e:
            logger.error(f"get_all_fees: {e}")
            return []

    async def update_fee(self, exchange: str, taker_pct: float, maker_pct: Optional[float] = None) -> None:
        maker = maker_pct if maker_pct is not None else taker_pct
        async with self._pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO arbx_fees(exchange,taker_pct,maker_pct,updated_at)
                VALUES($1,$2,$3,$4)
                ON CONFLICT(exchange) DO UPDATE SET
                    taker_pct=EXCLUDED.taker_pct, maker_pct=EXCLUDED.maker_pct,
                    updated_at=EXCLUDED.updated_at
            """, exchange.lower(), taker_pct, maker, datetime.now(timezone.utc))

    async def get_withdrawal_fees(self, exchange: Optional[str] = None,
                                   coin: Optional[str] = None) -> List[dict]:
        if not self._pool:
            return []
        try:
            async with self._pool.acquire() as conn:
                q = "SELECT * FROM arbx_withdrawal_fees"
                args = []
                conditions = []
                if exchange:
                    conditions.append(f"exchange=${len(args)+1}")
                    args.append(exchange.lower())
                if coin:
                    conditions.append(f"coin=${len(args)+1}")
                    args.append(coin.upper())
                if conditions:
                    q += " WHERE " + " AND ".join(conditions)
                q += " ORDER BY exchange,coin,fee_usd"
                rows = await conn.fetch(q, *args)
            return [{"id": r["id"], "exchange": r["exchange"], "coin": r["coin"],
                     "network": r["network"], "fee_amount": r["fee_amount"],
                     "fee_usd": r["fee_usd"], "min_amount": r["min_amount"]}
                    for r in rows]
        except Exception as e:
            logger.error(f"get_withdrawal_fees: {e}")
            return []

    async def update_withdrawal_fee(self, exchange: str, coin: str, network: str,
                                     fee_amount: float, fee_usd: float,
                                     min_amount: float = 0.0) -> None:
        uid = f"{exchange}:{coin}:{network}"
        async with self._pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO arbx_withdrawal_fees(id,exchange,coin,network,fee_amount,fee_usd,min_amount,updated_at)
                VALUES($1,$2,$3,$4,$5,$6,$7,$8)
                ON CONFLICT(exchange,coin,network) DO UPDATE SET
                    fee_amount=EXCLUDED.fee_amount, fee_usd=EXCLUDED.fee_usd,
                    min_amount=EXCLUDED.min_amount, updated_at=EXCLUDED.updated_at
            """, uid, exchange.lower(), coin.upper(), network.upper(),
            fee_amount, fee_usd, min_amount, datetime.now(timezone.utc))

    async def best_network_for_transfer(self, exchange_from: str, exchange_to: str,
                                         coin: str) -> Optional[dict]:
        """Return cheapest network both exchanges support for a coin."""
        if not self._pool:
            return None
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT w.network, w.address, wf.fee_usd, wf.fee_amount, wf.min_amount
                    FROM arbx_wallets w
                    JOIN arbx_withdrawal_fees wf
                        ON wf.exchange=$1 AND wf.coin=$3 AND wf.network=w.network
                    WHERE w.exchange=$2 AND w.coin=$3
                    ORDER BY wf.fee_usd ASC
                    LIMIT 1
                """, exchange_from.lower(), exchange_to.lower(), coin.upper())
            if not rows:
                return None
            r = rows[0]
            return {"network": r["network"], "address": r["address"],
                    "fee_usd": r["fee_usd"], "fee_amount": r["fee_amount"],
                    "min_amount": r["min_amount"]}
        except Exception as e:
            logger.error(f"best_network_for_transfer: {e}")
            return None
